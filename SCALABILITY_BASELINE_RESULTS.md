# Micromix Scalability — Phase 1 Baseline Results

- **Run ID:** `baseline-20261119c` (2026-11-20, 01:03–02:43 UTC)
- **Code under test:** `feature/scalability` @ `d0f53c05` (unmodified application code)
- **Framework:** `scripts/scalability_benchmarks/` (see its `README.md`)
- **Machine-readable results:** `scripts/scalability_benchmarks/results/`
  - `baseline-20261119c_raw.jsonl`: every measurement
  - `_measurements.csv`, `_summary.csv`, `_summary.json`, `_tables.md`
  - `_environment.json`
  - `dataset_manifest.json`

Every number in this report was measured. Nothing is estimated. Tests that failed, were rejected by the application, or were skipped are labelled as such. Two earlier runs were thrown away because the laptop slept in the middle of measurements; they are not used anywhere here. In the valid run, **0** measurements were flagged as invalid because of host sleep.

---

## 1. Executive summary

| Question | Measured answer |
|---|---|
| Largest dataset the **legacy** workflow completes | **250 samples** (integer counts, one matrix). With float/TPM values it only reaches **100**. With two matrices in one session: 100 (counts) or 32 (TPM). |
| Largest dataset the **orthology** workflow completes | **1,000 samples**, but only at function level. The HTTP upload route rejects files above 100 samples with **413**, because the 250-sample file is 131 MB and the cap is 50 MB. At 1,000 samples, each page request takes about **170 s** and uses about **6 GB** of process memory. |
| Does the 16 MB BSON limit cause real failures? | **Yes.** Every legacy upload at 500 samples (counts) or 250 samples (TPM) fails with `BSON document too large (21.9 MB / 25.1 MB)`. Adding a second matrix fails with `'update' command document too large`. |
| Is the "degradation near 500 samples" reproducible? | **Yes, for the legacy path, but it is a hard failure rather than a slowdown.** Legacy uploads hit the BSON wall between 250 and 500 samples. Timings stay under 1 s right up to that point. |
| Does pagination rebuild the full orthology matrix? | **Yes.** Page 2 costs the same as page 1 at every size (for example 169 s vs 171 s at 1,000 samples). More than 99.9 % of each page request is spent rebuilding the matrix; formatting the 50 rows takes 0.05 s. |
| Most significant confirmed bottleneck | **Legacy:** the whole matrix is stored inside one session document, at least three times over. **Orthology:** every request rebuilds the full matrix from about G×S MongoDB documents. |

---

## 2. Environment and methodology

### 2.1 Environment

| Item | Value |
|---|---|
| OS / hardware | macOS 27.0.1 (Darwin 27.0.0), Apple M1 Pro (8 cores), 16 GB RAM, on AC power, `caffeinate -i -m -s` |
| Python | 3.11.15 (existing venv `~/Micromix-1/Website/backend/venv`; nothing new installed) |
| Libraries | pandas 2.2.3, NumPy 1.26.4 (OpenBLAS 0.3.23, 8 pthreads, no thread environment variables set), SciPy 1.11.4, PyMongo 3.12.1, pyarrow 24.0.0, Flask 3 |
| MongoDB | 8.2.9. Disposable `mongod` on 127.0.0.1:**27099**, its own dbPath (`.work/mongo-data`), `--wiredTigerCacheSizeGB 1` |
| Node.js | v26.0.0 |

### 2.2 Safety and isolation

- **Branch and status checked:** the active branch is `feature/scalability` and it descends from `d0f53c05`. The backup branch `backup/pre-scalability-2026-11-19-clean` is still present and points to `d0f53c05`. The working tree was clean before this work. The only changes are a new `scripts/scalability_benchmarks/`, this report, and one `.gitignore` rule. Nothing was committed.
- **The developer database was never contacted.** That is the `mongod` on 27017 (`/opt/homebrew/var/mongodb`).
  - The harness sets `MONGO_URI` to the benchmark port before `app.py` is imported.
  - It refuses port 27017.
  - It checks that `app.client.address` is port 27099.
