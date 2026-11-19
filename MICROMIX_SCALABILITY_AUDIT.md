# MICROMIX_SCALABILITY_AUDIT.md

Micromix scalability and performance audit (read-only)

- **Date:** 2026-11-19
- **Scope:** `Website/backend` (Flask, MongoDB, pandas, the `orthology/`, `pcoa/` and `clustered_heatmap/` packages, plugins), `Website/frontend/src` (Vue 2 and Bootstrap-Vue), and the stand-alone `Heatmap/` and `ClusteredHeatmap/` plugin apps.
- **Method:** static code reading only. No code was changed, nothing was installed, and no database operation or benchmark was run. **None of the numbers below are measurements.** Sizes and run times are arithmetic estimates from array shapes and algorithmic complexity.

**Confidence labels**
- **[C] Confirmed by code:** the behaviour is directly visible in the source.
- **[S] Strongly suspected:** follows from the code, but runtime impact depends on the data and environment.
- **[B] Requires benchmarking.**

**Notation**
- *G* = genes or orthogroups (about 6,000).
- *S* = samples (value columns).
- *N* = stored long-format measurement rows (about G×S).
- *k* = number of uploaded source matrices.

Line numbers refer to the working tree on the audit date.

---

## 1. Executive Summary

Micromix has **two separate data paths** with different scaling behaviour:

1. **The legacy "session" path.** It runs Upload, then `/query`, then `/config`, then the visualizations. The whole wide matrix is stored as Parquet blobs **inside one MongoDB document per session**, held 3–4 times over. Every request re-reads the full document, and the full matrix is shipped to the browser as records-oriented JSON. All visualizations (deck.gl heatmap, clustered heatmap, PCoA, volcano) start from that full download.
2. **The newer multi-strain orthology path.** It runs `/upload_orthogroups`, then `/expression_upload`, then `/expression_imports/<id>/matrix`. It stores **one MongoDB document per measurement** and rebuilds the full orthogroup × sample matrix in pandas **on every page request**.

**Overall assessment: the slowdown near 500 samples is most likely the result of several limits that all start to bite at about the same size, not one bottleneck.** The most likely contributors at 6,000 × 500 (about 3M cells):

- **(a) MongoDB's 16 MB document limit.** Each session document holds `transformed_dataframe`, `active_matrices[].dataframe`, `preview_matrices[].dataframe` and `filtered_dataframe`. 3M float cells in Parquet is plausibly 10–25 MB per copy, so the document probably reaches or exceeds 16 MB in this range. Past that point, writes fail outright rather than slow down. [S/B]
- **(b) The `/config` response.** It re-serialises the full matrix twice as records-JSON, plus base64 copies of the Parquet blobs. That is probably 100+ MB of JSON, parsed twice in the browser. [C for behaviour, B for size]
- **(c) Vue 2 deep reactivity.** It is applied to multi-million-property arrays, with no `Object.freeze` anywhere. [C]
- **(d) `dataframe.vue`.** It renders a `b-table` with one sortable column per sample and no column virtualisation. [C]
- **(e) Browser-side clustering.** It uses an O(n³) UPGMA (`lib/hclust.js`) on the main thread. [C]

Each of these is tolerable at 32–100 samples. They begin to compound at a few hundred.

**At 10,000 samples**, the current code hits several hard limits before any performance question arises:

- 50 MB upload cap (`app.py:267`)
- 16 MB BSON document limit
- PCoA `MAX_SAMPLES = 2000` and `MAX_FEATURES = 5000` (`pcoa/service.py:80,84`)
- Browser memory needed for 60M-cell JSON and per-cell JS objects

**Storing** 10k samples is feasible with a different storage layout. **Building** a 6k × 10k matrix (480 MB as float64, 240 MB as float32) is feasible server-side. **Analysing** all samples is feasible only with O(n²) or better algorithms (current PCoA is O(n³)). **Rendering** 60M cells literally is not meaningful; it requires server-side aggregation or tiling.

---

## 2. Architecture Overview

### 2.1 Components

| Layer | Component | Key files |
|---|---|---|
| Frontend shell | Vue 2.6 SPA, Bootstrap-Vue | `Website/frontend/src/App.vue`, `components/dataframe.vue`, `search_query.vue`, `toolbar.vue` |
| Native visualizations | Clustered heatmap (client-side and server-side variants), PCoA, volcano | `components/clustered-heatmap/*`, `components/pcoa/*`, `components/volcano-plot/*`, `lib/*.js` |
| iframe plugins | deck.gl heatmap (`Heatmap/`), stand-alone clustered heatmap (`ClusteredHeatmap/`), Clustergrammer (external service) | `Heatmap/frontend/src/components/deckglCanvas.vue`, `Heatmap/backend/app.py`, `ClusteredHeatmap/backend/app.py`, `Website/backend/plugins/*.py` |
| Orthology UI | Orthogroup and expression import, reference selector, paginated matrix table | `components/orthology/*.vue` |
| Backend | Flask (Werkzeug dev server: `Dockerfile` uses `CMD ["flask","run"]`, `DEBUG = True` at `app.py:250`) | `Website/backend/app.py` (2,341 lines) |
| Session matrix pipeline | Upload, merge, filter and select | `process_file.py`, `filter_dataframe.py`, `initial_transformation.py`, `filter_genelists.py`, `row_filters.py`, `matrix_selection.py`, `experimental_features.py` |
| Orthology pipeline | Parse, validate, store, build matrix | `orthology/parse.py`, `validation.py`, `expression_validation.py`, `storage.py`, `expression_matrix.py`, `schema.py` |
| Analysis services | PCoA (classical MDS), hierarchical clustering | `pcoa/service.py`, `pcoa/dataset_store.py`, `clustered_heatmap/service.py` |
| Database | MongoDB | Collections listed in 2.2 |

### 2.2 MongoDB collections

