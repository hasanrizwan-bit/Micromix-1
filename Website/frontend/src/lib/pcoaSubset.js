// pcoaSubset.js — PURE state/selection/subset logic for the PCoA visualization
// (no DOM, no Vue). Ported from ClusteredHeatmap2's
// backend/static/js/pcoasubset.js, converted from an IIFE/global-exposing
// script into ES module exports so it can be imported by PcoaCanvas.vue and
// PcoaScatterPlot.vue. The logic itself (selection model, subset state
// machine, request builder, metadata parsing/colouring, box-selection
// geometry) is unchanged from the reference.
//
// ========================================================================
// WHAT LIVES HERE
// ========================================================================
//   * the SELECTION model            — ordered list of stable sample ids
//   * the SUBSET state machine       — original dataset vs. active subset
//   * the subset REQUEST builder     — dataset id + sample ids, nothing else
//   * optional sample METADATA       — parsing, categorical colour assignment
//   * plot GEOMETRY helpers          — box (rubber-band) selection hit test
//
// PcoaCanvas.vue / PcoaScatterPlot.vue own every DOM write and call into this
// module for all decisions, so "what is selected / what is being shown /
// what will be sent" stays testable without a browser or a Vue instance.
//
// ========================================================================
// STABLE SAMPLE IDENTITY (the load-bearing rule)
// ========================================================================
// A sample is identified ONLY by its ``sample_id`` — the first-column value of
// the uploaded matrix, which the backend validates to be non-blank and unique.
// That same string is:
//   * the key of the selection list here,
//   * the ``data-sample-id`` of the plotted point,
//   * the metadata lookup key,
//   * and the only thing sent back to the backend for a recalculation.
// Nothing in this file (or in the selection path of the scatter plot) ever
// uses a point's array index, pixel position, colour or rounded coordinate as
// an identity, so recolouring, re-rendering, resizing, filtering and
// recalculating cannot move a selection onto the wrong sample.
//
// ========================================================================
// STATE SHAPE (created by createState())
// ========================================================================
//   file             File | null    the uploaded file, kept so a subset can be
//                                   recomputed even if the server dropped its
//                                   cached copy of the dataset
//   filename         string
//   datasetId        string | null  opaque server handle for the ORIGINAL matrix
//   originalResult   payload | null full-dataset PCoA result (never mutated)
//   result           payload | null the PCoA result currently plotted
//   activeSampleIds  string[]|null  null = full dataset, array = active subset
//   selected         string[]       sample ids selected in the CURRENT plot
//   metadata         object | null  { fields, bySample, sampleIds, warnings }
//   colourField      string         metadata field used to colour points
//   busy             boolean        a request is in flight
//   error            string | null  last user-facing error
//
// The six concepts the UI must keep apart (original dataset / active subset /
// current result / current selection / visualization settings / full-vs-subset)
// are six separate fields; ``isSubsetView`` derives the last one instead of
// letting it drift out of sync.

/** Fewest samples that can produce a 2D PCoA. Mirrors backend/pcoa/service.py MIN_SAMPLES. */
export const MIN_SUBSET_SAMPLES = 3;

/** Sample-id chips rendered before collapsing into "+N more". */
export const SELECTION_PREVIEW_LIMIT = 24;

/** Distinct metadata values that get their own colour + legend row. */
export const MAX_LEGEND_ENTRIES = 10;

export const MISSING_LABEL = '(no value)';

/** Categorical palette: fill + a darker stroke so points keep a crisp edge. */
export const CATEGORY_PALETTE = [
  { fill: '#2f6feb', stroke: '#1d4ed8' },
  { fill: '#f79009', stroke: '#b54708' },
  { fill: '#12b76a', stroke: '#027a48' },
  { fill: '#f04438', stroke: '#b42318' },
  { fill: '#7a5af8', stroke: '#5925dc' },
  { fill: '#06aed4', stroke: '#0e7090' },
  { fill: '#ee46bc', stroke: '#c11574' },
  { fill: '#a9a29d', stroke: '#79716b' },
  { fill: '#eaaa08', stroke: '#a15c07' },
  { fill: '#4e5ba6', stroke: '#363f72' },
];

