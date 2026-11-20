# Micromix Scalability — Phase 2A: Orthology Matrix Regression Test Results

Branch: `feature/scalability` (base commit `e89fb993`, Phase 1 benchmarks). Backup branch `backup/pre-scalability-2026-11-19-clean` is unchanged at `d0f53c05`.
Python: existing venv `~/Micromix-1/Website/backend/venv` (3.11). Phase 1 benchmarks were **not** re-run.

## 1. Scope and changes

| File | Change |
|---|---|
| `Website/backend/orthology/tests/test_expression_matrix_regression.py` | **New.** 85 regression test cases (pytest-collected, including parametrized cases). |
| `Website/backend/orthology/tests/fake_db.py` | **Test-only fix.** `find()` now honours exclusion-only projections such as `{"_id": 0}`, which pymongo handles this way. Before the fix it returned empty documents, so `storage.get_reference_preview` could not be tested. Existing tests are unaffected. |
| `Website/backend/orthology/tests/test_expression_matrix_mongo_integration.py` | **New.** Opt-in real-MongoDB integration subset: 54 tests plus 4 strict xfail. Skipped unless `MICROMIX_TEST_MONGO_URI` is set. It refuses port 27017 and uses a fresh `micromix_regtest_<uuid>` database per test, dropped afterwards. |
| Application code | **No changes.** `expression_matrix.py`, `storage.py` and the rest of the app are unchanged. |

Run:
```bash
cd Website/backend
# FakeDB suite (the integration tests are skipped automatically)
~/Micromix-1/Website/backend/venv/bin/python -m pytest orthology/tests -q -rxX

# Real-MongoDB subset, using a disposable mongod (never 27017)
mongod --port 27099 --bind_ip 127.0.0.1 --dbpath "$(mktemp -d)" &
MICROMIX_TEST_MONGO_URI=mongodb://127.0.0.1:27099/ \
  ~/Micromix-1/Website/backend/venv/bin/python -m pytest \
  orthology/tests/test_expression_matrix_mongo_integration.py -q -rxX
```

## 2. Test design

- **Canonical dataset.** Two strains: `sA` with samples `sA_c1_r1`, `sA_c1_r2` and `sA_c2_r1`, and `sB` with samples `sB_c1_r1` and `sB_c1_r2`. There are 4 expressed orthogroups and 16 long-form rows. Counts are stored as strings, the same way the importer stores them.
  - OG1: one gene per strain.
  - OG2: two `sA` paralogs (`p2` and `p3`, including a real `0`) plus one `sB` gene.
  - OG3: present only in `sA`, and missing replicate `sA_c1_r2`.
  - OG4: present only in `sB`.
  - OG5: present in the reference table only, with no expression rows.
- **Independent expectations.** The raw matrices for each paralog rule (`RAW_SUM`, `RAW_MEAN` and `RAW_MAX`) and the replicate-aggregated matrix (`AGG_RAW`) are typed in by hand. CPM, log2(count+1) and log2(CPM+1) are calculated in the test from those literals in plain Python, without pandas or calls to the implementation. Several cells are also hard-coded, for example `10/23·1e6 = 434782.6087`.
- **Three comparison levels.**
  - Unrounded internal matrix (`for_export=True`), tolerance 1e-9.
  - Paginated preview (rounded to 4 dp), tolerance 5.1e-5.
  - TSV/CSV export (rounded to 6 dp): exact text for raw output, and a three-way export ↔ full ↔ pages comparison for transformed output.
- **`xfail(strict=True)` specification tests** cover behaviour that the module's own docs (or basic scientific expectations) promise but the code does not deliver. They are expected to fail today. Because they are strict, any change that silently alters this behaviour causes an XPASS, which the suite reports as a failure.

## 3. Tests added and expected numerical behaviour

