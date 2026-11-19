<template>
  <svg
    :width="svgWidth"
    :height="svgHeight"
    class="dendrogram-svg"
    :class="{ vertical: orientation === 'top', horizontal: orientation === 'left' }"
  >
    <g :transform="orientation === 'top' ? `translate(${svgWidth}, 0) rotate(90)` : ''">
    <template v-if="tree">
      <g class="dendrogram-links">
        <path
          v-for="link in layout.links"
          :key="link.key"
          :d="link.path"
          class="dendro-link"
          :class="{ collapsed: collapsedSet.has(link.nodeId) }"
          @click="emitClick(link.nodeId)"
        />
      </g>
      <g class="dendro-nodes">
        <circle
          v-for="node in layout.nodes"
          :key="node.id"
          :cx="node.cx"
          :cy="node.cy"
          r="4"
          class="dendro-node"
          :class="{ collapsed: collapsedSet.has(node.id) }"
          @click="emitClick(node.id)"
        >
          <title>{{ collapsedSet.has(node.id) ? `Expand (${node.size} items)` : `Collapse (${node.size} items)` }}</title>
        </circle>
      </g>
      <g class="collapsed-indicators">
        <polygon
          v-for="cn in layout.collapsedIndicators"
          :key="cn.id"
          :points="cn.points"
          class="collapsed-triangle"
          @click="emitClick(cn.id)"
        />
      </g>
    </template>
    </g>
  </svg>
</template>

<script>
// Compute the full dendrogram layout in a single O(N) traversal so the
// component re-renders cheaply. Leaf y-positions (or x-positions for the
// "top" orientation) are laid out along the axis parallel to the heatmap
// body, and internal-node positions are placed at the midpoint of their
// descendant leaves. Horizontal depth is proportional to the node's
// linkage height (clamped so we do not degenerate to a single line).
function buildLayout(tree, collapsedSet, cellSize, maxWidth) {
  const links = [];
  const nodes = [];
  const collapsedIndicators = [];

  if (!tree) {
    return { links, nodes, collapsedIndicators, axisLength: 0, maxHeight: 0 };
  }

  // First pass: compute max linkage height so we can scale depth.
  let maxHeight = 0;
  (function scanHeights(node) {
    if (!node || node.kind === 'leaf') return;
    if (node.height > maxHeight) maxHeight = node.height;
    scanHeights(node.left);
    scanHeights(node.right);
  })(tree);
  if (maxHeight === 0) maxHeight = 1; // avoid div-by-zero when every distance is equal

  // Reserve a small pad so the furthest-out nodes are not exactly at x=0.
  const depthPad = 4;
  const usableWidth = Math.max(maxWidth - depthPad, 1);

  // Second pass: compute axis positions by DFS. Each call returns the axis
  // center of the subtree. Collapsed nodes do not descend into children.
  let leafCursor = 0;
  function dfs(node, depthScale) {
    if (node.kind === 'leaf') {
      const axis = leafCursor * cellSize + cellSize / 2;
      leafCursor += 1;
      return { axis, node };
    }
    if (collapsedSet.has(node.id)) {
      // Reserve a single cell for the collapsed representation.
      const axis = leafCursor * cellSize + cellSize / 2;
      leafCursor += 1;
      collapsedIndicators.push({
        id: node.id,
        points: buildTrianglePoints(axis, maxWidth),
      });
      // Even a collapsed node still gets a clickable circle.
      nodes.push({
        id: node.id,
        cx: maxWidth - depthPad - usableWidth * (node.height / maxHeight),
        cy: axis,
        size: node.size,
      });
      return { axis, node };
    }

    const left = dfs(node.left, depthScale);
    const right = dfs(node.right, depthScale);
    const axis = (left.axis + right.axis) / 2;
    const nodeX = maxWidth - depthPad - usableWidth * (node.height / maxHeight);

    // Children are drawn at their own linkage depth. Leaves sit at x = maxWidth - depthPad.
    const leftChildX = node.left.kind === 'leaf'
      ? maxWidth - depthPad
      : maxWidth - depthPad - usableWidth * (node.left.height / maxHeight);
    const rightChildX = node.right.kind === 'leaf'
      ? maxWidth - depthPad
      : maxWidth - depthPad - usableWidth * (node.right.height / maxHeight);

    // Draw two L-shaped connectors: from the parent corner down to each child's
    // axis, then horizontally to the child's own x.
    links.push({
      key: `${node.id}_left`,
      nodeId: node.id,
      path: `M${nodeX},${left.axis} L${leftChildX},${left.axis}`,
    });
    links.push({
      key: `${node.id}_right`,
      nodeId: node.id,
      path: `M${nodeX},${right.axis} L${rightChildX},${right.axis}`,
    });
    links.push({
      key: `${node.id}_spine`,
      nodeId: node.id,
      path: `M${nodeX},${left.axis} L${nodeX},${right.axis}`,
    });

    nodes.push({
      id: node.id,
      cx: nodeX,
      cy: axis,
      size: node.size,
    });

    return { axis, node };
  }

  dfs(tree, 1);

  return {
    links,
    nodes,
    collapsedIndicators,
    axisLength: leafCursor * cellSize,
    maxHeight,
  };
}

function buildTrianglePoints(axis, maxWidth) {
  // Render the collapsed indicator as a small triangle pointing at the node.
  const x = maxWidth - 10;
  const y = axis;
  return `${x - 6},${y - 4} ${x},${y} ${x - 6},${y + 4}`;
}

export default {
  name: 'DendrogramSVG',
  props: {
    tree: { type: Object, default: null },
    orientation: { type: String, default: 'left' },
    cellSize: { type: Number, default: 20 },
    collapsedSet: { type: Set, default: () => new Set() },
    maxWidth: { type: Number, default: 120 },
  },
  computed: {
    layout() {
      // buildLayout is O(N) in leaves and runs once per reactive change,
      // rather than once per computed property.
      return buildLayout(this.tree, this.collapsedSet, this.cellSize, this.maxWidth);
    },
    svgWidth() {
      if (this.orientation === 'left') return this.maxWidth;
      return Math.max(this.layout.axisLength, 20);
    },
    svgHeight() {
      if (this.orientation === 'left') return Math.max(this.layout.axisLength, 20);
      return this.maxWidth;
    },
  },
  methods: {
    emitClick(nodeId) {
      // nodeId is always the true DendroNode.id (never a "_left"/"_right" suffix).
      this.$emit('branch-clicked', nodeId);
    },
  },
};
</script>

<style scoped>
.dendrogram-svg {
  display: block;
}

.dendro-link {
  fill: none;
  stroke: #2c3e50;
  stroke-width: 1.5;
  cursor: pointer;
}

.dendro-link.collapsed {
  stroke: #6c757d;
  stroke-dasharray: 4 2;
}

.dendro-link:hover {
  stroke: #007bff;
  stroke-width: 2.5;
}

.dendro-node {
  fill: #2c3e50;
  cursor: pointer;
}

.dendro-node.collapsed {
  fill: #dc3545;
}

.dendro-node:hover {
  fill: #007bff;
}

.collapsed-triangle {
  fill: #dc3545;
  cursor: pointer;
}

.collapsed-triangle:hover {
  fill: #c82333;
}
</style>