| Collection | Granularity | Indexes |
|---|---|---|
| `visualizations` | **One document per session.** Holds the matrix as Parquet `Binary` in `transformed_dataframe`, `filtered_dataframe`, `active_matrices[][].dataframe` and `preview_matrices[].dataframe` | `_id` only. Sufficient, since all access is by `_id`. |
| `plugins` | Plugin registry | `_id` |
| `orthogroup_references` | One document per (orthogroup, strain, gene) | **None** (`storage.py:211,254,493,501,542,647` filter on `import_id`) |
| `orthogroup_reference_imports` | Manifest per reference import | None |
| `orthogroup_expression` | **One document per measurement**. All values are strings (`parse.py` uses `dtype=str`) | 7 indexes (`expression_matrix.py:991-1017`). 4 are single-field and redundant or unused (`expression_set_id`, `reference_import_id`, `orthogroup_id`, `sample_id`). |
| `orthogroup_expression_sets` | Manifest per expression import (embeds `sample_names` and a duplicate copy in `summary`) | None |

### 2.3 Data flow: legacy session path

```
Browser upload (TSV/CSV/XLSX, ≤50 MB: app.py:267)
 → POST /upload → process_file.add_matrix (process_file.py:206)
     convert_to_df: pd.read_csv + adjust_numeric_dtype (per-column loop)
     find_one(full session doc) (process_file.py:211)
     df_to_parquet(df)                 → active_matrices[..].dataframe   (copy 1)
     merge_db_entry: re-decode ALL k blobs, outer-merge → transformed_dataframe (copy 2)
     make_preview_matrices: deepcopy incl. blobs → preview_matrices   (copy 3)
     $set entire document (process_file.py:72)
 → POST /query (app.py:512): find_one(full) → read_parquet → filter_dataframe.main → filtered_dataframe (copy 4)
 → POST /config (app.py:1094): find_one(full) → read_parquet → to_json(orient='records') ×2
     → bson.json_util.dumps(whole doc incl. base64 blobs) → browser
 → App.vue parses JSON strings (App.vue:694,697) → dataframe.vue b-table
 → Each visualization re-POSTs /config and re-parses:
     deck.gl heatmap   : Heatmap/backend /config (full doc, records JSON) → 1 JS object per cell
     clustered heatmap : lib/matrix.buildMatrix → lib/distances.pairwise → lib/hclust.cluster (browser)
     native clustered  : buildMatrix → POST full matrix JSON → /api/clustered_heatmap (SciPy linkage)
     PCoA              : buildMatrix → client builds full CSV → POST /api/pcoa → pdist+eigh
     volcano           : full /config → O(G) client computation
 → /sample_selection, /matrix_selection: find_one(full) → REPLAY saved query → select → store filtered copy
```

### 2.4 Data flow: orthology path

```
POST /upload_orthogroups → parse → validate → insert_many (orthogroup_references, row per gene)
POST /orthogroup_imports/<rid>/expression_upload (app.py:1603)
   parse (read_csv dtype=str) → validate (vectorised) → iterrows() → list of N dicts → insert_many
POST /expression_imports/<id>/matrix (app.py:1835) → build_matrix (expression_matrix.py:712)
   list(find(query, projection))  ← ALL matching measurements (line 296)
   → DataFrame.from_records → per-column map(_to_number) → dedupe → _build_row_metadata (groupby loop)
   → _collapse_paralogs → pivot_table (G×S dense) → per-sample mode() loops → CPM per-column loop
   → slice ONE page of rows → per-cell Python formatting → JSON (dict per row keyed by all S labels)
POST .../matrix_export → same full build → G×S Python double loop → whole CSV in memory
```

Reference-strain selection is display-only. `build_matrix` does not join against `orthogroup_references`; it only checks that the manifest exists (`expression_matrix.py:725`). Mapping is validated once at import (`expression_validation.py:167-184`). [C]

### 2.5 Duplicated work and unnecessary transfers (summary)

| Duplication | Evidence |
|---|---|
| Full session document read with no projection | **9 times in `app.py`** (L402, 535, 633, 779, 912, 970, 1070, 1116) and twice in `process_file.py` (L100, 211). `/active_plugin` reads the whole document to check one boolean. [C] |
| Parquet decoded for nothing | `/visualization` decodes the matrix (`app.py:976-980`), but the Heatmap, ClusteredHeatmap, PCoA and VolcanoPlot plugins ignore `df`. [C] |
| Full matrix downloaded repeatedly | Each native visualization re-POSTs `/config`: `clusteredHeatmapCanvas.vue:376`, `NativeClusteredHeatmapCanvas.vue:140`, `PcoaCanvas.vue:400`, `VolcanoPlotCanvas.vue:275`, `deckglCanvas.vue:1085`. `App.vue` already holds it. `generate_vis_link` reloads `/config` again (`App.vue:583-587`). [C] |
| Full matrix uploaded back | `NativeClusteredHeatmapCanvas.vue:177` posts the matrix as nested JSON. `pcoaFromMicromix.js:87-97` builds a full CSV in the browser and uploads it. [C] |
| Query replayed | `/sample_selection` (`app.py:649`) and `/matrix_selection` (`app.py:791`) re-run the whole saved query instead of reusing the stored `filtered_dataframe`. [C] |
| Merge rebuilt from scratch | Every upload and removal re-merges all k sources (`process_file.py:121,251,293-304`). [C] |
| Orthology matrix rebuilt per page | Every page or export call runs the whole `build_matrix` pipeline (`expression_matrix.py:712-898`). [C] |

---

## 3. 500-Sample Bottleneck Investigation

None of the candidates below is a hard-coded 500-sample limit. They are ranked by how likely they are to explain degradation starting around 6,000 genes × ~500 samples (about 3M cells).