| # | Area | Tests | Expected behaviour pinned |
|---|---|---|---|
| 1 | Orthogroup→gene mapping | `test_orthogroup_gene_mapping_metadata`, `test_orthogroup_present_in_reference_but_absent_from_expression_not_in_matrix` | `strains` is sorted. `seed_pegs` is a per-strain sorted list. `gene_count` = distinct (strain, seed_peg) pairs. `has_paralog` is set only when one strain has >1 seed_peg. `multi_strain` counts as expected. OG5 (in the reference only) is **not** a matrix row. |
| 2 | Reference strain and annotations | `test_reference_strains_from_summary_and_fallback`, `test_reference_preview_strain_sA`, `..._sB_and_pagination`, `..._copies_in_strain_column_flags_paralog`, `test_matrix_annotation_is_first_loaded_row_not_reference_strain` | Default strain is `Pa.PA14` if present, otherwise the first strain. Paralog label is `p2 (+1 copies)` with joined `p2; p3` and products. A missing member gets the label `missing in selected reference`. `copies_in_strain` overrides the row count. Reference preview pages concatenate to the full list. The matrix gene/product is the first non-null value in load order, across all strains. |
| 3 | Paralog aggregation | `test_raw_matrix_paralog_rules[sum/mean/max/keep_separate]`, `test_cross_strain_cell_is_sum...`, `test_paralog_mean_float_rounding_preview_vs_export`, `test_paralog_mean_skips_missing_member` | OG2/sA becomes `[6,16,8]` (sum), `[3,8,4]` (mean) or `[4,10,8]` (max). `keep_separate` gives the same result as sum. Paralogs are collapsed within each strain, then strains are **summed** into the cell. 4/3 is shown as 1.3333 in the preview and 1.333333 in the export. An NA paralog is skipped, not treated as 0. |
| 4 | Replicate aggregation | `test_replicate_aggregation_values_and_columns[mean/median]`, `test_replicate_median_odd_count_differs_from_mean`, `test_replicate_without_condition_grouped_under_placeholder`, `test_replicate_mean_then_cpm_current_order` | Groups are (strain, condition) and labelled `strain \| condition \| rule`. NaN replicates are skipped (mean(7, NaN) = 7). `column_info` lists the samples in each group. Conditions that are missing are grouped as `(no condition)`. Raw counts are aggregated **before** CPM. |
| 5 | Missing / absent | `test_missing_display_blank_vs_zero_full_matrix`, `test_missing_stays_missing_after_transformations`, `test_true_zero_count_is_not_missing`, `test_all_columns_zero_cpm_is_missing` | 7 missing cells, the same under blank and zero display. A missing cell stays missing after log2/CPM (it does not become log2(1) = 0). A real 0 is not counted as missing. A column with zero total gives NaN CPM with a reported total of 0. |
| 6 | Duplicates | `test_duplicate_rules[6 combos]`, `test_same_gene_different_samples_not_duplicates`, `test_rows_without_seed_peg_collapse_as_duplicates_when_mixed` | Triplicate key 10/5/3 plus paralog 4: sum/sum = 22, mean/sum = 10, first/sum = 14, sum/max = 18, mean/mean = 5, first/max = 10. `duplicate_key_count` = 2. Example keys are listed. Duplicates are not counted as paralogs. Metadata uses the first non-null value. |
| 7 | CPM and log2 | `test_transformations_full_matrix[4 transforms × 3 paralog rules]`, `test_cpm_hand_values_and_totals`, `test_log2_cpm_hand_values`, `test_log2_count_hand_values`, `test_cpm_library_size_depends_on_orthogroup_filter` | CPM = count / column total (NaN excluded) × 1e6. Each column total is 1,000,000. `cpm_column_totals` are taken before the log. Under an orthogroup filter, CPM uses the **filtered** library size. |
| 8 | Filtering | `test_filter_strain`, `..._samples_drops_orthogroups...`, `..._condition_and_replicate`, `..._orthogroup_ids`, `..._search_case_insensitive_fields`, `..._search_is_row_level_current_behaviour`, `test_combined_filters_and_aggregation` | Filters are applied before aggregation. A row with no remaining measurements disappears. Integer replicates are converted to strings. Search is case-insensitive over gene, product, seed_peg and orthogroup_id, and works **per row**. |
| 9 | Ordering | `test_row_and_column_order_lexicographic...`, `test_aggregated_column_order_sorted...` | Rows and columns use a plain lexicographic string sort that ignores insertion order (`OG1 < OG10 < OG2`, uppercase before lowercase). Aggregated columns are sorted by (strain, condition). |
| 10 | Pagination | `test_pages_concatenate_to_full_matrix[5 limits × 3 option sets]`, `test_pagination_page_contents_and_bounds`, `test_pagination_does_not_change_cpm` | Pages joined together equal the single-page rows exactly. The summary is the same on every page. page < 1 or invalid → 1. limit < 1 or invalid → 50. limit > 500 → 500. A page past the end is empty. CPM uses whole-matrix totals, not page totals. |
| 11 | Export | `test_export_tsv_exact_raw_blank`, `test_export_csv_equals_tsv_and_quotes_commas`, `test_export_missing_zero`, `test_export_equals_full_matrix_and_pages[5 option sets]` | Exact TSV text. CSV parses to the same table as TSV and quotes `sA:p2,p3; sB:q2`. Invalid formats are rejected. Export, full matrix and pages agree within rounding (6 dp vs 4 dp). Row order and columns match. |

