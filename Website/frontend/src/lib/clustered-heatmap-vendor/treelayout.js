/* eslint-disable */
// Vendored verbatim from the ClusteredHeatmap2 reference implementation
// (backend/static/js/treelayout.js). Not linted to Micromix's house style on
// purpose: this file is reused as-is, see
// Website/frontend/src/components/clustered-heatmap/NativeClusteredHeatmapCanvas.vue.
//
// Clustered Heat Map Tool — Iteration 8
// treelayout.js — PURE, DOM-free helpers that turn a SciPy linkage matrix
// plus a set of collapsed nodes into a *recomputed* visible tree layout.
//
// ========================================================================
// WHAT CHANGED vs. ITERATION 7 (collapsed terminal branches)
// ========================================================================
// Iteration 7 already treated a collapsed cluster as ONE visible leaf in
// ``visibleLeaves`` and excluded its hidden children from layout. But when it
// recomputed the dendrogram in ``computeVisibleDendrogram`` it only emitted a
// U-shape for *internal merges whose both children are visible* — a collapsed
// node, being a terminal, got NO branch geometry of its own. Its only
// connection was the vertical leg of its PARENT's U-shape dropping to height
// 0 at the collapsed node's slot. Visually that left a collapsed cluster with
// no terminal branch/line of its own: it looked like a bare endpoint, not a
// drawn leaf.
//
// Iteration 8 makes a collapsed node a fully DRAWN terminal leaf on BOTH
// axes, symmetrically:
//   * ``computeVisibleDendrogram`` now emits an explicit TERMINAL BRANCH for
//     every collapsed visible leaf — a short stub at the leaf's slot center
//     running from a small height down to height 0 (the heat-map row/column
//     center). It is recorded in ``terminalBranches`` (with the collapsed
//     node id) so the renderer can draw + make it clickable.
//   * The branch ends exactly at the leaf's slot center, which the renderer
//     maps to the collapsed row's yCenter (row axis) or the collapsed
//     column's xCenter (column axis). Hidden children still get NO
//     coordinates and reserve NO space.
// The logic is axis-agnostic: it works in "visible-leaf units" and the
// row/column renderers map those units to y or x respectively, so the same
// code path serves both axes (no row-only special-casing).
//
// ========================================================================
// WHY THIS MODULE EXISTS (the iteration-7 fix)
// ========================================================================
// Iteration 6 drew the dendrogram straight from SciPy's ``icoord``/``dcoord``
// arrays. Those arrays pin every ORIGINAL leaf to a fixed x position
// (leaf i sits at 10*i + 5) and include a U-shape for every original merge.
// When a cluster is collapsed, the heat map matrix is rebuilt correctly, but
// those static coordinates still reserve space for the now-hidden child
// leaves — so the dendrogram drifts out of alignment, branches get pushed
// out of place, and some are clipped.
//
// Iteration 7 throws those static coordinates away for layout purposes and
// instead RECOMPUTES the dendrogram geometry from the *current visible tree
// state* on every render. A collapsed internal node is treated as a single
// visible leaf; its hidden descendants receive NO coordinates and occupy NO
// layout space. The output coordinates are expressed in "visible-leaf units"
// (leaf v at 10*v + 5, just like SciPy) so the renderer can scale them to
// whatever the current visible row/column count and cell size happen to be.
//
// ------------------------------------------------------------------------
// WHERE COLLAPSED STATE LIVES
// ------------------------------------------------------------------------
// This module is stateless. The caller (main.js) owns the collapsed state as
// a Set of *node ids* per axis (see ``collapsedNodeIds``). Every function
// here takes that set as an argument and derives everything from it, so the
// visible matrix, visible labels, cell sizes, label positions, and
// dendrogram coordinates can all be produced from the SAME collapsed-node
// set in one render pass.
//
// ------------------------------------------------------------------------
// NODE ID CONVENTIONS (same as SciPy / collapse.js)
// ------------------------------------------------------------------------
//   * Leaf nodes:     ids 0 .. n_leaves-1  (map straight to an original
//                     row/column index).
//   * Internal nodes: ids n_leaves .. n_leaves + linkage.length - 1.
//                     Internal node (n_leaves + k) is created by linkage row
//                     k and merges children linkage[k][0] and linkage[k][1].
//   * Root node id:   n_leaves + linkage.length - 1.

