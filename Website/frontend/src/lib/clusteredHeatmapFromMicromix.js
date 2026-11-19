// clusteredHeatmapFromMicromix.js — converts the CURRENTLY OPEN Micromix
// dataset into the {row_labels, column_labels, values} matrix shape the
// existing, unmodified Clustered Heatmap backend expects (see
// Website/backend/clustered_heatmap/service.py::cluster_matrix, itself a
// verbatim port of ClusteredHeatmap2's `/api/clustered-heatmap-data` route).
//
// Why this file exists
// ---------------------------------------------------------------------
// The Clustered Heatmap's row/column orientation already matches Micromix's
// natural orientation (rows = genes/features, columns = sample/condition
// value columns), unlike PCoA (see pcoaFromMicromix.js), so no transpose is
// needed here -- only column detection and shape conversion. Value-column
// detection, metadata exclusion and the "(<matrix title>) <column>" naming
// convention are fully delegated to buildMatrix() so this follows the exact
// same "what counts as a sample column" rule as PCoA/Heatmap/Clustergrammer.
//
// Unlike PCoA's adapter (which imputes missing values with the column mean
// because the PCoA math requires a complete matrix), this adapter keeps
// missing cells as `null` (missingPolicy: 'nan'): the clustering backend
// already replaces NaN with 0 ONLY for the linkage math (verbatim from the
// reference) while preserving `null` in the values it returns, so there is
// no need to pre-impute here.

import { buildMatrix } from './matrix';

/** Raised when the current Micromix dataset cannot be turned into a clustered-heatmap matrix. */
export class MicromixClusteredHeatmapConversionError extends Error {}

/**
 * Build a {row_labels, column_labels, values} matrix from Micromix `/config`
 * records, ready to POST to `/api/clustered_heatmap`.
 *
 * @param {Array<Object>} jsonRecords - parsed active-dataframe records (see
 *   lib/activeDataframe.js::pickActiveDataframe).
 * @returns {{
 *   rowLabels: string[],
 *   columnLabels: string[],
 *   values: Array<Array<number|null>>,
 *   rowCount: number,
 *   columnCount: number,
 *   warnings: string[],
 * }}
 * @throws {MicromixClusteredHeatmapConversionError} when there is no usable
 *   dataset, no detected sample/value columns, or no feature rows.
 */
export function buildClusteredHeatmapMatrixFromMicromix(jsonRecords) {
  if (!jsonRecords || jsonRecords.length === 0) {
    throw new MicromixClusteredHeatmapConversionError(
      'No active Micromix dataset is available for the Clustered Heatmap.'
    );
  }

  // Numeric mode, no imputation: the backend's own NaN handling (identical
  // to the reference implementation's) is the single source of truth for
  // what a missing cell does to the clustering.
  const matrix = buildMatrix(jsonRecords, {
    valueMode: 'numeric',
    missingPolicy: 'nan',
  });

  const rowIds = matrix.rowIds; // Micromix rows (genes) -> heat map rows
  const colIds = matrix.colIds; // Micromix numeric value columns -> heat map columns

  if (rowIds.length === 0) {
    throw new MicromixClusteredHeatmapConversionError(
      'The current Micromix dataset has no rows to display in the Clustered Heatmap.'
    );
  }
  if (colIds.length === 0) {
    throw new MicromixClusteredHeatmapConversionError(
      'No numeric sample/value columns were found in the current Micromix dataset.'
    );
  }

  const rowLabels = rowIds.map((id) => matrix.rowLabels[id] || id);
  const columnLabels = colIds.map((id) => matrix.colLabels[id] || id);

  const values = rowIds.map((rowId) =>
    colIds.map((colId) => {
      const v = matrix.values[rowId] ? matrix.values[rowId][colId] : null;
      return v === null || v === undefined || !Number.isFinite(v) ? null : v;
    })
  );

  return {
    rowLabels,
    columnLabels,
    values,
    rowCount: rowIds.length,
    columnCount: colIds.length,
    warnings: matrix.warnings,
  };
}