- **Writes and drops are restricted to benchmark databases.** An ownership marker plus an owned-database registry limit writes and drops to `mmbench_*` databases.
- **No application code, schema, index, limit or calculation was modified.** Route-level tests rebind the module global `app.db` to the benchmark database at runtime.

### 2.3 Datasets

The generator is `generate_datasets.py`, version 1.0.0, with seed **20261119**. Full parameters and SHA-256 checksums are in `results/dataset_manifest.json`.

- **Structure:** 6,000 orthogroups and 8 strains.
  - 5,075 core orthogroups (present in all strains); the rest are accessory.
  - 177 paralog orthogroups.
  - 2 replicates per strain and condition; ⌈S/16⌉ conditions.
- **Counts:** negative-binomial with log-normal gene means (median about 150, matching the Pseudomonas reference median of 138).
  - 8 % of genes respond to each condition.
  - 2 % of genes are zero-inflated.
  - 0.5 % of orthology measurement rows are dropped, and accessory genes are structurally absent.
- **Schema:** checked against the real parsers and validators.
  - `orthology.validation.validate` and `expression_validation.validate` accept the files, with 0 unmatched orthogroups and 0 duplicate rows.
  - The legacy file loads through `process_file.convert_to_df`.

| S | Legacy counts TSV | Legacy TPM TSV | Orthology long TSV | Orthology rows |
|---|---|---|---|---|
| 32 | 0.81 MB | 1.26 MB | 16.7 MB | 177,721 |
| 100 | 2.28 MB | 3.68 MB | 52.3 MB | 555,393 |
| 250 | 5.52 MB | 9.04 MB | 130.6 MB | 1,388,561 |
| 500 | 10.9 MB | 18.0 MB | 261.3 MB | 2,777,044 |
| 1,000 | 21.7 MB | 35.8 MB | 522.5 MB | 5,553,931 |

The reference table is `orthology_reference.tsv`: 44,653 rows, 4.3 MB. TPM is a float companion to the counts file. It was added because float matrices compress much worse in Parquet, which matters for the 16 MB question.

### 2.4 Procedure

- **Process isolation:** each (suite, size) runs in its own subprocess, so peak memory is not inflated by earlier sizes.
  - Memory guard: 6,144 MB of process RSS, sampled every 20 ms.
  - Timeouts: 30 min for most suites, 3 h for orthology.
- **Repetitions:** 5 by default.
  - Reduced to 3 or 1 when a single run is longer than about 60 s, or for the slowest orthology steps at 500 and 1,000 samples.
  - The actual count appears as `n` in the tables.
  - Medians and IQR are reported.
- **Cold and warm runs:** the first repetition in a fresh process is marked `cold`. Cold and warm results differed by less than 10 % everywhere except one: the first `/config` call, which includes app import and warm-up.
- **HTTP level:** requests go through Flask `test_client()`, which uses real routing, form parsing and `MAX_CONTENT_LENGTH`. There is no network socket and no browser.
- **Memory measure:** "Peak RSS" is the whole process. "Δ" is the peak minus the RSS before the operation.

---

## 3. Results — orthology workflow (highest priority)

### 3.1 Import (`parse → validate → preview → store_expression_import`)

| S | HTTP route `/expression_upload` | Import total, median (n) | parse | validate | build docs (`iterrows`) | `insert_many` | Docs inserted | Peak RSS |
|---|---|---|---|---|---|---|---|---|
| 32 | ok, 6.8 s | 6.76 s (3) | 0.14 | 0.30 | 3.6 | 2.6 | 177,721 | 484 MB |
| 100 | ok, 21.5 s | 21.4 s (3) | 0.42 | 0.90 | 11.4 | 8.6 | 555,393 | 904 MB |
| 250 | **413 rejected** (130.6 MB > 50 MB) | 54.3 s (3)\* | 1.0 | 2.2 | 28.0 | 23.0 | 1,388,561 | 1.62 GB |
| 500 | **413 rejected** | 116.4 s (1)\* | 2.1 | 4.5 | 56.4 | 53.3 | 2,777,044 | 2.31 GB |
| 1,000 | **413 rejected** | 291.7 s (1)\* | 4.0 | 9.1 | 113.7 | 164.7 | 5,553,931 | 3.68 GB |

