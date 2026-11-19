/* eslint-disable */
// Vendored from the ClusteredHeatmap2 reference implementation
// (backend/static/js/main.js). Not linted to Micromix's house style on
// purpose: this file is reused with only the additive plumbing changes
// described in the "MICROMIX VENDORING NOTE" further below, see
// Website/frontend/src/components/clustered-heatmap/NativeClusteredHeatmapCanvas.vue.
//
// Clustered Heat Map Tool — Iteration 8 (collapsed terminal branches +
// symmetric row/column collapse)
//
// ========================================================================
// WHAT CHANGED vs. ITERATION 7
// ========================================================================
// Iteration 7 rebuilt the whole view from visible state on every interaction
// and already treated a collapsed cluster as one visible leaf. Two problems
// remained, fixed here:
//
//   1. A collapsed cluster had NO terminal dendrogram branch of its own — it
//      was only reached by the vertical leg of its parent's U-shape, so it
//      read as a bare endpoint rather than a drawn leaf. Iteration 8 draws an
//      explicit TERMINAL BRANCH (from treelayout's ``terminalBranches``) for
//      every collapsed leaf, ending exactly at the collapsed row's yCenter /
//      collapsed column's xCenter, and keeps it clickable to expand.
//   2. Column collapse is now driven by the SAME axis-agnostic terminal-branch
//      + leaf-center logic as rows. ``drawDendrogram`` is a single axis-aware
//      routine; ``renderRowDendrogram`` / ``renderColumnDendrogram`` are thin
//      wrappers that only differ in how a (leafUnit, height) pair maps to
//      (x, y). There is no row-only drawing path.
//
// ========================================================================
// WHAT CARRIED OVER FROM ITERATION 7 (rebuild-from-visible-state)
// ========================================================================
// Iteration 6 collapsed the matrix correctly but drew the dendrogram from
// SciPy's STATIC icoord/dcoord, which keep a fixed x slot for every original
// leaf — so after a collapse the hidden children still occupied layout space
// and the tree drifted out of alignment / got clipped.
//
// Iteration 7 rebuilds EVERYTHING from the current visible tree state on
// every interaction. There is no partial patching of old SVG coordinates.
// One render pass:
//   1. derives the ordered VISIBLE LEAVES per axis from the collapsed-node
//      sets (treelayout.visibleLeaves) — a collapsed cluster is ONE leaf and
//      its hidden children get no coordinates and no space,
//   2. builds the VISIBLE MATRIX + labels by aggregating from the ORIGINAL
//      clustered matrix (collapse.buildVisibleMatrix),
//   3. recomputes cell width/height from the current visible counts so the
//      plotting area stays a fixed size,
//   4. recomputes the dendrogram U-shapes in VISIBLE-leaf space
//      (treelayout.computeVisibleDendrogram),
//   5. redraws the heat map, both dendrograms, and all labels from scratch.
//
// The heat map, dendrograms, labels, cell sizes, and dendrogram coordinates
// therefore all come from the SAME collapsed/expanded tree state.
//
// ========================================================================
// MICROMIX VENDORING NOTE (additive only -- nothing above this note, and
// no clustering/rendering/collapse logic anywhere below, was changed)
// ========================================================================
// This file is vendored verbatim from the proven ClusteredHeatmap2 reference
// (backend/static/js/main.js) for reuse inside Micromix's
// NativeClusteredHeatmapCanvas.vue. Two additive changes only, both confined
// to plumbing, were needed to call this module from a Vue SPA instead of a
// static server-rendered page:
//
//   1. The DOM element lookups that used to run ONCE at module-evaluation
//      time (when a <script> tag runs at the bottom of a static HTML page
//      that already contains the elements) are now wrapped in a
//      `queryDomRefs()` function. A Vue component mounts/unmounts its
//      template, so the `#heatmap-container` element is a NEW DOM node each
//      time; `queryDomRefs()` lets the host component re-resolve it right
//      before rendering instead of caching a stale reference forever.
//   2. `renderClusteredHeatmap` and `queryDomRefs` are exposed on
//      `globalThis.HeatmapMain` (same export convention already used by
//      `collapse.js`'s `HeatmapCollapse` and `treelayout.js`'s
//      `HeatmapTreeLayout`) so the host component can feed it a data object
//      directly instead of this module fetching `/api/clustered-heatmap-data`
//      itself. The existing fetch-driven buttons/health-check keep working
//      unchanged when this file is loaded on the original static page --
//      every lookup is still guarded by the same `if (el) ...` checks that
//      already existed, so a missing button/health element is a no-op.

