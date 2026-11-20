#!/usr/bin/env python3
"""Legacy (session-document) workflow benchmark, one dataset size per process.

Drives the *unmodified* Flask routes through ``app.test_client()`` (real
request parsing, real MAX_CONTENT_LENGTH, real route code) against a
disposable database ``mmbench_legacy_S{S}`` on the isolated mongod.

Per repetition (fresh session each time):
  1. POST /upload        new session, whole wide matrix (1 source matrix)
  2. session document size ($bsonSize) + per-field blob sizes
  3. POST /query         "Filter values > 10 in any column" -> filtered_dataframe
  4. session document size again
  5. POST /config        response time + bytes (what the browser downloads)
Plus, once per size:
  6. POST /upload of a second matrix into the same session (k=2: triggers
     merge_db_entry + preview copy). The second matrix is the same file with a
     different title, i.e. 2*S value columns in the session.
  7. Function-level breakdown (outside Flask): convert_to_df, rename,
     df_to_parquet, merge_db_entry, filter_dataframe.main, read_parquet,
     to_json(orient='records').

Failures (DocumentTooLarge, app_error JSON, 413) are recorded and the
remaining independent steps continue.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench_common as bc  # noqa: E402

bc.configure_backend_import()

FILTER_QUERY = [[{
    "name": "Filter values",
    "properties": {"type": "filter", "query": "expression"},
    "forms": {"logical_operator": "> more than", "filter_value": "10", "filter_area": ["any column"]},
}]]


def upload_form(title, db_entry_id="", x=2, y=2):
    return {
        "title": title, "x": x, "y": y, "type": [], "matrix_id": None,
        "db_entry_id": db_entry_id, "plugins_id": [], "locked": False, "transformation": "",
        "formatting": {"file": {"csv_seperator": "\t", "decimal_character": "."},
                       "text": {"decimal_character": "."}},
        "source": {"file": None, "database": None, "url": None, "text": None},
        "local_active_organism_id": "bacteroides-thetaiotaomicron-e2ad6b25-40cb-4594-8685-f4fcb3ceb0e7",
        "database_columns": [],
    }


def doc_sizes(db, oid):
    from bson import ObjectId
    pipe = [{"$match": {"_id": ObjectId(oid)}}, {"$project": {
        "total": {"$bsonSize": "$$ROOT"},
        "transformed": {"$binarySize": {"$ifNull": [{"$cond": [{"$eq": [{"$type": "$transformed_dataframe"}, "binData"]}, "$transformed_dataframe", None]}, ""]}},
        "filtered": {"$binarySize": {"$ifNull": [{"$cond": [{"$eq": [{"$type": "$filtered_dataframe"}, "binData"]}, "$filtered_dataframe", None]}, ""]}},
    }}]
    r = list(db.visualizations.aggregate(pipe))
    if not r:
        return {}
    r = r[0]
    doc = db.visualizations.find_one({"_id": ObjectId(oid)})
    am = sum(len(m["dataframe"]) for row in doc.get("active_matrices", []) for m in row
             if isinstance(m.get("dataframe"), (bytes, bytearray)))
    pm = sum(len(m["dataframe"]) for m in doc.get("preview_matrices", [])
             if isinstance(m.get("dataframe"), (bytes, bytearray)))
    return {"session_doc_bytes": r["total"], "transformed_blob_bytes": r["transformed"],
            "filtered_blob_bytes": r["filtered"], "active_matrices_blob_bytes": am,
            "preview_matrices_blob_bytes": pm}


def parse_resp(r):
    body = r.get_data()
    out = {"http_status": r.status_code, "response_bytes": len(body)}
    status, err, payload = "ok", None, None
    try:
        payload = json.loads(body)
    except Exception:  # noqa: BLE001
        payload = None
    if r.status_code == 413:
        status = "rejected_413"
    if isinstance(payload, dict) and payload.get("error_type"):
        status = "app_error"
        err = f"{payload.get('error_type')}: {payload.get('error_message')}"[:1500]
    return out, status, err, payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, required=True)
    ap.add_argument("--run-id", default=bc.new_run_id())
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--variant", choices=["counts", "tpm"], default="counts",
                    help="counts: integer matrix; tpm: float TPM-like companion file")
    args = ap.parse_args()
    S = args.size
    out = args.out or (bc.RAW_DIR / f"{args.run_id}.jsonl")
    rec = bc.Recorder(out, args.run_id, "legacy")

    client = bc.bench_client()
    bc.ensure_ownership(client)
    dbname = f"{bc.BENCH_DB_PREFIX}legacy_{args.variant}_S{S}"
    if dbname in client.list_database_names():
        bc.register_owned_db(client, dbname)
        bc.drop_owned_db(client, dbname)
    bc.register_owned_db(client, dbname)

    import app as mm_app
    if mm_app.client.address[1] != bc.BENCH_MONGO_PORT:
        raise bc.UnsafeEnvironment("app.py connected to an unexpected MongoDB port")
    bdb = client[dbname]
    mm_app.db = bdb  # runtime rebinding of the module global to the isolated DB
    import process_file
    import filter_dataframe
    import pandas as pd

    manifest = json.loads((bc.DATA_DIR / "manifest.json").read_text())
    finfo = manifest["files"][f"legacy_wide_S{S}.tsv"]
    if args.variant == "tpm":
        path = bc.DATA_DIR / finfo["tpm_companion"]["file"]
        fbytes = finfo["tpm_companion"]["bytes"]
    else:
        path = bc.DATA_DIR / f"legacy_wide_S{S}.tsv"
        fbytes = finfo["bytes"]
    base = {"dataset": path.name, "variant": args.variant, "file_bytes": fbytes, "features": finfo["rows"],
            "max_content_length": mm_app.app.config["MAX_CONTENT_LENGTH"]}
    tc = mm_app.app.test_client()

    def do_upload(title, db_entry_id="", x=2):
        with open(path, "rb") as fh:
            return tc.post("/upload", data={"form": json.dumps(upload_form(title, db_entry_id, x=x)),
                                            "file": (fh, path.name)},
                           content_type="multipart/form-data")

    session_ids = []
    for rep in range(1, args.reps + 1):
        cold = rep == 1
        oid = None
        with rec.measure("legacy_upload", S, rep, dict(base, matrices=1), cold=cold) as box:
            r = do_upload("Synthetic")
            info, st, err, payload = parse_resp(r)
            box["extra"].update(info)
            box["status"], box["error"] = st, err
            if st == "ok":
                oid = payload["db_entry_id"]["$oid"]
        if oid is None:
            continue
        session_ids.append(oid)
        rec.write(operation="session_doc_after_upload", samples=S, rep=rep, status="ok", **base, **doc_sizes(bdb, oid))

        q_ok = False
        with rec.measure("legacy_query_filter", S, rep, dict(base, query="Filter values > 10 any column"), cold=cold) as box:
            r = tc.post("/query", data={"query": json.dumps(FILTER_QUERY), "url": json.dumps(oid)})
            info, st, err, payload = parse_resp(r)
            box["extra"].update(info)
            box["status"], box["error"] = st, err
            q_ok = st == "ok"
        if q_ok:
            rec.write(operation="session_doc_after_query", samples=S, rep=rep, status="ok", **base, **doc_sizes(bdb, oid))

        with rec.measure("legacy_config", S, rep, dict(base, filtered_present=q_ok), cold=cold) as box:
            r = tc.post("/config", data={"url": json.dumps(oid)})
            info, st, err, payload = parse_resp(r)
            box["extra"].update(info)
            box["status"], box["error"] = st, err
            if isinstance(payload, dict) and "db_entry" in payload:
                de = payload["db_entry"]
                box["extra"]["transformed_json_chars"] = len(de.get("transformed_dataframe") or "") \
                    if isinstance(de.get("transformed_dataframe"), str) else None
                box["extra"]["filtered_json_chars"] = len(de.get("filtered_dataframe") or "") \
                    if isinstance(de.get("filtered_dataframe"), str) else None
            del payload
        # The response body of /config is also re-requested by every native
        # visualization; size is identical, so it is measured once per rep.

    # ---- k = 2: add a second matrix to the first session (merge path) ----
    if session_ids:
        oid = session_ids[0]
        with rec.measure("legacy_upload_second_matrix", S, 1, dict(base, matrices=2,
                         note="same file, different title -> 2*S value columns; triggers merge_db_entry"), cold=False) as box:
            r = do_upload("Synthetic B", db_entry_id=oid, x=3)
            info, st, err, payload = parse_resp(r)
            box["extra"].update(info)
            box["status"], box["error"] = st, err
        if box["status"] == "ok":
            rec.write(operation="session_doc_after_second_matrix", samples=S, rep=1, status="ok", **base,
                      **doc_sizes(bdb, oid))
            with rec.measure("legacy_config_two_matrices", S, 1, dict(base, matrices=2)) as box:
                r = tc.post("/config", data={"url": json.dumps(oid)})
                info, st, err, payload = parse_resp(r)
                box["extra"].update(info)
                box["status"], box["error"] = st, err

    # ---- Function-level breakdown (no Mongo) ----
    meta = upload_form("Synthetic")
    for rep in range(1, 4):
        T = {}
        with rec.measure("legacy_function_breakdown", S, rep, dict(base), cold=(rep == 1)) as box:
            t = time.perf_counter(); df = process_file.convert_to_df(str(path), ".tsv", meta); T["convert_to_df"] = time.perf_counter() - t
            t = time.perf_counter(); df = process_file.rename_df_columns(df, "Synthetic"); T["rename_df_columns"] = time.perf_counter() - t
            t = time.perf_counter(); blob = process_file.df_to_parquet(df); T["df_to_parquet"] = time.perf_counter() - t
            entry = {"active_matrices": [[{"dataframe": blob}, {"dataframe": blob}]]}
            t = time.perf_counter(); process_file.merge_db_entry(entry, sum(entry["active_matrices"], [])); T["merge_db_entry_k2_same"] = time.perf_counter() - t
            t = time.perf_counter(); d2 = pd.read_parquet(BytesIO(blob)); T["read_parquet"] = time.perf_counter() - t
            t = time.perf_counter(); f = filter_dataframe.main(copy.deepcopy(FILTER_QUERY), d2); T["filter_dataframe_main"] = time.perf_counter() - t
            t = time.perf_counter(); js = d2.to_json(orient="records"); T["to_json_records"] = time.perf_counter() - t
            box["extra"].update({f"stage_{k}_s": round(v, 4) for k, v in T.items()})
            box["extra"].update(parquet_bytes=len(blob), records_json_bytes=len(js), filtered_rows=len(f),
                                dtypes=str(df.dtypes.value_counts().to_dict()))
            del js, d2, f, df

    print(f"[legacy] S={S} done", flush=True)


if __name__ == "__main__":
    main()
