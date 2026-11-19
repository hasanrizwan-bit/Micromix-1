// activeDataframe.js — resolves the CURRENT Micromix "active working matrix"
// from a `/config` response's db_entry, for native (non-iframe) visualizations
// that fetch `/config` directly (PCoA, Clustered Heatmap).
//
// Convention (see Website/backend/app.py `respond_config()`,
// `process_file.py` add_matrix/remove_matrix, and app.py `/sample_selection`):
//   - `transformed_dataframe` is the PERMANENT merged upload. Always present,
//     never modified by filtering/selection.
//   - `filtered_dataframe` is a TEMPORARY, always-recomputable derived view:
//       * absent, or the literal empty array `[]`, when neither a row-level
//         query filter nor a sample-column selection is active;
//       * a non-empty array of records (already a plain array, or a JSON
//         string that needs `JSON.parse`) once either is active.
//
// Native visualizations must prefer `filtered_dataframe` when it is
// non-empty, exactly like the existing `/visualization` route already does
// for the iframe plugins (Heatmap/Clustergrammer). This is what makes the
// "active working matrix" (e.g. a sample selection made from PCoA) apply
// consistently to every visualization, not just the one that produced it.

function parseDataframeField(value) {
  if (typeof value === 'string') {
    try {
      return JSON.parse(value);
    } catch (err) {
      return null;
    }
  }
  return Array.isArray(value) ? value : null;
}

/**
 * Pick the record array a native visualization should render.
 *
 * @param {Object} dbEntry - the `db_entry` object from a `/config` response.
 * @returns {Array<Object>|null} the records to visualize, or null if the
 *   session has no active dataset at all.
 */
export function pickActiveDataframe(dbEntry) {
  if (!dbEntry) return null;
  const filtered = parseDataframeField(dbEntry.filtered_dataframe);
  if (filtered && filtered.length > 0) return filtered;
  return parseDataframeField(dbEntry.transformed_dataframe);
}