| # | Candidate | Evidence | Why it bites around 500 samples | Confidence |
|---|---|---|---|---|
| 1 | **16 MB BSON limit on the session document**, with 3–4 Parquet copies | `process_file.py:249` (active_matrices), `:346` (transformed), `:441` (`copy.deepcopy` into `preview_matrices`, blobs included), `app.py:552/680/810` (filtered). Written with `insert_one` / `$set` of the whole document (`process_file.py:72,276`, `app.py:495`) | 3M cells × 3–4 copies. Even well-compressed Parquet gives roughly 10–25 MB per copy, so the total crosses 16 MB around a few hundred samples, depending on precision and compressibility. Symptom: `DocumentTooLarge` errors on upload or filter, not gradual slowness. | Mechanism [C]; exact threshold [B] |
| 2 | **`/config` payload size**, built repeatedly | `app.py:1116` full read; `:1135`, `:1140` `to_json(orient='records')` for both transformed and filtered; then `json_util.dumps` of the whole document, including the Binary blobs (base64, +33%). Records-orient repeats every column name in every row | ~3M cells × (value + repeated key) ≈ 50–150 MB of JSON per copy. The JSON is double-encoded (a JSON string inside JSON), parsed in `App.vue:694,697`, then re-parsed per visualization (`lib/activeDataframe.js:24`) | Behaviour [C]; size [B] |
| 3 | **Vue 2 deep reactivity on large arrays** | No `Object.freeze` / non-reactive storage anywhere. `rawRecords`, `matrix`, `config.*_dataframe` and `layerSettings.*.data` are declared in `data()` (`clusteredHeatmapCanvas.vue:217,382,399`, `deckglCanvas.vue:106,206`) | Vue 2 defines a getter/setter per property. 3M+ observed properties per copy means seconds of main-thread time and hundreds of MB | [C] mechanism; magnitude [B] |
| 4 | **`dataframe.vue` table** | `create_table_headers` (L193-201) creates one sortable field per column. `b-table` with client-side pagination (L55-68), `pageOptions` up to 1000 (L140), scoped slot per cell (L69-79). Search already disabled for freezing (comment L5-7) | 500 columns × 100 rows = 50k cells. At 1000 rows per page, 500k `<td>`. b-table also copies and sorts the full items array | [C] |
| 5 | **Client-side clustering** | `lib/hclust.js:60-78`: every merge re-sorts the active set and scans all pairs, so O(n³). `lib/distances.js:68-84` builds a full square n×n matrix, which `hclust` copies into plain Arrays (L49-55). Runs on the main thread in `clusteredHeatmapCanvas.vue:426-471` and re-runs on every setting change (watchers L319-329) | Row clustering of 6,000 genes is ~3.6×10¹⁰ steps at **any** sample count. Column clustering at S = 500 is ~4×10⁷ steps (cheap), but the distance computation is O(G²·S) = 1.8×10¹⁰ flops for rows | [C]; wall time [B] |
| 6 | **deck.gl heatmap data prep** | `deckglCanvas.vue:1140-1285` creates one object plus a `COORDINATES` array per cell. `Math.max(...allValues)` (L457-458). Full-dataset `stableStringify` + SHA-256 (L1093, L1122-1133) and a sort with `JSON.stringify` in its comparator (L744-756) | 3M objects: ~0.5–1 GB of JS heap. Spread arguments of a few hundred thousand or more can throw `RangeError` | [C]; crash threshold [B] |
| 7 | **50 MB upload cap** | `app.py:267-277` | A 6k × 500 TSV is ~20–40 MB, so it fits. At ~1,000 samples it is rejected (413). That explains a wall just above 500, not slowness at 500 | [C] |
| 8 | **Upload merge** | `process_file.py:293-304`: the loop starts at i = 0 again after seeding with element 0, so the first matrix is merged with itself. `pd.merge(..., how='outer')` has no `on=`, so it joins on **all shared columns**, including numeric ones | Cost and correctness both depend on how many columns are shared. Can multiply row counts or slow badly as columns grow | [C] bug; impact [B] |
| 9 | **Orthology `build_matrix` per page** | `expression_matrix.py:296` `list(collection.find(...))` of all N = G×S docs, string→number conversion (L309-314), per-sample `.mode()` loops (L770-775, L421-433) | 3M documents → several GB of Python dicts, and tens of seconds per page click | [S]; [B] |

**Conclusion.** The evidence points to **several interacting limits, with storage and transport as the shared root cause**: the whole matrix is copied into one document, then sent in full, as verbose JSON, to a reactive UI. Candidates 1–4 all scale as O(G·S) with large constants and appear together around 500 samples. Candidate 5 is driven mainly by gene count, not sample count, so it would hurt clustered-heatmap users at any S. Benchmarks (Section 8) are needed to tell which one triggers first on the deployed hardware.

---

## 4. Component-by-Component Analysis

Each item gives: **location, issue, consequence, scaling, proposal, confidence**.

### 4.1 Database and storage

**D1. Session matrix stored in one document, 3–4 copies**
- **Location:** `process_file.py:249,346,349,441`; `app.py:552,680,810`.
- **Consequence:** hard failure at 16 MB, plus large I/O on every read.
- **Scaling:** O(G·S) per copy, hard-capped by BSON.
- **Proposal:** store each matrix once, outside the document (GridFS, or Parquet/Arrow files on disk or in object storage, keyed by content hash), and keep only references in `visualizations`. Stop deep-copying blobs into `preview_matrices`. Store `filtered_dataframe` as a row/column index selection rather than a materialised copy.
- **Confidence:** [C].

**D2. Full-document `find_one` with no projection**
- **Location:** the 11 sites listed in 2.5.
- **Consequence:** every request, including trivial ones like `/active_plugin` (`app.py:912`), transfers every blob.
- **Scaling:** O(G·S·copies) per request.
- **Proposal:** field projections. For example, `{'locked':1}` for `/active_plugin`, and exclude the `active_matrices` and `preview_matrices` blobs from `/config`.
- **Confidence:** [C].

**D3. Whole-document `$set`**
- **Location:** `process_file.py:72`.
- **Issue:** rewrites all blobs on every change.
- **Proposal:** `$set` only the changed fields.
- **Confidence:** [C].

**D4. Orthology: one document per measurement, all values as strings**
- **Location:** `storage.py:665-679,719-721`; `parse.py:34-41`.
- **Consequence:** at 60M measurements, roughly 18–36 GB plus indexes (estimated from per-document overhead [B]). Counts are re-parsed from strings on every read (`expression_matrix.py:314`).
- **Scaling:** O(G·S) documents.
- **Proposal:** keep the long format for provenance if needed, but at import also **materialise a wide, numeric matrix per expression set**: Parquet/Zarr/NPY of float32 G×S with sample and orthogroup order arrays in the manifest, or one document per orthogroup with a packed float32 array of length S, about 40 KB per document at S = 10k. Store `count` as a number.
- **Confidence:** [C] layout; size [B].