/** Colour for values beyond MAX_LEGEND_ENTRIES and for missing values. */
export const OTHER_COLOUR = { fill: '#98a2b3', stroke: '#667085' };

// ---------------------------------------------------------------------
// Selection model — immutable, ordered, keyed by stable sample id
// ---------------------------------------------------------------------

/** Order-preserving de-duplication. */
export function uniqueIds(ids) {
  const seen = Object.create(null);
  const out = [];
  (ids || []).forEach(function (id) {
    const key = String(id);
    if (seen[key]) return;
    seen[key] = true;
    out.push(key);
  });
  return out;
}

export function isSelected(selected, id) {
  return (selected || []).indexOf(String(id)) !== -1;
}

/** Click a point: select it, or deselect it if it is already selected. */
export function toggleSelection(selected, id) {
  const key = String(id);
  const current = selected || [];
  return isSelected(current, key)
    ? current.filter(function (existing) {
        return existing !== key;
      })
    : current.concat([key]);
}

/** Box/lasso selection and "select all": additive, never loses prior picks. */
export function addToSelection(selected, ids) {
  return uniqueIds((selected || []).concat(ids || []));
}

/** Remove specific ids (chip "x" button, subtractive box selection). */
export function removeFromSelection(selected, ids) {
  const drop = Object.create(null);
  (ids || []).forEach(function (id) {
    drop[String(id)] = true;
  });
  return (selected || []).filter(function (id) {
    return !drop[id];
  });
}

export function clearSelection() {
  return [];
}

/**
 * Drop ids that are not in ``availableIds``.
 *
 * Called whenever the plotted result changes, so a selection can never
 * reference a sample that is not on screen (e.g. after resetting from a
 * subset back to the full dataset).
 */
export function retainSelection(selected, availableIds) {
  const available = Object.create(null);
  (availableIds || []).forEach(function (id) {
    available[String(id)] = true;
  });
  return (selected || []).filter(function (id) {
    return available[id];
  });
}

// ---------------------------------------------------------------------
// Human-readable summaries
// ---------------------------------------------------------------------

/** "0 samples selected" / "1 sample selected" / "12 samples selected". */
export function describeSelectionCount(count) {
  const n = Number(count) || 0;
  return n + (n === 1 ? ' sample selected' : ' samples selected');
}

/** "Showing 14 of 40 original samples." */
export function describeSubset(shown, total) {
  const s = Number(shown) || 0;
  const t = Number(total) || 0;
  if (t > 0 && s >= t) {
    return 'Showing all ' + t + (t === 1 ? ' sample.' : ' samples.');
  }
  return (
    'Showing ' +
    s +
    ' of ' +
    t +
    (t === 1 ? ' original sample.' : ' original samples.')
  );
}

/**
 * Chips to render for the selected-sample panel.
 *
 * A 500-point selection must not produce a 500-row panel, so only the first
 * ``limit`` ids are listed and the remainder is summarized.
 */
export function selectionPreview(ids, limit) {
  const all = ids || [];
  const max = limit === undefined ? SELECTION_PREVIEW_LIMIT : limit;
  const shown = all.slice(0, Math.max(0, max));
  const hiddenCount = all.length - shown.length;
  return {
    shown: shown,
    hiddenCount: hiddenCount,
    hiddenLabel: hiddenCount > 0 ? '+' + hiddenCount + ' more' : '',
  };
}

/**
 * Should "Rerun PCoA on selected samples" be clickable, and why not?
 *
 * ``reason`` is always populated so the UI can explain a disabled button
 * instead of leaving a dead control on the page.
 */
export function rerunAvailability(options) {
  const opts = options || {};
  const count = Number(opts.selectedCount) || 0;
  const min = opts.minSamples === undefined ? MIN_SUBSET_SAMPLES : opts.minSamples;
  if (opts.busy) {
    return { enabled: false, reason: 'Recalculating PCoA…' };
  }
  if (!opts.hasResult) {
    return {
      enabled: false,
      reason: 'Run a PCoA on a dataset before selecting samples.',
    };
  }
  if (count === 0) {
    return {
      enabled: false,
      reason:
        'No samples selected. Click points (or drag a box) to select at ' +
        'least ' +
        min +
        ' samples.',
    };
  }
  if (count < min) {
    return {
      enabled: false,
      reason:
        'Only ' +
        count +
        (count === 1 ? ' sample is' : ' samples are') +
        ' selected. At least ' +
        min +
        ' samples are required to compute a 2D PCoA.',
    };
  }
  return {
    enabled: true,
    reason:
      'Recalculate the PCoA from the original data using only the ' +
      count +
      ' selected samples.',
  };
}

