/**
 * Detects value columns using the standard Micromix convention:
 * name.startsWith('(') && name.includes(') ')
 * Falls back to columns that are >=80% numeric if no prefixed columns exist.
 */
function detectValueColumns(recordKeys) {
  const prefixedCols = recordKeys.filter(
    (k) => k.startsWith('(') && k.includes(') ')
  );
  if (prefixedCols.length > 0) {
    return { valueColumns: prefixedCols, detectedByPrefix: true };
  }
  return { valueColumns: [], detectedByPrefix: false };
}

/**
 * Parse a column name like "(WT_TPM) sample1" into { matrixTitle, sample }.
 * Falls back to raw name if pattern doesn't match.
 */
function parseColumnName(name) {
  const match = name.match(/^\((.+?)\)\s+(.+)$/);
  if (match) {
    return { matrixTitle: match[1], sample: match[2], pretty: `${match[1]} \u00b7 ${match[2]}` };
  }
  return { matrixTitle: '', sample: name, pretty: name };
}

/**
 * Handle duplicate row IDs by appending #2, #3, etc.
 */
function deduplicateIds(ids) {
  const counts = {};
  const result = [];
  for (const id of ids) {
    if (!counts[id]) {
      counts[id] = 1;
      result.push(id);
    } else {
      counts[id] += 1;
      result.push(`${id}#${counts[id]}`);
    }
  }
  return result;
}

/**
 * Check what percentage of values in a record's columns are numeric.
 */
function numericFraction(records, col) {
  let numeric = 0;
  let total = 0;
  for (const rec of records) {
    const v = rec[col];
    if (v !== null && v !== undefined) {
      total += 1;
      if (Number.isFinite(Number(v))) numeric += 1;
    }
  }
  return total === 0 ? 0 : numeric / total;
}

/**
 * Apply the selected value-mode transform to a single raw value.
 * Returns null when the transform is undefined for that value.
 *
 * Z-score is a column-level transform so it is handled separately with
 * precomputed column mean/std.
 */
function transformValue(v, valueMode) {
  if (v === null) return null;
  if (valueMode === 'presence') return v > 0 ? 1 : 0;
  if (valueMode === 'log') {
    // log10(v + 1) is only defined for v > -1. Treat 0 as 0 (log10(1) = 0)
    // and negatives as null to avoid complex numbers.
    if (v === 0) return 0;
    if (v < 0) return null;
    return Math.log10(v + 1);
  }
  return v;
}

/**
 * Build the internal HeatmapMatrix from JSON records.
 *
 * @param {Array<Object>} jsonRecords - array of records from /config
 * @param {Object} opts
 * @param {string} opts.valueMode - 'numeric' | 'presence' | 'log' | 'zscore'
 * @param {string} opts.missingPolicy - 'nan' | 'zero' | 'mean'
 * @returns {Object} HeatmapMatrix
 */