**D5. Index set**
- **Location:** `expression_matrix.py:991-1017`.
- **Issue:** 4 of the 7 indexes are redundant (`expression_set_id` is a prefix of the compound indexes) or unscoped (`orthogroup_id`, `sample_id`, `reference_import_id`). Each insert maintains all 7. `orthogroup_references` and both manifest collections have **no** index on `import_id` / `expression_set_id`, so `distinct`, `find` and `delete_many` scan the collection (`storage.py:211,254,493,501,542,647`).
- **Proposal:** drop the redundant indexes. Add `{import_id:1, strain:1}`, `{import_id:1, orthogroup_id:1}` and unique `{expression_set_id:1}` / `{import_id:1}` on the manifests.
- **Confidence:** [C] for the definitions; benefit [B].

**D6. Import builds all documents in memory**
- **Location:** `storage.py:78,671` (`iterrows`), `:114,723` (single `insert_many`).
- **Issue:** good that `insert_many` is used, but `iterrows` is an O(N·C) Python loop and the whole list is held in RAM. A failure mid-insert leaves partial rows.
- **Proposal:** `read_csv(chunksize=…)`, `to_dict('records')` per chunk, `insert_many(ordered=False)` per chunk, and a manifest status of `importing` → `complete`.
- **Confidence:** [C].

**D7. Expression preview pagination**
- **Location:** `storage.py:847-898`.
- **Issue:** `skip`-based (O(skip)), `count_documents` on every call, no `sort`, so page order is not guaranteed stable.
- **Proposal:** keyset pagination on `(expression_set_id, orthogroup_id, sample_id)`, and cache the count in the manifest.
- **Confidence:** [C].

### 4.2 Backend processing

**B1. No caching of decoded matrices**
- **Location:** every route in 2.5. No `lru_cache` or DataFrame cache exists; only the PCoA `DatasetStore` and the UniProt index are cached.
- **Consequence:** Parquet decode on every interaction.
- **Proposal:** a per-process LRU keyed by `(session_id, content_hash)`, or memory-mapped Arrow files shared across workers.
- **Confidence:** [C].

**B2. `transform_df` copies unconditionally**
- **Location:** `initial_transformation.py:41`.
- **Issue:** `unfiltered_df = df.copy()` runs whenever any transformation exists, but only TPM needs it.
- **Consequence:** +1× matrix memory.
- **Confidence:** [C].

**B3. Whole-frame `df.replace([inf,-inf], nan)` after log or fold-change**
- **Location:** `initial_transformation.py:199-256`.
- **Issue:** scans every column, including strings.
- **Proposal:** apply it to the numeric `filter_area` only.
- **Confidence:** [C].

**B4. Annotation filter**
- **Location:** `initial_transformation.py:476-487`, `filter_genelists.py:333-344`.
- **Issue:** `json.load('static/gene_annotations.json')` on every request, with list-membership loops, so O(A·G).
- **Proposal:** load once and use a `set` / `isin`.
- **Confidence:** [C]. This depends on gene count, not S.

**B5. String filter with a 2-D mask, then `drop_duplicates`**
- **Location:** `filter_genelists.py:317-322,118`.
- **Issue:** O(G·S) row hashing. The authors' own comments at L111-115 note unresponsiveness.
- **Confidence:** [C].

**B6. Per-column Python loops over S columns**
- **Locations:**
  - `experimental_features.adjust_numeric_dtype` (L12-77, ~6 passes per column)
  - `initial_transformation.replace` (L77-152)
  - orthology `_apply_cpm` (`expression_matrix.py:509-518`)
  - `rename_df_columns` (O(S²) list membership, `process_file.py:162`)
  - `matrix_selection.py:171` (O(S²))
- **Consequence:** per-column overhead is negligible at 32 samples and seconds at 10k.
- **Proposal:** vectorise (`matrix.div(colsums, axis=1)`) and use sets.
- **Confidence:** [C].
- **Correctness note:** `adjust_numeric_dtype` fills NaN with `min-1` (`experimental_features.py:35`). This corrupts missing values and must be preserved or fixed deliberately, because it changes scientific results.

**B7. Orthology matrix pipeline**
- **Location:** `expression_matrix.py:712-898`.
- **Steps and costs:**
  - `list(find)` of all rows (L296)
  - `df.apply(axis=1)` search (L320-328)
  - nested `groupby` loop for row metadata (L613-671)
  - `pivot_table` dense G×S (L758)
  - three per-sample `.mode()` passes (L770-775, 421-433)
  - per-cell page formatting (L853-892), where each row's `values` is a dict keyed by all S sample names
  - export double loop over G×S (L943-962)
- **Scaling:** O(N) Python-object work **per page click**. Peak memory is several copies of the G×S matrix plus the N-row object frame.
- **Proposal:**
  - build the wide numeric matrix once at import (D4)
  - cache the transformed variants (raw / CPM / log2CPM)
  - page both rows **and columns**
  - return `values` as arrays aligned to a single `columns` list
  - stream exports via `to_csv` chunks
- **Confidence:** [C]; timings [B].

**B8. Synchronous heavy work on the Werkzeug development server**
- **Location:** `Website/backend/Dockerfile` (`flask run`), `app.py:250` (`DEBUG = True`). No Celery, RQ or executor.
- **Consequence:** one PCoA, merge or export blocks the other requests in the process (GIL contention for pandas work outside BLAS).
- **Proposal:** gunicorn with multiple workers now; a job queue for PCoA, clustering, import and export once matrices exceed about 1,000 samples.
- **Confidence:** [C] config; impact [B].

**B9. Clustergrammer plugin**
- **Location:** `plugins/Clustergrammer.py`.
- **Issue:** `copy.deepcopy(df)` and a synchronous `requests.post` to an external host **with no timeout**. The 200-gene cap is in `App.vue:461-485`.
- **Confidence:** [C].

### 4.3 Matrix builders (frontend)

**M1. `lib/matrix.js` `buildMatrix`**
- **Location:** L91-347.
- **Issue:** O(G·S) time, but it stores `values[id][col]` and `imputed[id][col]` as nested string-keyed objects, plus `colRaw` arrays: about 3×G·S boxed values. `valueColumns.includes` (L123) is O(S²).
- **Consequence at 10k:** many GB, which is infeasible.
- **Proposal:** a `Float32Array` of length G·S with index maps.
- **Confidence:** [C].

