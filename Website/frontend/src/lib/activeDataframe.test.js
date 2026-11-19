import { describe, it, expect } from 'vitest';
import { pickActiveDataframe } from './activeDataframe';

describe('pickActiveDataframe', () => {
  it('returns null when there is no db entry', () => {
    expect(pickActiveDataframe(null)).toBeNull();
  });

  it('prefers a non-empty filtered_dataframe over transformed_dataframe', () => {
    // Models: PCoA (or a prior Clustered Heatmap "Apply Selection") already
    // produced a working-matrix subset. Any native visualization that reads
    // via pickActiveDataframe must receive THAT subset, not the full
    // original dataset.
    const dbEntry = {
      transformed_dataframe: [{ gene: 'A' }, { gene: 'B' }, { gene: 'C' }],
      filtered_dataframe: [{ gene: 'A' }],
    };
    expect(pickActiveDataframe(dbEntry)).toEqual([{ gene: 'A' }]);
  });

  it('falls back to transformed_dataframe when filtered_dataframe is empty', () => {
    const dbEntry = {
      transformed_dataframe: [{ gene: 'A' }, { gene: 'B' }],
      filtered_dataframe: [],
    };
    expect(pickActiveDataframe(dbEntry)).toEqual([{ gene: 'A' }, { gene: 'B' }]);
  });

  it('parses a JSON-string filtered_dataframe (as returned by /config before App.vue parses it)', () => {
    const dbEntry = {
      transformed_dataframe: [{ gene: 'A' }],
      filtered_dataframe: JSON.stringify([{ gene: 'B' }]),
    };
    expect(pickActiveDataframe(dbEntry)).toEqual([{ gene: 'B' }]);
  });

  it('falls back to transformed_dataframe when filtered_dataframe is absent', () => {
    const dbEntry = { transformed_dataframe: [{ gene: 'A' }] };
    expect(pickActiveDataframe(dbEntry)).toEqual([{ gene: 'A' }]);
  });
});
