#!/usr/bin/env python3
"""Orthology expression workflow benchmark (one dataset size per process).

Calls the *unmodified* Micromix orthology functions against a disposable
database ``mmbench_orth_S{S}`` on the isolated benchmark mongod:

  A. HTTP upload-cap probe   POST /orthogroup_imports/<rid>/expression_upload
                             (Flask test client; real MAX_CONTENT_LENGTH)
  B. Expression import       parse -> validate -> preview -> store_expression_import
                             (same call sequence as expression_import.import_expression_reference;
                             insert_many timed through a pass-through proxy)
  C. Storage                 collStats / dbStats after import
  D. Retrieval               raw list(find(query, projection)), expression_matrix._load_rows
  E. Matrix construction     build_matrix(for_export=True)  (full matrix, no page formatting)
  F. Pagination              build_matrix page 1 then page 2 (function level) and
                             POST /expression_imports/<id>/matrix page 1, page 2 (HTTP level)
  G. Variants                CPM, log2CPM, replicate mean, paralog max, strain filter, search
  H. Export                  build_matrix_export (TSV) and the HTTP export route

Run via run_benchmarks.py, or directly:  python bench_orthology.py --size 32
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench_common as bc  # noqa: E402

bc.configure_backend_import()


class TimedCollection:
    """Pass-through proxy that times insert_many (no behaviour change)."""

    def __init__(self, coll, timings):
        self._c = coll
        self._t = timings

    def insert_many(self, docs, *a, **kw):
        t0 = time.perf_counter()
        r = self._c.insert_many(docs, *a, **kw)
        self._t.setdefault("insert_many_seconds", 0.0)
        self._t["insert_many_seconds"] += time.perf_counter() - t0
        self._t["insert_many_docs"] = self._t.get("insert_many_docs", 0) + len(docs)
        return r

    def __getattr__(self, name):
        return getattr(self._c, name)


class TimedDB:
    def __init__(self, db, timings):
        self._db = db
        self._t = timings

    def __getitem__(self, name):
        return TimedCollection(self._db[name], self._t)

    def __getattr__(self, name):
        return getattr(self._db, name)


def reps_for(first_seconds, budget_s):
    """Repetition policy: 5 reps, 3 if a single run > 60 s, 1 if > budget."""
    if first_seconds > budget_s:
        return 1
    if first_seconds > 60:
        return 3
    return 5


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, required=True)
    ap.add_argument("--run-id", default=bc.new_run_id())
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--import-reps", type=int, default=None,
                    help="default: 3 for S<=250, else 1")
    ap.add_argument("--budget-s", type=float, default=300.0,
                    help="single-run time above which only one repetition is made")
    ap.add_argument("--skip-variants", action="store_true")
    ap.add_argument("--variants-max-size", type=int, default=250,
                    help="option variants (CPM, aggregation, filters) only run up to this size")
    args = ap.parse_args()
    S = args.size

    out = args.out or (bc.RAW_DIR / f"{args.run_id}.jsonl")
    rec = bc.Recorder(out, args.run_id, "orthology")
    client = bc.bench_client()
    bc.ensure_ownership(client)
    dbname = f"{bc.BENCH_DB_PREFIX}orth_S{S}"
    bc.register_owned_db(client, dbname)

    import app as mm_app  # connects to BENCH_MONGO_URI (verified below)
    if mm_app.client.address[1] != bc.BENCH_MONGO_PORT:
        raise bc.UnsafeEnvironment("app.py connected to an unexpected MongoDB port")
    import orthology
    from orthology import expression_matrix as em
    from orthology.parse import read_orthogroup_table
    from orthology.expression_validation import validate as validate_expr
    from orthology.expression_import import build_preview
    from orthology.storage import store_expression_import, get_reference_orthogroup_ids
    from bson.json_util import dumps

    data = bc.DATA_DIR
    ref_path = data / "orthology_reference.tsv"
    expr_path = data / f"orthology_expression_long_S{S}.tsv"
    manifest = json.loads((data / "manifest.json").read_text())
    finfo = manifest["files"][expr_path.name]
    base = {"dataset": expr_path.name, "file_bytes": finfo["bytes"], "input_rows": finfo["rows"],
            "features": finfo["orthogroups"]}

    # Route-level tests use the same isolated DB (runtime assignment of the
    # module global; app code is not modified).
    bdb = client[dbname]
    mm_app.db = bdb

    # ---------------- A. HTTP upload-cap probe ----------------
    cap = mm_app.app.config["MAX_CONTENT_LENGTH"]
    tc = mm_app.app.test_client()
    form = {"source": {"file": None, "database": None, "url": None, "text": None},
            "formatting": {"file": {"csv_seperator": "\t", "decimal_character": "."},
                           "text": {"decimal_character": "."}}}

    def fresh_reference():
        if dbname in client.list_database_names():
            bc.drop_owned_db(client, dbname)
        bc.register_owned_db(client, dbname)
        orthology.ensure_expression_indexes(bdb)  # what app.py does at startup
        res = orthology.import_orthogroup_reference(bdb, str(ref_path), ".tsv",
                                                    filename=ref_path.name)
        return res["import_id"]

    rid = fresh_reference()
    if finfo["bytes"] > cap:
        with rec.measure("http_expression_upload", S, 1, dict(base, max_content_length=cap)) as box:
            with open(expr_path, "rb") as fh:
                r = tc.post(f"/orthogroup_imports/{rid}/expression_upload",
                            data={"form": json.dumps(form), "file": (fh, expr_path.name)},
                            content_type="multipart/form-data")
            body = r.get_data()
            box["extra"].update(http_status=r.status_code, response_bytes=len(body),
                                response_head=body[:300].decode("utf-8", "replace"))
            box["status"] = "rejected_413" if r.status_code == 413 else "ok"
    else:
        with rec.measure("http_expression_upload", S, 1, dict(base, max_content_length=cap)) as box:
            with open(expr_path, "rb") as fh:
                r = tc.post(f"/orthogroup_imports/{rid}/expression_upload",
                            data={"form": json.dumps(form), "file": (fh, expr_path.name)},
                            content_type="multipart/form-data")
            body = r.get_data()
            payload = json.loads(body)
            box["extra"].update(http_status=r.status_code, response_bytes=len(body),
                                inserted_count=payload.get("inserted_count"),
                                error_type=payload.get("error_type"))
            if payload.get("error_type"):
                box["status"] = "app_error"
                box["error"] = payload.get("error_message")

    # ---------------- B. Function-level import (bypasses HTTP cap) ----------------
    expression_set_id = None
    n_reps = args.import_reps or (3 if S <= 250 else 1)
    rep = 0
    while rep < n_reps:
        rep += 1
        rid = fresh_reference()
        timings = {}
        tdb = TimedDB(bdb, timings)
        extra = dict(base, level="function", note="bypasses 50 MB HTTP cap; same call sequence as import_expression_reference")
        with rec.measure("expression_import_total", S, rep, extra, cold=(rep == 1)) as box:
            t = time.perf_counter()
            ref_ids = get_reference_orthogroup_ids(bdb, rid)
            timings["reference_lookup_seconds"] = time.perf_counter() - t
            t = time.perf_counter()
            df = read_orthogroup_table(str(expr_path), ".tsv")
            timings["parse_seconds"] = time.perf_counter() - t
            t = time.perf_counter()
            summary = validate_expr(df, ref_ids, rid)
            timings["validate_seconds"] = time.perf_counter() - t
            t = time.perf_counter()
            preview = build_preview(df)
            timings["preview_seconds"] = time.perf_counter() - t
            t = time.perf_counter()
            expression_set_id, inserted = store_expression_import(
                tdb, df, rid, filename=expr_path.name, display_name=expr_path.name,
                summary=summary, preview=preview)
            timings["store_total_seconds"] = time.perf_counter() - t
            timings["store_docbuild_seconds"] = timings["store_total_seconds"] - timings.get("insert_many_seconds", 0.0)
            del df
            box["extra"].update({k: (round(v, 4) if isinstance(v, float) else v) for k, v in timings.items()})
            box["extra"]["inserted_documents"] = inserted
        if rep == 1:
            last = json.loads(out.read_text().strip().splitlines()[-1])
            if last.get("status") != "ok":
                break
            n_reps = 1 if last["seconds"] > args.budget_s else n_reps

    if expression_set_id is None:
        print("[orth] import failed; aborting dependent tests", flush=True)
        return

    # ---------------- C. Storage ----------------
    stats = bdb.command("dbStats")
    rec.write(operation="storage_stats", samples=S, rep=1, status="ok", **base,
              expression_coll=bc.coll_stats(bdb, "orthogroup_expression"),
              reference_coll=bc.coll_stats(bdb, "orthogroup_references"),
              manifest_coll=bc.coll_stats(bdb, "orthogroup_expression_sets"),
              db_data_bytes=stats.get("dataSize"), db_storage_bytes=stats.get("storageSize"),
              db_index_bytes=stats.get("indexSize"), db_objects=stats.get("objects"))

    def repeat(op, fn, extra=None, min_reps=3):
        first = None
        r = 0
        n = min_reps
        while r < n:
            r += 1
            with rec.measure(op, S, r, dict(base, **(extra or {})), cold=(r == 1)) as box:
                res = fn(box)
            last = json.loads(out.read_text().strip().splitlines()[-1])
            if last.get("status") != "ok":
                return None
            if r == 1:
                first = last["seconds"]
                n = min(min_reps, reps_for(first, args.budget_s)) if min_reps < 3 else reps_for(first, args.budget_s)
                if S >= 500:
                    n = min(n, 3)
        return res

    opts = orthology.MatrixOptions()

    # ---------------- D. Retrieval ----------------
    coll = bdb["orthogroup_expression"]
    query = em._build_query(expression_set_id, opts)
    projection = {"_id": 0, **{c: 1 for c in em._LOAD_COLUMNS}}

    def raw_find(box):
        n = len(list(coll.find(query, projection)))
        box["extra"]["documents"] = n

    repeat("retrieval_raw_find", raw_find)

    def explain(box):
        ex = coll.find(query, projection).explain()
        es = ex.get("executionStats", {})
        box["extra"].update(docs_examined=es.get("totalDocsExamined"),
                            keys_examined=es.get("totalKeysExamined"),
                            mongo_exec_ms=es.get("executionTimeMillis"),
                            winning_plan=str(ex.get("queryPlanner", {}).get("winningPlan"))[:400])
    repeat("retrieval_explain", explain, min_reps=1)

    def load_rows(box):
        d = em._load_rows(bdb, expression_set_id, opts)
        box["extra"]["rows"] = len(d)
    repeat("retrieval_load_rows", load_rows)

    # ---------------- E. Full matrix construction ----------------
    def full_build(box):
        b = em.build_matrix(bdb, expression_set_id, opts, for_export=True)
        box["extra"].update(matrix_rows=b["total_matrix_rows"], matrix_cols=b["total_matrix_columns"],
                            missing_cells=b["summary"]["missing_value_count"],
                            paralog_ogs=b["summary"]["orthogroups_with_paralogs"])
    repeat("matrix_build_full", full_build, min_reps=1 if S >= 500 else 3)

    # ---------------- E2. Stage breakdown ----------------
    # Mirrors build_matrix() steps 2-9 + page formatting (expression_matrix.py
    # L736-892) by calling the same internal functions in the same order. Used
    # only to attribute time; totals are taken from matrix_build_full above.
    def stage_profile(box):
        T = {}
        t = time.perf_counter()
        df = em._load_rows(bdb, expression_set_id, opts); T["load_rows"] = time.perf_counter() - t
        t = time.perf_counter()
        dup, _ = em.detect_duplicates(df); T["detect_duplicates"] = time.perf_counter() - t
        if dup > 0:
            t = time.perf_counter(); df = em._resolve_duplicates(df, opts.duplicate_rule)
            T["resolve_duplicates"] = time.perf_counter() - t
        t = time.perf_counter()
        meta, _, _ = em._build_row_metadata(df); T["build_row_metadata"] = time.perf_counter() - t
        t = time.perf_counter()
        cell = em._collapse_paralogs(df, opts.paralog_rule); T["collapse_paralogs"] = time.perf_counter() - t
        t = time.perf_counter()
        m = cell.pivot_table(index="orthogroup_id", columns="sample_id", values="value",
                             aggfunc="sum", dropna=False).sort_index(axis=0).sort_index(axis=1)
        T["pivot_sort"] = time.perf_counter() - t
        t = time.perf_counter()
        ss = {}
        for sid, sg in df.groupby("sample_id", dropna=True):
            sv = sg["strain"].dropna()
            if not sv.empty:
                ss[sid] = str(sv.mode().iloc[0])
        em._sample_metadata(df); T["sample_strain_and_metadata"] = time.perf_counter() - t
        t = time.perf_counter()
        int(m.isna().sum().sum()); tr, _ = em._apply_transformation(m, "raw")
        T["missing_count_transform_raw"] = time.perf_counter() - t
        t = time.perf_counter()
        em._apply_transformation(m, "cpm"); T["cpm_transform"] = time.perf_counter() - t
        t = time.perf_counter()
        em._apply_transformation(m, "log2_cpm"); T["log2cpm_transform"] = time.perf_counter() - t
        t = time.perf_counter()
        cols = [str(c) for c in tr.columns]
        for og in [str(o) for o in tr.index[:50]]:
            rs = tr.loc[og]
            {c: em._cell_for_display(rs.get(c), "blank") for c in cols}
        T["format_50_rows"] = time.perf_counter() - t
        box["extra"].update({f"stage_{k}_s": round(v, 4) for k, v in T.items()})
        box["extra"]["long_rows"] = len(df)
    repeat("matrix_build_stage_profile", stage_profile, min_reps=1 if S >= 250 else 3)

    # ---------------- F. Pagination ----------------
    max_page_reps = 5 if S <= 100 else 3
    for rep in range(1, max_page_reps + 1):
        for page in (1, 2):
            with rec.measure(f"matrix_page{page}_function", S, rep, dict(base, page=page, limit=50,
                             sequence="page1 then page2 in the same process"), cold=(rep == 1 and page == 1)) as box:
                res = em.build_matrix(bdb, expression_set_id, opts, page=page, limit=50)
                box["extra"].update(returned_rows=res["returned_rows"], matrix_cols=res["total_matrix_columns"])
            last = json.loads(out.read_text().strip().splitlines()[-1])
            if last.get("status") != "ok":
                break
        if rep == 1 and last.get("seconds", 0) > args.budget_s:
            break
        if rep >= 3 and last.get("seconds", 0) > 60:
            break

    for rep in range(1, (3 if S <= 250 else 1) + 1):
        for page in (1, 2):
            with rec.measure(f"matrix_page{page}_http", S, rep, dict(base, page=page, limit=50)) as box:
                r = tc.post(f"/expression_imports/{expression_set_id}/matrix",
                            json={"page": page, "limit": 50})
                body = r.get_data()
                box["extra"].update(http_status=r.status_code, response_bytes=len(body))
                if b'"error_type"' in body[:200]:
                    box["status"] = "app_error"
                    box["error"] = body[:400].decode("utf-8", "replace")
        if json.loads(out.read_text().strip().splitlines()[-1]).get("seconds", 0) > 60:
            break

    # ---------------- G. Variants (filtering, aggregation, transforms) ----------------
    if not args.skip_variants and S <= args.variants_max_size:
        variants = {
            "matrix_page1_cpm": dict(transformation="cpm"),
            "matrix_page1_log2cpm": dict(transformation="log2_cpm"),
            "matrix_page1_replicate_mean": dict(replicate_aggregation="mean"),
            "matrix_page1_paralog_max": dict(paralog_rule="max"),
            "matrix_page1_filter_2_strains": dict(strains=["Syn.S01", "Syn.S02"]),
            "matrix_page1_search": dict(search="family 1"),
        }
        for op, kw in variants.items():
            o = orthology.MatrixOptions(**kw)

            def page_fn(box, o=o):
                res = em.build_matrix(bdb, expression_set_id, o, page=1, limit=50)
                box["extra"].update(matrix_rows=res["total_matrix_rows"], matrix_cols=res["total_matrix_columns"],
                                    source_rows=res["summary"]["source_row_count"])
            repeat(op, page_fn, extra={"options": kw}, min_reps=3 if S <= 100 else 1)

    # ---------------- H. Export ----------------
    def export_fn(box):
        text, summ = em.build_matrix_export(bdb, expression_set_id, opts, file_format="tsv")
        box["extra"].update(export_bytes=len(text.encode()), matrix_rows=summ["matrix_row_count"],
                            matrix_cols=summ["matrix_column_count"])
    repeat("matrix_export_function", export_fn, min_reps=1 if S >= 500 else 3)

    def export_http(box):
        r = tc.post(f"/expression_imports/{expression_set_id}/matrix_export", json={"file_format": "tsv"})
        body = r.get_data()
        box["extra"].update(http_status=r.status_code, response_bytes=len(body))
    if S <= 250:
        repeat("matrix_export_http", export_http, min_reps=1)

    print(f"[orth] S={S} done", flush=True)


if __name__ == "__main__":
    main()
