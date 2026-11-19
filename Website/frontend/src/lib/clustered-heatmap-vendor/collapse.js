/* eslint-disable */
// Vendored verbatim from the ClusteredHeatmap2 reference implementation
// (backend/static/js/collapse.js). Not linted to Micromix's house style on
// purpose: this file is reused as-is, see
// Website/frontend/src/components/clustered-heatmap/NativeClusteredHeatmapCanvas.vue.
//
// Clustered Heat Map Tool — Iteration 8
// collapse.js — PURE data-transformation helpers (no DOM). Loaded before
// treelayout.js / main.js and exposed under the global ``HeatmapCollapse``.
//
// ========================================================================
// ITERATION-7 MODEL (rebuild-from-visible-state)
// ========================================================================
// The whole visualization is regenerated from the CURRENT VISIBLE TREE STATE
// every time the user collapses or expands a cluster. Nothing is patched in
// place. The pieces that cooperate to do this:
//
//   * treelayout.js   — turns (linkage + collapsed node ids) into the ordered
//                       VISIBLE LEAVES and recomputed dendrogram coordinates.
//   * collapse.js     — turns those visible leaves into the VISIBLE MATRIX
//                       and VISIBLE LABELS, always aggregating from the
//                       ORIGINAL clustered matrix (never from already-averaged
//                       values).
//   * main.js         — owns the collapsed-node Sets and, on every render,
//                       asks the two modules above for the visible state, then
//                       recomputes cell sizes / label positions / dendrogram
//                       pixels from that single state and redraws everything.
//
// ------------------------------------------------------------------------
// WHERE COLLAPSED STATE IS STORED
// ------------------------------------------------------------------------
// main.js stores it as ``collapsedRowNodes`` / ``collapsedColNodes`` — two
// Sets of dendrogram NODE IDS. A node id is in the set iff that cluster is
// currently collapsed. Structuring state as a Set of node ids (rather than a
// single "collapsed group") means MULTIPLE collapsed clusters per axis are
// supported out of the box.
//
// ------------------------------------------------------------------------
// HOW THE AGGREGATED (VISIBLE) MATRIX IS BUILT
// ------------------------------------------------------------------------
// Each visible leaf carries ``originalLeaves`` — the ORIGINAL row/column
// indices it represents (one for a normal leaf, many for a collapsed
// cluster). ``buildVisibleMatrix`` aggregates straight from the immutable
// original clustered matrix:
//   * visible cell[vr][vc] = mean over { base.values[orig_r][orig_c] :
//       orig_r in rowVisible[vr].originalLeaves,
//       orig_c in colVisible[vc].originalLeaves }
// Because we always start from the original matrix, collapsing a 3-cluster
// then expanding part of it can never compound rounding or average-of-
// averages errors (requirement: aggregate from original data, not from
// already-averaged values).