## 4. Results

### 4.1 FakeDB

```
orthology/tests                                   : 102 passed, 58 skipped, 4 xfailed
  (21 existing + 81 new pass; 4 new strict xfail; 58 skipped = the opt-in Mongo module)
orthology + clustered_heatmap + pcoa + tests/     : 202 passed, 58 skipped, 4 xfailed
```

- **Passing:** all 21 existing tests and all 81 new reference tests.
- **Failing:** none.
- **Expected failures (strict xfail) documenting suspected issues:** 4.

While writing the tests, three of my own expectations were wrong and I corrected the tests, not the code: the source row count is 16, not 18; FakeDB had no exclusion-projection support; and `0` vs `0.0` in zero-filled float export columns (see A-5).

### 4.2 Real MongoDB integration

The integration run used a disposable `mongod` 8.2.9 on `127.0.0.1:27099` with a temporary dbPath, through PyMongo 3.12.1 from the existing venv. Port 27017 was not contacted. After the run, `list_database_names()` showed only `admin`, `config` and `local`. The server was stopped and its dbPath deleted.

```
test_expression_matrix_mongo_integration.py : 54 passed, 4 xfailed in 7.8 s
```

| Group | Count | What it shows |
|---|---|---|
| Regression tests re-run verbatim on a real DB (`make_db` patched to insert into Mongo) | 28 | Gene mapping, reference-strain lists/previews (including `{"_id": 0}` projection, `distinct`, `$in` over page orthogroups), load-order annotation, missing values, CPM/log2, all filters (including integer→string replicate `$in`), search, ordering, pagination bounds, exact TSV/CSV exports |
| Paralog rules / duplicate rules / replicate aggregation / pagination / export↔pages | 4 + 6 + 2 + 3 + 1 | Same hand-specified values as FakeDB |
| FakeDB ↔ MongoDB direct equality (`build_matrix` dict for 2 pages, TSV and CSV export text and summary) | 6 option sets | Byte-for-byte identical outputs |
| FakeDB ↔ MongoDB reference preview / strains | 3 strains (`sA`, `sB`, absent) | Identical dicts |
| Projection key sets | 1 | Inclusion and exclusion projections return identical documents |
| The 4 known discrepancies (strict xfail) | 4 | **Reproduce identically on real MongoDB.** They are not FakeDB artefacts. |

### 4.3 FakeDB vs MongoDB differences

