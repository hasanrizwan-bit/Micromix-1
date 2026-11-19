/**
 * Compute aggregate values for a collapsed cluster node.
 *
 * `matrix.values` already holds the user-selected value-mode transform applied
 * (see matrix.js:buildMatrix), so this function consumes those values
 * directly and does not re-transform. The `valueMode` argument is kept for
 * API compatibility and for callers that want to override the aggregation
 * behaviour per-mode (e.g. presence_pct).
 *
 * @param {Object} matrix - HeatmapMatrix from matrix.js
 * @param {string[]} memberIds - row IDs (or column IDs) belonging to this cluster
 * @param {string} axis - 'row' (aggregate across rows per column) or 'col' (aggregate across cols per row)
 * @param {string} aggregation - 'mean' | 'median' | 'sum' | 'presence_pct'
 * @param {string} valueMode - informational; see note above
 * @returns {Record<string, number|null>} aggregated values keyed by the opposite axis IDs
 */
export function aggregateCluster(matrix, memberIds, axis = 'row', aggregation = 'mean' /* , valueMode */) {
  const targetIds = axis === 'row' ? matrix.colIds : matrix.rowIds;
  const result = {};

  for (const targetId of targetIds) {
    const values = [];
    for (const memberId of memberIds) {
      const v = axis === 'row'
        ? matrix.values[memberId]?.[targetId]
        : matrix.values[targetId]?.[memberId];
      if (v === null || v === undefined || !Number.isFinite(v)) continue;
      values.push(v);
    }

    if (values.length === 0) {
      result[targetId] = null;
      continue;
    }

    if (aggregation === 'mean') {
      const sum = values.reduce((a, b) => a + b, 0);
      result[targetId] = sum / values.length;
    } else if (aggregation === 'presence_pct') {
      // Count entries that are strictly greater than zero. This is well-defined
      // regardless of the value mode: for "presence" mode values are already
      // 0/1 so this equals the fraction of members with a non-zero value.
      let present = 0;
      for (const v of values) if (v > 0) present += 1;
      result[targetId] = (present / values.length) * 100;
    } else if (aggregation === 'median') {
      const sorted = [...values].sort((a, b) => a - b);
      const mid = Math.floor(sorted.length / 2);
      result[targetId] = sorted.length % 2 !== 0
        ? sorted[mid]
        : (sorted[mid - 1] + sorted[mid]) / 2;
    } else if (aggregation === 'sum') {
      result[targetId] = values.reduce((a, b) => a + b, 0);
    } else {
      // Unknown aggregation: default to mean rather than silently returning 0.
      const sum = values.reduce((a, b) => a + b, 0);
      result[targetId] = sum / values.length;
    }
  }

  return result;
}