(function () {
  "use strict";

  const Collapse =
    typeof HeatmapCollapse !== "undefined" ? HeatmapCollapse : null;
  const TreeLayout =
    typeof HeatmapTreeLayout !== "undefined" ? HeatmapTreeLayout : null;

  // ======================================================================
  // COLLAPSED STATE (single source of truth)
  // ======================================================================
  // ``clusteredBase`` is the immutable payload from the backend. We never
  // mutate it. The collapsed state is two Sets of dendrogram NODE IDS — one
  // per axis. Using Sets of node ids (instead of a single "group") is what
  // makes MULTIPLE collapsed clusters per axis work for free.
  //
  // We also keep the two parsed linkage trees (rowTree / colTree) so every
  // render can re-derive visible leaves and recomputed dendrogram geometry
  // from the same collapsed-node sets.

  let clusteredBase = null;
  let collapsedRowNodes = new Set(); // node ids collapsed on the row axis
  let collapsedColNodes = new Set(); // node ids collapsed on the column axis
  let rowTree = null;
  let colTree = null;

  // ---------- Health check (unchanged) ------------------------------------

  const healthBtn = document.getElementById("test-backend-btn");
  const healthStatusEl = document.getElementById("backend-status");

  function setHealthStatus(text, kind) {
    if (!healthStatusEl) return;
    healthStatusEl.textContent = text;
    healthStatusEl.classList.remove("is-ok", "is-error");
    if (kind === "ok") healthStatusEl.classList.add("is-ok");
    else if (kind === "error") healthStatusEl.classList.add("is-error");
  }

  async function testBackend() {
    if (!healthBtn) return;
    healthBtn.disabled = true;
    setHealthStatus("Backend status: checking...");
    try {
      const response = await fetch("/api/health", {
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        setHealthStatus(
          "Backend status: error (HTTP " + response.status + ")",
          "error"
        );
        return;
      }
      const data = await response.json();
      const value =
        data && typeof data.status === "string" ? data.status : "unknown";
      setHealthStatus("Backend status: " + value, "ok");
    } catch (err) {
      setHealthStatus(
        "Backend status: error (" +
          (err && err.message ? err.message : err) +
          ")",
        "error"
      );
    } finally {
      healthBtn.disabled = false;
    }
  }

  if (healthBtn) healthBtn.addEventListener("click", testBackend);

  // ======================================================================
  // LAYOUT CONSTANTS
  // ======================================================================
  // The heat map PLOTTING AREA is sized from the host container on every
  // render (see `computeHeatmapFootprint()` below) so it uses the real
  // available UI space rather than a small fixed box. Cell size is then
  // DERIVED per render to fill that footprint:
  //     cellW = footprintWidth  / visibleColumnCount
  //     cellH = footprintHeight / visibleRowCount
  // ...but is clamped to a readable min/max (`minCellW/H` .. `maxCellW/H`):
  // for a few visible rows/columns, cells grow up to the max; for many,
  // cells shrink only down to the min and the TOTAL grid grows past the
  // footprint instead of shrinking further — the host container
  // (`.heatmap-container { overflow: auto }`) scrolls for the excess.

  const LAYOUT = {
    // Baseline/fallback plotting-area footprint. `computeHeatmapFootprint()`
    // (below) replaces `heatmapWidth` on every render with the ACTUAL
    // available width of the host container so the heat map uses the real
    // UI space instead of a small fixed box; these are only the fallback
    // used before the container has been measured.
    heatmapWidth: 1100,
    heatmapHeight: 700,
    // Floors for the above so the plotting area never shrinks below a
    // readable size even in a narrow/short host container.
    minHeatmapWidth: 800,
    minHeatmapHeight: 500,
    rowLabelWidth: 170,
    columnLabelHeight: 110,
    // Meaningful minimum dendrogram footprint (UI readability requirement):
    // column dendrogram height ~150-200px, row dendrogram width ~180-250px.
    dendrogramHeight: 170,
    dendrogramWidth: 220,
    // Cell size floor raised slightly from 6px so individual cells stay
    // visually present; large matrices still grow the TOTAL grid past the
    // footprint above (instead of shrinking further) and the host container
    // scrolls (see `.heatmap-container { overflow: auto }`).
    minCellW: 8,
    minCellH: 8,
    maxCellW: 240,
    maxCellH: 180,
    maxLabelChars: 20,
    branchPad: 4, // px breathing room so branches never touch the edge
    // Adaptive row-label thinning (readability requirement): below this row
    // count every row gets a visible label; above it, only a subset of
    // labels (plus any collapsed-cluster label) is drawn so text never
    // overlaps. Every row keeps its tooltip + underlying metadata either way.
    maxFullRowLabels: 60,
    maxVisibleRowLabels: 45,
  };

  const SVG_NS = "http://www.w3.org/2000/svg";

  /**
   * Measure the host container and turn that into the plotting-area
   * footprint for THIS render. Falls back to the static LAYOUT.heatmapWidth/
   * heatmapHeight defaults when the container isn't laid out yet. This is
   * what lets the heat map use substantially more of the available UI space
   * (requirement) instead of always rendering into a fixed 640x420 box.
   */
  function computeHeatmapFootprint() {
    const measuredWidth = heatmapContainer ? heatmapContainer.clientWidth : 0;
    const reserved = LAYOUT.rowLabelWidth + LAYOUT.dendrogramWidth + 80;
    const width =
      measuredWidth > reserved
        ? Math.max(LAYOUT.minHeatmapWidth, measuredWidth - reserved)
        : LAYOUT.heatmapWidth;
    const height = LAYOUT.heatmapHeight;
    return { width: width, height: Math.max(LAYOUT.minHeatmapHeight, height) };
  }

  /**
   * Derive per-cell pixel size for the current visible counts. The plotting
   * area footprint (`footprintW`/`footprintH`) is sized per-render by
   * `computeHeatmapFootprint()` to use the available UI space; cells are
   * clamped to a readable min/max so, for very large matrices, the TOTAL
   * grid grows past the footprint (and the host container scrolls) instead
   * of cells shrinking below a legible size.
   */
  function deriveCellSize(nCols, nRows, footprintW, footprintH) {
    const w = footprintW || LAYOUT.heatmapWidth;
    const h = footprintH || LAYOUT.heatmapHeight;
    const rawW = nCols > 0 ? w / nCols : LAYOUT.maxCellW;
    const rawH = nRows > 0 ? h / nRows : LAYOUT.maxCellH;
    const cellW = Math.max(LAYOUT.minCellW, Math.min(LAYOUT.maxCellW, rawW));
    const cellH = Math.max(LAYOUT.minCellH, Math.min(LAYOUT.maxCellH, rawH));
    return { cellW: cellW, cellH: cellH };
  }

  function truncateLabel(text) {
    const s = String(text);
    if (s.length <= LAYOUT.maxLabelChars) return s;
    return s.slice(0, LAYOUT.maxLabelChars - 1) + "\u2026";
  }

  // ---------- DOM handles + small helpers ---------------------------------
  //
  // `let` (not `const`) + `queryDomRefs()` so a host that re-mounts its own
  // template (e.g. a Vue component) can re-resolve these after the elements
  // are recreated -- see the "MICROMIX VENDORING NOTE" above. On the
  // original static page this still runs exactly once, at the same point in
  // the script's execution, with the same result as before.

  let loadBtn, loadClusteredBtn, heatmapStatusEl, heatmapTitleEl, heatmapContainer;

  function queryDomRefs() {
    loadBtn = document.getElementById("load-heatmap-btn");
    loadClusteredBtn = document.getElementById("load-clustered-heatmap-btn");
    heatmapStatusEl = document.getElementById("heatmap-status");
    heatmapTitleEl = document.getElementById("heatmap-title");
    heatmapContainer = document.getElementById("heatmap-container");
  }
  queryDomRefs();

  function setHeatmapStatus(text, kind) {
    if (!heatmapStatusEl) return;
    heatmapStatusEl.textContent = text || "";
    heatmapStatusEl.classList.remove("is-ok", "is-error");
    if (kind === "ok") heatmapStatusEl.classList.add("is-ok");
    else if (kind === "error") heatmapStatusEl.classList.add("is-error");
  }

  function setHeatmapTitle(text) {
    if (!heatmapTitleEl) return;
    heatmapTitleEl.textContent = text || "";
  }

  function valueToColor(value, maxAbs) {
    if (value === null || value === undefined || Number.isNaN(value)) {
      return "#dddddd";
    }
    const limit = maxAbs > 0 ? maxAbs : 1;
    let t = value / limit;
    if (t > 1) t = 1;
    if (t < -1) t = -1;
    const blue = [49, 130, 189];
    const white = [247, 247, 247];
    const red = [222, 45, 38];
    let rgb;
    if (t >= 0) rgb = white.map((w, i) => Math.round(w + (red[i] - w) * t));
    else {
      const a = -t;
      rgb = white.map((w, i) => Math.round(w + (blue[i] - w) * a));
    }
    return "rgb(" + rgb[0] + "," + rgb[1] + "," + rgb[2] + ")";
  }

  function clearHeatmap() {
    if (heatmapContainer) heatmapContainer.innerHTML = "";
  }

  function computeMaxAbs(values) {
    let maxAbs = 0;
    for (let r = 0; r < values.length; r++) {
      const row = values[r] || [];
      for (let c = 0; c < row.length; c++) {
        const v = row[c];
        if (typeof v === "number" && !Number.isNaN(v)) {
          const a = Math.abs(v);
          if (a > maxAbs) maxAbs = a;
        }
      }
    }
    return maxAbs === 0 ? 1 : maxAbs;
  }

  function buildCell(value, maxAbs, rowLabel, colLabel) {
    const cell = document.createElement("div");
    cell.className = "heatmap-cell";
    cell.style.backgroundColor = valueToColor(
      typeof value === "number" ? value : NaN,
      maxAbs
    );
    const valueText =
      typeof value === "number" && !Number.isNaN(value)
        ? value.toFixed(2)
        : "n/a";
    cell.title =
      "gene: " + rowLabel + "\nsample: " + colLabel + "\nvalue: " + valueText;
    cell.setAttribute(
      "aria-label",
      "gene " + rowLabel + ", sample " + colLabel + ", value " + valueText
    );
    return cell;
  }

  // ======================================================================
  // ORIGINAL (un-clustered) renderer — unchanged behavior
  // ======================================================================

  function renderHeatmap(data) {
    if (!heatmapContainer) return;
    const rowLabels = Array.isArray(data.row_labels) ? data.row_labels : [];
    const colLabels = Array.isArray(data.column_labels)
      ? data.column_labels
      : [];
    const values = Array.isArray(data.values) ? data.values : [];

    if (rowLabels.length === 0 || colLabels.length === 0) {
      clearHeatmap();
      const empty = document.createElement("div");
      empty.className = "heatmap-placeholder";
      empty.textContent = "No data to display.";
      heatmapContainer.appendChild(empty);
      return;
    }

    const maxAbs = computeMaxAbs(values);
    clearHeatmap();

    const grid = document.createElement("div");
    grid.className = "heatmap-grid";
    grid.style.gridTemplateColumns =
      "minmax(80px, auto) repeat(" + colLabels.length + ", minmax(60px, 1fr))";

    const corner = document.createElement("div");
    corner.className = "heatmap-corner";
    grid.appendChild(corner);

    for (let c = 0; c < colLabels.length; c++) {
      const th = document.createElement("div");
      th.className = "heatmap-col-label";
      th.textContent = String(colLabels[c]);
      grid.appendChild(th);
    }

    for (let r = 0; r < rowLabels.length; r++) {
      const rowLabel = String(rowLabels[r]);
      const rowValues = values[r] || [];
      const rh = document.createElement("div");
      rh.className = "heatmap-row-label";
      rh.textContent = rowLabel;
      grid.appendChild(rh);
      for (let c = 0; c < colLabels.length; c++) {
        const colLabel = String(colLabels[c]);
        grid.appendChild(buildCell(rowValues[c], maxAbs, rowLabel, colLabel));
      }
    }
    heatmapContainer.appendChild(grid);
  }

  // ======================================================================
  // DENDROGRAM DRAWING (from RECOMPUTED visible-leaf coordinates)
  // ======================================================================
  //
  // ``computeVisibleDendrogram`` hands us icoord/dcoord arrays expressed in
  // VISIBLE-leaf units (leaf v at 10v+5) plus ``branchNodeIds[k]`` for the
  // node each U-shape represents. We scale leaf units to pixels with the
  // CURRENT cell size so every visible leaf centers on its visible heat map
  // row/column, and we scale heights to fill the strip. Because hidden leaves
  // are never assigned a coordinate, nothing extends past the visible range
  // and no branch is clipped (we also clamp the strip to the visible extent).

  function makeSvg(width, height, className) {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("width", String(width));
    svg.setAttribute("height", String(height));
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    if (className) svg.setAttribute("class", className);
    return svg;
  }

  function addBranchHitArea(svg, pointsStr, nodeId, axis, onClick) {
    const hit = document.createElementNS(SVG_NS, "polyline");
    hit.setAttribute("points", pointsStr);
    hit.setAttribute("class", "dendrogram-hit");
    hit.setAttribute(
      "aria-label",
      "Collapse or expand this " + axis + " cluster"
    );
    if (typeof onClick === "function") {
      hit.addEventListener("click", function (ev) {
        ev.stopPropagation();
        onClick(axis, nodeId);
      });
    }
    svg.appendChild(hit);
  }

  /**
   * ONE axis-aware dendrogram renderer used for BOTH axes. Everything is
   * computed in "visible-leaf units" (leaf v at 10v+5) and "height units"
   * (cluster heights, leaves at 0); the only axis-specific thing is how a
   * (leafUnit, heightUnit) pair maps to SVG (x, y). That mapping is the
   * ``project`` callback:
   *
   *   * column axis: leaf unit -> x (across the strip), height -> y
   *                  (0 at the bottom, root at the top),
   *   * row axis:    leaf unit -> y (down the strip), height -> x
   *                  (0 at the right next to the heat map, root at the left).
   *
   * Both internal U-shapes (``dendro.icoord``/``dcoord``) AND the collapsed
   * leaf TERMINAL branches (``dendro.terminalBranches``) are drawn the same
   * way, so a collapsed cluster always shows a real terminal line ending at
   * its slot center (the collapsed row's yCenter / column's xCenter). Hidden
   * children were never assigned a position, so nothing is drawn for them.
   *
   * @param {Object} dendro       from treelayout.computeVisibleDendrogram
   * @param {Object} opts         { axis, svgWidth, svgHeight, className,
   *                                leafPxPerUnit, project, collapsedSet,
   *                                onClick }
   */
  function drawDendrogram(dendro, opts) {
    const svg = makeSvg(opts.svgWidth, opts.svgHeight, opts.className);
    if (!dendro || dendro.icoord.length === 0) {
      // Even with no internal merges there can still be a single collapsed
      // terminal (e.g. the whole axis collapsed to one leaf) — fall through.
      if (!dendro || !dendro.terminalBranches || dendro.terminalBranches.length === 0) {
        return svg;
      }
    }

    const maxH = dendro.maxHeight;
    const project = opts.project; // (leafUnit, heightUnit) -> {x, y}

    function pointsFor(units, heights) {
      const pts = [];
      for (let j = 0; j < 4; j++) {
        const p = project(units[j] * opts.leafPxPerUnit, heights[j], maxH);
        pts.push(p.x + "," + p.y);
      }
      return pts.join(" ");
    }

    // (1) Internal merge U-shapes.
    const icoord = dendro.icoord || [];
    const dcoord = dendro.dcoord || [];
    const branchNodeIds = dendro.branchNodeIds || [];
    for (let k = 0; k < icoord.length; k++) {
      const nodeId = branchNodeIds[k];
      const isCollapsed = opts.collapsedSet.has(nodeId);
      const pointsStr = pointsFor(icoord[k], dcoord[k]);
      appendBranchLine(svg, pointsStr, nodeId, isCollapsed, opts.axis, opts.onClick, false);
    }

    // (2) Collapsed leaf TERMINAL branches — the iteration-8 fix. Each is a
    // real drawn line ending at the collapsed leaf's slot center, marked
    // collapsed (highlighted) and clickable to expand.
    const terminals = dendro.terminalBranches || [];
    for (let t = 0; t < terminals.length; t++) {
      const tb = terminals[t];
      const pointsStr = pointsFor(tb.icoord, tb.dcoord);
      appendBranchLine(svg, pointsStr, tb.nodeId, true, opts.axis, opts.onClick, true);
    }

    return svg;
  }

  /**
   * Draw one branch polyline + its (transparent, fat) click target.
   * ``isTerminal`` marks the explicit terminal stub drawn for a collapsed
   * leaf so it gets the rounded-cap collapsed-leaf style.
   */
  function appendBranchLine(svg, pointsStr, nodeId, isCollapsed, axis, onClick, isTerminal) {
    const line = document.createElementNS(SVG_NS, "polyline");
    line.setAttribute("points", pointsStr);
    line.setAttribute(
      "class",
      "dendrogram-branch" +
        (isCollapsed ? " is-collapsed" : "") +
        (isTerminal ? " dendrogram-terminal" : "")
    );
    svg.appendChild(line);
    addBranchHitArea(svg, pointsStr, nodeId, axis, onClick);
  }

  /**
   * Column dendrogram. Spans the FIXED heat map width (cellW * nCols).
   * leaf unit -> x; height -> y with 0 at the bottom (next to the heat map)
   * and the root at the top.
   */
  function renderColumnDendrogram(dendro, nCols, cellW, collapsedSet, onClick) {
    const width = cellW * nCols;
    const height = LAYOUT.dendrogramHeight;
    const PAD = LAYOUT.branchPad;
    const usableH = height - PAD;
    return drawDendrogram(dendro, {
      axis: "column",
      svgWidth: width,
      svgHeight: height,
      className: "dendrogram dendrogram-col",
      leafPxPerUnit: cellW / 10, // visible-leaf unit -> px
      collapsedSet: collapsedSet,
      onClick: onClick,
      project: function (px, heightUnit, maxH) {
        return { x: px, y: height - PAD - (heightUnit / maxH) * usableH };
      },
    });
  }

  /**
   * Row dendrogram. Axes swapped: leaf unit -> y; height -> x with 0 at the
   * right (next to the heat map) and the root at the left.
   */
  function renderRowDendrogram(dendro, nRows, cellH, collapsedSet, onClick) {
    const width = LAYOUT.dendrogramWidth;
    const height = cellH * nRows;
    const PAD = LAYOUT.branchPad;
    const usableW = width - PAD;
    return drawDendrogram(dendro, {
      axis: "row",
      svgWidth: width,
      svgHeight: height,
      className: "dendrogram dendrogram-row",
      leafPxPerUnit: cellH / 10,
      collapsedSet: collapsedSet,
      onClick: onClick,
      project: function (px, heightUnit, maxH) {
        return { x: width - PAD - (heightUnit / maxH) * usableW, y: px };
      },
    });
  }

  // ======================================================================
  // COLLAPSE / EXPAND INTERACTION
  // ======================================================================
  // A single entry point toggles a node id in the appropriate collapsed set,
  // then triggers a full redraw from the new visible state. Toggling a node
  // that is already collapsed expands it (requirement: clicking a collapsed
  // branch/label expands it again).

  /** Toggle collapse on a clicked dendrogram branch (by axis + node id). */
  function handleBranchClick(axis, nodeId) {
    const tree = axis === "column" ? colTree : rowTree;
    if (!tree || !TreeLayout) return;
    if (!TreeLayout.isCollapsibleNode(tree, nodeId)) return; // single leaf

    const set = axis === "column" ? collapsedColNodes : collapsedRowNodes;

    if (set.has(nodeId)) {
      // Already collapsed → expand.
      set.delete(nodeId);
    } else {
      // Collapsing a new node. Remove any currently-collapsed node that is an
      // ANCESTOR or DESCENDANT of this one so the collapsed set never
      // contains overlapping clusters (keeps visible leaves well-defined
      // while still allowing multiple non-overlapping collapsed clusters).
      removeOverlapping(tree, set, nodeId);
      set.add(nodeId);
    }
    renderClusteredView();
    announceCollapseState();
  }

  /** Expand a specific collapsed node (used by collapsed-label clicks). */
  function expandNode(axis, nodeId) {
    const set = axis === "column" ? collapsedColNodes : collapsedRowNodes;
    if (set.delete(nodeId)) {
      renderClusteredView();
      announceCollapseState();
    }
  }

  /**
   * Drop any node in ``set`` whose leaf-set overlaps ``nodeId`` (i.e. an
   * ancestor or descendant). Two clusters that share no leaves can both stay
   * collapsed → multiple collapsed clusters per axis are supported.
   */
  function removeOverlapping(tree, set, nodeId) {
    const candLeaves = new Set(TreeLayout.leavesUnder(tree, nodeId));
    Array.from(set).forEach(function (existing) {
      const ex = TreeLayout.leavesUnder(tree, existing);
      for (let i = 0; i < ex.length; i++) {
        if (candLeaves.has(ex[i])) {
          set.delete(existing);
          return;
        }
      }
    });
  }

  function announceCollapseState() {
    const nRow = collapsedRowNodes.size;
    const nCol = collapsedColNodes.size;
    if (nRow === 0 && nCol === 0) {
      setHeatmapStatus(
        "Showing all rows and columns. Click a dendrogram branch to collapse a cluster.",
        "ok"
      );
      return;
    }
    const parts = [];
    if (nRow > 0) parts.push(nRow + " row cluster" + (nRow === 1 ? "" : "s"));
    if (nCol > 0)
      parts.push(nCol + " column cluster" + (nCol === 1 ? "" : "s"));
    setHeatmapStatus(
      parts.join(" and ") +
        " collapsed. Click a highlighted branch or a collapsed label to expand.",
      "ok"
    );
  }

  // ======================================================================
  // CLUSTERED ENTRY POINT + FULL REDRAW
  // ======================================================================

  /**
   * Store the immutable clustered base, parse the linkage trees, reset the
   * collapsed sets, and do the first render.
   */
  function renderClusteredHeatmap(data) {
    if (!heatmapContainer) return;

    const rowLabels = Array.isArray(data.row_labels) ? data.row_labels : [];
    const colLabels = Array.isArray(data.column_labels)
      ? data.column_labels
      : [];
    const values = Array.isArray(data.values) ? data.values : [];

    if (rowLabels.length === 0 || colLabels.length === 0) {
      clusteredBase = null;
      collapsedRowNodes = new Set();
      collapsedColNodes = new Set();
      rowTree = colTree = null;
      clearHeatmap();
      const empty = document.createElement("div");
      empty.className = "heatmap-placeholder";
      empty.textContent = "No data to display.";
      heatmapContainer.appendChild(empty);
      return;
    }

    clusteredBase = {
      values: values,
      rowLabels: rowLabels,
      columnLabels: colLabels,
      rowOrder: Array.isArray(data.row_order)
        ? data.row_order
        : rowLabels.map((_, i) => i),
      columnOrder: Array.isArray(data.column_order)
        ? data.column_order
        : colLabels.map((_, i) => i),
      rowDendro: data.row_dendrogram || null,
      columnDendro: data.column_dendrogram || null,
      maxAbs: computeMaxAbs(values),
    };

    // Parse the linkage trees once. These let every render recompute visible
    // leaves + dendrogram geometry from the collapsed-node sets.
    rowTree =
      TreeLayout && clusteredBase.rowDendro
        ? TreeLayout.buildTree(
            clusteredBase.rowDendro.linkage,
            clusteredBase.rowDendro.n_leaves
          )
        : null;
    colTree =
      TreeLayout && clusteredBase.columnDendro
        ? TreeLayout.buildTree(
            clusteredBase.columnDendro.linkage,
            clusteredBase.columnDendro.n_leaves
          )
        : null;

    collapsedRowNodes = new Set();
    collapsedColNodes = new Set();

    renderClusteredView();
    announceCollapseState();
  }

  /**
   * THE redraw. Regenerates the entire visualization from the current visible
   * tree state every time it runs — no incremental patching of old SVG
   * coordinates anywhere.
   */
  function renderClusteredView() {
    if (!heatmapContainer || !clusteredBase) return;

    // --- (a) derive VISIBLE LEAVES per axis from the collapsed-node sets ---
    // A collapsed cluster collapses to ONE visible leaf; its hidden children
    // are excluded here and therefore receive no coordinates / no space.
    const rowVisible =
      rowTree && TreeLayout
        ? TreeLayout.visibleLeaves(rowTree, collapsedRowNodes)
        : clusteredBase.rowLabels.map((_, i) => ({
            nodeId: i,
            isCollapsed: false,
            originalLeaves: [clusteredBase.rowOrder[i]],
          }));
    const colVisible =
      colTree && TreeLayout
        ? TreeLayout.visibleLeaves(colTree, collapsedColNodes)
        : clusteredBase.columnLabels.map((_, i) => ({
            nodeId: i,
            isCollapsed: false,
            originalLeaves: [clusteredBase.columnOrder[i]],
          }));

    // --- (b) build the VISIBLE MATRIX + labels from the ORIGINAL matrix ----
    const view = Collapse
      ? Collapse.buildVisibleMatrix(clusteredBase, rowVisible, colVisible)
      : {
          values: clusteredBase.values,
          rowLabels: clusteredBase.rowLabels,
          columnLabels: clusteredBase.columnLabels,
          rowMeta: [],
          colMeta: [],
        };

    const rowLabels = view.rowLabels;
    const colLabels = view.columnLabels;
    const values = view.values;
    const nRows = rowLabels.length;
    const nCols = colLabels.length;
    const maxAbs = clusteredBase.maxAbs;

    // --- (c) recompute cell size from the CURRENT visible counts ----------
    // Measure the host container fresh on every render so resizing the
    // browser/panel (or collapsing clusters) always re-derives cell size
    // from the real available space rather than a stale fixed box.
    const footprint = computeHeatmapFootprint();
    const cellSize = deriveCellSize(nCols, nRows, footprint.width, footprint.height);
    const cellW = cellSize.cellW;
    const cellH = cellSize.cellH;
    const gridW = cellW * nCols;
    const gridH = cellH * nRows;
    // Dense matrices (many small cells) read better as a continuous block of
    // color than as hundreds of individually outlined boxes; this flag
    // drives a CSS-only change (removing the per-cell outline), not a data
    // or clustering change.
    const isDense = cellW <= 12 || cellH <= 12;

    // --- temporary verification logs (requirement) ------------------------
    console.log("[heatmap] visible row labels:", rowLabels);
    console.log("[heatmap] visible column labels:", colLabels);
    console.log("[heatmap] visible rows:", nRows, "visible columns:", nCols);
    console.log(
      "[heatmap] cellW:",
      cellW.toFixed(2),
      "cellH:",
      cellH.toFixed(2)
    );

    // --- (d) recompute dendrogram coordinates in VISIBLE-leaf space -------
    const colDendro =
      colTree && TreeLayout
        ? TreeLayout.computeVisibleDendrogram(colTree, collapsedColNodes)
        : null;
    const rowDendro =
      rowTree && TreeLayout
        ? TreeLayout.computeVisibleDendrogram(rowTree, collapsedRowNodes)
        : null;

    // "has a drawable dendrogram" now includes the case where the only thing
    // to draw is a collapsed leaf's terminal branch (e.g. the whole axis is
    // collapsed to a single leaf, so there are no internal merges left).
    function hasDrawable(d) {
      return !!(
        d &&
        ((d.icoord && d.icoord.length > 0) ||
          (d.terminalBranches && d.terminalBranches.length > 0))
      );
    }
    const hasColDendro = hasDrawable(colDendro);
    const hasRowDendro = hasDrawable(rowDendro);
    const colStripH = colTree ? LAYOUT.dendrogramHeight : 0;
    const rowStripW = rowTree ? LAYOUT.dendrogramWidth : 0;

    // --- (e) redraw everything from scratch -------------------------------
    clearHeatmap();

    const wrapper = document.createElement("div");
    wrapper.className = "clustered-heatmap";
    wrapper.style.gridTemplateColumns =
      rowStripW + "px " + gridW + "px " + LAYOUT.rowLabelWidth + "px";
    wrapper.style.gridTemplateRows =
      colStripH + "px " + gridH + "px " + LAYOUT.columnLabelHeight + "px";

    // (1,1) corner
    wrapper.appendChild(makeCorner());

    // (1,2) column dendrogram
    if (colTree) {
      const cell = document.createElement("div");
      cell.className = "dendrogram-col-cell";
      const lbl = document.createElement("div");
      lbl.className = "dendrogram-label";
      lbl.textContent = "Column Dendrogram";
      cell.appendChild(lbl);
      if (hasColDendro) {
        cell.appendChild(
          renderColumnDendrogram(
            colDendro,
            nCols,
            cellW,
            collapsedColNodes,
            handleBranchClick
          )
        );
      }
      wrapper.appendChild(cell);
    } else {
      wrapper.appendChild(makeCorner());
    }

    // (1,3) corner
    wrapper.appendChild(makeCorner());

    // (2,1) row dendrogram
    if (rowTree) {
      const cell = document.createElement("div");
      cell.className = "dendrogram-row-cell";
      const lbl = document.createElement("div");
      lbl.className = "dendrogram-label dendrogram-label-row";
      lbl.textContent = "Row Dendrogram";
      cell.appendChild(lbl);
      if (hasRowDendro) {
        cell.appendChild(
          renderRowDendrogram(
            rowDendro,
            nRows,
            cellH,
            collapsedRowNodes,
            handleBranchClick
          )
        );
      }
      wrapper.appendChild(cell);
    } else {
      wrapper.appendChild(makeCorner());
    }

    // (2,2) heat map cells from the VISIBLE matrix
    const cells = document.createElement("div");
    cells.className = "clustered-cells" + (isDense ? " is-dense" : "");
    cells.style.gridTemplateColumns = "repeat(" + nCols + ", " + cellW + "px)";
    cells.style.gridTemplateRows = "repeat(" + nRows + ", " + cellH + "px)";
    for (let r = 0; r < nRows; r++) {
      const rowLabel = String(rowLabels[r]);
      const rowValues = values[r] || [];
      const rowCollapsed = view.rowMeta[r] && view.rowMeta[r].isCollapsed;
      for (let c = 0; c < nCols; c++) {
        const colLabel = String(colLabels[c]);
        const colCollapsed = view.colMeta[c] && view.colMeta[c].isCollapsed;
        const cell = buildCell(rowValues[c], maxAbs, rowLabel, colLabel);
        if (rowCollapsed || colCollapsed) cell.classList.add("is-collapsed-cell");
        cells.appendChild(cell);
      }
    }
    wrapper.appendChild(cells);

    // (2,3) row labels (right). Centered on each visible row via the grid.
    // Adaptive row-label behavior (readability requirement): small matrices
    // show every label; large matrices show only an evenly-spaced subset
    // (plus any collapsed-cluster label, which is always meaningful) so text
    // never overlaps. Every row still gets its label element + `title`
    // tooltip + underlying metadata -- only the VISIBLE TEXT is thinned.
    const rowLabelsCol = document.createElement("div");
    rowLabelsCol.className = "clustered-row-labels";
    rowLabelsCol.style.gridTemplateRows =
      "repeat(" + nRows + ", " + cellH + "px)";
    const showAllRowLabels = nRows <= LAYOUT.maxFullRowLabels;
    const rowLabelStep = showAllRowLabels
      ? 1
      : Math.max(1, Math.ceil(nRows / LAYOUT.maxVisibleRowLabels));
    for (let r = 0; r < nRows; r++) {
      const meta = view.rowMeta[r] || {};
      const showLabelText =
        showAllRowLabels || r % rowLabelStep === 0 || (meta && meta.isCollapsed);
      rowLabelsCol.appendChild(
        buildAxisLabel(
          String(rowLabels[r]),
          "clustered-row-label",
          meta,
          "row",
          showLabelText
        )
      );
    }
    wrapper.appendChild(rowLabelsCol);

    // (3,1) corner
    wrapper.appendChild(makeCorner());

    // (3,2) column labels (rotated, centered on each visible column)
    const colLabelsRow = document.createElement("div");
    colLabelsRow.className = "clustered-col-labels";
    colLabelsRow.style.gridTemplateColumns =
      "repeat(" + nCols + ", " + cellW + "px)";
    for (let c = 0; c < nCols; c++) {
      const meta = view.colMeta[c] || {};
      colLabelsRow.appendChild(
        buildColumnLabel(String(colLabels[c]), meta)
      );
    }
    wrapper.appendChild(colLabelsRow);

    // (3,3) corner
    wrapper.appendChild(makeCorner());

    heatmapContainer.appendChild(wrapper);
  }

  function makeCorner() {
    const el = document.createElement("div");
    el.className = "clustered-corner";
    return el;
  }

  /**
   * Row/column axis label. Collapsed clusters get the short label, the full
   * member tooltip, and become a keyboard-accessible expand control.
   *
   * `showText` (default true) controls only whether the label TEXT is
   * rendered -- used by the adaptive row-label thinning above for large
   * matrices. The element, its grid slot, and its `title` tooltip (row
   * identity) are always created either way, so hovering a thinned-out label
   * still reveals the row name and no row metadata is ever dropped.
   */
  function buildAxisLabel(text, baseClass, meta, axis, showText) {
    const el = document.createElement("div");
    el.className = baseClass;
    const display = truncateLabel(text);
    if (showText === false) {
      el.classList.add("label-text-hidden");
    } else {
      el.textContent = display;
    }
    el.title = meta && meta.tooltip ? meta.tooltip : text;

    if (meta && meta.isCollapsed) {
      el.classList.add("is-collapsed-label");
      el.setAttribute("role", "button");
      el.setAttribute("tabindex", "0");
      el.title =
        (meta.tooltip || text) + " — click to expand this collapsed cluster";
      el.addEventListener("click", function () {
        expandNode(axis, meta.nodeId);
      });
      el.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          expandNode(axis, meta.nodeId);
        }
      });
    }
    return el;
  }

  /**
   * Rotated column label cell. Occupies exactly one heat map column so it
   * stays aligned. Collapsed clusters get the short label + tooltip + expand
   * affordance.
   */
  function buildColumnLabel(text, meta) {
    const cell = document.createElement("div");
    cell.className = "clustered-col-label";

    const span = document.createElement("span");
    span.className = "clustered-col-label-text";
    const display = truncateLabel(text);
    span.textContent = display;
    span.title = meta && meta.tooltip ? meta.tooltip : text;

    if (meta && meta.isCollapsed) {
      cell.classList.add("is-collapsed-label");
      span.classList.add("is-collapsed-label-text");
      cell.setAttribute("role", "button");
      cell.setAttribute("tabindex", "0");
      cell.title =
        (meta.tooltip || text) + " — click to expand this collapsed cluster";
      cell.addEventListener("click", function () {
        expandNode("column", meta.nodeId);
      });
      cell.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          expandNode("column", meta.nodeId);
        }
      });
    }
    cell.appendChild(span);
    return cell;
  }

  // ======================================================================
  // LOADERS (unchanged plumbing)
  // ======================================================================

  async function fetchAndRenderHeatmap(options) {
    const url = options.url;
    const title = options.title;
    const loadingMessage = options.loadingMessage;
    const successPrefix = options.successPrefix;
    const errorPrefix = options.errorPrefix;
    const renderer = options.renderer || renderHeatmap;
    const buttons = [loadBtn, loadClusteredBtn].filter(Boolean);

    if (!heatmapContainer) return;

    buttons.forEach((b) => (b.disabled = true));
    setHeatmapStatus(loadingMessage);
    try {
      const response = await fetch(url, {
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        setHeatmapTitle("");
        setHeatmapStatus(
          errorPrefix + " (HTTP " + response.status + ").",
          "error"
        );
        return;
      }
      const data = await response.json();
      renderer(data);
      setHeatmapTitle(titleForResponse(title, data));
      const rowCount = Array.isArray(data.row_labels)
        ? data.row_labels.length
        : 0;
      const colCount = Array.isArray(data.column_labels)
        ? data.column_labels.length
        : 0;
      // For the clustered view, announceCollapseState already set a status.
      if (renderer !== renderClusteredHeatmap) {
        setHeatmapStatus(
          successPrefix + " " + rowCount + " genes × " + colCount + " samples.",
          "ok"
        );
      }
    } catch (err) {
      setHeatmapTitle("");
      setHeatmapStatus(
        errorPrefix + " (" + (err && err.message ? err.message : err) + ").",
        "error"
      );
    } finally {
      buttons.forEach((b) => (b.disabled = false));
    }
  }

  function titleForResponse(baseTitle, data) {
    if (
      data &&
      data.clustered &&
      typeof data.clustered === "object" &&
      data.clustered.rows === false &&
      data.clustered.columns === false
    ) {
      return baseTitle + " (no clustering — too few rows/columns)";
    }
    return baseTitle;
  }

  function loadHeatmap() {
    return fetchAndRenderHeatmap({
      url: "/api/heatmap-data",
      title: "Original heat map",
      loadingMessage: "Loading heat map...",
      successPrefix: "Loaded",
      errorPrefix: "Failed to load heat map",
      renderer: renderHeatmap,
    });
  }

  function loadClusteredHeatmap() {
    return fetchAndRenderHeatmap({
      url: "/api/clustered-heatmap-data",
      title: "Clustered heat map",
      loadingMessage: "Loading clustered heat map...",
      successPrefix: "Loaded clustered",
      errorPrefix: "Failed to load clustered heat map",
      renderer: renderClusteredHeatmap,
    });
  }

  if (loadBtn) loadBtn.addEventListener("click", loadHeatmap);
  if (loadClusteredBtn)
    loadClusteredBtn.addEventListener("click", loadClusteredHeatmap);

  // ------------------------------------------------------------------
  // Micromix integration hook (additive; see "MICROMIX VENDORING NOTE"
  // above). Exposes the SAME pure render entry point this module's own
  // "Load Clustered Heat Map" button already uses, plus `queryDomRefs` so a
  // host component can re-resolve the DOM handles after (re)mounting its
  // template, and `reset` to drop the in-memory clustered state (e.g. when
  // the host unmounts). No new rendering/clustering/collapse behavior is
  // introduced here -- this only re-exposes existing functions.
  // ------------------------------------------------------------------
  const HeatmapMain = {
    render: renderClusteredHeatmap,
    queryDomRefs: queryDomRefs,
    reset: function () {
      clusteredBase = null;
      collapsedRowNodes = new Set();
      collapsedColNodes = new Set();
      rowTree = colTree = null;
      clearHeatmap();
    },
  };
  (typeof globalThis !== "undefined" ? globalThis : this).HeatmapMain = HeatmapMain;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = HeatmapMain;
  }
})();
