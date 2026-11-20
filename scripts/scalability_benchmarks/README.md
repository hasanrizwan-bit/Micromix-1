# Micromix scalability benchmarks — Phase 1 (baseline)

Reproducible, read-only measurement of the **current, unmodified** Micromix
code at 32, 100, 250, 500 and 1,000 samples × ~6,000 genes/orthogroups.
No application code, schema, index, limit or scientific calculation is
changed. Results are written to `SCALABILITY_BASELINE_RESULTS.md` (repo root)
and `results/`.

## Layout

| File | Purpose |
|---|---|
| `start_isolated_mongo.sh` | Starts a disposable `mongod` on **127.0.0.1:27099** with its own dbPath in `.work/mongo-data/` (never 27017, never the Homebrew dbPath). |
| `bench_common.py` | Safety guards (port check, ownership marker, owned-DB registry), RSS sampler + memory guard, host-sleep detection, JSONL recorder, environment capture. |
| `generate_datasets.py` | Deterministic synthetic data generator (seed 20261119). |
| `bench_orthology.py` | Orthology workflow: import, storage, retrieval, `build_matrix`, pagination, variants, export. |
| `bench_legacy.py` | Legacy session workflow through Flask `test_client()`: `/upload`, `/query`, `/config`, session-document sizes, k=2 merge, function breakdown. |
| `bench_numerical.py` | PCoA (`pcoa/service.py`) and server clustered heat map (`clustered_heatmap/service.py`). |
| `bench_hclust_node.mjs` | Browser clustering code (`frontend/src/lib/distances.js`, `hclust.js`) under Node. |
| `run_benchmarks.py` | Orchestrator: one subprocess per (suite, size), timeouts, failure isolation. |
| `summarize_results.py` | Aggregates raw JSONL → `results/<run>_summary.{csv,json}`, `_measurements.csv`, `_tables.md`. |
| `.work/` (git-ignored) | Datasets, raw JSONL, logs, mongod data. |

## Requirements

Python 3.11 with the backend requirements plus `psutil` and `threadpoolctl`.
The baseline used the existing venv `~/Micromix-1/Website/backend/venv`
(pandas 2.2.3, NumPy 1.26.4, PyMongo 3.12.1, pyarrow 24.0.0, SciPy 1.11.4,
Flask). No new packages were installed. Also: `mongod` (8.2.9 used) and
Node.js (v26 used).

```bash
PY=~/Micromix-1/Website/backend/venv/bin/python   # or any env with backend deps
cd scripts/scalability_benchmarks
```

## 1. Start the isolated database (separate terminal)

```bash
./start_isolated_mongo.sh            # foreground; Ctrl-C to stop
```

Safety rules enforced in code:
* `MONGO_URI` is forced to `mongodb://127.0.0.1:27099/` **before** `app.py` is
  imported; an already-set different `MONGO_URI` aborts the run; port 27017 is
  refused.
* On first connect the instance must be empty (or hold only an empty
  `micromix` DB created by `app.py`'s index bootstrap); an ownership marker is
  written to `bench_meta.ownership`. Every later run verifies it.
* Benchmarks only write to `mmbench_*` databases registered in the marker and
  only drop databases that are registered there.
* To reset everything: stop mongod and delete `.work/mongo-data/`.

## 2. Generate datasets

```bash
$PY generate_datasets.py                  # ~35 s, ~1.1 GB in .work/data/
$PY generate_datasets.py --sizes 32 100   # subset
```

`manifest.json` records the generator version, all parameters, byte sizes,
row counts and SHA-256 checksums. Outputs per size S:
`legacy_wide_S{S}.tsv` (integer counts), `legacy_wide_tpm_S{S}.tsv`
(float TPM-like companion), `orthology_expression_long_S{S}.tsv`; plus one
shared `orthology_reference.tsv`.

Generator design: 6,000 orthogroups, 8 strains, 85 % core / 15 % accessory
orthogroups, 3 % paralog orthogroups (2 copies in 1–3 strains), 2 replicates,
⌈S/16⌉ conditions, negative-binomial counts with log-normal gene means
(median ≈150), per-gene dispersion 0.05–0.4, library-size factor
lognormal(0, 0.25), 8 % condition-responsive genes, 2 % zero-inflated genes,
0.5 % dropped orthology measurement rows. Sample *j* is identical in every
dataset size (per-sample `SeedSequence` spawn keys). Schema follows
`orthology/schema.py` and the Pseudomonas `orthogroup_expression_long.tsv`.

## 3. Run

```bash
# everything (≈2–4 h; orthology dominates). Keep the machine on AC power.
caffeinate -i -m $PY run_benchmarks.py --run-id my-run

# selected suites / sizes
$PY run_benchmarks.py --run-id my-run --suites legacy legacy_tpm numerical hclust_js
$PY run_benchmarks.py --run-id my-run --suites orthology --sizes 32 100 --orthology-timeout-s 10800

# single benchmark directly
$PY bench_orthology.py --size 100 --run-id my-run
```

Guards: `BENCH_MEM_LIMIT_MB` (default 6144; the worker exits with code 3 and
records `memory_guard_exceeded`), `BENCH_TIMEOUT_S` / `--orthology-timeout-s`
(subprocess killed, recorded `timeout`). If the host sleeps during a
measurement (wall clock vs. monotonic clock gap > 2 s) the row is recorded as
`invalid_host_sleep` and excluded from statistics.

## 4. Summarise

```bash
$PY summarize_results.py --run-id my-run
```

## Interpreting the outputs

* Each JSONL row = one measurement: `operation`, `samples`, `rep`, `cold`,
  `status`, `seconds`, `peak_rss_mb` (process RSS sampled every 20 ms),
  `peak_delta_mb` (peak minus RSS before the operation), plus
  operation-specific fields (`session_doc_bytes`, `response_bytes`,
  `stage_*_s`, collection stats, …).
* `status`: `ok`, `app_error` (Micromix returned its JSON error, message in
  `error`), `rejected_413`, `rejected_by_app` (explicit validation limit,
  e.g. PCoA `MAX_FEATURES`), `memory_guard_exceeded`, `timeout`,
  `skipped_unsafe`, `invalid_host_sleep`.
* `_process` rows record each subprocess outcome.
* Repetitions: 5 by default; reduced to 3 (or 1) for operations whose single
  run exceeds 60 s (or the budget) and at S ≥ 500 for the slowest orthology
  steps — the `n_ok` column in the summary shows the actual count.
  Medians and IQR / CV are reported. `cold` marks the first run in a fresh
  process (`cold_s` vs `warm_median_s`).
* RSS is the whole Python process (includes the Flask app and earlier
  allocations not yet returned to the OS); `peak_delta_mb` is the better
  per-operation indicator.
* Stage breakdowns (`stage_*`) re-run the same internal functions in the same
  order as the application to attribute time; totals come from the real entry
  points.

## Known methodological limits

* HTTP is exercised through Flask's in-process `test_client()` (real routing,
  request parsing and `MAX_CONTENT_LENGTH`), not a network socket or the
  browser. Browser parse/render costs are not measured in Phase 1.
* The orthology import at sizes whose file exceeds the 50 MB upload cap is
  measured at function level (`import_expression_reference` call sequence)
  and labelled as such; the HTTP route is separately recorded as 413.
* The isolated mongod uses `--wiredTigerCacheSizeGB 1`.
