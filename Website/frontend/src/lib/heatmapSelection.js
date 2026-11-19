// heatmapSelection.js — pure, framework-free selection helpers for the
// Clustered Heatmap's row/column/cluster selection + "Apply Selection to
// Matrix" flow. Mirrors lib/pcoaSubset.js's style: no DOM, no Vue, fully
// unit-testable.
//
// Identity rule (see also lib/matrix.js's `rawRowIds`): rows must always be
// identified by their RAW (pre-dedup) backend row-id-column value, never by
// the deduped "#2"-suffixed display id and never by visual/grid position.
// Columns are identified by their exact Micromix value-column name (already
// unique, so no raw/display distinction is needed there).

/**
 * Return a new Set with `id` toggled in/out of `set`. Never mutates `set`.
 *
 * @param {Set<string>} set
 * @param {string} id
 * @returns {Set<string>}
 */
export function toggleInSet(set, id) {
  const next = new Set(set);
  if (next.has(id)) {
    next.delete(id);
  } else {
    next.add(id);
  }
  return next;
}

/**
 * Return a new Set with every id in `ids` added to `set`. Never mutates `set`.
 *
 * @param {Set<string>} set
 * @param {string[]} ids
 * @returns {Set<string>}
 */
export function addAllToSet(set, ids) {
  const next = new Set(set);
  for (const id of ids) next.add(id);
  return next;
}

/**
 * Map a list of DISPLAY row ids (as shown in the UI, possibly "#2"-suffixed)
 * to their RAW backend row-id-column values, using the `rawIdMap` built from
 * `matrix.rowIds`/`matrix.rawRowIds` (see `buildRawIdMap`).
 *
 * Unknown display ids (should not normally happen) are dropped rather than
 * throwing, since this is only ever fed ids that came from the matrix itself.
 *
 * @param {Iterable<string>} displayIds
 * @param {Map<string,string>} rawIdMap
 * @returns {string[]} de-duplicated raw ids
 */
export function rawIdsFor(displayIds, rawIdMap) {
  const seen = new Set();
  const out = [];
  for (const displayId of displayIds) {
    const raw = rawIdMap.has(displayId) ? rawIdMap.get(displayId) : displayId;
    if (!seen.has(raw)) {
      seen.add(raw);
      out.push(raw);
    }
  }
  return out;
}

/**
 * Build the display-id -> raw-id lookup used by `rawIdsFor`, from a
 * `buildMatrix()` result's `rowIds`/`rawRowIds` arrays (index-aligned).
 *
 * @param {string[]} rowIds - display ids (possibly "#2"-suffixed)
 * @param {string[]} rawRowIds - raw backend ids, same length/order
 * @returns {Map<string,string>}
 */
export function buildRawIdMap(rowIds, rawRowIds) {
  const map = new Map();
  const n = Math.min(rowIds ? rowIds.length : 0, rawRowIds ? rawRowIds.length : 0);
  for (let i = 0; i < n; i++) {
    map.set(rowIds[i], rawRowIds[i]);
  }
  return map;
}

/**
 * Build the `/matrix_selection` request body implementing the task's
 * "only restrict the axis that was actually selected" rule:
 *   - rows selected, no columns selected -> row_ids: [...], and sample_ids
 *     preserves every currently active sample column
 *   - columns selected, no rows selected -> sample_ids: [...], and row_ids
 *     preserves every currently active row
 *   - both selected -> both arrays present (intersection)
 *   - neither selected -> both null (== "nothing to apply"; callers should
 *     treat this as a no-op and not make a network request at all)
 *
 * IMPORTANT: the backend's `/matrix_selection` route always recomputes its
 * base matrix from the PERMANENT original dataset (composed only with the
 * session's row-level query filter), not from whatever the Clustered Heatmap
 * happened to already be displaying. So "preserve the untouched axis"
 * cannot be expressed by sending `null` for it (that would mean "no
 * restriction at all", i.e. every ORIGINAL row/sample, silently discarding
 * any selection already active before this Clustered Heatmap session was
 * opened, e.g. one made by PCoA). Instead, when `allRawRowIds`/`allColIds`
 * are provided (the full id lists the caller is CURRENTLY showing, which
 * already reflect any pre-existing selection because they were built from
 * `filtered_dataframe`), the untouched axis is resolved to that explicit
 * full list rather than `null`, so "preserve" always means "keep exactly
 * what's currently active," never "reset to everything."
 *
 * @param {Object} params
 * @param {Set<string>} params.selectedRowDisplayIds
 * @param {Set<string>} params.selectedColIds
 * @param {Map<string,string>} params.rawIdMap
 * @param {string[]} [params.allRawRowIds] - every row currently active/shown
 *   (e.g. `matrix.rawRowIds`); used to preserve rows when only columns were
 *   selected. Omit to fall back to `null` (legacy/lower-level behavior).
 * @param {string[]} [params.allColIds] - every sample column currently
 *   active/shown (e.g. `matrix.colIds`); used to preserve columns when only
 *   rows were selected. Omit to fall back to `null`.
 * @returns {{ row_ids: string[]|null, sample_ids: string[]|null, isEmpty: boolean }}
 */
export function buildSelectionRequest({
  selectedRowDisplayIds,
  selectedColIds,
  rawIdMap,
  allRawRowIds = null,
  allColIds = null,
}) {
  const hasRows = selectedRowDisplayIds && selectedRowDisplayIds.size > 0;
  const hasCols = selectedColIds && selectedColIds.size > 0;

  let row_ids = null;
  if (hasRows) {
    row_ids = rawIdsFor(selectedRowDisplayIds, rawIdMap);
  } else if (hasCols && allRawRowIds) {
    row_ids = Array.from(allRawRowIds);
  }

  let sample_ids = null;
  if (hasCols) {
    sample_ids = Array.from(selectedColIds);
  } else if (hasRows && allColIds) {
    sample_ids = Array.from(allColIds);
  }

  return {
    row_ids,
    sample_ids,
    isEmpty: !hasRows && !hasCols,
  };
}
