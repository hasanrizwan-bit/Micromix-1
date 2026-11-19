import { describe, it, expect } from 'vitest';
import {
  buildClusteredHeatmapMatrixFromMicromix,
  MicromixClusteredHeatmapConversionError,
} from './clusteredHeatmapFromMicromix';

function record(id, values) {
  const rec = { gene: id };
  Object.assign(rec, values);
  return rec;
}

describe('buildClusteredHeatmapMatrixFromMicromix', () => {
  it('converts Micromix records into a row x column numeric matrix without transposing', () => {
    const records = [
      record('GeneA', { '(WT_TPM) sample1': 1, '(WT_TPM) sample2': 2 }),
      record('GeneB', { '(WT_TPM) sample1': 3, '(WT_TPM) sample2': 4 }),
    ];

    const result = buildClusteredHeatmapMatrixFromMicromix(records);

    expect(result.rowLabels).toEqual(['GeneA', 'GeneB']);
    expect(result.columnLabels).toEqual(['WT_TPM \u00b7 sample1', 'WT_TPM \u00b7 sample2']);
    expect(result.values).toEqual([
      [1, 2],
      [3, 4],
    ]);
    expect(result.rowCount).toBe(2);
    expect(result.columnCount).toBe(2);
  });

  it('preserves missing cells as null instead of imputing them', () => {
    const records = [
      record('GeneA', { '(WT_TPM) sample1': null, '(WT_TPM) sample2': 2 }),
      record('GeneB', { '(WT_TPM) sample1': 3, '(WT_TPM) sample2': 4 }),
    ];

    const result = buildClusteredHeatmapMatrixFromMicromix(records);

    expect(result.values[0][0]).toBeNull();
    expect(result.values[0][1]).toBe(2);
  });

  it('throws MicromixClusteredHeatmapConversionError for an empty dataset', () => {
    expect(() => buildClusteredHeatmapMatrixFromMicromix([])).toThrow(
      MicromixClusteredHeatmapConversionError
    );
    expect(() => buildClusteredHeatmapMatrixFromMicromix(null)).toThrow(
      MicromixClusteredHeatmapConversionError
    );
  });

  it('throws when no numeric/value columns are detected', () => {
    const records = [record('GeneA', { annotation: 'foo' })];
    expect(() => buildClusteredHeatmapMatrixFromMicromix(records)).toThrow(
      /No numeric sample\/value columns/
    );
  });
});