- **Before this phase:** FakeDB ignored exclusion-only projections (`{"_id": 0}`) and returned empty documents. This is fixed in test code and confirmed equivalent against real Mongo.
- **Natural order:** both return documents in insertion order for these small, freshly inserted collections, so load-order-dependent annotation (A-1) matched. MongoDB does **not** guarantee natural order in general (after updates, deletes, compaction or sharding), so A-1 labels may vary in production even without code changes.
- **Query operators:** FakeDB supports only equality and `$in`. That covers every query the matrix builder and the reference preview use today. Optimizations that introduce `$group`, `$sort`, aggregation pipelines, collation or `skip/limit` must be checked with the Mongo integration module, not FakeDB.
- **`count_documents`, `delete_many` and `sort`** are not implemented in FakeDB. They are not used by the tested functions.
- No numerical difference was found.

## 5. Suspected scientific correctness problems (not fixed)

| ID | Severity | Issue | Evidence |
|---|---|---|---|
| **I-1** | High | **A null or unparseable count becomes 0.** `_collapse_paralogs` correctly keeps NaN (`sum(min_count=1)`), but `pivot_table(aggfunc="sum")` in `build_matrix` step 6 turns an all-NaN cell into **0**. This contradicts the module header ("Missing measurements stay NULL … never silently coerced to 0"). It affects raw values, `missing_value_count`, CPM totals, and log2 (shows 0 instead of missing). It applies to *recorded* rows whose count is null; absent rows correctly stay NaN. | `test_spec_null_count_cell_stays_missing`, `test_spec_null_count_cell_missing_after_log2_cpm` (xfail). Probe: `count=None` → value `0`, `missing_value_count=0`. |
| **I-2** | High (crash) | **KeyError when no row has a seed_peg and duplicates exist.** `_resolve_duplicates` groups without `seed_peg`, so the column is dropped. `_build_row_metadata` then reads `sgroup["seed_peg"]` → `KeyError` → HTTP 500. `seed_peg` was the gene identifier for the original *Pseudomonas* dataset only; it is **not** a universally required identifier for orthology datasets, so datasets without it are legitimate and must not crash. | `test_spec_duplicates_without_seed_peg_do_not_crash` (xfail, `raises=KeyError`). |
| **I-3** | Medium (doc/code mismatch) | **CPM order vs replicate aggregation.** The header says "CPM is computed independently per sample column (before any replicate aggregation)". The code averages raw counts first and then calculates CPM on the averaged column (the step 7 comment says so explicitly). The two approaches give different results when library sizes differ between replicates. The intended method needs a scientific decision. | `test_spec_cpm_computed_per_sample_before_replicate_aggregation` (xfail). Current behaviour is pinned in `test_replicate_mean_then_cpm_current_order`. |
| **I-4** | Medium | **Filters change normalization and orthogroup content.** (a) CPM library size is the sum over *filtered* rows, so `orthogroup_ids` or `search` change every CPM value. (b) `search` filters individual rows, not orthogroups: searching `dup` drops paralog `p3` from OG2, which changes the summed counts and clears `has_paralog`. Searching a gene name for one strain removes the other strain's columns. | `test_cpm_library_size_depends_on_orthogroup_filter`, `test_filter_search_is_row_level_current_behaviour` (pinned as current behaviour). |
| **I-5** | Medium | **Missing gene identifiers / mixed seed_peg presence.** The duplicate key, `gene_count`, `has_paralog` and `seed_pegs` metadata all assume `seed_peg` identifies a gene. Without it, paralogs cannot be told apart from duplicate measurements. If some rows in a set have a `seed_peg` and others do not, the rows without one share a NaN key and are merged as *duplicates* (30 + 5 = 35) instead of being treated as separate genes. `gene_count` leaves them out. | `test_rows_without_seed_peg_collapse_as_duplicates_when_mixed` (pinned). |
| **I-6** | Low (design) | **Sample ID collisions: cross-strain cell = sum of strains.** If two strains ever share a `sample_id`, their values are added together. Normally sample IDs are specific to one strain, so this is harmless, but it is a silent assumption. | `test_cross_strain_cell_is_sum_of_strain_values_when_samples_shared` (pinned). |

## 6. Ambiguities requiring investigation