(function (global) {
  "use strict";

  // ----------------------------------------------------------------------
  // Tree construction
  // ----------------------------------------------------------------------

  /**
   * Build a lightweight node-lookup for a linkage matrix.
   *
   * @param {Array<Array<number>>} linkage  rows of [left, right, height, n]
   * @param {number} nLeaves                number of original leaves
   * @returns {{nLeaves:number, rootId:number,
   *            children:(id:number)=>[number,number]|null,
   *            height:(id:number)=>number}}
   */
  function buildTree(linkage, nLeaves) {
    const rootId =
      linkage.length > 0 ? nLeaves + linkage.length - 1 : 0;

    function children(id) {
      if (id < nLeaves) return null; // leaf has no children
      const row = linkage[id - nLeaves];
      if (!row) return null;
      return [row[0] | 0, row[1] | 0];
    }

    function height(id) {
      if (id < nLeaves) return 0; // leaves sit at depth 0
      const row = linkage[id - nLeaves];
      return row ? row[2] : 0;
    }

    return { nLeaves: nLeaves, rootId: rootId, children: children, height: height };
  }

  // ----------------------------------------------------------------------
  // Visible leaves (the heart of the redraw fix)
  // ----------------------------------------------------------------------
  //
  // A "visible leaf" is a terminal slot along the axis as the user currently
  // sees it. It is EITHER:
  //   * an original leaf that is not inside any collapsed cluster, OR
  //   * a collapsed internal node, which stands in for all of its (hidden)
  //     descendant leaves and occupies exactly ONE slot.
  //
  // We derive these by an in-order (left-to-right) walk of the tree. When we
  // reach a collapsed internal node we EMIT IT AS A SINGLE VISIBLE LEAF and
  // do NOT descend into it — that is exactly how hidden children are excluded
  // from layout (requirement: hidden children get no coordinates / no space).

  /**
   * Compute the ordered list of visible "leaf" nodes for the current
   * collapsed state.
   *
   * @param {Object} tree                     from buildTree
   * @param {Set<number>} collapsedNodeIds    node ids that are collapsed
   * @returns {Array<{nodeId:number, isCollapsed:boolean,
   *                   originalLeaves:number[]}>}
   *   In left-to-right display order. ``originalLeaves`` is the set of
   *   original leaf indices this visible slot represents (one element for a
   *   normal leaf; many for a collapsed cluster).
   */
  function visibleLeaves(tree, collapsedNodeIds) {
    const collapsed = collapsedNodeIds || new Set();
    const out = [];

    // Iterative in-order traversal preserving SciPy's left-to-right leaf
    // order. We push children so the LEFT child is processed first.
    const stack = [tree.rootId];
    // To keep left-to-right order with a stack we use an explicit "expanded"
    // marker approach: push right then left so left pops first.
    // (A recursive walk would be simpler but can blow the stack on big trees.)
    const work = [{ id: tree.rootId }];
    // Replace naive stack with an ordered DFS using a second stack for output.
    // We do a manual pre-order that appends leaves in order.
    void stack; // (kept for clarity; not used)

    while (work.length > 0) {
      const { id } = work.pop();
      const kids = tree.children(id);

      // A node is a visible terminal if it is an original leaf OR it is
      // collapsed. Collapsed nodes are emitted as ONE slot and NOT expanded,
      // which is how their hidden children are excluded from the layout.
      if (kids === null || collapsed.has(id)) {
        out.push({
          nodeId: id,
          isCollapsed: kids !== null && collapsed.has(id),
          originalLeaves: leavesUnder(tree, id),
        });
        continue;
      }

      // Internal, not collapsed: descend. Push RIGHT first so LEFT pops
      // first → preserves left-to-right display order.
      work.push({ id: kids[1] });
      work.push({ id: kids[0] });
    }

    return out;
  }

  /**
   * All original leaf indices beneath a node (sorted, de-duplicated).
   * Mirrors collapse.js's leavesUnderNode but works from the tree object.
   */
  function leavesUnder(tree, nodeId) {
    const out = [];
    const seen = new Set();
    const stack = [nodeId];
    while (stack.length > 0) {
      const id = stack.pop();
      const kids = tree.children(id);
      if (kids === null) {
        if (!seen.has(id)) {
          seen.add(id);
          out.push(id);
        }
        continue;
      }
      stack.push(kids[0], kids[1]);
    }
    out.sort((a, b) => a - b);
    return out;
  }

  // ----------------------------------------------------------------------
  // Recomputed dendrogram coordinates (visible-leaf space)
  // ----------------------------------------------------------------------
  //
  // Given the visible leaves, we recompute the U-shape coordinates for the
  // SUBTREE that connects them. Only nodes that are ancestors of visible
  // leaves (and not themselves inside a collapsed cluster) get coordinates.
  //
  // Output is intentionally SciPy-shaped so the existing pixel-scaling code
  // can be reused:
  //   icoord[k] = [x1, x2, x3, x4]   in VISIBLE-leaf units (leaf v -> 10v+5)
  //   dcoord[k] = [y1, y2, y3, y4]   cluster heights (leaves at 0)
  // Plus ``leaves`` = ordered visible node ids, and ``branchNodeIds[k]`` =
  // the internal node id that drew U-shape k (so a clicked branch maps back
  // to a node id directly, with no SciPy-index bookkeeping).
  //
  // Iteration 8 additionally returns ``leafCenters`` (slot center per visible
  // terminal) and ``terminalBranches`` (a drawable stub per COLLAPSED visible
  // leaf) so a collapsed cluster is rendered as a real terminal leaf/branch
  // ending at its row yCenter / column xCenter — on either axis.

  /**
   * Recompute dendrogram geometry from the current visible tree state.
   *
   * @param {Object} tree                    from buildTree
   * @param {Set<number>} collapsedNodeIds   collapsed node ids
   * @returns {{icoord:number[][], dcoord:number[][], leaves:number[],
   *            branchNodeIds:number[], maxHeight:number,
   *            leafCenters:Array<{nodeId:number, center:number,
   *                               isCollapsed:boolean}>,
   *            terminalBranches:Array<{nodeId:number, center:number,
   *                                    icoord:number[], dcoord:number[]}>,
   *            visible:Array}}
   *
   * ``leafCenters`` gives, for every visible terminal (normal leaf OR
   * collapsed cluster) its slot-center position in visible-leaf units (10v+5).
   * The renderer maps that to the collapsed row's yCenter / column's xCenter.
   *
   * ``terminalBranches`` gives an explicit drawable stub for every COLLAPSED
   * visible leaf (axis-agnostic, in the same icoord/dcoord shape as internal
   * branches) so a collapsed cluster shows a real terminal branch/line ending
   * at its slot center. Normal leaves are not given a stub: their terminal
   * connection is the vertical leg of their parent's U-shape.
   */
  function computeVisibleDendrogram(tree, collapsedNodeIds) {
    const collapsed = collapsedNodeIds || new Set();
    const visible = visibleLeaves(tree, collapsed);

    // Assign each visible leaf an x position on the SciPy 10-unit pitch.
    // visibleX[nodeId] = x position of that visible terminal.
    const visibleX = new Map();
    for (let v = 0; v < visible.length; v++) {
      visibleX.set(visible[v].nodeId, 10 * v + 5);
    }

    const icoord = [];
    const dcoord = [];
    const branchNodeIds = [];
    let maxHeight = 0;

    // A node counts as a "visible terminal" if it has an x in visibleX —
    // i.e. it's an original leaf that's shown, or a collapsed cluster.
    function isVisibleTerminal(id) {
      return visibleX.has(id);
    }

    // Post-order walk: compute each visible node's x as the midpoint of its
    // two visible children, emitting one U-shape per internal merge whose
    // BOTH children are visible (terminals or already-merged internals).
    // We memoize each node's resolved x position.
    const resolvedX = new Map();

    function resolve(id) {
      // Terminal (leaf or collapsed cluster): x is fixed; height 0.
      if (isVisibleTerminal(id)) {
        const x = visibleX.get(id);
        resolvedX.set(id, x);
        return { x: x, drawn: true };
      }
      const kids = tree.children(id);
      if (kids === null) {
        // Defensive: an original leaf not in visibleX shouldn't happen, but
        // if it does it's hidden → not drawn.
        return { x: null, drawn: false };
      }
      const left = resolve(kids[0]);
      const right = resolve(kids[1]);

      // If either side is hidden (inside a collapsed cluster that isn't this
      // node), this node cannot be drawn. In practice, because collapsed
      // nodes are themselves visible terminals, both sides resolve whenever
      // this node is an ancestor of visible leaves only.
      if (!left.drawn || !right.drawn || left.x === null || right.x === null) {
        return { x: null, drawn: false };
      }

      const parentX = (left.x + right.x) / 2;
      const h = tree.height(id);
      const lh = tree.height(kids[0]);
      const rh = tree.height(kids[1]);
      if (h > maxHeight) maxHeight = h;

      // SciPy U-shape: up the left child, across the top, down the right.
      icoord.push([left.x, left.x, right.x, right.x]);
      dcoord.push([lh, h, h, rh]);
      branchNodeIds.push(id);

      resolvedX.set(id, parentX);
      return { x: parentX, drawn: true };
    }

    if (visible.length > 0) {
      resolve(tree.rootId);
    }

    const effMaxHeight = maxHeight === 0 ? 1 : maxHeight;

    // Slot center for every visible terminal (normal leaf or collapsed
    // cluster), in visible-leaf units. The renderer maps this to the
    // collapsed row's yCenter / collapsed column's xCenter.
    const leafCenters = visible.map(function (v) {
      return {
        nodeId: v.nodeId,
        center: visibleX.get(v.nodeId),
        isCollapsed: !!v.isCollapsed,
      };
    });

    // Explicit terminal branch (stub) for every COLLAPSED visible leaf so the
    // collapsed cluster is drawn as a real terminal leaf with a line ending at
    // its slot center. The stub is a short L: it descends from a small height
    // straight down to height 0 at the leaf center, mirroring how an internal
    // U-shape's vertical leg reaches a normal leaf. Axis-agnostic: the
    // renderer turns the same coords into a vertical (column) or horizontal
    // (row) line.
    const STUB_FRACTION = 0.12; // stub height as a fraction of maxHeight
    const stubHeight = effMaxHeight * STUB_FRACTION;
    const terminalBranches = [];
    for (let v = 0; v < visible.length; v++) {
      if (!visible[v].isCollapsed) continue;
      const cx = visibleX.get(visible[v].nodeId);
      // Same [x1,x2,x3,x4] / [y1,y2,y3,y4] shape as icoord/dcoord so the
      // renderer can reuse its scaling. A straight vertical stub: both x's are
      // the center; y goes stubHeight -> 0 -> 0 -> stubHeight (a thin U that
      // renders as a single line ending at center, height 0).
      terminalBranches.push({
        nodeId: visible[v].nodeId,
        center: cx,
        icoord: [cx, cx, cx, cx],
        dcoord: [stubHeight, 0, 0, stubHeight],
      });
    }

    return {
      icoord: icoord,
      dcoord: dcoord,
      // ``leaves`` here is the ordered list of visible TERMINAL node ids.
      leaves: visible.map((v) => v.nodeId),
      branchNodeIds: branchNodeIds,
      leafCenters: leafCenters,
      terminalBranches: terminalBranches,
      maxHeight: effMaxHeight,
      visible: visible,
    };
  }

  // ----------------------------------------------------------------------
  // Click → node id mapping for branches
  // ----------------------------------------------------------------------
  //
  // Because computeVisibleDendrogram records ``branchNodeIds[k]`` alongside
  // each drawn U-shape, the renderer can attach that node id directly to the
  // clickable branch. Clicking it toggles collapse on that node id. No SciPy
  // ``icoord`` index translation is needed anymore — the geometry and the
  // node ids come from the same recomputation.

  /**
   * Convenience: is this node id one we can collapse (an internal node with
   * >= 2 leaves)? Single leaves aren't worth collapsing.
   */
  function isCollapsibleNode(tree, nodeId) {
    const kids = tree.children(nodeId);
    if (kids === null) return false;
    return leavesUnder(tree, nodeId).length >= 2;
  }

  const api = {
    buildTree: buildTree,
    visibleLeaves: visibleLeaves,
    leavesUnder: leavesUnder,
    computeVisibleDendrogram: computeVisibleDendrogram,
    isCollapsibleNode: isCollapsibleNode,
  };

  global.HeatmapTreeLayout = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
