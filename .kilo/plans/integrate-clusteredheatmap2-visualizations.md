# Clustered Heatmap Selection Integration — Plan

Status: **Supersedes the previous version of this file.** That version was written
before PCoA had been implemented; PCoA now exists in `Website/backend/pcoa/` and
`Website/frontend/src/components/pcoa/` and is the pattern this plan reuses.
Scope: `ClusteredHeatmap2` (at `/Users/hasanrizwan/ClusteredHeatmap2`) is read-only
reference. All changes target `Micromix-1/Website` only.

## 0. Ground truth (current state, verified by reading the code)

- **PCoA is fully implemented** and is the model to copy:
  - Backend: `Website/backend/pcoa/{service.py,dataset_store.py}` (Flask-free), thin
    route `POST /api/pcoa` in `app.py`, plugin shim `plugins/PCoA.py` returning the
    marker string `/pcoa?config=<id>`.
  - The **real** bridge from Micromix into PCoA is `POST /config` (generic session
    fetch) → `pickActiveDataframe()` (prefers `filtered_dataframe` over
    `transformed_dataframe`) → client-side reshape → PCoA's own compute endpoint.
  - The **real** bridge back into Micromix is `POST /sample_selection`: composes the
    current row-level `query` filter with an explicit sample-column id list, writes
    the result into `filtered_dataframe` + `active_sample_ids` on the *same* Mongo
    `visualizations` document (never touches `transformed_dataframe` or the
    original per-source `active_matrices[].dataframe`). `App.vue.handle_samples_committed()`
    then clears the active plugin/vis-link and reloads `/config`, so the plain
    matrix table view reappears showing `filtered_dataframe`.
  - "Restore full matrix" = `POST /sample_selection` with `sample_ids: null`.
- **Micromix already has its own native Clustered Heatmap component**
  (`Website/frontend/src/components/clustered-heatmap/{clusteredHeatmapCanvas,dendrogramSVG,settingsPanel}.vue`
  + `Website/frontend/src/lib/{matrix,distances,hclust,aggregate,treeOrder}.js`),
  architecturally parallel to PCoA (same `configId` prop, same `pickActiveDataframe`
  bridge in), independently written and **more Vue-idiomatic** than
  `ClusteredHeatmap2`. It already has: hierarchical clustering (client-side,
  average-linkage via custom `hclust.js`), separate row/column dendrograms,
  collapse/expand with correct "always aggregate from the immutable original
  matrix" semantics (`aggregate.js`, mirrors `ClusteredHeatmap2`'s
  `collapse.js` design), truncated/tooltip labels, a settings panel. **None of this
  needs to be ported from `ClusteredHeatmap2`.**
- **What Micromix's Clustered Heatmap is missing** (the actual gap vs. this task):
  1. It is **not registered in `Website/plugins.json`** (dispatch code in `App.vue`
     already expects plugin id `ch_01hxz9cbl8z3k0000000000000` and the backend
     shim `plugins/ClusteredHeatmap.py` already exists — only the plugin *card*
     entry is missing, so it currently cannot be launched from the UI at all).
  2. It has **no selection concept** (no row/column/cluster selection state) and
     **no "Apply Selection to Matrix" / "Clear Selection" / "Close" controls** —
     i.e. none of the PCoA-style "turn a visualization into a temporary working
     matrix" workflow this task asks for.
  3. The backend has **no endpoint that can subset by row id** at all today —
     `/sample_selection` only ever subsets **columns** (samples). There is no
     equivalent for genes/orthogroups.
- `ClusteredHeatmap2`'s own Clustered Heatmap tool (`backend/app.py` routes
  `/api/heatmap-data`, `/api/clustered-heatmap-data`, `static/js/{main,collapse,
  treelayout}.js`) has **no selection/filtering feature either** — only
  collapse/expand. So there is nothing to port from it for the *selection* feature
  this task centers on; it's confirmed purely as a "this is the algorithm class we
  already match/exceed" reference.
- Row identity in Micromix: the **first column** of a session's dataframe (same
  convention as `lib/matrix.js`'s `rowIdKey = Object.keys(record)[0]`) is always the
  row/gene/orthogroup identifier; every other non-`"(Title) sample"`-shaped column
  is metadata. Sample identity is the exact value-column name (e.g.
  `"(WT_TPM) sample1"`), already validated by `process_file.is_value_column()`.
  `lib/matrix.js`'s `buildMatrix()` **deduplicates** row ids for display
  (`GeneX`, `GeneX#2`, ...); the raw, un-suffixed id is what the backend's row
  column actually contains, so the frontend must track both.