export function buildMatrix(jsonRecords, opts = {}) {
  const { valueMode = 'numeric', missingPolicy = 'mean' } = opts;

  if (!jsonRecords || jsonRecords.length === 0) {
    return {
      rowIds: [],
      colIds: [],
      rowLabels: {},
      colLabels: {},
      colMeta: {},
      values: {},
      imputed: {},
      valueMode,
      missingPolicy,
      stats: { rowMin: {}, rowMax: {}, colMin: {}, colMax: {}, globalMin: 0, globalMax: 0, globalMean: 0 },
      warnings: [],
    };
  }

  const keys = Object.keys(jsonRecords[0]);
  const rowIdKey = keys[0];

  // Detect value columns
  let { valueColumns, detectedByPrefix } = detectValueColumns(keys);

  // Fallback: if no prefixed columns, use columns that are >=80% numeric
  if (!detectedByPrefix && valueColumns.length === 0) {
    valueColumns = keys.slice(1).filter((k) => numericFraction(jsonRecords, k) >= 0.8);
  }

  // Non-value columns are categorical metadata
  const metaColumns = keys.filter((k) => k !== rowIdKey && !valueColumns.includes(k));

  // Extract row IDs and handle duplicates. We keep them in the same index order
  // as jsonRecords so downstream loops can use the record index directly
  // (O(N) rather than O(N^2) via indexOf).
  let rowIds = jsonRecords.map((r) => {
    const v = r[rowIdKey];
    return v === null || v === undefined || v === '' ? null : String(v);
  });

  const warnings = [];
  let nullCount = 0;
  for (let i = 0; i < rowIds.length; i++) {
    if (rowIds[i] === null) {
      rowIds[i] = `row_${i}`;
      nullCount++;
    }
  }
  if (nullCount > 0) {
    warnings.push(`${nullCount} row(s) had null/empty IDs, assigned fallback names`);
  }

  const preDedup = rowIds.slice();
  rowIds = deduplicateIds(rowIds);
  let dupCount = 0;
  for (let i = 0; i < rowIds.length; i++) {
    if (rowIds[i] !== preDedup[i]) dupCount += 1;
  }
  if (dupCount > 0) {
    warnings.push(`${dupCount} duplicate row ID(s) detected, suffixed with #N`);
  }

  // Build column metadata
  const colMeta = {};
  const colLabels = {};
  for (const col of valueColumns) {
    const parsed = parseColumnName(col);
    colMeta[col] = parsed;
    colLabels[col] = parsed.pretty;
  }

  // Build row metadata
  const rowMeta = {};
  for (let i = 0; i < jsonRecords.length; i++) {
    const rec = jsonRecords[i];
    const id = rowIds[i];
    rowMeta[id] = {};
    for (const mc of metaColumns) {
      rowMeta[id][mc] = rec[mc];
    }
  }

  // Build row labels: use id, or append name/symbol if available in meta
  const rowLabels = {};
  for (const id of rowIds) {
    const meta = rowMeta[id];
    let label = id;
    if (meta) {
      const name = meta.Name || meta.name || meta.symbol || meta.Symbol;
      if (name) label = `${id} (${name})`;
    }
    rowLabels[id] = label;
  }

  // First pass: collect raw numeric values and compute column means / std.
  // Raw values are kept in a column-major buffer so we can z-score efficiently.
  const colRaw = {};
  const colMeans = {};
  const colStds = {};
  for (const col of valueColumns) {
    colRaw[col] = new Array(rowIds.length);
    let colSum = 0;
    let colCount = 0;
    for (let i = 0; i < rowIds.length; i++) {
      const rawVal = jsonRecords[i]?.[col];
      let v = rawVal === null || rawVal === undefined ? null : Number(rawVal);
      if (!Number.isFinite(v)) v = null;
      colRaw[col][i] = v;
      if (v !== null) {
        colSum += v;
        colCount += 1;
      }
    }
    colMeans[col] = colCount > 0 ? colSum / colCount : 0;

    // Column std (population) for z-score mode.
    let sqSum = 0;
    let sqCount = 0;
    for (let i = 0; i < rowIds.length; i++) {
      const v = colRaw[col][i];
      if (v !== null) {
        sqSum += (v - colMeans[col]) ** 2;
        sqCount += 1;
      }
    }
    colStds[col] = sqCount > 0 ? Math.sqrt(sqSum / sqCount) : 0;
  }

  // Second pass: apply value-mode transform and imputation, build values/imputed
  // maps, and track stats. `values` holds the *displayed* value (post-transform)
  // so colors and aggregates see the same numbers. `imputed` is used by the
  // clustering step and substitutes for null according to missingPolicy.
  const values = {};
  const imputed = {};
  const rowMin = {};
  const rowMax = {};
  const colMin = {};
  const colMax = {};

  for (const col of valueColumns) {
    colMin[col] = Infinity;
    colMax[col] = -Infinity;
  }

  let globalMin = Infinity;
  let globalMax = -Infinity;
  let globalSum = 0;
  let globalCount = 0;

  for (let i = 0; i < rowIds.length; i++) {
    const id = rowIds[i];
    values[id] = {};
    imputed[id] = {};
    rowMin[id] = Infinity;
    rowMax[id] = -Infinity;

    for (const col of valueColumns) {
      const raw = colRaw[col][i];

      // Apply the user-selected value-mode transform to produce the displayed
      // value. Null propagates.
      let displayVal;
      if (valueMode === 'zscore') {
        displayVal = raw !== null && colStds[col] > 0
          ? (raw - colMeans[col]) / colStds[col]
          : (raw !== null ? 0 : null);
      } else {
        displayVal = transformValue(raw, valueMode);
      }

      values[id][col] = displayVal;

      // Imputation happens on the *transformed* value so the clustering input
      // matches what is shown on screen.
      let imputedVal;
      if (displayVal === null) {
        if (missingPolicy === 'zero') imputedVal = 0;
        else if (missingPolicy === 'mean') {
          // For numeric mode, colMeans[col] is already correct. For z-score,
          // the column mean of a z-scored column is 0. For presence, the mean
          // is the presence fraction. Compute on the fly only for non-numeric
          // modes to keep perf reasonable.
          if (valueMode === 'numeric') imputedVal = colMeans[col];
          else if (valueMode === 'zscore') imputedVal = 0;
          else {
            // Fallback: use the raw column mean transformed, or 0.
            imputedVal = transformValue(colMeans[col], valueMode);
            if (imputedVal === null || !Number.isFinite(imputedVal)) imputedVal = 0;
          }
        } else imputedVal = null; // 'nan'
      } else {
        imputedVal = displayVal;
      }
      imputed[id][col] = imputedVal;

      if (displayVal !== null && Number.isFinite(displayVal)) {
        if (displayVal < globalMin) globalMin = displayVal;
        if (displayVal > globalMax) globalMax = displayVal;
        globalSum += displayVal;
        globalCount += 1;
        if (displayVal < colMin[col]) colMin[col] = displayVal;
        if (displayVal > colMax[col]) colMax[col] = displayVal;
        if (displayVal < rowMin[id]) rowMin[id] = displayVal;
        if (displayVal > rowMax[id]) rowMax[id] = displayVal;
      }
    }
  }

  if (globalCount === 0) {
    globalMin = 0;
    globalMax = 0;
  }

  for (let i = 0; i < rowIds.length; i++) {
    const id = rowIds[i];
    if (rowMin[id] === Infinity) rowMin[id] = 0;
    if (rowMax[id] === -Infinity) rowMax[id] = 0;
  }
  for (const col of valueColumns) {
    if (colMin[col] === Infinity) colMin[col] = 0;
    if (colMax[col] === -Infinity) colMax[col] = 0;
  }

  return {
    rowIds,
    colIds: valueColumns,
    rowLabels,
    colLabels,
    rowMeta,
    colMeta,
    values,
    imputed,
    valueMode,
    missingPolicy,
    stats: {
      rowMin,
      rowMax,
      colMin,
      colMax,
      globalMin,
      globalMax,
      globalMean: globalCount > 0 ? globalSum / globalCount : 0,
    },
    warnings,
  };
}
