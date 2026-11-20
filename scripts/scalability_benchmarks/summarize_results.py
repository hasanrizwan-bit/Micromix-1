#!/usr/bin/env python3
"""Aggregate raw JSONL measurements into machine-readable and Markdown summaries.

Outputs (results/ is small and may be committed; raw data stays in .work/):
  results/<run_id>_measurements.csv   every raw measurement row (flattened)
  results/<run_id>_summary.csv        per (workflow, operation, samples[, variant]):
                                      n, median, min, max, IQR, CV, peak RSS, status counts
  results/<run_id>_summary.json       same as JSON + environment + log-log slopes
  results/<run_id>_tables.md          Markdown tables used in SCALABILITY_BASELINE_RESULTS.md

Only measured values are reported. Non-ok outcomes are kept with their status.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench_common as bc  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402


def load(run_id):
    rows = [json.loads(l) for l in open(bc.RAW_DIR / f"{run_id}.jsonl") if l.strip()]
    return pd.DataFrame(rows)


def slope(df_ok, op, variant=None):
    d = df_ok[df_ok["operation"] == op]
    if variant is not None and "variant" in d:
        d = d[d["variant"] == variant]
    g = d.groupby("samples")["seconds"].median()
    g = g[g > 0]
    if len(g) < 3:
        return None
    x, y = np.log(g.index.to_numpy(float)), np.log(g.to_numpy(float))
    return round(float(np.polyfit(x, y, 1)[0]), 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    args = ap.parse_args()
    df = load(args.run_id)
    df = df[df["operation"] != "_process"].copy() if "operation" in df else df
    procs = load(args.run_id)
    procs = procs[procs["operation"] == "_process"]
    if "variant" not in df:
        df["variant"] = None
    df["variant"] = df["variant"].fillna("")
    bc.RESULTS_DIR.mkdir(exist_ok=True)
    out = bc.RESULTS_DIR / args.run_id

    flat = df.drop(columns=[c for c in df.columns if df[c].map(lambda v: isinstance(v, (dict, list))).any()])
    flat.to_csv(f"{out}_measurements.csv", index=False)

    keys = ["workflow", "operation", "samples", "variant"]
    recs = []
    for k, g in df.groupby(keys, dropna=False):
        ok = g[g["status"] == "ok"]
        sec = ok["seconds"].dropna() if "seconds" in ok else pd.Series(dtype=float)
        r = dict(zip(keys, k))
        r["n_total"] = len(g)
        r["n_ok"] = len(ok)
        r["statuses"] = ";".join(f"{s}={c}" for s, c in g["status"].value_counts().items())
        if len(sec):
            q1, q3 = np.percentile(sec, [25, 75])
            r.update(median_s=round(float(sec.median()), 4), min_s=round(float(sec.min()), 4),
                     max_s=round(float(sec.max()), 4), iqr_s=round(float(q3 - q1), 4),
                     cv=round(float(sec.std(ddof=1) / sec.mean()), 3) if len(sec) > 1 and sec.mean() > 0 else None)
            if "cold" in ok and ok["cold"].notna().any():
                cold = ok[ok["cold"] == True]["seconds"]  # noqa: E712
                warm = ok[ok["cold"] == False]["seconds"]  # noqa: E712
                r["cold_s"] = round(float(cold.median()), 4) if len(cold) else None
                r["warm_median_s"] = round(float(warm.median()), 4) if len(warm) else None
        for col in ("peak_rss_mb", "peak_delta_mb", "response_bytes", "session_doc_bytes",
                    "transformed_blob_bytes", "filtered_blob_bytes", "active_matrices_blob_bytes",
                    "preview_matrices_blob_bytes", "export_bytes", "inserted_documents", "file_bytes",
                    "parquet_bytes", "records_json_bytes", "heap_used_mb", "documents"):
            if col in g and g[col].notna().any():
                r[col] = float(g[col].max()) if col.startswith("peak") or col == "heap_used_mb" else float(g[col].dropna().median())
        stage_cols = [c for c in g.columns if c.startswith("stage_") or c.endswith("_seconds")]
        for c in stage_cols:
            if c in ok and ok[c].notna().any():
                r[c] = round(float(ok[c].median()), 4)
        errs = g["error"].dropna().unique().tolist() if "error" in g else []
        r["error_example"] = errs[0][:300] if errs else ""
        recs.append(r)
    summ = pd.DataFrame(recs).sort_values(keys)
    summ.to_csv(f"{out}_summary.csv", index=False)

    ok = df[df["status"] == "ok"]
    slopes = {}
    for op in ["expression_import_total", "retrieval_raw_find", "retrieval_load_rows", "matrix_build_full",
               "matrix_page1_function", "matrix_page2_function", "matrix_page1_http", "matrix_export_function",
               "pcoa_parse", "pcoa_run_on_matrix_total", "heatmap_cluster_matrix_total",
               "hclust_js_items"]:
        s = slope(ok, op)
        if s is not None:
            slopes[op] = s
    for v in ("counts", "tpm"):
        s = slope(ok, "legacy_function_breakdown", v)
        if s is not None:
            slopes[f"legacy_function_breakdown[{v}]"] = s
        s = slope(ok, "legacy_config", v)
        if s is not None:
            slopes[f"legacy_config[{v}]"] = s
    env_path = bc.RAW_DIR / f"{args.run_id}.environment.json"
    env = json.loads(env_path.read_text()) if env_path.exists() else {}
    json.dump({"run_id": args.run_id, "environment": env, "loglog_slopes_time_vs_samples": slopes,
               "processes": procs.to_dict(orient="records"),
               "summary": json.loads(summ.to_json(orient="records"))},
              open(f"{out}_summary.json", "w"), indent=1, default=str)

    # Markdown tables
    md = [f"# Tables for run {args.run_id}\n", "## Log-log slopes (time vs samples, medians)\n",
          "| operation | slope |", "|---|---|"]
    md += [f"| {k} | {v} |" for k, v in slopes.items()]
    md += ["", "## Process outcomes\n", "| suite | samples | status | wall s |", "|---|---|---|---|"]
    md += [f"| {r.workflow} | {r.samples} | {r.status} | {r.seconds} |" for r in procs.itertuples()]
    md += ["", "## All operations\n",
           "| workflow | operation | variant | S | n ok/total | median s | IQR s | min–max s | peak RSS MB | statuses |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for r in summ.itertuples():
        med = getattr(r, "median_s", None)
        med = "" if med is None or (isinstance(med, float) and math.isnan(med)) else med
        rng = ""
        if med != "":
            rng = f"{r.min_s}–{r.max_s}"
        iqr = getattr(r, "iqr_s", "")
        iqr = "" if iqr is None or (isinstance(iqr, float) and math.isnan(iqr)) else iqr
        pk = getattr(r, "peak_rss_mb", "")
        pk = "" if pk is None or (isinstance(pk, float) and math.isnan(pk)) else pk
        md.append(f"| {r.workflow} | {r.operation} | {r.variant} | {r.samples} | {r.n_ok}/{r.n_total} | {med} | {iqr} | {rng} | {pk} | {r.statuses} |")
    Path(f"{out}_tables.md").write_text("\n".join(md) + "\n")
    print(f"wrote {out}_summary.csv/.json, {out}_measurements.csv, {out}_tables.md")


if __name__ == "__main__":
    main()