## 1. What this task actually requires (delta only)

1. Register the existing Clustered Heatmap plugin in `plugins.json` (1-line fix,
   currently blocking any use of the feature).
2. A new backend endpoint that can subset the **current working matrix** by an
   explicit **row id list**, a **sample id list**, or both (intersection), composed
   on top of the existing row-level `query` filter — i.e. the row-axis equivalent of
   `/sample_selection`, kept as a **new, additive** route
   (`POST /matrix_selection`) so the already-working, already-tested
   `/sample_selection` (used by PCoA) is not touched/risked.
3. Selection UI in `clusteredHeatmapCanvas.vue`: click-to-toggle row selection,
   click-to-toggle column selection, shift-click a dendrogram branch to select all
   its member rows ("cluster selection"), plus **Apply Selection to Matrix**,
   **Clear Selection**, **Close** controls, wired into `App.vue` exactly like
   PCoA's `samples-committed` flow (reusing the existing generic handler) plus one
   new generic "close without applying" handler (usable by both PCoA and Heatmap
   later).
4. Stable-identity plumbing: expose the *raw* (pre-dedup) row id alongside the
   *display* row id from `buildMatrix()`, so a click on a clustered/reordered row
   always maps back to the correct backend column value, never to a visual index.

## 2. File-by-file plan

### Backend

