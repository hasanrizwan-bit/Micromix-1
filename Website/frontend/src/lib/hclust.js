/**
 * Agglomerative hierarchical clustering with average linkage (UPGMA).
 *
 * @param {number[][]} distMatrix - symmetric pairwise distance matrix (array of arrays)
 * @param {Object} opts
 * @param {string[]} opts.leafIds - optional labels for leaves
 * @returns {DendroNode|null} root of the dendrogram tree
 *
 * DendroNode shape:
 * {
 *   kind: "node",
 *   id: string,
 *   height: number,
 *   size: number,
 *   left: DendroLeaf | DendroNode,
 *   right: DendroLeaf | DendroNode,
 *   leaves: string[],
 * }
 *
 * DendroLeaf shape:
 * {
 *   kind: "leaf",
 *   id: string,
 *   index: number,
 * }
 */
export function cluster(distMatrix, { leafIds } = {}) {
  const n = distMatrix.length;
  if (n < 2) {
    if (leafIds && leafIds.length > 0) {
      return { kind: 'leaf', id: leafIds[0], index: 0 };
    }
    return null;
  }

  // Each cluster tracks: { leaves: string[], node: DendroLeaf|DendroNode, size: number }
  const clusters = [];
  for (let i = 0; i < n; i++) {
    const leafId = leafIds ? leafIds[i] : String(i);
    clusters.push({
      leaves: [leafId],
      node: { kind: 'leaf', id: leafId, index: i },
      size: 1,
    });
  }

  // Mutable distance matrix. Use plain arrays (not Float64Array) so we can
  // extend rows as merged clusters are added without OOB silent-writes.
  const dist = [];
  for (let i = 0; i < n; i++) {
    dist[i] = new Array(n);
    for (let j = 0; j < n; j++) {
      dist[i][j] = distMatrix[i][j];
    }
  }

  const active = new Set(Array.from({ length: n }, (_, i) => i));
  let nodeId = 0;

  while (active.size > 1) {
    // Find the two closest active clusters
    let minDist = Infinity;
    let ci = -1;
    let cj = -1;
    const indices = Array.from(active).sort((a, b) => a - b);

    for (let a = 0; a < indices.length; a++) {
      for (let b = a + 1; b < indices.length; b++) {
        const i = indices[a];
        const j = indices[b];
        const d = dist[i][j];
        if (d !== undefined && d < minDist) {
          minDist = d;
          ci = i;
          cj = j;
        }
      }
    }

    if (ci === -1 || cj === -1) break;

    const clusterI = clusters[ci];
    const clusterJ = clusters[cj];

    // Create merged node
    const newNode = {
      kind: 'node',
      id: `n_${nodeId++}`,
      height: minDist,
      size: clusterI.size + clusterJ.size,
      left: clusterI.node,
      right: clusterJ.node,
      leaves: [...clusterI.leaves, ...clusterJ.leaves],
    };

    // Register new cluster; its index is the current length.
    const newIdx = clusters.length;
    clusters.push({
      leaves: newNode.leaves,
      node: newNode,
      size: newNode.size,
    });

    // Allocate the new row. It needs room for its own index (newIdx) so existing
    // rows can also address back into it.
    dist[newIdx] = new Array(newIdx + 1);

    // Compute UPGMA (weighted average by cluster size) distance from the new
    // cluster to every still-active cluster, and record both directions so
    // symmetric lookups work regardless of index order.
    for (const k of active) {
      if (k === ci || k === cj) continue;
      const dNewK = (clusterI.size * dist[ci][k] + clusterJ.size * dist[cj][k]) / (clusterI.size + clusterJ.size);
      dist[newIdx][k] = dNewK;
      // Extend dist[k] so dist[k][newIdx] is addressable. Rows are plain arrays
      // so direct assignment extends length as needed.
      dist[k][newIdx] = dNewK;
    }

    // Remove merged clusters, add new one
    active.delete(ci);
    active.delete(cj);
    active.add(newIdx);
  }

  const rootIdx = Array.from(active)[0];
  return clusters[rootIdx].node;
}

/**
 * Check if there are enough members to cluster.
 */
export function canCluster(n) {
  return n >= 3;
}
