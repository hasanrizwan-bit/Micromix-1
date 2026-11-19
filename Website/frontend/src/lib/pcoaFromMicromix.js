// pcoaFromMicromix.js — converts the CURRENTLY OPEN Micromix dataset into the
// sample x feature CSV matrix expected by the existing, unmodified PCoA
// backend (see backend/pcoa/service.py).
//
// Why this file exists
// ---------------------------------------------------------------------
// The native Clustered Heatmap already treats the Micromix dataframe
// (fetched from the same `/config` route App.vue and every other
// visualization use) as rows = genes/features, columns = sample/condition
// value columns, using buildMatrix() in ./matrix.js to tell metadata columns
// (Locus Tag, Name, gene annotations, ...) apart from numeric sample
// columns (the "(prefix) sample" convention also used by
// backend/plugins/Clustergrammer.py and backend/plugins/Heatmap.py).
//
// The PCoA service, however, expects the OPPOSITE orientation: rows =
// samples, columns = features (first column = sample id, first row =
// feature names, see backend/pcoa/service.py::parse_matrix). This module
// does ONLY the orientation + column-selection work — value detection,
// metadata exclusion and missing-value handling are fully delegated to
// buildMatrix() so PCoA follows the exact same "what counts as a sample
// column" convention as Heatmap/Clustergrammer/Clustered Heatmap. The PCoA
// math itself (distance, classical MDS, validation) is untouched: this
// module only ever produces the plain CSV text that the existing
// `/api/pcoa` multipart upload endpoint already knows how to parse.

import { buildMatrix } from './matrix';
import { csvField } from './pcoaRender';

/** Raised when the current Micromix dataset cannot be turned into a PCoA matrix. */
export class MicromixPcoaConversionError extends Error {}

/**
 * Build a PCoA-ready sample x feature CSV from Micromix `/config` records.
 *
 * Orientation: Micromix's `transformed_dataframe` is genes/features (rows) x
 * sample/condition value columns (columns). PCoA needs samples (rows) x
 * features (columns), so this function TRANSPOSES the detected value-column
 * matrix: each Micromix value column becomes one PCoA sample (one CSV row),
 * and each Micromix row (gene) becomes one PCoA feature (one CSV column).
 *
 * @param {Array<Object>} jsonRecords - parsed `transformed_dataframe` records
 *   (the same records passed to buildMatrix() by clusteredHeatmapCanvas.vue).
 * @returns {{
 *   csvText: string,
 *   sampleIds: string[],
 *   featureNames: string[],
 *   sampleCount: number,
 *   featureCount: number,
 *   warnings: string[],
 * }}
 * @throws {MicromixPcoaConversionError} when there is no usable dataset, no
 *   detected sample/value columns, or no feature rows.
 */
export function buildPcoaMatrixFromMicromix(jsonRecords) {
  if (!jsonRecords || jsonRecords.length === 0) {
    throw new MicromixPcoaConversionError(
      'No active Micromix dataset is available for PCoA.'
    );
  }

  // Same value-column detection, metadata exclusion and missing-value
  // imputation as the native Clustered Heatmap's default settings
  // (numeric mode, mean imputation) — see clusteredHeatmapCanvas.vue's
  // `rebuildMatrix()`. This is the single source of truth for "which
  // columns are samples" that this module defers to.
  const matrix = buildMatrix(jsonRecords, {
    valueMode: 'numeric',
    missingPolicy: 'mean',
  });

  const sampleIds = matrix.colIds; // Micromix's numeric value columns -> PCoA samples (points)
  const featureNames = matrix.rowIds; // Micromix's rows (genes) -> PCoA features (distance basis)

  if (sampleIds.length === 0) {
    throw new MicromixPcoaConversionError(
      'No numeric sample/value columns were found in the current Micromix dataset.'
    );
  }
  if (featureNames.length === 0) {
    throw new MicromixPcoaConversionError(
      'The current Micromix dataset has no rows to use as PCoA features.'
    );
  }

  // Transpose. Micromix stores values as values[rowId(gene)][colId(sample)];
  // the PCoA CSV needs one row per sample, one column per gene.
  const header = ['Sample ID'].concat(featureNames).map(csvField).join(',');
  const lines = [header];
  for (const sampleId of sampleIds) {
    const cells = [csvField(sampleId)];
    for (const featureId of featureNames) {
      const imputedRow = matrix.imputed[featureId];
      const value = imputedRow ? imputedRow[sampleId] : null;
      cells.push(value === null || value === undefined || !Number.isFinite(value) ? '0' : String(value));
    }
    lines.push(cells.join(','));
  }

  return {
    csvText: lines.join('\n') + '\n',
    sampleIds,
    featureNames,
    sampleCount: sampleIds.length,
    featureCount: featureNames.length,
    warnings: matrix.warnings,
  };
}

/**
 * Wrap the converted CSV text in a File so it can be sent through the SAME
 * multipart upload path the PCoA backend already handles (see
 * PcoaCanvas.vue's `uploadRequest`), keeping the backend route, parsing,
 * validation and dataset_id caching completely unchanged.
 */
export function buildPcoaFileFromMicromix(jsonRecords, filename) {
  const converted = buildPcoaMatrixFromMicromix(jsonRecords);
  const file = new File([converted.csvText], filename || 'micromix_current_dataset.csv', {
    type: 'text/csv',
  });
  return { file, ...converted };
}
