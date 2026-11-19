import { describe, it, expect } from 'vitest';
import {
  toggleInSet,
  addAllToSet,
  buildRawIdMap,
  rawIdsFor,
  buildSelectionRequest,
} from './heatmapSelection';

describe('toggleInSet', () => {
  it('adds an id that is not present, without mutating the input set', () => {
    const original = new Set(['a']);
    const next = toggleInSet(original, 'b');
    expect(next.has('b')).toBe(true);
    expect(original.has('b')).toBe(false); // input untouched
  });

  it('removes an id that is present', () => {
    const next = toggleInSet(new Set(['a', 'b']), 'a');
    expect(next.has('a')).toBe(false);
    expect(next.has('b')).toBe(true);
  });
});

describe('addAllToSet', () => {
  it('adds every id, de-duplicating against existing members', () => {
    const next = addAllToSet(new Set(['a']), ['a', 'b', 'c']);
    expect([...next].sort()).toEqual(['a', 'b', 'c']);
  });
});

describe('buildRawIdMap / rawIdsFor', () => {
  it('maps a deduped display id back to its raw backend id', () => {
    // Simulates buildMatrix()'s dedup suffixing: two rows both named "GeneX"
    // in the source data end up displayed as "GeneX" and "GeneX#2".
    const rowIds = ['GeneX', 'GeneX#2', 'GeneY'];
    const rawRowIds = ['GeneX', 'GeneX', 'GeneY'];
    const map = buildRawIdMap(rowIds, rawRowIds);

    expect(map.get('GeneX')).toBe('GeneX');
    expect(map.get('GeneX#2')).toBe('GeneX');
    expect(map.get('GeneY')).toBe('GeneY');
  });

  it('rawIdsFor de-duplicates when both dedup-siblings are selected', () => {
    const map = buildRawIdMap(['GeneX', 'GeneX#2', 'GeneY'], ['GeneX', 'GeneX', 'GeneY']);
    const raw = rawIdsFor(['GeneX', 'GeneX#2'], map);
    expect(raw).toEqual(['GeneX']);
  });

  it('falls back to the display id itself if it is missing from the map', () => {
    const map = buildRawIdMap(['GeneX'], ['GeneX']);
    expect(rawIdsFor(['Unmapped'], map)).toEqual(['Unmapped']);
  });

  it('is unaffected by reordering: the map is keyed by id, not position', () => {
    // Models "clustering rearranges rows" -- rowIds/rawRowIds passed here
    // are in a different order than the original upload, but the id -> raw
    // mapping must still be correct regardless of that order.
    const rowIds = ['GeneC', 'GeneA', 'GeneB'];
    const rawRowIds = ['GeneC', 'GeneA', 'GeneB'];
    const map = buildRawIdMap(rowIds, rawRowIds);
    expect(rawIdsFor(['GeneA'], map)).toEqual(['GeneA']);
    expect(rawIdsFor(['GeneC'], map)).toEqual(['GeneC']);
  });
});

describe('buildSelectionRequest', () => {
  const rawIdMap = buildRawIdMap(['GeneA', 'GeneB'], ['GeneA', 'GeneB']);

  it('rows only: sample_ids stays null so all current samples are preserved', () => {
    const req = buildSelectionRequest({
      selectedRowDisplayIds: new Set(['GeneA']),
      selectedColIds: new Set(),
      rawIdMap,
    });
    expect(req).toEqual({ row_ids: ['GeneA'], sample_ids: null, isEmpty: false });
  });

  it('columns only: row_ids stays null so all current rows are preserved', () => {
    const req = buildSelectionRequest({
      selectedRowDisplayIds: new Set(),
      selectedColIds: new Set(['(Title) sample1']),
      rawIdMap,
    });
    expect(req).toEqual({ row_ids: null, sample_ids: ['(Title) sample1'], isEmpty: false });
  });

  it('both selected: both arrays are present (intersection)', () => {
    const req = buildSelectionRequest({
      selectedRowDisplayIds: new Set(['GeneA', 'GeneB']),
      selectedColIds: new Set(['(Title) sample1']),
      rawIdMap,
    });
    expect(req.row_ids).toEqual(['GeneA', 'GeneB']);
    expect(req.sample_ids).toEqual(['(Title) sample1']);
    expect(req.isEmpty).toBe(false);
  });

  it('neither selected: both null and isEmpty is true (caller should skip the request)', () => {
    const req = buildSelectionRequest({
      selectedRowDisplayIds: new Set(),
      selectedColIds: new Set(),
      rawIdMap,
    });
    expect(req).toEqual({ row_ids: null, sample_ids: null, isEmpty: true });
  });

  describe('preserving the untouched axis via explicit full lists', () => {
    // Models: a PCoA sample selection was already applied before this
    // Clustered Heatmap session opened, so the matrix currently only shows
    // 2 of the original samples. Selecting rows-only here must not silently
    // widen back out to "every sample that was ever uploaded" -- it must
    // preserve exactly the 2 samples currently active.
    const allColIds = ['(Title) sample1', '(Title) sample2'];
    const allRawRowIds = ['GeneA', 'GeneB', 'GeneC'];

    it('rows-only + allColIds provided: sample_ids preserves the full current column list, not null', () => {
      const req = buildSelectionRequest({
        selectedRowDisplayIds: new Set(['GeneA']),
        selectedColIds: new Set(),
        rawIdMap,
        allColIds,
      });
      expect(req.row_ids).toEqual(['GeneA']);
      expect(req.sample_ids).toEqual(allColIds);
    });

    it('columns-only + allRawRowIds provided: row_ids preserves the full current row list, not null', () => {
      const req = buildSelectionRequest({
        selectedRowDisplayIds: new Set(),
        selectedColIds: new Set(['(Title) sample1']),
        rawIdMap,
        allRawRowIds,
      });
      expect(req.sample_ids).toEqual(['(Title) sample1']);
      expect(req.row_ids).toEqual(allRawRowIds);
    });

    it('both selected: allRawRowIds/allColIds are ignored (explicit selections win)', () => {
      const req = buildSelectionRequest({
        selectedRowDisplayIds: new Set(['GeneA']),
        selectedColIds: new Set(['(Title) sample1']),
        rawIdMap,
        allRawRowIds,
        allColIds,
      });
      expect(req.row_ids).toEqual(['GeneA']);
      expect(req.sample_ids).toEqual(['(Title) sample1']);
    });

    it('without allRawRowIds/allColIds (legacy call sites): falls back to null', () => {
      const req = buildSelectionRequest({
        selectedRowDisplayIds: new Set(['GeneA']),
        selectedColIds: new Set(),
        rawIdMap,
      });
      expect(req.sample_ids).toBeNull();
    });
  });
});