\* Function level: the same call sequence as `import_expression_reference`, which bypasses the HTTP cap. Rows marked this way are not reachable through the UI today.

Import time is linear in S (log-log slope 1.08). About 95 % of it is per-row Python document building plus a single `insert_many`.

### 3.2 Storage (`orthogroup_expression`, after import)

| S | Documents | Avg doc size | Data size | On-disk storage | Index size (7 indexes) |
|---|---|---|---|---|---|
| 32 | 177,721 | 458 B | 81 MB | 9.9 MB | 7.7 MB |
| 100 | 555,393 | 459 B | 255 MB | 35.8 MB | 31.1 MB |
| 250 | 1,388,561 | 459 B | 638 MB | 89.2 MB | 94.6 MB |
| 500 | 2,777,044 | 459 B | 1,275 MB | 180 MB | 157 MB |
| 1,000 | 5,553,931 | 460 B | 2,555 MB | 359 MB | **382 MB** |

On disk, the indexes are as large as the data. At 6,000 × 1,000, the logical size is 2.6 GB, compared with 48 MB for the equivalent float64 matrix.

### 3.3 Retrieval and matrix construction

| S | Raw `find` (list of dicts) | `_load_rows` (find + DataFrame + per-cell normalise) | **`build_matrix` full** | Peak RSS (Δ) |
|---|---|---|---|---|
| 32 | 0.40 s (5) | 0.85 s (5) | **8.35 s** (5) | 525 MB (213) |
| 100 | 1.18 s (5) | 2.61 s (5) | **11.2 s** (5) | 1.24 GB (753) |
| 250 | 2.92 s (5) | 6.44 s (5) | **17.6 s** (5) | 2.53 GB (1,726) |
| 500 | 6.64 s (3) | 17.8 s (3) | **33.0 s** (1) | 3.89 GB (3,355) |
| 1,000 | 13.9 s (3) | 79.2 s (3) | **194.0 s** (1) | 5.08 GB (4,414) |

`explain()` shows that `totalDocsExamined` equals the document count (5.55 M at 1,000 samples), with MongoDB execution time of 5.2 s.

#### Stage breakdown of `build_matrix` (single run each; same internal calls in the same order)

| Stage | 32 | 100 | 250 | 500 | 1,000 |
|---|---|---|---|---|---|
| `_load_rows` | 0.85 | 2.49 | 6.47 | 15.3 | 65.7 |
| `detect_duplicates` | 0.09 | 0.26 | 0.65 | 1.51 | 16.2 |
| **`_build_row_metadata`** (Python groupby loop over 6,000 orthogroups) | **7.02** | **7.31** | **7.81** | 9.54 | 43.6 |
| `_collapse_paralogs` | 0.13 | 0.39 | 1.00 | 2.16 | 14.4 |
| `pivot_table` + sort | 0.03 | 0.10 | 0.27 | 0.57 | 1.22 |
| sample→strain `mode()` + `_sample_metadata` | 0.16 | 0.50 | 1.28 | 3.13 | 34.9 |
| CPM / log2CPM | <0.01 | 0.01 / 0.04 | 0.03 / 0.04 | 0.07 / 0.08 | 0.14 / 0.16 |
| Format 50 page rows | 0.002 | 0.006 | 0.013 | 0.025 | 0.049 |

### 3.4 Pagination (50 rows) — is anything cached?

| S | Page 1, function (n) | Page 2, function (n) | Page 1, HTTP | Page 2, HTTP | HTTP response size | Peak RSS |
|---|---|---|---|---|---|---|
| 32 | 8.07 s (5) | 8.00 s (5) | 8.31 s | 8.23 s | 55 KB | 0.52 GB |
| 100 | 11.3 s (5) | 11.3 s (5) | 10.9 s | 10.9 s | 123 KB | 1.25 GB |
| 250 | 17.2 s (3) | 17.3 s (3) | 17.8 s | 18.0 s | 272 KB | 2.58 GB |
| 500 | 34.2 s (3) | 32.6 s (3) | 36.4 s | 30.9 s | 521 KB | 4.12 GB |
| 1,000 | **169.0 s** (3) | **171.1 s** (3) | 182.8 s | 171.8 s | 1.0 MB | **6.03 GB** |