- **A-1 Reference strain in the matrix.** `build_matrix` has no reference-strain option. The displayed gene/product is the first non-null value in **database load order**, across all strains (pinned: reversing the insertion order changes OG1's label from `gA1/kinase A` to `gB1/kinase B`). An optimization that changes query order, uses `$group`, or caches results may change labels unless this order is preserved. Decide whether labels should follow the selected reference strain, as `get_reference_preview` does.
- **A-2 `keep_separate`.** The name suggests separate rows per paralog, but the result is the same as `sum` (as the code comment admits). The UI meaning needs confirming.
- **A-3 NaN paralog handling.** An NA paralog is skipped by mean/max/sum (mean(NA, 10) = 10). This may or may not be intended.
- **A-4 Lexicographic ordering.** `OG10` sorts before `OG2`. Optimizations must keep exactly this sort (Python/pandas string order, not Mongo collation or natural sort) or pagination will change.
- **A-5 Export integer/float formatting.** Zero-filled missing cells are written as `0` in all-integer columns but `0.0` in float columns, because pandas upcasts the dtype. The values are numerically the same, but a text-level diff of exports would show this.
- **A-6 Reference vs expression orthogroups.** Orthogroups present in the reference but not expressed (OG5) are excluded from the matrix. Confirm this is wanted.

## 7. Confirmed discrepancies (FakeDB and real MongoDB)

| ID | Discrepancy | Locked by |
|---|---|---|
| I-1 | Missing (null or unparseable) counts appear as **0** instead of missing, which distorts CPM totals, log2 and `missing_value_count` | 2 strict xfail (FakeDB) + 2 strict xfail (Mongo) |
| I-2 | Duplicate handling crashes (`KeyError`) when `seed_peg` is absent | strict xfail (both) |
| I-3 | CPM is calculated **after** replicate averaging, not per sample before it (contradicts module docs) | strict xfail (both); current order pinned |
| I-4 | Filtering by orthogroup or search changes CPM denominators; search removes individual paralog rows from an orthogroup's sum | pinned current behaviour (both) |

Additional concerns pinned as current behaviour: missing identifiers (I-5), sample ID collisions (I-6), reference-strain labels in the matrix (A-1), row ordering (A-4).

## 8. Scientific decisions still required

1. **I-1:** should a recorded null count be missing (NaN) or 0? The documentation says missing.
2. **I-2 / I-5:** which gene identifier should be used when `seed_peg` is absent (`locus_tag`, `gene`, a generic `gene_id`, or none)? How should rows without an identifier be treated: as separate genes, or as duplicates?
3. **I-3:** should CPM be calculated per sample and then averaged, or averaged first and then normalised?
4. **I-4:** should the CPM library size be the whole sample (all orthogroups) or the filtered selection? Should search select whole orthogroups?
5. **I-6:** should sample IDs be required to be unique per strain, and should collisions be rejected at import?
6. **A-1:** should matrix gene/product labels follow the selected reference strain, as `get_reference_preview` does, instead of load order?
7. **A-2, A-3, A-4, A-6:** what should `keep_separate` mean? Should a NA paralog be skipped or treated as 0? Is natural sort wanted? Should orthogroups that exist only in the reference be included?

## 9. Readiness for performance optimization

**Ready, with conditions.** Numerical output is pinned for every option combination (4 transformations × 4 paralog rules × 3 duplicate rules × replicate aggregation × filters × pagination × export). It is checked at three levels against independently specified values, and FakeDB and real MongoDB give identical results.

Conditions:
1. After every optimization step, run the FakeDB suite (about 2 s) **and** the Mongo integration module against a disposable `mongod` on 27099. The integration module is mandatory for any change to queries or aggregation pipelines.
2. The 8 strict xfails (4 FakeDB + 4 Mongo) freeze current behaviour. An optimization that flips one is a behaviour change and must be reported, not accepted silently.
3. Make scientific fixes (section 8) in separate, explicitly approved commits, never mixed with performance work.
4. Preserve load-order annotation (A-1) and lexicographic ordering (A-4), or change them deliberately with updated tests.

Application processing logic is unchanged. Optimization has **not** been started.
