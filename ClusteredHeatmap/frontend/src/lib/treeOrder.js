/**
 * Collect leaf IDs in DFS order from a dendrogram node.
 *
 * @param {DendroNode|DendroLeaf|null} node
 * @returns {string[]} ordered leaf IDs
 */
export function dfsLeaves(node) {
  if (!node) return [];
  if (node.kind === 'leaf') return [node.id];
  return [...dfsLeaves(node.left), ...dfsLeaves(node.right)];
}

/**
 * Collect all internal node IDs from a dendrogram tree.
 *
 * @param {DendroNode|null} node
 * @returns {string[]} internal node IDs
 */
export function allInternalNodeIds(node) {
  if (!node || node.kind === 'leaf') return [];
  const ids = [node.id];
  return [...ids, ...allInternalNodeIds(node.left), ...allInternalNodeIds(node.right)];
}

/**
 * Build the list of "visual rows" by walking the dendrogram in DFS order
 * and respecting collapsed nodes.
 *
 * @param {DendroNode|null} dendro
 * @param {Set<string>} collapsedSet
 * @returns {Array<{ type: "leaf", id: string } | { type: "cluster", nodeId: string, memberIds: string[], size: number }>}
 */
export function visualRows(dendro, collapsedSet) {
  if (!dendro) return [];
  const result = [];
  walk(dendro);
  return result;

  function walk(node) {
    if (node.kind === 'leaf') {
      result.push({ type: 'leaf', id: node.id });
      return;
    }
    if (collapsedSet.has(node.id)) {
      result.push({
        type: 'cluster',
        nodeId: node.id,
        memberIds: node.leaves,
        size: node.size,
      });
      return;
    }
    walk(node.left);
    walk(node.right);
  }
}

/**
 * Collect the "top-level" internal node IDs (children of the root).
 * Useful for default-collapse behavior on large datasets.
 *
 * @param {DendroNode|null} dendro
 * @returns {string[]}
 */
export function topLevelNodeIds(dendro) {
  if (!dendro || dendro.kind === 'leaf') return [];
  const ids = [];
  collect(dendro);
  return ids;

  function collect(node) {
    if (node.kind === 'leaf') return;
    if (node.left.kind === 'leaf' && node.right.kind === 'leaf') {
      // Don't include nodes whose children are both leaves (too granular)
      return;
    }
    // Include nodes at the second level from root
    if (node.left.kind === 'node') ids.push(node.left.id);
    if (node.right.kind === 'node') ids.push(node.right.id);
  }
}