- **No caching.** The page 2 / page 1 ratio is 0.95–1.01 at every size.
- **Each page request repeats the full build.** Page time equals full-build time within noise.
- **Formatting is negligible.** Rendering the page rows takes 0.002–0.05 s, so 99.97 % or more of each request is matrix rebuild.
- **Near the memory limit at 1,000 samples.** Peak RSS reached 6.03 GB, 98 % of the 6.14 GB guard.

### 3.5 Options (page 1; n = 5 at 32 and 100 samples, n = 1 at 250; not run above 250)

| Option | 32 | 100 | 250 |
|---|---|---|---|
| default (raw) | 8.07 | 11.3 | 17.2 |
| CPM | 8.59 | 10.8 | 18.0 |
| log2(CPM+1) | 8.43 | 10.8 | 17.4 |
| replicate mean | 8.39 | 10.9 | 17.3 |
| paralog = max | 8.25 | 11.0 | 17.6 |
| filter to 2 of 8 strains | 5.67 | 6.32 | 7.95 |
| free-text search | 2.33 | 5.85 | 13.9 |

Transformations, replicate aggregation and paralog rules cost almost nothing beyond the rebuild. Filters only help because they reduce the number of documents loaded.

### 3.6 Export (TSV)

| S | `build_matrix_export` | HTTP export route | Export size | Peak RSS |
|---|---|---|---|---|
| 32 | 8.47 s (5) | 8.50 s | 2.1 MB | 0.50 GB |
| 100 | 11.7 s (5) | 11.6 s | 3.5 MB | 1.21 GB |
| 250 | 18.8 s (5) | 19.0 s | 6.5 MB | 2.55 GB |
| 500 | 33.5 s (1) | not run | 11.6 MB | 4.07 GB |
| 1,000 | 168.8 s (1) | not run | 21.8 MB | 5.89 GB |

The HTTP export route was only run up to 250 samples to save time; at function level, export is a full rebuild plus serialisation.

---

## 4. Results — legacy session workflow

All requests go through Flask `test_client()`: one `/upload` (new session), then `/query` (`Filter values > 10, any column`), then `/config`. Each repetition uses a new session.

### 4.1 Integer counts

| S | File | Upload `/upload` (n) | Session doc after upload | after `/query` | `/query` | `/config` time | **`/config` response** | Peak RSS |
|---|---|---|---|---|---|---|---|---|
| 32 | 0.81 MB | 0.048 s (5) | 1.63 MB | 2.20 MB | 0.025 s | 0.134 s | 14.2 MB | 319 MB |
| 100 | 2.28 MB | 0.098 s (5) | 4.57 MB | 6.12 MB | 0.050 s | 0.353 s | 42.5 MB | 668 MB |
| 250 | 5.52 MB | 0.214 s (5) | 11.0 MB | **14.8 MB** | 0.095 s | 0.797 s | **105 MB** | 1.17 GB |
| 500 | 10.9 MB | **FAIL ×5**: `BSON document too large (21,887,288 bytes)` | — | — | not reachable | not reachable | — | 486 MB |
| 1,000 | 21.7 MB | **FAIL ×5**: `BSON document too large (43,500,498 bytes)` | — | — | not reachable | not reachable | — | 844 MB |

### 4.2 Float TPM values (same genes and samples)

| S | File | Upload | Session doc after upload / after query | `/config` time | `/config` response |
|---|---|---|---|---|---|
| 32 | 1.26 MB | 0.071 s | 3.42 / 4.53 MB | 0.119 s | 16.1 MB |
| 100 | 3.68 MB | 0.147 s | 10.2 / **13.5 MB** | 0.367 s | 48.9 MB |
| 250 | 9.04 MB | **FAIL ×5**: `BSON document too large (25.1 MB)` | — | — | — |
| 500 | 18.0 MB | **FAIL ×5** (49.9 MB) | — | — | — |
| 1,000 | 35.8 MB | **FAIL ×5** (99.5 MB) | — | — | — |