**M2. Additional per-visualization copies**
- **Location:** `clusteredHeatmapFromMicromix.js:78-83`; `pcoaFromMicromix.js:87-97` (CSV string); `clusteredHeatmapCanvas.vue:472-486` (`prepareVectors` builds both row and column vector copies).
- **Confidence:** [C].

### 4.4 Visualizations

**V1. PCoA**
- **Location:** `pcoa/service.py`.
- **Algorithm:**
  - Euclidean `squareform(pdist(X))` (L590): O(S²·G) time, n² dense.
  - `centering = np.eye(n) - np.ones((n,n))/n; b = -0.5*centering@squared@centering` (L680-681): **two dense O(n³) matmuls**, about 4 extra n² arrays.
  - `np.linalg.eigh(b)` (L686): **full O(n³) decomposition**, even though only 2 axes are plotted.
  - The parser converts every cell in pure Python (L337-364).
- **Memory:** S = 2,000 needs ~200 MB of n² arrays. S = 10,000 needs ~5–6 GB peak (8 B × 10⁸ × ~7 arrays).
- **Caps:** `MAX_SAMPLES = 2000` (L80) and `MAX_FEATURES = 5000` (L84). The 5,000-feature cap **already rejects a 6,000-orthogroup matrix**.
- **Proposals:**
  1. Double-centre in O(n²) using row and column means.
  2. Use a truncated eigensolver (`scipy.sparse.linalg.eigsh(k≤10)` or randomized).
  3. **For Euclidean distance, PCoA equals PCA on the centred data.** A truncated SVD of the S×G matrix gives identical coordinates in O(S·G·k) without ever forming n². This is scientifically exact for the current metric. Non-Euclidean metrics such as Bray–Curtis would still need the distance route, or landmark/FastMap approximations, which must be labelled as approximate.
  4. Take input from the server-side session matrix instead of the client-built CSV upload.
- **Confidence:** [C] algorithm; timings [B].

**V2. Server-side clustered heatmap**
- **Location:** `clustered_heatmap/service.py:156,171`, `app.py:2286`.
- **Algorithm:** SciPy `linkage(average, euclidean)` on rows and columns: O(n²) memory (condensed: 144 MB for 6k rows, 400 MB for 10k columns), roughly O(n²) time. Computationally feasible at the target.
- **Blockers:** input arrives as a JSON matrix from the browser (limited by the 50 MB body cap), the reordered full matrix is sent back, there is no cap, and it is synchronous.
- **Proposal:** compute from the server-side matrix. Cache the linkages per (matrix hash, metric, transform). Return the order plus an aggregated or tiled view.
- **Confidence:** [C].

**V3. Client-side clustered heatmap**
- **Location:** `clusteredHeatmapCanvas.vue`, `lib/hclust.js`, `lib/distances.js`.
- **Issue:** naive UPGMA, O(n³) time, with an n² square distance matrix (not condensed) copied into plain Arrays. `leaves` arrays are spread at each merge, which is O(n²) in the worst case (`hclust.js:93`). Recursive tree utilities (`treeOrder.js`) risk stack overflow at depth ~10⁴. Recomputed on every `valueMode` / `missingPolicy` / `metric` change. Runs on the main thread (no Web Workers anywhere).
- **Good:** rendering uses a canvas with caps of 500×200 (`MAX_VISIBLE_ROWS/COLS`, L198-199).
- **Gaps:** the column dendrogram SVG is uncapped (L98-105). `aggregateCluster` aggregates across all S columns, not just the visible ones (`lib/aggregate.js:17-62`).
- **Proposal:** retire it in favour of V2 for large inputs, or move it into a Worker with an NN-chain O(n²) algorithm. Enforce a size gate.
- **Confidence:** [C].

**V4. Vendored native heatmap renderer**
- **Location:** `lib/clustered-heatmap-vendor/main.js:882-893`.
- **Issue:** one DOM `<div>` per cell.
- **Consequence:** infeasible beyond ~10⁵ cells.
- **Proposal:** canvas or WebGL.
- **Confidence:** [C].

**V5. deck.gl heatmap**
- **Strength:** WebGL `GridCellLayer` instancing, which can render millions of cells.
- **Problems:**
  - per-cell object creation (`deckglCanvas.vue:1214-1220`)
  - `Object.keys(json[0])` inside the column loop (L1204, O(S²))
  - `Math.max(...)` spread (L457-458)
  - whole-dataset hashing twice (L1093, L730)
  - reactive `rawData`
  - the backend `/config` (`Heatmap/backend/app.py:68-82`) sends the full records JSON
- **Proposal:** binary columnar transfer (Arrow), deck.gl binary attributes (`data.attributes` with typed arrays), a reduce loop for min/max, and hashing on the server.
- **Confidence:** [C].

**V6. Volcano plot**
- **Location:** `lib/volcanoCalc.js:236-313`.
- **Behaviour:** the calculation is O(G) per threshold change, which is fine. `computeColumnStats` (`volcanoPlotFromMicromix.js:90`) is O(G·S) once.
- **Issue:** to use two or three columns, it downloads the **entire** matrix (`VolcanoPlotCanvas.vue:275`). Three `<select>`s each list all S columns (L68-84). SVG with one `<g>` + `<title>` per gene.
- **Proposal:** a server endpoint returning only the selected columns (or precomputed log2FC/p-value), and a searchable column picker.
- **Confidence:** [C].

**V7. PCoA scatter rendering**
- **Location:** `PcoaScatterPlot.vue:90-117`, `PcoaCanvas.vue:185`.
- **Issue:** SVG with one group per sample, plus an unpaginated coordinates table (S rows). Workable at 2k, sluggish at 10k [S].
- **Proposal:** canvas/WebGL points, a quadtree for hit testing, and a virtualised table.
- **Confidence:** [S].

### 4.5 Frontend state and tables

**F1. No `Object.freeze` or non-reactive storage for large data**
- **Locations:** listed in §3 #3.
- **Confidence:** [C].

**F2. `dataframe.vue`**
- **Issue:** no column virtualisation, and sortable fields for every sample. The `dataframe` and `filtered` watchers each call `update_table`, so it runs twice per update (L115-125, acknowledged in a comment).
- **Confidence:** [C].

