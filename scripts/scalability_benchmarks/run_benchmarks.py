#!/usr/bin/env python3
"""Orchestrates the Phase-1 baseline benchmarks.

Every (suite, size) runs in its own Python/Node process so that:
  * peak RSS is not polluted by earlier sizes,
  * a memory-guard abort (exit 3) or wall-clock timeout only loses that one
    benchmark, and the remaining independent benchmarks still run.

Suites: legacy, legacy_tpm, orthology, numerical, hclust_js.

Examples:
    python run_benchmarks.py --suites legacy numerical --sizes 32 100
    python run_benchmarks.py                      # everything, all sizes
    python run_benchmarks.py --run-id <id> ...    # append to an existing run

Results: .work/raw_results/<run_id>.jsonl (+ environment JSON); then run
summarize_results.py to produce results/*.csv|json|md.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench_common as bc  # noqa: E402

HERE = Path(__file__).resolve().parent
HCLUST_SIZES = [32, 100, 250, 500, 1000, 2000]
HCLUST_UNSAFE = {6000: "row clustering of 6,000 genes with the O(n^3) browser UPGMA: "
                       "~2e11 inner-loop steps (>1 h extrapolated); not run"}


def run(cmd, timeout, log, rec_path, run_id, suite, size, env=None):
    t0 = time.time()
    with open(log, "a") as fh:
        fh.write(f"\n=== {' '.join(map(str, cmd))}\n")
        fh.flush()
        try:
            p = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, timeout=timeout,
                               cwd=HERE, env=env)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            rc = "timeout"
    status = {0: "ok", 3: "memory_guard_exceeded", "timeout": "timeout"}.get(rc, f"failed_rc_{rc}")
    with open(rec_path, "a") as fh:
        fh.write(json.dumps({"run_id": run_id, "workflow": suite, "operation": "_process",
                             "samples": size, "status": status, "seconds": round(time.time() - t0, 1),
                             "timeout_s": timeout, "cmd": " ".join(map(str, cmd))}) + "\n")
    print(f"[run] {suite:10s} S={size:<5} -> {status} ({time.time() - t0:.0f} s)", flush=True)
    return status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suites", nargs="+",
                    default=["legacy", "legacy_tpm", "numerical", "hclust_js", "orthology"])
    ap.add_argument("--sizes", type=int, nargs="+", default=bc.SIZES)
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--timeout-s", type=int, default=bc.DEFAULT_TIMEOUT_S)
    ap.add_argument("--orthology-timeout-s", type=int, default=5400)
    args = ap.parse_args()

    run_id = args.run_id or bc.new_run_id()
    bc.RAW_DIR.mkdir(parents=True, exist_ok=True)
    rec_path = bc.RAW_DIR / f"{run_id}.jsonl"
    log = bc.WORK / "logs" / f"{run_id}.log"
    log.parent.mkdir(parents=True, exist_ok=True)

    client = bc.bench_client()  # aborts unless the isolated instance is up
    bc.ensure_ownership(client)
    env_path = bc.RAW_DIR / f"{run_id}.environment.json"
    if not env_path.exists():
        env_path.write_text(json.dumps(bc.capture_environment(client), indent=2, default=str))
    if not (bc.DATA_DIR / "manifest.json").exists():
        sys.exit("No datasets: run generate_datasets.py first.")
    print(f"[run] run_id={run_id}\n[run] results -> {rec_path}\n[run] log -> {log}", flush=True)

    py = sys.executable
    env = dict(os.environ)
    for suite in args.suites:
        if suite == "hclust_js":
            for n in HCLUST_SIZES:
                cmd = ["node", "--max-old-space-size=4096", "bench_hclust_node.mjs", "--n", str(n),
                       "--dim", "32", "--reps", "3", "--out", str(rec_path), "--run-id", run_id,
                       "--label", "hclust_js_items"]
                run(cmd, 900, log, rec_path, run_id, "numerical", n, env)
            for n, why in HCLUST_UNSAFE.items():
                with open(rec_path, "a") as fh:
                    fh.write(json.dumps({"run_id": run_id, "workflow": "numerical",
                                         "operation": "hclust_js_items", "samples": n,
                                         "status": "skipped_unsafe", "error": why}) + "\n")
            continue
        for S in args.sizes:
            if suite == "legacy":
                cmd = [py, "bench_legacy.py", "--size", str(S), "--run-id", run_id, "--out", str(rec_path)]
                to = args.timeout_s
            elif suite == "legacy_tpm":
                cmd = [py, "bench_legacy.py", "--size", str(S), "--run-id", run_id, "--out", str(rec_path),
                       "--variant", "tpm"]
                to = args.timeout_s
            elif suite == "orthology":
                cmd = [py, "bench_orthology.py", "--size", str(S), "--run-id", run_id, "--out", str(rec_path)]
                to = args.orthology_timeout_s
            elif suite == "numerical":
                cmd = [py, "bench_numerical.py", "--size", str(S), "--run-id", run_id, "--out", str(rec_path)]
                to = args.timeout_s
            else:
                sys.exit(f"unknown suite {suite}")
            run(cmd, to, log, rec_path, run_id, suite, S, env)
    print(f"[run] finished. Summarise with: python summarize_results.py --run-id {run_id}")


if __name__ == "__main__":
    main()