(function (global) {
  "use strict";

  /**
   * Arithmetic mean of an array of cell values, ignoring null/NaN (missing)
   * entries. Returns null if every value is missing so the collapsed cell
   * renders as "n/a" rather than 0.
   */
  function meanIgnoringMissing(values) {
    let sum = 0;
    let count = 0;
    for (let i = 0; i < values.length; i++) {
      const v = values[i];
      if (typeof v === "number" && !Number.isNaN(v)) {
        sum += v;
        count += 1;
      }
    }
    return count === 0 ? null : sum / count;
  }

  /**
   * Build a SHORT label for a collapsed cluster, e.g. "8 genes collapsed" or
   * "3 samples collapsed". Kept terse so it fits in the label gutter; the
   * full member list is exposed separately as a tooltip (see
   * ``memberTooltip``).
   *
   * @param {number} count   number of collapsed members
   * @param {string} noun    "gene" (rows) or "sample" (columns)
   */
  function collapsedLabel(count, noun) {
    if (!count || count <= 0) return "Collapsed cluster";
    const plural = count === 1 ? noun : noun + "s";
    return count + " " + plural + " collapsed";
  }

  /**
   * Build the full-member tooltip text for a collapsed cluster, e.g.
   * "Collapsed cluster (3): GeneD, GeneE, GeneI". Used as a title attribute
   * so the user can hover to see exactly what was folded together.
   */
  function memberTooltip(memberLabels) {
    if (!memberLabels || memberLabels.length === 0) return "Collapsed cluster";
    return (
      "Collapsed cluster (" +
      memberLabels.length +
      "): " +
      memberLabels.join(", ")
    );
  }

  // ----------------------------------------------------------------------
  // Visible matrix / labels from visible leaves
  // ----------------------------------------------------------------------

  /**
   * Map ORIGINAL leaf indices to their position in a display order array so
   * we can fetch labels in display order. ``order[displayIndex] = original``.
   * Returns the display labels for a set of original leaves, in display
   * order, for tooltips.
   *
   * @param {number[]} originalLeaves  original indices (sorted)
   * @param {number[]} order           row_order / column_order
   * @param {string[]} displayLabels   clustered (display-order) labels
   * @returns {string[]} member labels in display order
   */
  function membersInDisplayOrder(originalLeaves, order, displayLabels) {
    const origToDisplay = new Map();
    for (let d = 0; d < order.length; d++) origToDisplay.set(order[d], d);
    const displayIdx = originalLeaves
      .map((o) => origToDisplay.get(o))
      .filter((d) => d !== undefined)
      .sort((a, b) => a - b);
    return displayIdx.map((d) => displayLabels[d]);
  }

  /**
   * Build the VISIBLE matrix + VISIBLE labels for the current collapsed
   * state, aggregating from the immutable ORIGINAL clustered matrix.
   *
   * This is the single source of truth for what the heat map renders. It is
   * driven entirely by the visible-leaf lists produced by treelayout.js, so
   * the matrix, the labels, and the dendrogram all come from the SAME visible
   * tree state.
   *
   * @param {Object} base
   * @param {Array<Array<number|null>>} base.values  clustered (display-order) matrix
   * @param {string[]} base.rowLabels                clustered row labels
   * @param {string[]} base.columnLabels             clustered column labels
   * @param {number[]} base.rowOrder                 row_order (display->original)
   * @param {number[]} base.columnOrder              column_order
   * @param {Array<{nodeId,isCollapsed,originalLeaves}>} rowVisible
   *        ordered visible row leaves (from treelayout.visibleLeaves)
   * @param {Array<{nodeId,isCollapsed,originalLeaves}>} colVisible
   *        ordered visible column leaves
   * @returns {{
   *   values: Array<Array<number|null>>,
   *   rowLabels: string[], columnLabels: string[],
   *   rowMeta: Array<{nodeId,isCollapsed,count,tooltip}>,
   *   colMeta: Array<{nodeId,isCollapsed,count,tooltip}>
   * }}
   */
  function buildVisibleMatrix(base, rowVisible, colVisible) {
    // Invert the order arrays once: originalIndex -> displayIndex, so we can
    // read original cells out of the clustered (display-order) matrix.
    const rowOrigToDisplay = new Map();
    for (let d = 0; d < base.rowOrder.length; d++) {
      rowOrigToDisplay.set(base.rowOrder[d], d);
    }
    const colOrigToDisplay = new Map();
    for (let d = 0; d < base.columnOrder.length; d++) {
      colOrigToDisplay.set(base.columnOrder[d], d);
    }

    // Precompute, per visible slot, the list of DISPLAY indices it covers.
    const rowDisplaySets = rowVisible.map((rv) =>
      rv.originalLeaves
        .map((o) => rowOrigToDisplay.get(o))
        .filter((d) => d !== undefined)
    );
    const colDisplaySets = colVisible.map((cv) =>
      cv.originalLeaves
        .map((o) => colOrigToDisplay.get(o))
        .filter((d) => d !== undefined)
    );

    // Build the aggregated visible matrix. Each visible cell averages every
    // original cell in the cartesian product of its row/column display sets.
    const values = [];
    for (let vr = 0; vr < rowVisible.length; vr++) {
      const rowDisplay = rowDisplaySets[vr];
      const outRow = [];
      for (let vc = 0; vc < colVisible.length; vc++) {
        const colDisplay = colDisplaySets[vc];
        if (rowDisplay.length === 1 && colDisplay.length === 1) {
          // Fast path: a plain (uncollapsed) cell — copy the original value.
          outRow.push(base.values[rowDisplay[0]][colDisplay[0]]);
        } else {
          // Aggregate from ORIGINAL data over the full block.
          const block = [];
          for (let i = 0; i < rowDisplay.length; i++) {
            const r = base.values[rowDisplay[i]] || [];
            for (let j = 0; j < colDisplay.length; j++) {
              block.push(r[colDisplay[j]]);
            }
          }
          outRow.push(meanIgnoringMissing(block));
        }
      }
      values.push(outRow);
    }

    // Labels + per-slot metadata (collapsed flag, member count, tooltip).
    const rowLabels = [];
    const rowMeta = [];
    for (let vr = 0; vr < rowVisible.length; vr++) {
      const rv = rowVisible[vr];
      if (rv.isCollapsed) {
        const members = membersInDisplayOrder(
          rv.originalLeaves,
          base.rowOrder,
          base.rowLabels
        );
        rowLabels.push(collapsedLabel(members.length, "gene"));
        rowMeta.push({
          nodeId: rv.nodeId,
          isCollapsed: true,
          count: members.length,
          tooltip: memberTooltip(members),
        });
      } else {
        const d = rowOrigToDisplay.get(rv.originalLeaves[0]);
        rowLabels.push(base.rowLabels[d]);
        rowMeta.push({
          nodeId: rv.nodeId,
          isCollapsed: false,
          count: 1,
          tooltip: base.rowLabels[d],
        });
      }
    }

    const columnLabels = [];
    const colMeta = [];
    for (let vc = 0; vc < colVisible.length; vc++) {
      const cv = colVisible[vc];
      if (cv.isCollapsed) {
        const members = membersInDisplayOrder(
          cv.originalLeaves,
          base.columnOrder,
          base.columnLabels
        );
        columnLabels.push(collapsedLabel(members.length, "sample"));
        colMeta.push({
          nodeId: cv.nodeId,
          isCollapsed: true,
          count: members.length,
          tooltip: memberTooltip(members),
        });
      } else {
        const d = colOrigToDisplay.get(cv.originalLeaves[0]);
        columnLabels.push(base.columnLabels[d]);
        colMeta.push({
          nodeId: cv.nodeId,
          isCollapsed: false,
          count: 1,
          tooltip: base.columnLabels[d],
        });
      }
    }

    return {
      values: values,
      rowLabels: rowLabels,
      columnLabels: columnLabels,
      rowMeta: rowMeta,
      colMeta: colMeta,
    };
  }

  const api = {
    meanIgnoringMissing: meanIgnoringMissing,
    collapsedLabel: collapsedLabel,
    memberTooltip: memberTooltip,
    membersInDisplayOrder: membersInDisplayOrder,
    buildVisibleMatrix: buildVisibleMatrix,
  };

  // Expose for the browser (main.js) and for Node-based unit tests.
  global.HeatmapCollapse = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
