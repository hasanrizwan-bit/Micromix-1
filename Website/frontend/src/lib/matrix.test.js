import { describe, it, expect } from 'vitest';
import { buildMatrix } from './matrix';

function record(id, values) {
  const rec = { gene: id };
  Object.assign(rec, values);
  return rec;
}

describe('buildMatrix rawRowIds', () => {
  it('exposes rawRowIds index-aligned with rowIds, identical when no duplicates', () => {
    const records = [
      record('GeneA', { '(Title) s1': 1 }),
      record('GeneB', { '(Title) s1': 2 }),
    ];
    const matrix = buildMatrix(records);
    expect(matrix.rowIds).toEqual(['GeneA', 'GeneB']);
    expect(matrix.rawRowIds).toEqual(['GeneA', 'GeneB']);
  });

  it('maps a deduped display id back to the raw, un-suffixed backend value', () => {
    const records = [
      record('GeneX', { '(Title) s1': 1 }),
      record('GeneX', { '(Title) s1': 2 }), // duplicate raw id
      record('GeneY', { '(Title) s1': 3 }),
    ];
    const matrix = buildMatrix(records);

    // Display ids get a "#2" suffix to stay unique in the UI...
    expect(matrix.rowIds).toEqual(['GeneX', 'GeneX#2', 'GeneY']);
    // ...but rawRowIds preserves what the backend's row-id column actually
    // contains, so a selection can round-trip correctly.
    expect(matrix.rawRowIds).toEqual(['GeneX', 'GeneX', 'GeneY']);
  });

  it('returns an empty rawRowIds array for an empty input', () => {
    const matrix = buildMatrix([]);
    expect(matrix.rawRowIds).toEqual([]);
  });

  it('reordering the input records (simulating a different clustering result) does not desync rawRowIds', () => {
    // buildMatrix always derives rowIds/rawRowIds directly from the input
    // records in the order given; a caller that re-sorts records before
    // calling buildMatrix (or re-orders rows for display afterwards using
    // matrix.rowIds as the stable key, never a plain array index) can never
    // end up mapping a display id to the wrong raw id.
    const clusteredOrder = [
      record('GeneC', { '(Title) s1': 3 }),
      record('GeneA', { '(Title) s1': 1 }),
      record('GeneB', { '(Title) s1': 2 }),
    ];
    const matrix = buildMatrix(clusteredOrder);
    const rawById = new Map(matrix.rowIds.map((id, i) => [id, matrix.rawRowIds[i]]));
    expect(rawById.get('GeneC')).toBe('GeneC');
    expect(rawById.get('GeneA')).toBe('GeneA');
    expect(rawById.get('GeneB')).toBe('GeneB');
  });
});