### 4.3 Second matrix in the same session (k = 2, triggers `merge_db_entry`)

| Variant, S | Result | Session doc |
|---|---|---|
| counts 32 / 100 | ok (0.10 / 0.20 s) | 3.17 / 9.05 MB |
| counts 250 | **FAIL**: `'update' command document too large` | — |
| TPM 32 | ok (0.14 s) | 6.77 MB |
| TPM 100 | **FAIL**: `'update' command document too large` | — |

### 4.4 What fills the session document

The document holds the same Parquet blob three times, plus a fourth filtered copy after `/query`:

- `transformed_dataframe`
- `active_matrices[].dataframe`
- `preview_matrices[].dataframe` (a deep copy)
- `filtered_dataframe` (after `/query`)

For example, at 100 samples (counts): each Parquet copy is 1.52 MB, giving 4.57 MB after upload and 6.12 MB after the filtered copy is added. The rejected document sizes (21.9 MB at 500 counts, 43.5 MB at 1,000) are almost exactly 3 × the measured Parquet size (7.30 MB and 14.5 MB). So the failure is caused by the duplication itself, not by data volume alone: **one copy of the 1,000-sample matrix (14.5 MB) would fit under 16 MB.**

### 4.5 `/config` payload

- **Size grows linearly with S.** The response is about 420 KB per sample (counts).
- **The double JSON is confirmed.** At 250 samples, the transformed and filtered matrices each contribute about 45 MB of records-oriented JSON, plus base64 copies of the Blobs.
- **Server time is small.** 0.8 s at 250 samples.
- **The browser cost was not measured in Phase 1.** That includes parsing 105 MB twice and Vue reactivity over it.

### 4.6 Function-level breakdown (outside Flask/Mongo, all sizes, n = 3)

| S | `convert_to_df` | `df_to_parquet` | **`merge_db_entry` (k=2)** | `filter_dataframe.main` | `to_json(records)` | Parquet / records JSON |
|---|---|---|---|---|---|---|
| 32 | 0.015 | 0.007 | 0.049 | 0.003 | 0.015 | 0.54 / 5.9 MB |
| 100 | 0.048 | 0.016 | 0.151 | 0.007 | 0.043 | 1.5 / 18 MB |
| 250 | 0.098 | 0.037 | 0.362 | 0.016 | 0.108 | 3.7 / 45 MB |
| 500 | 0.187 | 0.072 | 1.80 | 0.031 | 0.208 | 7.3 / 89 MB |
| 1,000 | 0.387 | 0.144 | **18.3** | 0.062 | 0.447 | 14.5 / 178 MB |

TPM at 1,000 samples: `merge_db_entry` takes 21.7 s. The merge test merges a matrix with itself, which is what the code does for the first matrix (it is merged with itself). It goes from 1.8 s to 18.3 s when S doubles from 500 to 1,000, which is worse than quadratic. Every other stage is linear.

### 4.7 HTTP 413

The legacy path never reached the 50 MB cap: the largest file, TPM at 1,000 samples, is 35.8 MB. The 16 MB BSON limit is hit first, at a file size of only 5.5–9 MB.

---

## 5. Numerical analyses

### 5.1 PCoA (`pcoa/service.py`, Euclidean)

The application rejects a 6,000-gene matrix outright at every size: `Found 6000 feature columns, which exceeds the current limit of 5000` (`MAX_FEATURES`). The measurements below therefore use the largest accepted shape, S × 5,000 features.

| S | `parse_matrix` (n=3) | pdist | Centring (two n³ matmuls) | `eigh` | `run_pcoa_on_matrix` total (n=5) | Peak RSS |
|---|---|---|---|---|---|---|
| 32 | 0.11 s | 0.001 | <0.001 | <0.001 | 0.025 s | 184 MB |
| 100 | 0.33 s | 0.007 | 0.013 | 0.002 | 0.026 s | 225 MB |
| 250 | 0.85 s | 0.051 | 0.016 | 0.043 | 0.130 s | 377 MB |
| 500 | 1.74 s | 0.190 | 0.028 | 0.159 | 0.429 s | 571 MB |
| 1,000 | 3.59 s | 0.723 | 0.260 | **1.71** | **2.26 s** | 701 MB |