**F3. Orthology table**
- **Location:** `expressionMatrixTable.vue:45-52,82-89`.
- **Issue:** server-paginated rows (good), but all S columns are rendered per page (50 × 10k = 500k `<td>`), with `toLocaleString` per cell (L181).
- **Confidence:** [C].

**F4. Unvirtualised checkbox list of all sample names**
- **Location:** `expressionMatrixControls.vue:102-103`.
- **Confidence:** [C].

**F5. Selection payloads**
- **Location:** `lib/heatmapSelection.js:134-143`.
- **Issue:** sends every row and column id when only one axis is selected.
- **Confidence:** [C].

---

## 5. 10,000-Sample Feasibility Assessment

Assumes G ≈ 6,000. The numbers are arithmetic estimates, not measurements; "fails" means a hard limit in code or BSON.

| Operation | Complexity (current) | 500 | 1,000 | 2,500 | 5,000 | 10,000 |
|---|---|---|---|---|---|---|
| Legacy upload (file ≤50 MB cap) | O(G·S) parse + O(k) merges | OK | **Rejected (413) unless `MAX_UPLOAD_MB` is raised** | Rejected | Rejected | Rejected |
| Session document storage (3–4 copies) | O(G·S) per copy | Near or over 16 MB [B] | **Fails (BSON)** | Fails | Fails | Fails |
| `/config` transfer + browser parse | O(G·S), records JSON | Slow (~100 MB) [B] | Very slow | Likely tab out-of-memory | Fails | Fails |
| `dataframe.vue` table | O(rows/page × S) DOM | Sluggish | Poor | Unusable | Unusable | Unusable |
| Client clustered heatmap | O(G²·S) distance + O(G³) / O(S³) hclust; O(n²) memory | Slow (row clustering dominated by G) | Slow | Stall | Stall / out-of-memory | Out-of-memory (800 MB+ distance matrix ×2) |
| Server clustered heatmap compute | O(G²·S + S²·G) distance, ~O(n²) linkage | OK | OK | OK [B] | OK-ish [B] | Feasible (~0.5 GB condensed) **if not sent as JSON** |
| PCoA (current) | O(S²·G) + 3×O(S³); ~7 S² arrays | OK if G ≤ 5000 | OK if G ≤ 5000 | **Rejected (`MAX_SAMPLES` 2000)** | Rejected | Rejected; ~5–6 GB if uncapped |
| PCoA via truncated SVD (proposed) | O(S·G·k) | OK | OK | OK | OK | Feasible (~seconds to tens of seconds [B]) |
| Volcano compute | O(G) | OK | OK | OK | OK | OK; only the transport needs fixing |
| deck.gl heatmap | O(G·S) JS objects | Heavy | Very heavy | Out-of-memory | Out-of-memory | Out-of-memory. WebGL itself could render 60M only with binary attributes plus aggregation |
| Orthology import | O(N) docs, 7 indexes | OK-ish | Upload cap | Upload cap | Upload cap | Upload cap; ~60M docs ≈ tens of GB [B] |
| Orthology matrix page | O(N) per click | Seconds to tens of seconds [B] | Tens of seconds | Minutes | Out-of-memory likely | Out-of-memory (60M Python dicts) |
| Orthology export | O(G·S) Python loop + in-memory string | OK | Slow | Slow | Very slow | ~1 GB string in memory |

### Separating the four challenges

| Challenge | Feasible at 10k? | Requirement |
|---|---|---|
| **Store** | Yes | 60M float32 values ≈ 240 MB raw. Columnar or packed storage, not one document per value and not one 16 MB document. |
| **Construct a matrix** | Yes, server-side | 480 MB as float64 (240 MB as float32). Build once, cache, slice. |
| **Analyse all samples** | Yes for linear or O(n²) methods | PCoA via SVD; linkage with O(n²) memory (~400 MB condensed) on a background worker. Not with the current O(n³) / n²-dense code. |
| **Render all samples** | Not literally | 10k columns exceed screen pixels. Needs server-side aggregation (cluster means, binning), tiling, or subset-based views. |

---

## 6. Existing Optimizations

| Feature | Status | Evidence |
|---|---|---|
| Parquet (pyarrow) instead of JSON in Mongo | **Implemented** (but duplicated and in-document) | `df_to_parquet` `app.py:2047`, `process_file.py:316` |
| Upload size limit with a clean 413 | Implemented | `app.py:267-279` |
| Short Mongo server-selection timeout, shared client | Implemented | `app.py:343` |
| Orthology compound indexes | Implemented (partly redundant) | `expression_matrix.py:991-1017`, created at startup `app.py:357-364` |
| Orthology bulk inserts (`insert_many`) with manifest rollback | Implemented (not chunked) | `storage.py:114,723,132-136` |
| Projections and `$in` filter push-down in the matrix load | Implemented | `expression_matrix.py:253-265,292-294` |
| Server-side row pagination (orthology matrix, previews) | **Partially**: output only, built after the full load; no column paging | `expression_matrix.py:80-81,853-892`; `storage.py:485,866` |
| Batched `$in` page fetch (no N+1) | Implemented | `storage.py:542` |
| PCoA caps, streaming row-cap check, bounded LRU/TTL `DatasetStore`, subset re-runs via `dataset_id` | Implemented (process-local) | `pcoa/service.py:80,84,206,243`; `dataset_store.py:69-75` |
| Vectorised pandas: validation, paralog collapse, row filters, TPM, log | Implemented | `expression_validation.py`, `expression_matrix.py:454-499`, `row_filters.py` |
| `select_matrix` uses sets and `isin`, no mutation; empty query returns the input unchanged | Implemented | `matrix_selection.py:119-161`; `filter_dataframe.py:48` |
| Selection stores `[]` instead of a redundant copy | Implemented | `app.py:677-680,807-810` |
| UniProt annotation lazy singleton, O(1) lookup | Implemented | `uniprot_annotation.py:81-237` |
| Server-side clustering (`NativeClusteredHeatmapCanvas` → SciPy) | **Partial**: compute is server-side, but data is round-tripped through the browser | `NativeClusteredHeatmapCanvas.vue:140-181` |
| Canvas heatmap with visible-cell caps (500×200), auto-collapse, aggregate cache | Implemented (client clustered heatmap only) | `clusteredHeatmapCanvas.vue:198-200,464,547-561,589-649` |
| WebGL rendering | Implemented (deck.gl plugin), but data prep is per-cell objects | `deckglCanvas.vue:668` |
| Client-side table pagination | Implemented (rows only) | `dataframe.vue:55-68` |
| Set-based selection state | Implemented | `lib/heatmapSelection.js` |
| Clustergrammer 200-gene cap | Implemented | `App.vue:461-485` |
| Background or async jobs, Web Workers, DataFrame caching, column virtualisation, binary transport | **Absent** | — |

