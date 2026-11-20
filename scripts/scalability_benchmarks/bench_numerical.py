#!/usr/bin/env python3
"""Numerical-core benchmarks (no MongoDB, no browser).

PCoA  (Website/backend/pcoa/service.py, unmodified):
  * parse_matrix() on the exact CSV a 6,000-feature matrix produces
    -> records the application's own MAX_FEATURES (5000) rejection.
  * parse_matrix() on the largest accepted shape (S samples x 5,000 features).
  * compute_distance_matrix() (pdist + squareform), the double-centring step
    and np.linalg.eigh() timed separately (same expressions as classical_mds),
    plus classical_mds() and run_pcoa_on_matrix() end-to-end.

Clustered heat map (Website/backend/clustered_heatmap/service.py, unmodified):
  * row distance (pdist on 6000 x S), column distance (pdist on S x 6000),
    SciPy average linkage on rows and columns, and cluster_matrix() end-to-end
    (includes list-of-lists -> ndarray conversion and JSON-able output).

Browser clustering (Website/frontend/src/lib/{distances,hclust}.js):
  * run separately by bench_hclust_node.mjs (Node), sizes capped.

Inputs are the log2(x+1) of the synthetic legacy count matrices.
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

if str(bc.BACKEND) not in sys.path:
    sys.path.insert(0, str(bc.BACKEND))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.cluster.hierarchy import linkage  # noqa: E402
from scipy.spatial.distance import pdist  # noqa: E402

from pcoa import service as pcoa  # noqa: E402
from clustered_heatmap import service as chm  # noqa: E402


def load_matrix(S):
    df = pd.read_csv(bc.DATA_DIR / f"legacy_wide_S{S}.tsv", sep="\t")
    genes = df["Locus Tag"].tolist()
    samples = list(df.columns[2:])
    X = np.log2(df.iloc[:, 2:].to_numpy(dtype=float) + 1.0)  # genes x samples
    return genes, samples, X


def pcoa_csv(samples, features, Xs):
    """Sample-by-feature CSV text, as pcoaFromMicromix.js would upload."""
    buf = io.StringIO()
    pd.DataFrame(Xs, index=samples, columns=features).round(6).to_csv(buf, index_label="sample")
    return buf.getvalue().encode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, required=True)
    ap.add_argument("--run-id", default=bc.new_run_id())
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--skip-heatmap-e2e-above", type=int, default=1000)
    args = ap.parse_args()
    S = args.size
    out = args.out or (bc.RAW_DIR / f"{args.run_id}.jsonl")
    rec = bc.Recorder(out, args.run_id, "numerical")
    genes, samples, X = load_matrix(S)
    G = len(genes)
    base = {"features": G}

    # ---------------- PCoA ----------------
    csv_full = pcoa_csv(samples, genes, X.T)
    with rec.measure("pcoa_parse_6000_features", S, 1, dict(base, csv_bytes=len(csv_full))) as box:
        try:
            pcoa.parse_matrix(csv_full, filename="matrix.csv")
            box["status"] = "ok"
        except pcoa.PcoaInputError as exc:
            box["status"] = "rejected_by_app"
            box["error"] = str(exc)
    del csv_full

    F = pcoa.MAX_FEATURES  # largest accepted feature count
    Xp = X[:F, :].T.copy()  # samples x features
    csv = pcoa_csv(samples, genes[:F], Xp)
    pbase = {"features": F, "csv_bytes": len(csv), "note": f"first {F} genes (MAX_FEATURES cap)"}
    parsed = None
    for rep in range(1, min(args.reps, 3) + 1):
        with rec.measure("pcoa_parse", S, rep, pbase, cold=rep == 1):
            parsed = pcoa.parse_matrix(csv, filename="matrix.csv")
    del csv
    if parsed is not None:
        V = parsed.values
        for rep in range(1, args.reps + 1):
            T = {}
            with rec.measure("pcoa_stages", S, rep, pbase, cold=rep == 1) as box:
                t = time.perf_counter(); d = pcoa.compute_distance_matrix(V); T["distance"] = time.perf_counter() - t
                n = d.shape[0]
                t = time.perf_counter()
                squared = d ** 2
                centering = np.eye(n) - np.ones((n, n)) / n
                b = -0.5 * centering @ squared @ centering
                b = (b + b.T) / 2.0
                T["centering"] = time.perf_counter() - t
                t = time.perf_counter(); np.linalg.eigh(b); T["eigh"] = time.perf_counter() - t
                box["extra"].update({f"stage_{k}_s": round(v, 5) for k, v in T.items()})
                del d, squared, centering, b
        for rep in range(1, args.reps + 1):
            with rec.measure("pcoa_run_on_matrix_total", S, rep, pbase, cold=rep == 1):
                pcoa.run_pcoa_on_matrix(parsed)
    del parsed, Xp

    # ---------------- Clustered heat map ----------------
    hbase = {"features": G, "rows": G, "cols": S}
    for rep in range(1, min(args.reps, 3) + 1):
        T = {}
        with rec.measure("heatmap_stages", S, rep, hbase, cold=rep == 1) as box:
            t = time.perf_counter(); pdist(X, metric="euclidean"); T["row_distance"] = time.perf_counter() - t
            t = time.perf_counter(); pdist(X.T, metric="euclidean"); T["col_distance"] = time.perf_counter() - t
            t = time.perf_counter(); linkage(X, method="average", metric="euclidean"); T["row_linkage_total"] = time.perf_counter() - t
            t = time.perf_counter(); linkage(X.T, method="average", metric="euclidean"); T["col_linkage_total"] = time.perf_counter() - t
            T["row_clustering_only"] = T["row_linkage_total"] - T["row_distance"]
            T["col_clustering_only"] = T["col_linkage_total"] - T["col_distance"]
            box["extra"].update({f"stage_{k}_s": round(v, 5) for k, v in T.items()})
    if S <= args.skip_heatmap_e2e_above:
        values = X.tolist()  # what the route receives after JSON decoding
        for rep in range(1, min(args.reps, 3) + 1):
            with rec.measure("heatmap_cluster_matrix_total", S, rep, hbase, cold=rep == 1) as box:
                res = chm.cluster_matrix(genes, samples, values)
                box["extra"]["response_json_bytes"] = len(json.dumps(res))
                del res
    print(f"[num] S={S} done", flush=True)


if __name__ == "__main__":
    main()