// ---------------------------------------------------------------------
// Plot geometry (box / rubber-band selection)
// ---------------------------------------------------------------------

/** Two drag corners -> an ordered rectangle (plus its size). */
export function normalizeBox(a, b) {
  const x1 = Math.min(a.x, b.x);
  const y1 = Math.min(a.y, b.y);
  const x2 = Math.max(a.x, b.x);
  const y2 = Math.max(a.y, b.y);
  return { x1: x1, y1: y1, x2: x2, y2: y2, width: x2 - x1, height: y2 - y1 };
}

/**
 * Ids of ``points`` ([{ id, x, y }], pixel space) inside ``box`` (inclusive).
 *
 * The hit test is the ONLY place pixel positions are used, and it returns
 * stable sample ids immediately, so no downstream step depends on geometry.
 */
export function pointsInBox(points, box) {
  if (!box) return [];
  const out = [];
  (points || []).forEach(function (p) {
    if (!p || typeof p.x !== 'number' || typeof p.y !== 'number') return;
    if (p.x >= box.x1 && p.x <= box.x2 && p.y >= box.y1 && p.y <= box.y2) {
      out.push(String(p.id));
    }
  });
  return out;
}

// ---------------------------------------------------------------------
// Subset request (ids only — never coordinates, never feature values)
// ---------------------------------------------------------------------

export function serializeSampleIds(ids) {
  return JSON.stringify(uniqueIds(ids));
}

/**
 * Build a request for the PCoA backend endpoint.
 *
 * Two shapes, one endpoint:
 *   * ``formData``  -> a multipart upload (new dataset, optionally already
 *     filtered through a ``sample_ids`` form field). Used for the first run
 *     and as the recovery path when the server no longer holds the dataset.
 *   * otherwise     -> the JSON subset body below.
 *
 * The JSON body carries the dataset handle, the selected STABLE SAMPLE IDS
 * and the distance metric. It deliberately carries no coordinates and no
 * feature values: the server re-filters its own copy of the original upload,
 * so the plot can never become the input to its own recalculation.
 */