---

## 7. Prioritized Recommendations

Impact: H/M/L. Effort: S/M/L. Risk is mainly the risk of changing scientific results or multi-strain behaviour.

| # | Recommendation | Addresses | Impact | Effort | Risk |
|---|---|---|---|---|---|
| R1 | **Instrument first**: per-route timing, response bytes, and Mongo document size logging (Section 8). Confirm the BSON hypothesis. | §3 | H (decision-making) | S | None |
| R2 | Add field projections to all 11 `find_one` sites; skip the Parquet decode in `/visualization` for URL-only plugins; exclude blobs from `/config`. | D2, 2.5 | H | S | Low |
| R3 | Move session matrices out of the document (GridFS or Parquet files) and store each matrix once. Drop blob copies from `preview_matrices`. Store filtered state as an index selection. Keep the document schema backward-compatible with a migration that reads legacy inline blobs. | D1, D3 | **H (removes the hard 16 MB wall)** | M | Medium (session compatibility) |
| R4 | Fix `merge_db_entry`: the self-merge off-by-one, and an explicit `on=<gene id column>` key. Then merge incrementally. **Verify outputs against current results on the bundled datasets first**, because this changes behaviour. | B (process_file:293-304) | H | S | Medium (scientific output) |
| R5 | Replace `/config` full records-JSON with (a) a metadata-only `/config` and (b) a data endpoint that is paginated and column-sliced, using `orient='split'` or Arrow IPC. Stop double JSON encoding. Make visualizations reuse `App.vue` data or request only the columns they need (volcano: 2–3 columns). | §3 #2, V5, V6 | H | M | Low–Medium |
| R6 | Frontend: freeze large datasets (`Object.freeze`) so Vue 2 does not observe them; virtualise columns in `dataframe.vue` and `expressionMatrixTable.vue`; make the sample picker searchable. | F1–F4 | H at 500–2.5k | S–M | Low |
| R7 | PCoA: O(n²) double centring plus a truncated eigensolver now (identical results to numerical tolerance). Next, a truncated-SVD PCA path for Euclidean (mathematically equivalent). Feed it from the server matrix. Lift `MAX_FEATURES` above 6,000. | V1 | H for analysis | S (step 1), M | Low (validate with the existing `pcoa/tests`) |
| R8 | Orthology: materialise a numeric wide matrix per expression set at import; cache CPM / log2CPM variants; paginate columns; return array-shaped rows; stream exports; chunked import; tidy up indexes. | D4–D7, B7 | H for the multi-strain path | M–L | Medium (paralog/replicate semantics must match the existing tests in `orthology/tests`) |
| R9 | Clustered heatmap: route large inputs to server-side SciPy linkage computed from the stored matrix; cache linkages; return order plus aggregated tiles. Gate the client O(n³) path, e.g. to ≤ 1,000 items, or move it to a Worker. Cap the column dendrogram SVG. | V2–V4 | H for the heatmap | M | Low–Medium (linkage tie-breaking may reorder leaves) |
| R10 | Run gunicorn with multiple workers, not the debug server; use a job queue (RQ or Celery) for PCoA, clustering, import and export above a size threshold. A shared cache is needed (the `DatasetStore` is process-local). | B8 | M–H | M | Low |
| R11 | Vectorise the per-column loops (`adjust_numeric_dtype`, `_apply_cpm`, `replace`), replace O(S²) list membership with sets, cache `gene_annotations.json`, remove the unconditional `df.copy()`. Separately review the NaN→`min-1` behaviour, which is a scientific correctness issue. | B2–B6 | M | S | Low (except the NaN change) |
| R12 | deck.gl: binary attributes, no per-cell objects, reduce-based min/max, no client hashing of the full dataset. Add server-side downsampling for more than ~2M cells. | V5 | M | M | Low |

Targeted improvements (R2–R12) are sufficient; **a full architectural replacement is not justified**. The one structural change that cannot be avoided is R3/R8: moving dense numeric matrices out of per-document and per-value MongoDB layouts. MongoDB can remain the metadata and provenance store.

---

## 8. Benchmarking Plan

### 8.1 Synthetic datasets

Sizes: **S ∈ {32, 100, 500, 1,000, 2,500, 5,000, 10,000}**, crossed with **G ∈ {2,000, 6,000}**, with a fixed random seed per size.

Extend `scripts/generate_transcriptome.py` (or a new generator under `scripts/`) to produce:

- **Counts:** negative-binomial, with per-gene means drawn from a log-normal fitted to the bundled `static/salmonella_salcom_complete_tpm.tsv` / `b-theta-rna-seq_complete.csv`, and gene-specific dispersion. Also emit TPM/CPM versions.
- **Structure:**
  - strains (2–8), conditions (5–50) and replicates (2–4), with condition effects on 5–10% of genes (to give the volcano plot and PCoA real signal)
  - batch effects
  - 0–5% missing values (MCAR plus some gene-specific missingness)
  - some zero-inflated genes
- **Orthology:**
  - orthogroup tables mapping per-strain locus tags
  - ~85% core orthogroups, accessory orthogroups absent in some strains
  - ~3% paralog orthogroups
  - long-format expression files in the exact `EXPRESSION_KNOWN_COLUMNS` schema (`orthology/schema.py:79-108`)
- **Formats:** wide TSV for the legacy path; long TSV for the orthology path.
- **Reproducibility:** record the generator version, seed and checksums.

### 8.2 Operations and metrics