| File | Change |
|---|---|
| `Website/backend/matrix_selection.py` (new) | Pure, Flask-free module (mirrors `pcoa/service.py`'s style): `MatrixSelectionError`, `select_matrix(df, row_ids=None, sample_ids=None, row_id_column=None)` → `(working_df, meta)`. Validates ids exist, dedups requested ids, preserves **original row/column order** (not selection order), never mutates input `df`, raises on unknown ids with a clear message. `row_ids=None and sample_ids=None` is a no-op (returns `df` unchanged) — this is what "restore" reduces to. |
| `Website/backend/tests/__init__.py` (new) | empty, for pytest package discovery (mirrors `pcoa/tests/__init__.py`). |
| `Website/backend/tests/test_matrix_selection.py` (new) | Unit tests against `select_matrix()` directly (no Flask/Mongo needed) — see §4. |
| `Website/backend/app.py` | Add `import matrix_selection` near the existing `import pcoa` block. Add new route `POST /matrix_selection` (`set_matrix_selection()`), modeled on `set_sample_selection()`: loads `transformed_dataframe`, composes the existing `query` via `filter_dataframe.main`, calls `matrix_selection.select_matrix(base_df, row_ids=row_ids, sample_ids=sample_ids)`, writes `filtered_dataframe` + `active_sample_ids` + **new** `active_row_ids` via the same `df_to_parquet`/`upload_db_entry` pattern. Add a `matrix_selection_error` entry to `ERROR_MESSAGES`. Add `'active_row_ids': None` to `DB_ENTRY_MOCKUP`. `/sample_selection` itself is **not modified** (zero regression risk to PCoA). |
| `Website/backend/process_file.py` | Alongside the two existing `db_entry['active_sample_ids'] = None` resets (`remove_matrix`, `add_matrix`), add `db_entry['active_row_ids'] = None` so a row selection is correctly invalidated whenever the underlying matrices change, exactly like the sample selection already is. |

### Frontend

| File | Change |
|---|---|
| `Website/plugins.json` | Add the missing entry: `{"_id": "ch_01hxz9cbl8z3k0000000000000", "name": "ClusteredHeatmap", "desc": "...", "image_url": ".../clustered_heatmap.svg"}`, matching the id `App.vue` already hardcodes and the existing `plugins/ClusteredHeatmap.py`/`clustered_heatmap.svg`. |
| `Website/frontend/src/lib/matrix.js` | Add `rawRowIds` (array, index-aligned with `rowIds`) to `buildMatrix()`'s return value — the pre-dedup id string for every row, so a display id (`GeneX#2`) always maps back to the real backend column value (`GeneX`). Additive change; no existing consumer reads a fixed key set. |
| `Website/frontend/src/lib/treeOrder.js` | Add `findNodeById(tree, nodeId)` (DFS search returning the internal `DendroNode`, or `null`) — needed for "shift-click an expanded dendrogram branch to select its members" (collapsed clusters already expose `memberIds` via `visualRows`, but an *expanded* branch's members aren't otherwise reachable). |
| `Website/frontend/src/lib/heatmapSelection.js` (new) | Pure, framework-free helpers: `toggleInSet(set, id)`, `rawIdsFor(displayIds, rawIdMap)`, `buildSelectionRequest({ selectedRowDisplayIds, selectedColIds, rawIdMap })` → `{ row_ids: [...]|null, sample_ids: [...]|null }` implementing the "only restrict the axis that was actually touched" rule. Mirrors `lib/pcoaSubset.js`'s "pure state helpers, no DOM" style. |
| `Website/frontend/src/components/clustered-heatmap/dendrogramSVG.vue` | Pass the native click `$event` through `emitClick`; emit `branch-clicked` on a plain click (unchanged — still drives collapse/expand) and a new `cluster-select` event on a shift-click, carrying the node id. |
| `Website/frontend/src/components/clustered-heatmap/clusteredHeatmapCanvas.vue` | Add: `selectedRowIds`/`selectedColIds` (Sets of *display* ids), row-label click → toggle (or toggle all `memberIds` for a collapsed cluster row), column-label click → toggle, `@cluster-select` handler on the row dendrogram (uses `findNodeById` + `.leaves`), a small selection toolbar (**Apply Selection to Matrix**, **Clear Selection**, **Close**, live "N rows / M columns selected" text, shift-click hint), `applySelectionToMatrix()` (POSTs to `/matrix_selection` via `heatmapSelection.buildSelectionRequest`, emits `selection-applied`), `close()` (emits `closed`, no network call — guarantees "close without applying leaves the matrix unchanged"). Selected rows/columns get a highlight class on labels and a highlight stroke on their cells in `drawHeatmap()`. |
| `Website/frontend/src/App.vue` | Wire `<clusteredHeatmapCanvas @selection-applied="handle_samples_committed" @closed="handle_visualization_closed" ...>` (the existing PCoA handler is already generic enough to reuse verbatim for "a native visualization committed a working-matrix change"). Add new `handle_visualization_closed()` (clears `active_plugin_id`/`active_vis_link`, persists via `post_active_plugin("")`, does **not** touch `filtered`/reload-as-filtered — matrix stays exactly as it was). Extend the "Active working matrix" banner condition/text to also mention `config.active_row_ids` when populated. Also wire `@closed` onto `<pcoaCanvas>` for consistency (additive; PCoA doesn't emit it yet, so this is a no-op until/unless PCoA adds a Close button later). |
| `Website/frontend/package.json` | Add `vitest` as a devDependency + `"test": "vitest run"` script — there is currently **no JS test runner at all** in this repo, and the task explicitly requires tests for the new pure selection/id-mapping logic. Dev-only, does not touch the Vue CLI / webpack build. |
| `Website/frontend/vitest.config.js` (new) | Minimal config (Node environment, `src/**/*.test.js`). |
| `Website/frontend/src/lib/heatmapSelection.test.js` (new) | Unit tests — see §4. |
| `Website/frontend/src/lib/matrix.test.js` (new) | Tests for `rawRowIds` / dedup mapping. |
| `Website/frontend/src/lib/activeDataframe.test.js` (new) | Tests for `pickActiveDataframe()` (filtered-over-transformed precedence) — cheap, directly backs requirement "Clustered Heatmap receives the current working matrix." |

### Not changed (explicitly out of scope)

- `Website/backend/pcoa/*`, `Website/backend/plugins/PCoA.py`, `/api/pcoa`,
  `/sample_selection` — PCoA keeps working exactly as-is.
- `Website/frontend/src/components/pcoa/*` — untouched except the additive
  `@closed` binding in `App.vue` (PCoA component itself not modified).
- No server-side clustering is added for the heatmap (Micromix's client-side
  `hclust.js` already works and this wasn't asked for); no iframe is introduced.
- Volcano plot is not part of this task.

## 3. End-to-end flow after this change

1. User is on the Micromix matrix view → clicks the **ClusteredHeatmap** plugin
   card (now visible because of the `plugins.json` fix).
2. `clusteredHeatmapCanvas.vue` fetches `/config`, picks
   `filtered_dataframe || transformed_dataframe` (already-existing code — this is
   what makes it automatically receive a PCoA-produced subset, or a prior
   Clustered-Heatmap-produced subset, with zero extra work).
3. User clusters/explores, clicks row labels / column labels / shift-clicks a
   dendrogram branch to build a selection.
4. **Apply Selection to Matrix** → `POST /matrix_selection` with `row_ids`
   and/or `sample_ids` (raw ids only) → backend composes with the existing query
   filter, writes the intersection into `filtered_dataframe`/`active_sample_ids`/
   `active_row_ids` on the same session document → frontend clears the active
   plugin, reloads `/config`, lands back on the matrix table view showing the
   subset.
5. From there the user can open PCoA (or Clustered Heatmap again) and it will see
   that same subset, because both read the same `filtered_dataframe` field via
   the same `pickActiveDataframe()` bridge.
6. **Close** → no network call → matrix view reappears completely unchanged.
7. **Restore full matrix** banner → unaffected/unchanged existing behavior
   (`/sample_selection` with `sample_ids: null`); a follow-up (not required by
   this task, noted for completeness) would be to also clear `active_row_ids`
   there for full symmetry once a heatmap-driven row selection has been applied —
   tracked as a known follow-up, not blocking, since `/matrix_selection` with both
   ids `null` already provides a full-reset path and `active_row_ids` is always
   reset to `None` on any dataset edit (`process_file.py`).

## 4. Test plan (mapped to the task's 10 required scenarios)

Backend (`pytest`, pure `select_matrix()`, no Flask/Mongo needed — mirrors
`pcoa/tests/test_service.py`'s style):
1. 100×20 in → select 25 row ids + 8 sample ids → exactly 25×8 out, correct ids.
2. Row-only selection (25 ids, no sample_ids) → all 20 sample columns preserved.
3. Column-only selection (8 ids, no row_ids) → all 100 rows preserved.
4. Selection result row order follows the **original** dataframe order, not the
   order ids were passed in (mirrors PCoA's `subset_matrix` guarantee).
5. Unknown row id / unknown sample id → `MatrixSelectionError`, original `df`
   provably unmutated (`df.equals()` check against a pre-call copy).
6. `row_ids=None, sample_ids=None` → passthrough (this is what "restore" and
   "close without applying" reduce to).
7. Chained subsetting: apply a row selection, then apply a further column
   selection to the *result* → composes correctly (models PCoA subset → Heatmap
   subset → further subset interoperability).

Frontend (`vitest`, pure lib functions):
8. `buildMatrix()` exposes `rawRowIds` and correctly maps a deduplicated display
   id (`GeneX#2`) back to its real backend column value (`GeneX`) — proves
   clustering/reordering (which only ever reorders `rowIds`, never regenerates
   them) cannot desync the id mapping.
9. `heatmapSelection.buildSelectionRequest()`: rows-only → `sample_ids: null`;
   columns-only → `row_ids: null`; both → both arrays present; neither → both
   `null`.
10. `pickActiveDataframe()` prefers a non-empty `filtered_dataframe` (simulating a
    PCoA- or Heatmap-produced subset) over `transformed_dataframe`.

Known coverage gap (documented, not silently skipped): there is no Vue
component-level or E2E test harness in this repo (no `vue-test-utils`, no
Cypress/Playwright config) prior to or added by this change, so the click-to-select
UI interactions and the full `App.vue` open→select→apply→return round trip are
verified manually (see Phase 4) rather than by an automated component test.

## 5. Implementation order

1. Backend: `matrix_selection.py` + tests → run `pytest`.
2. Backend: `app.py` route + `DB_ENTRY_MOCKUP`/`process_file.py` resets.
3. Frontend: `matrix.js` (`rawRowIds`), `treeOrder.js` (`findNodeById`),
   `heatmapSelection.js` + tests, `activeDataframe.test.js`, `matrix.test.js` →
   set up `vitest` → run tests.
4. Frontend: `dendrogramSVG.vue` shift-click emit.
5. Frontend: `clusteredHeatmapCanvas.vue` selection state, toolbar, apply/clear/close.
6. Frontend: `App.vue` wiring + banner text + `plugins.json` entry.
7. Full verification pass (Phase 4 below).