- **Parsing is linear in S and is the larger cost up to 500 samples.** The parser is a pure-Python per-cell loop.
- **`eigh` dominates the math at 1,000 samples** (×10.8 when S doubles from 500 to 1,000, about cubic).
- `MAX_SAMPLES = 2000` was respected; no size above 1,000 was run.

### 5.2 Server clustered heat map (`clustered_heatmap/service.py`, 6,000 genes × S)

| S | Row distance (6,000×S) | Column distance | Row linkage (incl. distance) | Column linkage | `cluster_matrix` total (n=3) | Peak RSS |
|---|---|---|---|---|---|---|
| 32 | 0.17 s | 0.001 | 0.55 s | 0.001 | 0.71 s | 473 MB |
| 100 | 0.65 s | 0.008 | 0.83 s | 0.008 | 1.19 s | 529 MB |
| 250 | 2.30 s | 0.048 | 1.56 s | 0.047 | 2.35 s | 692 MB |
| 500 | 4.97 s | 0.19 | 3.00 s | 0.19 | 4.64 s | 944 MB |
| 1,000 | 14.1 s | 0.79 | 6.57 s | 0.78 | **10.2 s** | 1.13 GB |

- **Row clustering dominates.** The cost is O(G²·S). Memory is about 300 MB extra for the 18M-entry condensed row distance matrix.
- **Inconsistent stage timings.** The standalone `pdist` timing is larger than `linkage`, which includes its own distance computation (SciPy's internal pdist path is faster than the standalone one in this build). Stage values are therefore indicative only. The end-to-end `cluster_matrix` totals are the authoritative numbers.
- **HTTP transport was not benchmarked.** The JSON payload and the 50 MB cap on the route were not tested.

### 5.3 Browser UPGMA (`frontend/src/lib/distances.js` + `hclust.js` under Node)

| Items n | 32 | 100 | 250 | 500 | 1,000 | 2,000 | 6,000 (gene rows) |
|---|---|---|---|---|---|---|---|
| Total (n=3) | 0.002 s | 0.006 s | 0.010 s | 0.060 s | 0.418 s | **3.32 s** | **skipped (unsafe)** |
| `hclust` share | — | — | — | 0.055 | 0.396 | 3.26 | — |

- **Scaling is about cubic.** Time rose ×7.9 between 1,000 and 2,000 items.
- **6,000 items was not run.** Row clustering of all genes in the browser was skipped deliberately: from the measured cubic trend it would take tens of minutes on the main thread. This is a judgement, not a measurement.
- **Browser cost not included.** The measurement excludes rendering and Vue overhead.

---

## 6. Observed errors and hard limits

| Limit | Where | First size hit (6,000 genes) | Observed outcome |
|---|---|---|---|
| 16 MB BSON, single upload | `process_file.add_matrix` → `insert_one` | **500** (counts), **250** (TPM) | `BSON document too large (21.9 / 25.1 MB)`, returned as Upload Error JSON |
| 16 MB BSON, second matrix | `insert_update_entry` `$set` | **250** (counts), **100** (TPM) | `'update' command document too large` |
| 50 MB upload cap | `app.py` `MAX_CONTENT_LENGTH` | Orthology: **250** samples (131 MB file) | HTTP 413 with a clean JSON error |
| PCoA `MAX_FEATURES` = 5,000 | `pcoa/service.py:84` | **All sizes** (6,000 features) | `PcoaInputError`; must subset to ≤5,000 genes |
| PCoA `MAX_SAMPLES` = 2,000 | `pcoa/service.py:80` | Not reached | — |
| Benchmark memory guard (6.1 GB) | harness | Not exceeded. Orthology at 1,000 samples peaked at **6.03 GB** | — |

Within the measured range there were no timeouts, no crashes and no `memory_guard_exceeded` aborts.

---

## 7. Scaling versus sample count

Log-log slopes of median time against S (1 = linear, 2 = quadratic, 3 = cubic):

| Operation | Slope (32→1,000) | Notes |
|---|---|---|
| Orthology import | 1.08 | Linear |
| Raw `find` of all measurements | 1.04 | Linear |
| `_load_rows` | 1.27 | Linear up to 500, then ×4.5 from 500 to 1,000 |
| `build_matrix` / page / export | 0.8 overall | About 7 s fixed cost plus a linear term up to 500; **×5.9 from 500 to 1,000** |
| Legacy `/config` (≤250) | 0.87 | Linear in payload |
| Legacy `merge_db_entry` | ×10 from 500 to 1,000 | Worse than quadratic |
| PCoA total | 1.34 | `eigh` alone ×10.8 from 500 to 1,000 (≈cubic) |
| Server heat map | 0.77 | Linear in S (G fixed) |
| Browser UPGMA (items) | 1.81 overall; ×7.9 from 1,000 to 2,000 | ≈cubic |

Medians in seconds against S, for the main entry points:

```
S          32     100    250    500    1000
orth page  8.1    11.3   17.2   34.2   169.0
orth build 8.3    11.2   17.6   33.0   194.0
orth import 6.8   21.4   54.3   116.4  291.7
legacy upl 0.05   0.10   0.21   FAIL   FAIL
legacy cfg 0.13   0.35   0.80   n/a    n/a
pcoa total 0.03   0.03   0.13   0.43   2.26   (5,000 features)
heatmap    0.71   1.19   2.35   4.64   10.2
```

---

## 8. Confirmed bottlenecks and open hypotheses

### Confirmed by measurement

1. **Legacy: matrix duplication inside a single session document causes hard failures.** Uploads fail at 500 samples with counts, at 250 with floats, and at 250 or 100 with two matrices. The document is about 3× the Parquet size.
2. **Legacy: `/config` sends about 420 KB of JSON per sample.** That is 105 MB at 250 samples, including two records-JSON copies.
3. **Orthology: every page or export request rebuilds the whole matrix.** There is no caching; page 2 costs the same as page 1.
4. **Orthology: the one-document-per-measurement layout is costly.**
   - 460 B per value; 2.6 GB of data plus 382 MB of indexes at 1,000 samples.
   - Retrieval time and memory scale with G×S Python dictionaries: 4.2 GB Δ just to `find` 5.5 M documents.
5. **Orthology: `_build_row_metadata` costs about 7 s per request regardless of S.** It is the dominant cost for small datasets (85 % of an 8 s page at 32 samples).
6. **Orthology HTTP upload is capped at about 100 samples** by the 50 MB limit with the long format.
7. **PCoA cannot accept 6,000-feature matrices at any sample count** (`MAX_FEATURES`). Its `eigh` step scales cubically.
8. **Browser UPGMA scales cubically.**
9. **`merge_db_entry` scales worse than quadratically** (18 s at 1,000 samples, k = 2, function level).

### Remaining hypotheses (not measured in Phase 1)

- **The jump from 500 to 1,000 orthology samples has not been explained.** Time went from 33 to 194 s, with every stage growing 4–11×. It is probably memory pressure (about 6 GB process plus `mongod` on a 16 GB host) rather than algorithmic scaling. Confirming this needs a re-run with swap and page-fault counters, or on a larger-memory host.
- **The cause of the `merge_db_entry` slowdown is unconfirmed.** The suspect is `pd.merge` without `on=`, which joins on all shared columns.
- **Browser-side costs are unmeasured.** These include parsing the 105 MB `/config` twice, Vue 2 deep reactivity, the `b-table` with S columns, deck.gl per-cell objects, and the volcano plot. A Chrome Performance profile is needed.
- **Concurrent-user behaviour on the single-process Flask dev server is untested.**
- **Real user data may compress differently.** The real Pseudomonas or Salmonella values may produce different Parquet sizes, which would move the BSON threshold between the measured counts and TPM extremes.

---

## 9. Answers to the Phase-1 questions

1. **Legacy maximum:** 250 samples × 6,000 genes (integer counts, one matrix). Float data: 100.
2. **Orthology maximum:** 1,000 samples at function level, with about 170 s per page and 6.0 GB peak. Through the HTTP upload route: 100 samples.
3. **Dominant costs:**
   - Legacy: BSON size from the triplicated Parquet blobs, and the size of the `/config` JSON. Server CPU is under 1 s.
   - Orthology time: loading and normalising G×S documents, plus row-metadata and sample-metadata groupby loops, on every request.
   - Orthology memory: the Python dictionaries and object DataFrames for about 5.5 M rows (4–5 GB Δ).
4. **500-sample degradation:** reproduced. For the legacy workflow it is a hard failure (`BSON document too large`) that appears between 250 and 500 samples for count data.
5. **16 MB limit:** yes. It is the first and only failure observed in the legacy path.
6. **Pagination rebuild cost:** 100 % of the build is repeated on each page: 8 s at 32 samples, 11 s at 100, 17 s at 250, 33 s at 500, 169 s at 1,000. Only 0.002–0.05 s of each request is page-specific.
7. **Scaling classes:**
   - Linear: orthology import, retrieval, `/config`, `convert_to_df`, PCoA parse, server heat map in S.
   - Fixed cost plus linear, with a superlinear break above 500: `build_matrix`.
   - Worse than quadratic: `merge_db_entry`.
   - About cubic: PCoA `eigh`, browser UPGMA.
8. **Address first to reach 1,000 samples:**
   - Legacy: store each session matrix once and outside the document (GridFS or Parquet files), and stop copying blobs into `preview_matrices` and `filtered_dataframe`. This alone removes the measured failure, since one 1,000-sample copy is 14.5 MB.
   - Orthology, in parallel: build the matrix once per (expression set, options) and serve pages from a cache, or from a materialised wide matrix created at import. This cuts page time from 169 s to well under 1 s, because page formatting is already only 0.05 s.
9. **Biggest levers for 10,000 samples:**
   - A columnar numeric matrix store (float32 wide matrix per dataset, about 240 MB at 6,000 × 10,000) instead of per-value documents or in-document blobs.
   - A sliced, binary data API instead of full records-JSON `/config`.
   - Chunked or streamed upload instead of the 50 MB single request.
   - PCoA via truncated SVD or `eigsh`, with `MAX_FEATURES` raised above 6,000.
   - Background jobs for import, export and clustering.
   - Server-side aggregation instead of browser O(n³) clustering.

## 10. Recommended priorities for Phase 2

| # | Change | Evidence |
|---|---|---|
| 1 | Legacy: single out-of-document matrix storage (no triplication), with field projections on `find_one` | §4.1–4.4: the BSON failure at 250–500 samples |
| 2 | Orthology: cache or materialise the built matrix so pages do not rebuild it, and vectorise `_build_row_metadata` and `_sample_metadata` | §3.3–3.4: 100 % rebuild per page; 7 s fixed metadata cost |
| 3 | Orthology: chunked import plus a numeric wide matrix at import, so the HTTP cap is no longer hit at 250 samples | §3.1–3.2 |
| 4 | Legacy: a sliced or columnar `/config` replacement | §4.5: 105 MB at 250 samples |
| 5 | Fix and verify `merge_db_entry` with golden-output tests, because it changes behaviour | §4.6 |
| 6 | PCoA: raise `MAX_FEATURES`, use `eigsh` or SVD | §5.1 |
| 7 | Phase-1b measurements: browser profiling, the memory-pressure check at 1,000 samples, real-dataset compressibility | §8 |

---

## Reproduction

```bash
cd scripts/scalability_benchmarks
PY=~/Micromix-1/Website/backend/venv/bin/python
./start_isolated_mongo.sh &                          # isolated mongod :27099
$PY generate_datasets.py                             # checksums in .work/data/manifest.json
caffeinate -i -m -s $PY run_benchmarks.py --run-id <id> --orthology-timeout-s 10800   # on AC power
$PY summarize_results.py --run-id <id>
```