export function buildSubsetRequest(options) {
  const opts = options || {};
  if (opts.formData) {
    return {
      url: opts.url,
      options: { method: 'POST', body: opts.formData },
      payload: null,
    };
  }
  const body = {
    dataset_id: opts.datasetId || null,
    sample_ids: uniqueIds(opts.sampleIds),
    metric: opts.metric || 'euclidean',
  };
  return {
    url: opts.url,
    options: {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
    payload: body,
  };
}

/**
 * Send a PCoA request (upload or subset) and normalize every outcome.
 *
 * Always resolves (never throws) to
 *   { ok: true,  payload }
 *   { ok: false, message, code, status }
 * so the caller has exactly one error path for HTTP errors, validation
 * errors, malformed bodies and network failures.
 */
export function requestPcoa(options) {
  const opts = options || {};
  const fetchImpl = opts.fetchImpl || (typeof fetch === 'function' ? fetch : null);
  if (!fetchImpl) {
    return Promise.resolve({
      ok: false,
      message: 'This browser cannot send the recalculation request (no fetch).',
      code: 'no_fetch',
      status: 0,
    });
  }
  const request = buildSubsetRequest(opts);
  return fetchImpl(request.url, request.options).then(
    function (response) {
      return Promise.resolve()
        .then(function () {
          return response.json();
        })
        .catch(function () {
          return null;
        })
        .then(function (payload) {
          if (!response.ok) {
            return {
              ok: false,
              status: response.status,
              code: (payload && payload.error_code) || null,
              message:
                (payload && payload.error) ||
                'PCoA failed (HTTP ' + response.status + ').',
            };
          }
          if (!payload || !payload.sample_ids) {
            return {
              ok: false,
              status: response.status,
              code: 'bad_payload',
              message: 'The server returned an unexpected response.',
            };
          }
          return { ok: true, payload: payload, status: response.status };
        });
    },
    function (err) {
      return {
        ok: false,
        status: 0,
        code: 'network',
        message:
          'Could not reach the server: ' + (err && err.message ? err.message : String(err)),
      };
    }
  );
}

// ---------------------------------------------------------------------
// Subset state machine
// ---------------------------------------------------------------------

export function createState() {
  return {
    file: null,
    filename: '',
    datasetId: null,
    originalResult: null,
    result: null,
    activeSampleIds: null,
    selected: [],
    metadata: null,
    colourField: '',
    metric: 'euclidean',
    busy: false,
    error: null,
  };
}

function assign(state, patch) {
  const next = {};
  Object.keys(state).forEach(function (key) {
    next[key] = state[key];
  });
  Object.keys(patch).forEach(function (key) {
    next[key] = patch[key];
  });
  return next;
}

/** True when the plot shows a subset rather than the whole upload. */
export function isSubsetView(state) {
  return !!(state && state.activeSampleIds);
}

/** Sample count of the full upload (independent of what is plotted). */
export function originalSampleCount(state) {
  if (!state) return 0;
  if (state.result && typeof state.result.n_original_samples === 'number') {
    return state.result.n_original_samples;
  }
  if (state.originalResult && state.originalResult.sample_ids) {
    return state.originalResult.sample_ids.length;
  }
  return 0;
}

/** Sample count of the plot on screen. */
export function activeSampleCount(state) {
  if (!state || !state.result || !state.result.sample_ids) return 0;
  return state.result.sample_ids.length;
}

/**
 * A brand-new full-dataset run: this becomes the ORIGINAL dataset that every
 * later subset is filtered out of, and any previous subset is discarded.
 * Metadata is kept because it is a separate, sample-id-keyed upload.
 */
export function withUpload(state, options) {
  const opts = options || {};
  const result = opts.result || null;
  return assign(state, {
    file: opts.file === undefined ? state.file : opts.file,
    filename: opts.filename === undefined ? state.filename : opts.filename,
    datasetId: (result && result.dataset_id) || null,
    originalResult: result,
    result: result,
    activeSampleIds: null,
    selected: [],
    busy: false,
    error: null,
  });
}

/**
 * A successful subset recalculation.
 *
 * The selection is emptied (its points have been consumed), the active subset
 * becomes the recalculated sample list, the original dataset and the original
 * result are retained for reset, and the metadata/colour settings survive
 * untouched.
 *
 * Selecting every sample is not a subset, so ``activeSampleIds`` goes back to
 * ``null`` in that case and the "subset" badge disappears honestly.
 */
export function withSubsetResult(state, payload) {
  if (!payload || !payload.sample_ids) return state;
  const ids = payload.sample_ids.map(String);
  return assign(state, {
    result: payload,
    activeSampleIds: payload.is_subset ? ids : null,
    datasetId: payload.dataset_id || state.datasetId,
    selected: [],
    busy: false,
    error: null,
  });
}

/**
 * A failed recalculation: the plot on screen and the user's selection are
 * both preserved so nothing has to be re-picked, and the loading state ends.
 */
export function withFailure(state, message) {
  return assign(state, { busy: false, error: message || 'Recalculation failed.' });
}

export function withBusy(state, busy) {
  return assign(state, { busy: !!busy, error: busy ? null : state.error });
}

export function withSelection(state, selected) {
  return assign(state, { selected: uniqueIds(selected) });
}

/**
 * One-level reset back to the complete original dataset.
 *
 * The full-dataset result is re-displayed from state (it was computed from
 * the original matrix and is never mutated), so reset works instantly, works
 * offline, and works even if the server has since dropped its cached copy of
 * the dataset.
 */
export function withReset(state) {
  if (!state.originalResult) return state;
  return assign(state, {
    result: state.originalResult,
    activeSampleIds: null,
    selected: [],
    busy: false,
    error: null,
  });
}

/** Attach (or clear) the optional metadata table. */
export function withMetadata(state, metadata, colourField) {
  const fields = (metadata && metadata.fields) || [];
  let field = colourField === undefined ? state.colourField : colourField;
  if (fields.indexOf(field) === -1) field = '';
  return assign(state, { metadata: metadata || null, colourField: field });
}

/**
 * Change the metadata field used for point colour.
 *
 * ``selected`` is intentionally untouched: colouring is a visualization
 * setting, and selection is keyed by sample id, so recolouring can never
 * move, drop or add a selected sample.
 */
export function withColourField(state, field) {
  return assign(state, { colourField: field || '' });
}

// ---------------------------------------------------------------------
// Optional sample metadata (grouping / colouring / tooltips)
// ---------------------------------------------------------------------

/** Quote-aware delimited parser (RFC4180-ish): rows of trimmed cells. */
export function parseDelimitedRows(text, delimiter) {
  const rows = [];
  let row = [];
  let cell = '';
  let quoted = false;
  const src = String(text || '').replace(/\r\n?/g, '\n');
  for (let i = 0; i < src.length; i += 1) {
    const ch = src[i];
    if (quoted) {
      if (ch === '"') {
        if (src[i + 1] === '"') {
          cell += '"';
          i += 1;
        } else {
          quoted = false;
        }
      } else {
        cell += ch;
      }
      continue;
    }
    if (ch === '"') {
      quoted = true;
    } else if (ch === delimiter) {
      row.push(cell.trim());
      cell = '';
    } else if (ch === '\n') {
      row.push(cell.trim());
      cell = '';
      rows.push(row);
      row = [];
    } else {
      cell += ch;
    }
  }
  row.push(cell.trim());
  rows.push(row);
  return rows.filter(function (r) {
    return r.some(function (c) {
      return c !== '';
    });
  });
}

/** Delimiter from the file extension, falling back to header counting. */
export function detectDelimiter(text, filename) {
  const name = String(filename || '').toLowerCase();
  if (/\.tsv$/.test(name)) return '\t';
  if (/\.csv$/.test(name)) return ',';
  const header = String(text || '').split('\n')[0] || '';
  return header.split('\t').length - 1 > header.split(',').length - 1 ? '\t' : ',';
}

/**
 * Parse an optional metadata table: first column = sample id, first row =
 * field names, remaining cells = free-text values.
 *
 * Returns { fields, bySample, sampleIds, warnings }. Throws ``Error`` with a
 * user-facing message when the file cannot be used at all. Metadata is
 * annotation, not maths, so ragged rows are padded (with a warning) rather
 * than rejected.
 */
export function parseMetadataTable(text, filename) {
  const delimiter = detectDelimiter(text, filename);
  const rows = parseDelimitedRows(text, delimiter);
  if (rows.length === 0) {
    throw new Error('The metadata file is empty.');
  }
  if (rows.length < 2) {
    throw new Error('The metadata file needs a header row plus at least one sample row.');
  }
  const header = rows[0];
  if (header.length < 2) {
    throw new Error(
      'The metadata file needs a sample id column plus at least one metadata column.'
    );
  }
  const fields = header.slice(1).map(function (name, i) {
    return name === '' ? 'column_' + (i + 2) : name;
  });

  const bySample = Object.create(null);
  const sampleIds = [];
  const warnings = [];
  let ragged = 0;
  let duplicates = 0;
  for (let r = 1; r < rows.length; r += 1) {
    const row = rows[r];
    const id = row[0];
    if (id === '') continue;
    if (bySample[id]) {
      duplicates += 1;
      continue; // first row wins, mirroring the matrix's unique-id rule
    }
    if (row.length !== header.length) ragged += 1;
    const record = Object.create(null);
    fields.forEach(function (field, i) {
      record[field] = row[i + 1] === undefined ? '' : row[i + 1];
    });
    bySample[id] = record;
    sampleIds.push(id);
  }
  if (sampleIds.length === 0) {
    throw new Error('The metadata file contains no sample rows.');
  }
  if (duplicates > 0) {
    warnings.push(
      duplicates +
        ' duplicate sample id(s) in the metadata file were ignored (the first row for each sample was used).'
    );
  }
  if (ragged > 0) {
    warnings.push(
      ragged +
        ' metadata row(s) did not have one value per column; missing values are shown as blank.'
    );
  }
  return {
    fields: fields,
    bySample: bySample,
    sampleIds: sampleIds,
    warnings: warnings,
    delimiter: delimiter === '\t' ? 'tab' : 'comma',
  };
}

/** How many plotted samples the metadata actually covers. */
export function metadataCoverage(metadata, sampleIds) {
  if (!metadata) return { matched: 0, total: (sampleIds || []).length };
  let matched = 0;
  (sampleIds || []).forEach(function (id) {
    if (metadata.bySample[String(id)]) matched += 1;
  });
  return { matched: matched, total: (sampleIds || []).length };
}

/** Raw metadata value for one sample/field ("" when unknown). */
export function metadataValue(metadata, sampleId, field) {
  if (!metadata || !field) return '';
  const record = metadata.bySample[String(sampleId)];
  if (!record) return '';
  const value = record[field];
  return value === undefined || value === null ? '' : String(value);
}

/** [[field, value], ...] for a tooltip, capped so the tooltip stays short. */
export function metadataPairs(metadata, sampleId, limit) {
  if (!metadata) return [];
  const record = metadata.bySample[String(sampleId)];
  if (!record) return [];
  const max = limit === undefined ? 4 : limit;
  const out = [];
  metadata.fields.forEach(function (field) {
    if (out.length >= max) return;
    const value = record[field];
    if (value === undefined || value === null || value === '') return;
    out.push([field, String(value)]);
  });
  return out;
}

/**
 * Assign a colour per distinct value of ``field`` across ``sampleIds``.
 *
 * Values are ranked by frequency (ties broken by first appearance) so the
 * biggest groups get the distinct palette colours; anything past
 * ``MAX_LEGEND_ENTRIES`` is folded into one grey "Other" entry so the legend
 * stays readable for a high-cardinality column.
 *
 * Returns ``null`` when there is nothing to colour by, which tells the
 * renderer to fall back to the default single-colour points.
 */
export function buildColourAssignment(options) {
  const opts = options || {};
  const metadata = opts.metadata;
  const field = opts.field;
  const sampleIds = (opts.sampleIds || []).map(String);
  if (!metadata || !field || metadata.fields.indexOf(field) === -1) return null;

  const stats = Object.create(null);
  const order = [];
  sampleIds.forEach(function (id, index) {
    const raw = metadataValue(metadata, id, field);
    const label = raw === '' ? MISSING_LABEL : raw;
    if (!stats[label]) {
      stats[label] = { label: label, count: 0, firstIndex: index };
      order.push(label);
    }
    stats[label].count += 1;
  });

  const ranked = order
    .map(function (label) {
      return stats[label];
    })
    .sort(function (a, b) {
      if (b.count !== a.count) return b.count - a.count;
      return a.firstIndex - b.firstIndex;
    });

  const colourByLabel = Object.create(null);
  const entries = [];
  const overflow = [];
  ranked.forEach(function (entry, i) {
    if (i < MAX_LEGEND_ENTRIES) {
      const colour = CATEGORY_PALETTE[i % CATEGORY_PALETTE.length];
      colourByLabel[entry.label] = colour;
      entries.push({
        value: entry.label,
        label: entry.label,
        count: entry.count,
        fill: colour.fill,
        stroke: colour.stroke,
      });
    } else {
      overflow.push(entry);
    }
  });
  if (overflow.length > 0) {
    const otherCount = overflow.reduce(function (sum, e) {
      return sum + e.count;
    }, 0);
    const otherLabel = 'Other (' + overflow.length + ' values)';
    overflow.forEach(function (e) {
      colourByLabel[e.label] = OTHER_COLOUR;
    });
    entries.push({
      value: otherLabel,
      label: otherLabel,
      count: otherCount,
      fill: OTHER_COLOUR.fill,
      stroke: OTHER_COLOUR.stroke,
      isOther: true,
    });
  }

  function colourFor(sampleId) {
    const raw = metadataValue(metadata, sampleId, field);
    const label = raw === '' ? MISSING_LABEL : raw;
    const colour = colourByLabel[label] || OTHER_COLOUR;
    return { fill: colour.fill, stroke: colour.stroke, label: label };
  }

  return { field: field, entries: entries, colourFor: colourFor };
}
