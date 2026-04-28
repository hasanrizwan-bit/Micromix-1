# Clustered Heatmap / Dendrogram Feature Plan

> Implementation instruction document for adding a **Clustered Heatmap with Dendrograms** plugin to Micromix.
>
> Read this alongside `codebase_exploration_opus.md`. Where the two disagree, trust what this document says (it was written after re-reading the actual files) and note the discrepancy in §15.
>
> **This is a planning document. Do not implement the feature from this file alone without confirming the file paths still exist.**

---

## 1. Goal

Add a new **third visualization plugin** to Micromix — *"ClusteredHeatmap"* — that renders a clustered heatmap with **row and column dendrograms** directly in the browser, with the ability to **collapse large dendrogram branches** into aggregate rows.

Why this is useful:

- Micromix already ships two heatmap-style plugins:
  - **Clustergrammer** — an external service (Ma'ayan Lab). It's clustered but capped at 200 rows, depends on a third-party URL, and has no dendrogram-branch interaction inside Micromix's control.
  - **Heatmap** (Deck.gl) — a WebGL renderer that is in-house, but **does not cluster** and has no dendrograms.
- Biologists using Micromix commonly want to (a) see hierarchical structure between genes/locus-tags across TraDIS/RNA-seq/TPM conditions, (b) compare multiple strains/samples (the `(<matrix title>) <column>` subtables after a merge), and (c) drill down into very large gene sets without losing overview.
- A *collapsible* clustered heatmap gives scaling that Clustergrammer cannot (no 200-row ceiling, runs locally, no external network dependency) and context that the Deck.gl heatmap cannot (biological grouping by expression similarity).
- Rows will represent genes / locus-tags / orthologs / annotation categories (whatever is in the merged dataframe's first "index" column). Columns will represent strains × samples (the merged `(<title>) <col>` subtable columns). Cell values will be the numeric values from the merged dataframe (expression, TPM, fold-change, presence/absence 1/0, etc.).

---

## 2. Relevant Existing Architecture

Key files (verified against the current repo):

### Main app — backend

| File | What it does |
|---|---|
| `Website/backend/app.py` | All Flask routes. `/visualization` (`make_vis_link`, L497) calls `visualize.route(db.plugins, df, plugin, ObjectId(url))`. `/active_plugin` (L436) persists which plugin is active. `/config` returns the merged session doc including `transformed_dataframe` / `filtered_dataframe` as parquet-bytes → JSON-records strings. |
| `Website/backend/visualize.py` | Dispatcher. Calls `importlib.import_module("plugins.<plugin_name>")`, then `plugin_module.main({"df": df, "db_entry_id": db_entry_id})` and returns `{plugin_name, plugin_id, link}`. |
| `Website/backend/plugins/Heatmap.py` | Returns `f"{HEATMAP_FRONTEND_URL}/?config={db_entry_id}"`. Trivially small — our new plugin file will follow the same shape. |
| `Website/backend/plugins/Clustergrammer.py` | Larger example: POSTs the dataframe to an external URL, returns the response URL. Shows how a plugin may inspect columns using the `(<title>) col` convention. |
| `Website/backend/plugins/template.py` | Skeleton. |
| `Website/backend/process_file.py` | `add_matrix`, `merge_db_entry`, `df_to_parquet`, `rename_df_columns`. Source of the `(<matrix title>) <column>` naming convention. |

### Main app — frontend

| File | What it does |
|---|---|
| `Website/plugins.json` | **Declarative plugin registry.** Two entries today: Clustergrammer (`5f984ac1b478a2c8653ed827`) and Heatmap (`khds8fohoduskfi7syf99`). This file is imported statically at frontend build time (`App.vue:202`) and **shallow-merged over the DB entry** on every `/config` response (`App.vue:474`). A new plugin must be added here to appear in the plugin picker. |
| `Website/frontend/src/App.vue` | Root component. Owns `config`. Renders the plugin picker by iterating `config.plugins` (L108-116) and handing each entry to `<plugins>` (which is the card). Selecting a plugin calls `select_plugin(plugin)` (L329) → `generate_vis_link(plugin)` → `POST /visualization` → puts the returned URL into `active_vis_link` → `<visualization>` renders an `<iframe>`. Clustergrammer's 200-row guard lives here (L362). |
| `Website/frontend/src/components/plugins.vue` | Plugin card UI. Already generic. Will render our new plugin automatically once it's in `plugins.json`. |
| `Website/frontend/src/components/visualization.vue` | Simple wrapper around `<iframe :src="vis_link">`. The new plugin reuses this: **no change needed** if we host the new visualization as a standalone SPA (matching the existing Heatmap pattern). |

### Heatmap SPA (reference pattern we will clone)

| File | What it does |
|---|---|
| `Heatmap/backend/app.py` | Three routes: `/status`, `/config` (POST with `url`=ObjectId → JSON records of filtered or transformed dataframe), `/save-settings`, `/get-user-settings/<dbId>`. |
| `Heatmap/frontend/src/App.vue` | Mounts `deckglCanvas` + `loadingOverlay`. |
| `Heatmap/frontend/src/components/deckglCanvas.vue` | 1437-line engine. Fetches `${backendUrl}/config`, calls `processJsonData` to turn the JSON records into layer data, builds Deck.gl layers, wires up settings. |
| `Heatmap/frontend/src/components/mainMenu.vue` / `settingsMenu.vue` / `cameraMenu.vue` / `exportMenu.vue` / `loadingOverlay.vue` | Settings UI + overlays. |
| `Heatmap/frontend/package.json` | Vue 2.6, `@deck.gl/core`, `@deck.gl/layers`, `chroma-js`, `crypto-js`, `bootstrap-vue`, `axios`. |
| `Heatmap/docker-compose.yml` | Deploys this plugin as `heatmap-frontend:80 → host:8081` and `heatmap-backend:5000 → host:3000`. |

### Dataset selection / data model

- Organism picker writes `config.active_organism_id` locally in `App.vue:set_local_organism`.
- Dataset (matrix) upload happens through `addDataForm.vue` (bound at `App.vue:152`) and talks to `/upload`.
- After upload, `merge_db_entry` performs an outer-join over all active matrices' parquet payloads into one `transformed_dataframe`. Numeric columns are renamed to `(<matrix title>) <original column>` (see `process_file.rename_df_columns`).
- **There is one dataframe per session.** Multiple strains/datasets/conditions are already merged into one wide table whose column-name *prefix* identifies the strain/dataset.
- The query builder (`search_query.vue` → `/query`) can produce a `filtered_dataframe`; the visualization prefers this if present (`app.py:515`).

### Plugin registration points (summary)

To make a new plugin appear:

1. Add a record in `Website/plugins.json`.
2. Create a file `Website/backend/plugins/<PluginName>.py` exposing `def main(parameters): ...` that returns a URL string.
3. (This plugin) Stand up a new SPA or reuse an existing one to serve that URL.

---

## 3. Current Data Flow

Confirmed end-to-end:

```
Upload  →  process_file.add_matrix  →  merge_db_entry
           (parquet bytes in Mongo visualizations.transformed_dataframe)
                           │
                           ▼
Query  →  POST /query  →  filter_dataframe.main
           (writes filtered_dataframe parquet bytes)
                           │
                           ▼
Pick plugin  →  App.vue:select_plugin  →  POST /visualization
           (app.py:make_vis_link reads filtered_dataframe if len>0
             else transformed_dataframe → pd.read_parquet →
             visualize.route → plugins/<name>.main({df, db_entry_id})
             → returns {plugin_name, plugin_id, link})
                           │
                           ▼
App.vue sets active_vis_link  →  <visualization> renders <iframe src="link">
                           │
                           ▼
The SPA at `link` POSTs {url: <db_entry_id>} to its own /config, which
reads the Mongo doc and returns the dataframe as JSON records
(filtered preferred over transformed — see Heatmap/backend/app.py:63-79)
```

The **exactly same shape of JSON records** (`orient='records'` on the dataframe, first column is usually the locus-tag index) is what our new visualization will consume. We should reuse this pattern verbatim.

---

## 4. Required Data Shape

### 4.1 What the new SPA will fetch

Identical to what the Deck.gl Heatmap fetches from `Heatmap/backend/app.py:/config`:

```json
[
  { "locus_tag": "BT0001", "(WT_TPM) sample1": 12.4, "(WT_TPM) sample2": 8.1, "(KO_TPM) sample1": 0.2, "(KO_TPM) sample2": null, "GO_term": "GO:0008150" },
  { "locus_tag": "BT0002", "(WT_TPM) sample1":  1.2, "(WT_TPM) sample2": 1.8, "(KO_TPM) sample1": 0.0, "(KO_TPM) sample2": 0.0,  "GO_term": null },
  ...
]
```

Conventions (confirmed against `plugins/Clustergrammer.py:29` and `deckglCanvas.processJsonData`):

- The **first key** is the row identifier (locus tag / gene ID / ortholog ID / feature ID).
- Numeric columns are those whose names start with `(` and contain `) ` → `(<matrix title>) <colname>`. These are the **value columns** / potential heatmap cells.
- Other (non-`(...) ...`) columns are **categorical metadata** (annotation codes, textual descriptors). These are *not* part of the numeric matrix, but they are candidate row-annotation tracks.

### 4.2 Internal heatmap model (built in the new component)

```ts
// All of the following are internal JS objects, not wire format.

type RowId = string;        // e.g. "BT0001"
type ColId = string;        // the raw column name, e.g. "(WT_TPM) sample1"

interface HeatmapMatrix {
  rowIds:    RowId[];                       // order after clustering
  colIds:    ColId[];                       // order after clustering
  rowLabels: Record<RowId, string>;         // locus_tag → display label (may equal id)
  colLabels: Record<ColId, string>;         // raw col → pretty label, e.g. "WT_TPM · sample1"
  rowMeta?:  Record<RowId, Record<string, string | number | null>>;  // annotations
  colMeta?:  Record<ColId, { matrixTitle: string; sample: string }>; // parsed from "(title) sample"
  // values[rowId][colId] – missing/NaN allowed
  values:    Record<RowId, Record<ColId, number | null>>;
  // presence for categorical toggle mode (0/1); only populated if valueMode === "presence"
  presence?: Record<RowId, Record<ColId, 0 | 1>>;
  valueMode: "numeric" | "presence" | "log" | "zscore";
  missingPolicy: "nan" | "zero" | "mean";
  stats: {
    rowMin: Record<RowId, number>;
    rowMax: Record<RowId, number>;
    colMin: Record<ColId, number>;
    colMax: Record<ColId, number>;
    globalMin: number; globalMax: number; globalMean: number;
  };
}
```

### 4.3 Dendrogram tree

```ts
interface DendroLeaf {
  kind: "leaf";
  id: RowId | ColId;                  // the original row/column id
  index: number;                      // 0-based position in the input matrix before clustering
}

interface DendroNode {
  kind: "node";
  id: string;                         // synthetic, e.g. "n_17"
  height: number;                     // linkage distance
  size: number;                       // number of leaves below this node
  left:  DendroLeaf | DendroNode;
  right: DendroLeaf | DendroNode;
  // cached for rendering
  leaves: Array<RowId | ColId>;       // in DFS (clustering) order
}

type Dendrogram = DendroNode | DendroLeaf | null;  // null ⇒ not clustered (too few rows)
```

### 4.4 Collapsed state

```ts
interface CollapsedClusters {
  // keyed by the synthetic DendroNode.id that is collapsed
  rows: Record<string, {
    nodeId: string;
    memberIds: RowId[];
    size: number;
    aggregatedValues: Record<ColId, number | null>;  // one aggregate per column
    label: string;                                   // e.g. "Cluster (42 items)"
    aggregation: "mean" | "median" | "sum" | "presence_pct";
  }>;
  cols: Record<string, {
    nodeId: string;
    memberIds: ColId[];
    size: number;
    aggregatedValues: Record<RowId, number | null>;
    label: string;
    aggregation: "mean" | "median" | "sum" | "presence_pct";
  }>;
}
```

### 4.5 Missing value representation

- On the wire: `null` (pandas `to_json(orient='records')` serializes `NaN` as `null`).
- Internally: coerce to `NaN` for clustering inputs (`Number.NaN`) or to the `missingPolicy`-selected substitute.
- In the heatmap render: cells with `null` are drawn with a neutral hatched/gray fill and the tooltip reads `"—" / "n/a"`.

---

## 5. Data Transformation Plan

All transformations run **client-side inside the new SPA** (matching the existing Deck.gl heatmap's pattern; no backend work). Steps:

1. **Row selection**
   - Use every row in the JSON payload (it's already the filtered_dataframe if one exists, else transformed_dataframe).
   - Row id = value of the first column key. If that value is `null` or duplicated, fall back to `"row_<i>"` and record a warning.

2. **Column selection (the numeric matrix)**
   - Detect value columns with the same regex used elsewhere:
     `name.startsWith("(") && name.includes(") ")` — taken from `Clustergrammer.prepare_df` and `deckglCanvas.processJsonData`.
   - If **no** such columns exist (non-biological dataset), fall back: every column whose values are >=80% numeric becomes a value column.
   - Non-value columns are stored separately as `rowMeta` for tooltip/annotation display; they are not clustered.

3. **Value computation**
   - Parse each cell with `Number(x)`; `Number.isFinite(v)` gates numeric. Otherwise mark `null`.
   - `valueMode` options exposed in the UI (`"numeric" | "presence" | "log" | "zscore"`):
     - `numeric` — raw value.
     - `presence` — `v != null && v > 0` → 1, else 0.
     - `log` — `v > 0 ? Math.log10(v + 1) : null` (0 kept as 0 after +1).
     - `zscore` — per-column (or per-row, user-toggleable) `(v − μ) / σ`.
   - Default: `numeric`. If the matrix looks binary (≤2 unique numeric values across >95% of cells), suggest `presence` in the UI.

4. **Missing value handling (before clustering)**
   - `missingPolicy` options:
     - `nan` — drop the row from clustering if any column is `null` **only if** <20% of rows would be dropped; otherwise silently impute column mean.
     - `zero` — replace with 0.
     - `mean` — replace with the column mean (default).
   - Always remember the original `null` in `values` so the rendered cell can show "—".

5. **Labels**
   - Row label = row id by default; if `rowMeta` has a "Name" or "symbol" key, append it in parentheses (e.g. `BT0001 (susC)`).
   - Column label = strip `(` and `) ` → `"<matrix title> · <sample>"`. If a column doesn't match the pattern, use the raw name.

6. **Duplicate identifiers**
   - If two rows share an id, de-duplicate with a suffix: `BT0001`, `BT0001#2`. Log to console.

7. **Categorical / presence conversion**
   - If `valueMode === "presence"`, build `matrix.presence[row][col]` and treat that as the clustering input. Display it as a 2-color (e.g. white / dark-blue) heatmap.

8. **Aggregation when clusters collapse**
   - For each collapsed node, compute per-column (or per-row) aggregate across its member ids:
     - `numeric`/`log`/`zscore` modes → default aggregation **mean** (also offer median/sum).
     - `presence` mode → **presence percentage** = `mean(0-or-1) × 100`.
   - Ignore `null` values in the average (use `nanmean`-style). If all members are null for a column, aggregate is `null`.

---

## 6. Clustering Plan

- **Where it runs**: client-side, in the new Vue component (keeps the backend untouched, matches Deck.gl Heatmap pattern, avoids changes to `Website/backend/app.py`).
- **Library**: use a small dependency such as [`ml-hclust`](https://www.npmjs.com/package/ml-hclust) (≈10 kB gzipped) or an equivalent JS implementation, OR hand-roll average-linkage agglomerative clustering (straightforward, ~60 lines) to avoid adding a dependency.
- **Recommended method**: **average linkage (UPGMA)** — stable, well-understood for expression data, matches Clustergrammer defaults.
- **Recommended distance**: **correlation distance** (`1 − Pearson r`) for numeric expression modes, **Euclidean** on z-scored rows as a secondary option, **Jaccard** for `presence` mode. Expose as a dropdown; default by `valueMode`.
- **Row clustering**
  - Input: rows of the (imputed) numeric matrix. Output: `Dendrogram` (see §4.3) + row order (DFS left-to-right across leaves).
  - Apply the order to `rowIds` and render the row dendrogram on the left.
- **Column clustering**
  - Same as row clustering but on the transpose. Apply order to `colIds` and render on top.
- **Too few rows/columns**
  - If `rowIds.length < 3` (or `colIds.length < 3`), skip that axis' clustering, set its dendrogram to `null`, render the heatmap with the input order, and show a small muted banner: *"Not enough rows/columns to cluster"*.
- **All-missing or non-numeric**
  - If `>90%` of the numeric matrix is `null`, fall back to `valueMode: "presence"` and Jaccard automatically; if that is also degenerate (≤1 distinct pattern), skip clustering and show: *"Data could not be clustered"*.
- **Dendrogram storage**: keep the full `DendroNode` tree in component `data()`. Cache leaf DFS order on each node (`leaves`) to make cluster expand/collapse O(1) lookups.
- **Applying order**: after clustering, build `orderedRowIds` / `orderedColIds` and use them to index into `matrix.values` at render time. Do **not** mutate `matrix.values`.

---

## 7. Collapsible Dendrogram Plan

- **Practical?** Yes. Vue 2 reactive data + SVG for the dendrogram gives fine control. Collapsible trees are a 1-day task with D3's `d3-hierarchy`, or fully hand-rolled with a recursive `<g>` SVG template.
- **Implementation technique**: custom Vue component that renders the tree as an SVG (so we control click handlers per branch), paired with a Canvas/WebGL heatmap body for performance. See §8 for the overall library choice.
- **Component state**:
  ```js
  data() {
    return {
      rowDendro: null,              // DendroNode | null
      colDendro: null,
      collapsedRowNodeIds: new Set(),
      collapsedColNodeIds: new Set(),   // (stretch goal)
      aggregation: "mean",
    };
  }
  ```
- **Rendering collapsed rows**
  - Compute an *effective* list of "visual rows", each either `{ type: "leaf", id, label }` or `{ type: "cluster", nodeId, size, label, members }`.
  - Walk the `rowDendro` in DFS order; for each subtree, if `collapsedRowNodeIds.has(node.id)` emit one cluster entry and skip its descendants; otherwise recurse.
  - This preserves clustering order naturally because we walk the tree in the same order we used to compute `orderedRowIds`.
- **Restoring a branch**
  - On click, remove the `nodeId` from `collapsedRowNodeIds`. Vue reactivity re-renders.
- **Stretch — collapsible columns**
  - Same algorithm applied to `colDendro` and `collapsedColNodeIds`. Do not implement this in v1; leave the hooks in place but hide the UI.
- **Aggregated row computation**
  - For each collapsed node, compute `aggregatedValues[colId]` using the `aggregation` setting from §5.8.
  - Cache aggregates keyed by `(nodeId, valueMode, aggregation)` so repeated collapse/expand doesn't recompute.
- **Visual indication**
  - Collapsed cluster rows get:
    - A triangle ▸ glyph at the start of the row label (expanded siblings get ▾).
    - A thicker, darker border on the cluster row in the heatmap.
    - A "N items" badge appended to the label (`"Cluster ▸ 42 items"`).
- **Tooltip content for a collapsed cluster**
  - Header: `Cluster (<size> items)`
  - Aggregate cell: `mean = X.XX  (median = Y.YY)` (or `presence = 38%`).
  - First N member ids (N=8) + "… and K more".
- **Performance**
  - Cap leaf render to ≈500 visible rows at any time. If `visualRows.length > 500`, show a banner: *"Collapse clusters to see all rows"* and render only the first 500.
  - Dendrogram SVG should debounce click handlers.
  - Heatmap body uses Canvas (see §8) to stay smooth at 10k+ cells.

---

## 8. Visualization Library Recommendation

**Recommendation: `d3` + a native `<canvas>` for the heatmap body, with `d3-hierarchy` / custom code for the dendrogram SVG. No Vue-specific charting library.**

Rationale (graded against the requirements):

| Option | Heatmap | Row dendro | Col dendro | Collapsible branches | Tooltips | Legends | Large data | Vue 2 fit |
|---|---|---|---|---|---|---|---|---|
| **D3 (SVG dendro + Canvas body)** *(recommended)* | ✅ Canvas = very fast | ✅ full control | ✅ full control | ✅ trivial (we own the tree) | ✅ custom | ✅ custom | ✅ Canvas scales | ✅ wraps cleanly in a Vue component |
| Plotly.js `heatmap` | ✅ | ⚠️ no native dendro, need `Plotly.FF.create_dendrogram` (Python only) or manual | ⚠️ same | ❌ no branch-collapse API | ✅ | ✅ | ⚠️ SVG slows past ~5k cells | ✅ |
| Observable Plot | ✅ | ❌ no built-in dendrogram | ❌ | ❌ | ⚠️ basic | ✅ | ⚠️ SVG | ⚠️ newer, not in stack |
| ECharts | ✅ `heatmap` + `tree` series | ✅ `tree` series | ✅ | ⚠️ `collapse` event exists but heatmap+tree coordination is manual | ✅ | ✅ | ✅ Canvas | ✅ |
| Deck.gl (reuse existing) | ✅ already used | ❌ not a dendro library | ❌ | ❌ | ✅ | already exists | ✅ excellent | ✅ already in repo |
| Vue-only heatmap libs (vue-heatmapjs etc.) | ⚠️ basic | ❌ | ❌ | ❌ | varies | ⚠️ | ❌ | ✅ |

Why **D3 + Canvas** wins for this codebase:

- Vue 2.6 and axios are already the stack; adding d3 is a single small dep.
- We fully own the dendrogram tree (§4.3) and need branch-collapse as a first-class feature — that rules out libraries where the dendrogram is opaque.
- Canvas for the heatmap body matches the existing Deck.gl heatmap's philosophy (browser-only rendering, tolerate 10k+ cells), but is simpler than introducing WebGL layers.
- D3's `scaleLinear` / `scaleSequential` + `d3-interpolate` give us the color mapping and legend for free.
- No external service dependency (unlike Clustergrammer).

**Second choice**: ECharts, if the team wants a batteries-included option; accept that branch-collapse coordination between the `tree` and `heatmap` series is manual.

**Do NOT reuse Deck.gl** for v1 — it's excellent for the existing heatmap but adds complexity (layer coordinate math, orientation tricks) that is not worth it for a dendrogram-first visualization.

---

## 9. UI/UX Behavior

### Where it appears

A new card in the plugin picker row of `App.vue` (already dynamically rendered from `config.plugins`), right next to the existing Heatmap and Clustergrammer cards. The card uses the name **"ClusteredHeatmap"** and a new SVG icon.

### Controls

Rendered inside the new SPA (left drawer, mirroring the Deck.gl heatmap's `settingsMenu` pattern):

- **Clustering** on/off (global toggle).
- **Distance metric**: `correlation`, `euclidean`, `jaccard` (auto-filtered by value mode).
- **Linkage**: `average` (default), `single`, `complete`. v1 can ship with `average` only and list the others as a stretch.
- **Cluster rows** / **Cluster columns** (two separate toggles).
- **Value mode**: `numeric`, `log`, `zscore`, `presence`.
- **Aggregation** (for collapsed clusters): `mean`, `median`, `sum`, `presence %`.
- **Color scale preset** (dropdown reusing chroma-js palettes already available: `Viridis`, `RdBu`, `RdYlGn`, `Greys`, `Blues`).
- **Collapse all rows** / **Expand all rows** / **Reset clustering** buttons.
- **Row dendrogram click** → toggles collapse on that branch node.
- **Column dendrogram click** → (stretch) toggles collapse on that column branch.

### Tooltips

On cell hover:
```
Row:   BT0001 (susC)
Col:   WT_TPM · sample1
Value: 12.40
```
On collapsed-cluster cell hover:
```
Row cluster: 42 items
Aggregation: mean across members
Value:       9.73
Members:     BT0001, BT0002, BT0003, … and 39 more
```

### Legend

- Vertical color strip on the right, showing `min → mid → max` ticks, mirroring the existing Deck.gl heatmap's gradient layer concept.
- For `presence` mode: two-color strip labeled `absent` / `present`.

### Color scale

- Diverging (`RdBu`) auto-selected when the data contains both negative and positive values (detected via `globalMin < 0 && globalMax > 0`).
- Sequential (`Viridis`) otherwise.
- Missing values get a fixed `#e5e5e5` with diagonal hatching.

### Large datasets

- v1 hard-caps visible rows at 500. If more, show a banner and render only the first 500 visible rows (collapsed clusters count as 1).
- Column count cap: 200 visible columns.
- If the user's numeric matrix has more than `10,000` total cells pre-collapse, default every top-level row cluster to collapsed on first render.

### Loading / empty / error states

- **Loading**: reuse `loadingOverlay.vue` verbatim (copy from the Deck.gl Heatmap).
- **Empty**: show a centered message *"No data to display. Upload a dataset or relax your filter."*
- **Error**: show a card with the error message and a *"Reload"* button that re-POSTs `/config`.
- **Cannot cluster**: banner *"Data could not be clustered. Showing original order."*

---

## 10. Files to Create or Modify

Legend: **[v1 required]**, **[v1 optional]**, **[stretch]**.

### Create

| Path | Purpose | Key content |
|---|---|---|
| `Website/backend/plugins/ClusteredHeatmap.py` **[v1 required]** | The backend plugin entry point invoked by `visualize.route`. Mirrors `plugins/Heatmap.py`. | ```python
import os
def main(parameters):
    upload_url = os.environ.get("CLUSTERED_HEATMAP_FRONTEND_URL", "http://127.0.0.1:8082/").rstrip("/")
    return upload_url + "/?config=" + str(parameters["db_entry_id"])
``` |
| `Website/backend/plugins/clustered_heatmap.svg` **[v1 required]** | Icon shown on the plugin card. A small SVG with a dendrogram-over-grid glyph. | — |
| `ClusteredHeatmap/backend/app.py` **[v1 required]** | Flask server for the new SPA. Exact clone of `Heatmap/backend/app.py`; only route paths change if needed. Provides `/status`, `/config` (reads same `visualizations` collection by ObjectId). | Copy `Heatmap/backend/app.py`, change port default to 3001, rename collection variables verbatim. |
| `ClusteredHeatmap/backend/Dockerfile` **[v1 required]** | Copy from `Heatmap/backend/Dockerfile`. | — |
| `ClusteredHeatmap/backend/requirements.txt` **[v1 required]** | Copy from `Heatmap/backend/requirements.txt`. | — |
| `ClusteredHeatmap/backend/saved_sessions/` **[v1 optional]** | Optional parity with Deck.gl Heatmap for saving user settings. v1 can skip. | — |
| `ClusteredHeatmap/frontend/package.json` **[v1 required]** | Vue 2.6 + axios + bootstrap-vue + `d3@7` (+ optional `ml-hclust`). Clone from `Heatmap/frontend/package.json` and swap `@deck.gl/*` + `chroma-js` for `d3` (`d3` already includes `d3-scale-chromatic` which replaces chroma-js for our needs). | — |
| `ClusteredHeatmap/frontend/src/main.js` **[v1 required]** | Bootstrap Vue with BootstrapVue + router. Clone from `Heatmap/frontend/src/main.js`. | — |
| `ClusteredHeatmap/frontend/src/App.vue` **[v1 required]** | Mounts the new canvas + loading overlay. Clone `Heatmap/frontend/src/App.vue` and swap `deckglCanvas` for `clusteredHeatmapCanvas`. | — |
| `ClusteredHeatmap/frontend/src/components/clusteredHeatmapCanvas.vue` **[v1 required]** | **The core component.** Fetches `/config`, transforms data, clusters, renders heatmap + dendrograms, handles collapse. | See §11 for the scaffold. |
| `ClusteredHeatmap/frontend/src/components/dendrogramSVG.vue` **[v1 required]** | Child component that renders a dendrogram as SVG and emits `branch-clicked(nodeId)`. | — |
| `ClusteredHeatmap/frontend/src/components/settingsPanel.vue` **[v1 required]** | Left-side settings drawer (clustering toggles, distance metric, value mode, color scale, aggregation, collapse-all/expand-all). | — |
| `ClusteredHeatmap/frontend/src/components/loadingOverlay.vue` **[v1 required]** | Copy from `Heatmap/frontend/src/components/loadingOverlay.vue`. | — |
| `ClusteredHeatmap/frontend/src/lib/hclust.js` **[v1 required]** | Pure-JS hierarchical clustering implementation (or thin wrapper around `ml-hclust`). Exports `cluster(matrix, { metric, linkage })` → `DendroNode`. | — |
| `ClusteredHeatmap/frontend/src/lib/distances.js` **[v1 required]** | `euclidean`, `correlationDistance`, `jaccard`, plus `pairwise(matrix, metric)` returning a square distance matrix. | — |
| `ClusteredHeatmap/frontend/src/lib/matrix.js` **[v1 required]** | `buildMatrix(jsonRecords, { valueMode, missingPolicy })` → `HeatmapMatrix`. Handles the `(title) col` detection, imputation, duplicates, etc. | — |
| `ClusteredHeatmap/frontend/src/lib/aggregate.js` **[v1 required]** | `aggregateCluster(matrix, memberIds, axis, aggregation)` → `Record<ColId, number|null>`. | — |
| `ClusteredHeatmap/frontend/src/lib/treeOrder.js` **[v1 required]** | `dfsLeaves(node)`, `visualRows(dendro, collapsedSet)`. | — |
| `ClusteredHeatmap/frontend/Dockerfile` **[v1 required]** | Clone from `Heatmap/frontend/Dockerfile`, serve on port 8082. | — |
| `ClusteredHeatmap/frontend/Nginx/default.conf` **[v1 required]** | Clone from `Heatmap/frontend/Nginx/`. | — |
| `ClusteredHeatmap/docker-compose.yml` **[v1 required]** | Clone from `Heatmap/docker-compose.yml`. Ports: backend `3001:5000`, frontend `8082:80`. | — |
| `Website/docker-compose.yml` **[v1 required, edit]** | Add env var `CLUSTERED_HEATMAP_FRONTEND_URL=http://127.0.0.1:8082/` to the Website backend service so the plugin URL is environment-driven. | — |

### Modify

| Path | Purpose | Edit |
|---|---|---|
| `Website/plugins.json` **[v1 required]** | Register the new plugin so `App.vue` renders the card. | Add a third entry: ```json
{
  "_id": "ch_01hxz9cbl8z3k0000000000000",
  "desc": "Clustered heatmap with collapsible row dendrograms",
  "image_url": "https://raw.githubusercontent.com/BarquistLab/Micromix/main/Website/backend/plugins/clustered_heatmap.svg",
  "name": "ClusteredHeatmap"
}
``` The `_id` follows the existing mixed-style convention (Clustergrammer uses an ObjectId-looking value, Heatmap uses a plain string). Prefer an unambiguous non-ObjectId string. |
| `Website/frontend/src/App.vue` **[v1 required]** | Do **not** add a hardcoded 200-row guard (that's Clustergrammer-specific). Optionally add a soft warning when the dataframe exceeds 5,000 rows: `if (plugin.name === "ClusteredHeatmap" && rows > 5000) warn(…)`. | Add a `name`-based check near L362; do not block. |
| `Website/backend/app.py` **[v1 optional]** | Add `'ch_01hxz9cbl8z3k0000000000000'` (the new plugin `_id`) to `PRE_CONFIGURED_PLUGINS` (L35) for parity, even though the runtime source of truth is `plugins.json`. | One-line edit. |
| `codebase_exploration_opus.md` **[v1 required]** | Document the new plugin folder + frontend URL. See §15. | — |

### Not changed

- `Website/backend/visualize.py` — already dispatches by `plugin.name`; no edit needed.
- `Website/frontend/src/components/plugins.vue` — generic card, no edit.
- `Website/frontend/src/components/visualization.vue` — generic `<iframe>`, no edit.
- `Website/backend/app.py:make_vis_link` — already plugin-agnostic.
- All query / upload / merge / export code — untouched.

---

## 11. Implementation Steps

Follow these in order. Do not skip steps; each assumes the previous succeeded.

### Step 1 — Register the plugin (5 minutes)

1. Edit `Website/plugins.json` and add the third entry shown in §10.
2. Copy `Website/backend/plugins/Heatmap.py` to `Website/backend/plugins/ClusteredHeatmap.py` and change the env var to `CLUSTERED_HEATMAP_FRONTEND_URL` (default `http://127.0.0.1:8082/`).
3. Drop a new SVG icon at `Website/backend/plugins/clustered_heatmap.svg` (simple dendrogram-over-grid glyph).
4. In `Website/docker-compose.yml`, add `CLUSTERED_HEATMAP_FRONTEND_URL=http://127.0.0.1:8082/` to the main backend service's environment block.
5. Restart the main backend. Confirm the new plugin card appears in the UI with a broken iframe (expected — there is no frontend yet).

### Step 2 — Stand up the ClusteredHeatmap SPA skeleton (30 minutes)

1. `cp -R Heatmap ClusteredHeatmap`.
2. In `ClusteredHeatmap/docker-compose.yml`, change service names + exposed ports to `3001` (backend) and `8082` (frontend).
3. In `ClusteredHeatmap/backend/app.py`, nothing functional must change — it already reads from the same `micromix.visualizations` Mongo collection. Change the default backend-internal port only if you want to run both containers on the same Docker network; external mapping stays at 3001.
4. In `ClusteredHeatmap/frontend/package.json`, remove `@deck.gl/core`, `@deck.gl/layers`, `deck.gl`, `chroma-js`, and add `"d3": "^7"`. Keep `axios`, `bootstrap-vue`, `vue@^2.6`, `vue-router@^3`, `crypto-js` (useful for data hash, parity with Heatmap's save-settings cache).
5. Remove `ClusteredHeatmap/frontend/src/components/deckglCanvas.vue` / `cameraMenu.vue` / `exportMenu.vue` / `mainMenu.vue` / `settingsMenu.vue` (copy only the bits worth reusing).
6. Update `ClusteredHeatmap/frontend/src/App.vue` to mount a new `<clusteredHeatmapCanvas>` + `<loadingOverlay>`.
7. Boot both containers. The SPA should render a blank canvas.

### Step 3 — Fetch and transform data (2 hours)

1. In `clusteredHeatmapCanvas.vue`:
   ```js
   created() {
     this.backendUrl = process.env.VUE_APP_CLUSTERED_HEATMAP_BACKEND_URL || 'http://127.0.0.1:3001';
     const url = new URLSearchParams(window.location.search).get('config');
     this.fetchData(url);
   },
   methods: {
     async fetchData(url) {
       const form = new FormData();
       form.append('url', JSON.stringify(url));
       const res = await axios.post(`${this.backendUrl}/config`, form);
       this.rawRecords = res.data;          // array of records
       this.matrix = buildMatrix(this.rawRecords, { valueMode: 'numeric', missingPolicy: 'mean' });
       this.computeClusters();
     },
   }
   ```
2. Implement `lib/matrix.js:buildMatrix` per §4 + §5.

### Step 4 — Implement clustering helpers (2 hours)

1. `lib/distances.js` — `euclidean`, `correlationDistance`, `jaccard`, `pairwise(vectors, metric)`.
2. `lib/hclust.js` — agglomerative clustering with `average` linkage, returning a `DendroNode` with cached `leaves`.
3. Handle the too-few-members case by returning `null`.
4. Unit-test manually against a 3×3 toy matrix.

### Step 5 — Render the heatmap body (3 hours)

1. Use a `<canvas>` sized to `cellW × visualCols + margins` and `cellH × visualRows + margins`.
2. Determine cell width/height to fit the viewport (min 6 px per side).
3. Build a `d3.scaleSequential(d3.interpolateRdBu).domain([globalMin, globalMax])` (or Viridis).
4. For each visible (row, col) draw a rectangle.
5. For `null` cells: fill `#e5e5e5` and draw a subtle hatched overlay.
6. On mousemove, map `(x, y)` to `(rowIdx, colIdx)` and update a Vue-driven tooltip div; on mouseout clear it.

### Step 6 — Render row and column dendrograms (2 hours)

1. `dendrogramSVG.vue` receives `{ tree, orientation: 'left'|'top', cellSize, collapsedSet }` props.
2. Compute node positions with a simple recursive layout: `xPixel(node) = node.height * widthScale`, `yPixel(node) = mean(yPixel(children))`, leaf `yPixel(i) = i * cellSize + cellSize/2`.
3. Draw each internal node as an L-shape connecting its two children. Add a small invisible `<rect>` at the corner for click hit-testing.
4. Collapsed nodes render as a filled triangle ▸ at their corner.
5. Clicking a node emits `branch-clicked(nodeId)` up to `clusteredHeatmapCanvas`.

### Step 7 — Hook up collapse/expand for rows (2 hours)

1. Maintain `collapsedRowNodeIds: new Set()` in `clusteredHeatmapCanvas.vue`.
2. On `branch-clicked(nodeId)`: if the set has it, delete; otherwise add. Force reactivity (`this.collapsedRowNodeIds = new Set(this.collapsedRowNodeIds)`).
3. Build `visualRows = treeOrder.visualRows(rowDendro, collapsedRowNodeIds)`.
4. For `cluster` entries, call `aggregate.aggregateCluster(matrix, cluster.memberIds, 'row', this.aggregation)`; cache per `(nodeId, valueMode, aggregation)`.
5. Re-render heatmap + left dendrogram (which now draws a ▸ at the collapsed corner and skips drawing below it).

### Step 8 — Column clustering render (1 hour) + collapse (stretch)

1. Implement `colDendro` rendering along the top edge.
2. Leave `collapsedColNodeIds` logic in place but do not bind it to clicks in v1 (no click listener on the top dendro).
3. Flip the flag in v2.

### Step 9 — Settings panel (1 hour)

1. `settingsPanel.vue` emits `update:*` events for each control.
2. `clusteredHeatmapCanvas.vue` reacts by re-running the minimal pipeline:
   - Value mode change → `buildMatrix` → `computeClusters`.
   - Distance/linkage change → `computeClusters` only.
   - Aggregation change → `rebuildVisualRows` only.
   - Color scale change → just redraw.
   - Collapse-all → set `collapsedRowNodeIds = new Set(allInternalNodeIds(rowDendro.rootChildren))`.
   - Expand-all → `collapsedRowNodeIds = new Set()`.
   - Reset clustering → rerun with defaults.

### Step 10 — Handle large datasets (30 minutes)

1. After computing `visualRows`, if `length > 500`:
   - Show a banner.
   - Slice to first 500.
2. Similarly cap columns at 200.
3. Default-collapse top-level row clusters when `rowIds.length > 200`.

### Step 11 — Manual test (see §12).

---

## 12. Testing Plan

### Setup

1. Boot the full stack (`Website/docker-compose.yml` + `Heatmap/docker-compose.yml` + `ClusteredHeatmap/docker-compose.yml`).
2. Create a session via the UI.
3. Upload two bundled Salmonella/Bacteroides datasets from `Website/backend/static/` into two matrix slots so you get prefixed columns `(<title A>) col` + `(<title B>) col`.

### Manual test cases

1. **Happy path — default numeric**. Click ClusteredHeatmap. Expect a heatmap with row and column dendrograms, with row labels legible for ≤500 rows.
2. **Collapse a row branch**. Click an internal node of the row dendrogram. Expect the branch to collapse into a single cluster row with a ▸ glyph and "N items" label. Tooltip over a cluster cell should show aggregation = mean and member preview.
3. **Expand**. Click the ▸ glyph. Expect the branch to restore exactly the same members in the same pre-collapse order.
4. **Collapse all / expand all**. Verify the buttons work and no duplicate rows appear.
5. **Value mode = presence**. Switch. Colors become binary, tooltips read `0` / `1`, clustering metric auto-switches to Jaccard. Verify.
6. **Missing values**. Intentionally upload a CSV with a column containing blanks. Verify the affected cells render hatched gray and tooltips say "—".
7. **Too few rows**. Load a session with ≤2 rows. Verify banner *"Not enough rows to cluster"* and matrix renders unclustered.
8. **Non-clusterable data**. Load data where all cells are `null`. Verify banner *"Data could not be clustered"*.
9. **Large dataset**. Upload a ~5,000-row file. Verify v1 caps to 500 visible rows and defaults to collapsed top-level clusters. No browser freeze.
10. **Reload session URL**. Refresh the page with `?config=<id>`. Expect same plot.
11. **Switch plugin**. Click Clustergrammer → ClusteredHeatmap → Heatmap. No crashes in any direction.
12. **Filtered vs transformed**. Run a filter (`search_query`) so `filtered_dataframe` is populated. Expect the ClusteredHeatmap to show the filtered rows only (backend `make_vis_link` prefers filtered).
13. **Locked session**. Lock, reshare URL. Expect consistent clustering.

### Edge cases

- Duplicate row ids → check the console warning and the `#2` suffix.
- A matrix title that contains `) ` (known fragility of the prefix convention) → document that the parser will mis-detect; no fix in v1.
- Column with non-numeric mixed string/number → column is treated as categorical metadata, not clustered. Verify.

### Unit/component tests

The Vue codebase does **not currently have a test runner** (`package.json` has no `test` script in either Website or Heatmap). v1 ships without tests. If Jest/Vitest is added later, priority specs:

- `lib/matrix.js:buildMatrix` with synthetic JSON records.
- `lib/distances.js` all three metrics against known-value fixtures.
- `lib/hclust.js` against a 5-point toy dataset compared to SciPy results.
- `lib/aggregate.js` for mean/median/sum/presence_pct incl. `null` handling.
- `lib/treeOrder.js:visualRows` for leaf, single-collapse, nested-collapse, all-collapse, all-expand cases.

---

## 13. Version One vs Future Enhancements

### Version 1 (ship this)

- New plugin registered in `plugins.json` + backend `plugins/ClusteredHeatmap.py`.
- New ClusteredHeatmap SPA (Docker service + Flask + Vue).
- Fetches same `/config` shape used by Deck.gl Heatmap.
- Client-side hierarchical clustering (average linkage, correlation/euclidean/jaccard).
- Renders a Canvas heatmap + SVG row dendrogram + SVG column dendrogram.
- **Collapsible row dendrogram branches** with mean aggregation and tooltip-listed members.
- Value modes: `numeric`, `log`, `zscore`, `presence`.
- Missing-value handling (hatched cells + configurable imputation for clustering).
- Tooltips, legend, color scale.
- Graceful fallbacks for too-few / un-clusterable data.
- Basic controls: value mode, distance metric, color scale, aggregation, collapse-all, expand-all, reset.

### Future enhancements

- **Collapsible column dendrogram branches** (stretch; easy to add once rows work).
- Linkage method selection (`single`, `complete`, `ward`) exposed in UI.
- **Export**: PNG/SVG of the current view, CSV of the clustered-order matrix.
- Search / filter rows inside the heatmap (highlight matching locus tags).
- Virtualized rendering (`canvas`-backed viewport with only visible rows drawn) to remove the 500-row cap.
- Annotation tracks (show `rowMeta` columns as a color strip next to the heatmap).
- Saved state (POST `/save-settings` + GET `/get-user-settings/<id>`), following the exact pattern from Deck.gl Heatmap.
- Parallel-coordinates or PCA companion view.
- Server-side clustering for sessions > 10k rows, returning precomputed trees.
- Cross-session comparison of clusterings (stability analysis).

---

## 14. Risks and Unknowns

1. **Clustering performance in the browser**. Pairwise distance is O(n²) in rows, agglomerative is O(n² log n). At 5k rows this is ~25M ops, borderline. Mitigation: subsample + flag for server-side move in v2.
2. **The `(<title>) <col>` prefix convention is string-based**. A matrix title containing `") "` breaks column detection here and in `plugins/Clustergrammer.py` and in the Deck.gl heatmap. This is a pre-existing issue (flagged in §4.5 of `codebase_exploration_opus.md`); the new plugin inherits it.
3. **`gene_annotations.json` is not used by this plugin in v1**. If users expect annotation tracks, a server endpoint or a frontend fetch of that 97k-line file will be needed (see §7.1 of `codebase_exploration_opus.md` for the per-request parsing cost).
4. **Distance metric choice is domain-dependent**. For normalized RNA-seq log-fold changes, correlation is appropriate. For raw counts, Euclidean after log is better. v1 picks correlation by default; biologists may disagree — exposing `Distance` as a visible control mitigates.
5. **Ambiguity in row identifiers**. We assume the first key of the JSON record is the row id. For truly empty / anomaly datasets this may not hold. The de-duplication fallback helps but does not resolve biological meaning.
6. **Cluster collapse semantics for presence mode**. "Presence %" is well-defined for binary data but not universally the user's intent; document in the tooltip.
7. **200-row Clustergrammer guard in `App.vue:362`**. Our new plugin must not accidentally inherit it. Guard is keyed on the Clustergrammer `_id` literal `"5f984ac1b478a2c8653ed827"`, so it is safely isolated — but any future refactor to that guard must keep the ID-check explicit.
8. **Browser memory for 10k × 200 numeric matrix** (~2M floats = 16 MB). Fine for modern browsers but the Canvas pixel count is the real limit; the 500-visible-rows cap mitigates.
9. **No existing test infrastructure**. v1 cannot ship automated tests without adding a test runner. Manual test plan in §12 must be followed by the implementer.
10. **Docker port collisions**. `8082` and `3001` are assumed free on the dev machine. Confirm before booting.
11. **The `"_id"` field in `plugins.json` is not a real ObjectId for the Heatmap entry** (it's the string `"khds8fohoduskfi7syf99"`). We must follow the same pattern to avoid `ObjectId()` cast failures elsewhere. Do **not** use a 24-char hex that looks like an ObjectId unless you mean it.
12. **`Website/backend/app.py` hard-codes plugin icon uploads to `/Users/`** (§7.1 of the exploration doc). Not on our code path in v1 (we put the icon in `Website/backend/plugins/`), but flagged for completeness.

---

## 15. Updates Needed to `codebase_exploration_opus.md`

After this feature is merged, `codebase_exploration_opus.md` should be updated as follows. (None of the existing statements are *wrong* — the updates are additions.)

### New entries to add

- **Service topology diagram** (§2): add a third SPA box `ClusteredHeatmap Vue frontend (port 8082 → :80)` + `ClusteredHeatmap Flask backend (port 3001 → :5000)`, both pointing at the same MongoDB.
- **Main entry points table** (§1): add rows for `ClusteredHeatmap/backend/app.py`, `ClusteredHeatmap/frontend/src/App.vue`, `ClusteredHeatmap/frontend/src/components/clusteredHeatmapCanvas.vue`.
- **`Website/plugins.json`** (§2 and §4.6): document that there are now **three** entries: Clustergrammer, Heatmap, ClusteredHeatmap.
- **`visualization dispatch`** (§3.4): note that `visualize.route` now resolves three plugin modules. No code change to `visualize.py` was needed; its dynamic import already supports arbitrary names.
- **Appendix A file index**: add entries for the new files listed in §10 of this plan.
- **Appendix B at-a-glance diagram**: add a third iframe/SPA arrow.

### Corrections / clarifications discovered during planning

- **§5.3 Clustergrammer**: the hard 200-row cap is a *frontend* guard in `App.vue:362` keyed on the Clustergrammer plugin `_id`. The current wording ("Fails if the external service is down or if >200 rows") is correct but could be more explicit that the guard is purely client-side.
- **§4.5 Column-prefix convention**: the detection in `Clustergrammer.prepare_df` uses `name.startsWith('(') and ") " in name`. The Deck.gl heatmap uses an equivalent check. The new ClusteredHeatmap will use the same check. Worth adding a single sentence: *"Any future plugin that reads the merged dataframe should use the same check to stay consistent."*
- **§5.2 Heatmap — `createSubTableGradientForms` mutation**: acknowledged as existing tech-debt; the new plugin avoids this class of bug by not mutating any shared template JSON.
- **§4.3 API request/response shapes**: the Heatmap backend row is listed as having three endpoints but the row count says *"3 endpoints"* while four are listed (`/status`, `/config`, `/save-settings`, `/get-user-settings/<dbEntryId>`). Fix the row count to **4**.
- **§1 "Main technologies" table**: after v1 merges, add `d3` (v7) to the Heatmap frontend stack row OR add a new *"ClusteredHeatmap frontend"* row listing Vue 2.6 + d3 + axios + BootstrapVue.

### Deltas confirmed while re-reading the codebase (no change to document, but worth noting)

- `Website/backend/visualize.py` really does use `importlib.import_module("plugins.{plugin['name']}")`, so no dispatcher edits are needed to introduce `ClusteredHeatmap` — the name in `plugins.json` just has to match the filename in `Website/backend/plugins/`. This matches `codebase_exploration_opus.md` §2's description.
- `Website/backend/app.py:make_vis_link` (L497) prefers `filtered_dataframe` when non-empty. This behavior is already documented in §3.4 and is what the new plugin relies on.
- `Heatmap/backend/app.py:/config` (L58) does not use the `db.plugins` collection — it just fetches `db.visualizations.find_one({_id})`. Our new backend should do exactly the same.

---

*End of plan.*