| Operation | Entry point | Metrics |
|---|---|---|
| Expression upload | `POST /upload`, `POST /.../expression_upload` | Wall time, peak RSS, HTTP status (413 / `DocumentTooLarge`), request bytes |
| Database insertion | `process_file.add_matrix`, `storage.store_expression_import` | Insert time, `db.stats()` / `collStats` size and index size, **session document size (`Object.bsonsize`)** |
| Expression retrieval | `find_one` sites, `_load_rows` | `explain("executionStats")`: docsExamined, keysExamined, executionTimeMillis; bytes returned |
| Matrix construction | `merge_db_entry`, `build_matrix` | Wall time, peak memory (tracemalloc / memray), number of DataFrame copies |
| Matrix filtering | `/query`, `/sample_selection`, `/matrix_selection` | Per-stage time (decode, filter, encode, write) |
| PCoA | `pcoa.service` directly, and `/api/pcoa` | Per-stage time (parse, pdist, centring, eigh), peak memory. Also compare against the SVD path for numerical equivalence (Procrustes/correlation of axes up to sign) |
| Heat map clustering | `clustered_heatmap.service`, `lib/hclust.js` (Node harness) | Time and memory for rows and columns separately |
| Volcano | `lib/volcanoCalc.js` | Compute time vs G; transfer bytes |
| API responses | All routes | Time-to-first-byte, total time, payload bytes (raw and gzip) |
| Frontend | Each view | Time to interactive, long tasks > 50 ms, JS heap peak, DOM node count, FPS while scrolling/zooming |

Repeat each measurement at least 5 times; report median and IQR. Record CPU model, RAM, MongoDB version, Python/pandas/numpy versions, and BLAS thread count (`threadpoolctl`). Log errors and failures as outcomes, not as missing data.

### 8.3 Attributing limitations to a layer

- **Database:** Mongo profiler (`db.setProfilingLevel(1, {slowms: 50})`), `explain`, and document sizes. Compare route time against the `find_one` duration.
- **Backend:** timing middleware (`before_request` / `after_request`) logging route, duration and response length. `pyinstrument` or `py-spy record` for flame graphs. `memray` or `tracemalloc` for peak memory. Run the services (`pcoa.service`, `expression_matrix.build_matrix` with `FakeDB` from `orthology/tests/fake_db.py`) **outside Flask** to separate algorithm cost from HTTP cost.
- **Algorithmic:** fit time against S on a log-log plot. A slope of ~1 is linear, ~2 quadratic, ~3 cubic. Expected: PCoA ~3, client hclust ~3, `/config` ~1.
- **Network:** Chrome DevTools network panel (size, TTFB vs content download), and `curl -w '%{size_download} %{time_total}'` against each route.
- **Frontend:** Chrome Performance panel (scripting vs rendering vs GC), Vue Devtools component timings, `performance.mark/measure` around JSON parse, `buildMatrix`, `pairwise`, `cluster` and draw. Heap snapshots before and after freezing data.
- **Load tests:** `locust` with concurrent users against `/config` and `/api/pcoa`, to expose blocking on the single-process development server.

Run benchmarks against a disposable MongoDB instance, never the production database.

---

## 9. Suggested Development Roadmap

| Phase | Goal | Steps | Exit criterion |
|---|---|---|---|
| 0. Baseline | Measure, don't guess | R1 instrumentation; synthetic generator; run the 32–1,000 sample tiers; record document sizes | Baseline report identifying the first failing component at each size |
| 1. Quick wins (→ 1,000 samples) | Remove waste | R2 projections; skip the unneeded decodes; R6 freeze plus column virtualisation; R11 vectorisation and sets; R7 step 1 (O(n²) centring + `eigsh`); add regression tests on the bundled datasets | 1,000 samples work end-to-end on the legacy path; outputs match the baseline |
| 2. Storage and transport (→ 2,500) | Remove hard walls | R3 out-of-document storage; R4 merge fix (validated); R5 sliced/columnar data API; configurable upload limit with chunked or streamed upload | No 16 MB failures; `/config` < a few MB |
| 3. Analysis services (→ 5,000) | Scalable maths | R7 SVD PCoA from the server matrix; R9 server linkage with cache; R10 gunicorn plus job queue; R8 materialised orthology matrix and column paging | PCoA and clustering complete asynchronously at 5k; orthology page < 1 s from cache |
| 4. Visualization at scale (→ 10,000) | Meaningful views | Server-side aggregation/tiling for heat maps; WebGL binary attributes (R12); canvas scatter; precomputed volcano statistics; subset workflows (select a condition or strain first) | 10k × 6k: interactive overview plus drill-down; memory within the target host |

Run the `orthology/tests` and `pcoa/tests` suites at every phase. Add golden-output comparisons for matrix construction (paralog modes, replicate aggregation, CPM) to protect multi-strain behaviour.

---

## 10. Uncertainties and Validation Requirements

| Claim | Status | How to validate |
|---|---|---|
| The session document exceeds 16 MB near 500 samples | Mechanism confirmed; threshold unknown (Parquet compression depends on value precision and repetition) | Upload synthetic 6k × {250…1,000} matrices; log `bsonsize` and errors |
| `/config` payload is ~100 MB at 500 samples | Estimate | Measure response bytes |
| Which of the frontend costs (reactivity, b-table, parse) dominates at 500 | Unknown | Chrome Performance profile with and without `Object.freeze` |
| Client hclust run times | Complexity confirmed; wall time unknown | Node harness timing at n = 500, 1k, 2k |
| PCoA at 10k needs ~5–6 GB and minutes | Estimate from array counts; BLAS-dependent | Run `classical_mds` at n = 1k, 2k, 4k with the cap bypassed in a test harness; extrapolate |
| Orthology storage of ~18–36 GB at 60M docs | Estimate | Insert 1M synthetic docs; measure `avgObjSize` and index size |
| `merge_db_entry` row explosion when shared numeric columns exist | Depends on the data | Merge test with overlapping sample columns |
| Which operations users actually performed when degradation was reported | **Unknown.** The "~500 samples" report has no attached trace | Collect user workflow and logs; reproduce with matching data |
| Whether production runs `flask run` (dev server) as the Dockerfile states | Deployment not inspected | Check the deployed process list |
| Whether the scientific results of the merge / NaN-fill fixes differ from current outputs | Behaviour change | Golden-output diff before merging any fix |

Every timing and size above is an estimate derived from code and array shapes. Section 8 defines the measurements needed to confirm or reject each one.
