// volcanoCalc.js — PURE calculation/classification logic for the Volcano
// Plot, ported from the ClusteredHeatmap2 reference prototype's
// `backend/static/js/volcanocalc.js` (see that file for the original,
// unmodified source -- ClusteredHeatmap2 is treated as a read-only
// reference and is never edited by Micromix).
//
// This is a faithful port of the numeric-column parsing/validation,
// -log10 transform, threshold classification and label-ranking logic from
// the reference prototype, converted from a global/UMD module to a plain
// ES module so it can be imported by VolcanoPlotCanvas.vue /
// VolcanoPlotScatterPlot.vue. The math itself is unchanged.
//
// Not ported (out of scope for this integration step -- see the task's
// scope restrictions): the click/box-select "selection" state machine and
// rubber-band geometry helpers (`toggleSelection`, `pointsInBox`, etc.) from
// the reference's volcanocalc.js, since this integration does not yet
// implement gene selection -> matrix subset creation.
//
// ============================================================================
// -log10(0) SAFETY (a required behavior, not an edge case)
// ============================================================================
// A p-value of exactly 0 (common after floating-point underflow in DE
// tools) would make -log10(p) = +Infinity, which breaks axis scaling. Zero
// (and any non-positive) significance value is instead floored to a small
// positive number DERIVED FROM THE DATASET: the smallest strictly positive
// significance value present, divided by 10 (never below
// ABSOLUTE_MIN_FLOOR). The resulting -log10 is additionally hard-capped at
// MAX_NEG_LOG10.
//
// ============================================================================
// LABEL RANKING RULE
// ============================================================================
// "Notable" genes are ranked by combined effect size and significance:
//     score = -log10(significance) * |log2FoldChange|
// among genes that pass BOTH current thresholds (classified "up"/"down").
// Ties break by higher -log10(significance), then larger |log2FoldChange|,
// then the feature id (ascending) for determinism.

export const DEFAULT_LOG2FC_THRESHOLD = 1;
export const DEFAULT_SIGNIFICANCE_THRESHOLD = 0.05;

/** Absolute floor for a zero/non-positive significance value. */
export const ABSOLUTE_MIN_FLOOR = 1e-300;

/** -log10 is never allowed to exceed this, however small the floor is. */
export const MAX_NEG_LOG10 = 300;

/** Tolerance for "the significance column is basically in [0, 1]". */
const RANGE_TOLERANCE = 1e-6;

/** A column needs at least this fraction of its non-blank cells to parse
 * as a number before it is usable as log2FC / significance. */
const MIN_NUMERIC_FRACTION = 0.5;

export const LABEL_OPTIONS = [0, 5, 10, 20];

const MISSING_TOKENS = { na: 1, 'n/a': 1, nan: 1, null: 1, none: 1, '-': 1, '.': 1 };

/** Thrown for any condition that should stop the plot with a clear message. */
export class VolcanoCalcError extends Error {
  constructor(message) {
    super(message);
    this.name = 'VolcanoCalcError';
  }
}

// ---------------------------------------------------------------------
// Numeric column parsing
// ---------------------------------------------------------------------

/**
 * Parse one column of raw values to numbers.
 *
 * Returns:
 *   {
 *     numbers: (number|null)[]   same length as `values`; null = blank/unparsable
 *     missingCount: number       blank / "NA"-like cells
 *     invalidCount: number       non-blank cells that did not parse
 *     nonBlankCount: number
 *     numericFraction: number    numeric / nonBlank (0 when nonBlank===0)
 *     invalidSamples: string[]   up to 3 example bad values, for messages
 *   }
 */
export function parseNumericColumn(values) {
  const numbers = [];
  let missingCount = 0;
  let invalidCount = 0;
  let numericCount = 0;
  const invalidSamples = [];
  (values || []).forEach((raw) => {
    const cell = raw === null || raw === undefined ? '' : String(raw).trim();
    if (cell === '' || MISSING_TOKENS[cell.toLowerCase()]) {
      numbers.push(null);
      missingCount += 1;
      return;
    }
    const value = Number(cell);
    if (!isFinite(value)) {
      numbers.push(null);
      invalidCount += 1;
      if (invalidSamples.length < 3) invalidSamples.push(cell);
      return;
    }
    numbers.push(value);
    numericCount += 1;
  });
  const nonBlankCount = (values || []).length - missingCount;
  return {
    numbers,
    missingCount,
    invalidCount,
    nonBlankCount,
    numericFraction: nonBlankCount > 0 ? numericCount / nonBlankCount : 0,
    invalidSamples,
  };
}

/**
 * Validate a parsed log2 fold-change column. Throws `VolcanoCalcError` when
 * the column is clearly the wrong pick (mostly non-numeric) or empty.
 */
export function validateLog2FoldChangeColumn(parsed, columnName) {
  if (parsed.nonBlankCount === 0) {
    throw new VolcanoCalcError(`The log2 fold-change column '${columnName}' has no values.`);
  }
  if (parsed.numericFraction < MIN_NUMERIC_FRACTION) {
    throw new VolcanoCalcError(
      `The log2 fold-change column '${columnName}' does not look numeric (` +
        `${Math.round(parsed.numericFraction * 100)}% of its values parsed as numbers` +
        (parsed.invalidSamples.length ? `, e.g. '${parsed.invalidSamples.join("', '")}'` : '') +
        '). Choose a different column for log2 fold change.'
    );
  }
  return parsed;
}

/**
 * Validate a parsed significance column (p-value or adjusted p-value).
 * Throws for: mostly non-numeric, entirely empty/invalid, or values clearly
 * outside the expected [0, 1] probability range.
 */
export function validateSignificanceColumn(parsed, columnName) {
  if (parsed.nonBlankCount === 0) {
    throw new VolcanoCalcError(`The significance column '${columnName}' has no values.`);
  }
  if (parsed.numericFraction < MIN_NUMERIC_FRACTION) {
    throw new VolcanoCalcError(
      `The significance column '${columnName}' does not look numeric (` +
        `${Math.round(parsed.numericFraction * 100)}% of its values parsed as numbers` +
        (parsed.invalidSamples.length ? `, e.g. '${parsed.invalidSamples.join("', '")}'` : '') +
        '). Choose a different column for the significance value.'
    );
  }
  const validNumbers = parsed.numbers.filter((v) => v !== null);
  if (validNumbers.length === 0) {
    throw new VolcanoCalcError(
      `All significance values in '${columnName}' are missing or invalid. Choose a different column.`
    );
  }
  let outOfRange = 0;
  let example = null;
  validNumbers.forEach((v) => {
    if (v < -RANGE_TOLERANCE || v > 1 + RANGE_TOLERANCE) {
      outOfRange += 1;
      if (example === null) example = v;
    }
  });
  if (outOfRange > 0) {
    throw new VolcanoCalcError(
      `The significance column '${columnName}' has ${outOfRange} value(s) outside the expected ` +
        `0\u20131 range (e.g. ${example}). Significance must be a p-value or adjusted p-value between ` +
        '0 and 1 \u2014 choose a different column (this one may already be -log10 transformed, a ' +
        'percentage, or a score).'
    );
  }
  return parsed;
}

// ---------------------------------------------------------------------
// -log10 transform with a safe, data-derived floor for p == 0
// ---------------------------------------------------------------------

/** Smallest strictly-positive value among `numbers` (nulls ignored). */
export function smallestPositive(numbers) {
  let min = null;
  numbers.forEach((v) => {
    if (v !== null && v > 0 && (min === null || v < min)) min = v;
  });
  return min;
}

/** The floor used to replace a zero/non-positive significance value. */
export function computeSignificanceFloor(numbers) {
  const smallest = smallestPositive(numbers);
  if (smallest === null) return ABSOLUTE_MIN_FLOOR;
  return Math.max(smallest / 10, ABSOLUTE_MIN_FLOOR);
}

/** -log10(p), flooring non-positive p and capping the result. */
export function negLog10(p, floor) {
  const safe = p > 0 ? p : floor;
  const value = -Math.log10(safe);
  if (!isFinite(value)) return MAX_NEG_LOG10;
  return Math.min(value, MAX_NEG_LOG10);
}

// ---------------------------------------------------------------------
// Classification
// ---------------------------------------------------------------------

/** "up" | "down" | "not_sig" for one gene, given the CURRENT thresholds. */
export function classifyGene(log2fc, significance, log2fcThreshold, sigThreshold) {
  if (typeof log2fc !== 'number' || typeof significance !== 'number') {
    return 'not_sig';
  }
  const passesSignificance = significance <= sigThreshold;
  if (!passesSignificance) return 'not_sig';
  if (log2fc >= log2fcThreshold) return 'up';
  if (log2fc <= -log2fcThreshold) return 'down';
  return 'not_sig';
}

// ---------------------------------------------------------------------
// Main assembly: raw columns -> plottable records + summary
// ---------------------------------------------------------------------

/**
 * Build the full set of plottable records from raw column data.
 *
 * `input`: { ids, log2fcRaw, sigRaw, log2fcColumn, sigColumn, extraColumns }
 * `options`: { log2fcThreshold, sigThreshold }
 *
 * Throws `VolcanoCalcError` for any condition that should stop the plot
 * rather than silently produce a wrong one.
 */
export function buildVolcanoData(input, options) {
  const opts = options || {};
  const log2fcThreshold =
    typeof opts.log2fcThreshold === 'number' ? Math.abs(opts.log2fcThreshold) : DEFAULT_LOG2FC_THRESHOLD;
  const sigThreshold = typeof opts.sigThreshold === 'number' ? opts.sigThreshold : DEFAULT_SIGNIFICANCE_THRESHOLD;

  const ids = input.ids || [];
  const n = ids.length;

  const log2fcParsed = validateLog2FoldChangeColumn(
    parseNumericColumn(input.log2fcRaw || []),
    input.log2fcColumn || 'log2FoldChange'
  );
  const sigParsed = validateSignificanceColumn(
    parseNumericColumn(input.sigRaw || []),
    input.sigColumn || 'significance'
  );

  const floor = computeSignificanceFloor(sigParsed.numbers);
  const extraColumns = input.extraColumns || [];

  const records = [];
  let skippedMissing = 0;
  let skippedInvalidLog2fc = 0;
  let skippedInvalidSignificance = 0;
  let up = 0;
  let down = 0;
  let notSig = 0;

  for (let i = 0; i < n; i += 1) {
    const log2fc = log2fcParsed.numbers[i];
    const significance = sigParsed.numbers[i];
    if (log2fc === null || significance === null) {
      if (log2fc === null) skippedInvalidLog2fc += 1;
      if (significance === null) skippedInvalidSignificance += 1;
      skippedMissing += 1;
      continue;
    }
    const nl10 = negLog10(significance, floor);
    const classification = classifyGene(log2fc, significance, log2fcThreshold, sigThreshold);
    if (classification === 'up') up += 1;
    else if (classification === 'down') down += 1;
    else notSig += 1;

    const rawId = ids[i];
    const id = rawId === null || rawId === undefined || String(rawId).trim() === '' ? `row_${i + 1}` : String(rawId).trim();

    const extras = [];
    extraColumns.forEach((col) => {
      const value = col.values ? col.values[i] : undefined;
      if (value !== undefined && value !== null && String(value).trim() !== '') {
        extras.push([col.name, String(value).trim()]);
      }
    });

    records.push({
      id,
      log2fc,
      significance,
      negLog10: nl10,
      classification,
      rowIndex: i,
      extras,
    });
  }

  return {
    records,
    summary: { total: records.length, up, down, notSig },
    skipped: {
      missing: skippedMissing,
      invalidLog2fc: skippedInvalidLog2fc,
      invalidSignificance: skippedInvalidSignificance,
    },
    significanceFloor: floor,
    thresholds: { log2fcThreshold, sigThreshold },
  };
}

// ---------------------------------------------------------------------
// Label ranking
// ---------------------------------------------------------------------

/**
 * Top `topN` "notable" gene ids among significant (up/down) records.
 * Returns an ordered array of ids (most notable first).
 */
export function rankForLabels(records, topN) {
  if (!topN || topN <= 0) return [];
  const candidates = (records || []).filter((r) => r.classification === 'up' || r.classification === 'down');
  const scored = candidates.map((r) => ({
    id: r.id,
    score: r.negLog10 * Math.abs(r.log2fc),
    negLog10: r.negLog10,
    absLog2fc: Math.abs(r.log2fc),
  }));
  scored.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.negLog10 !== a.negLog10) return b.negLog10 - a.negLog10;
    if (b.absLog2fc !== a.absLog2fc) return b.absLog2fc - a.absLog2fc;
    return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
  });
  return scored.slice(0, topN).map((s) => s.id);
}

// ---------------------------------------------------------------------
// Small formatting helpers shared by the Vue layer
// ---------------------------------------------------------------------

export function formatLog2fc(value) {
  if (typeof value !== 'number' || !isFinite(value)) return 'n/a';
  return value.toFixed(2);
}

export function formatSignificance(value) {
  if (typeof value !== 'number' || !isFinite(value)) return 'n/a';
  if (value === 0) return '0';
  if (value < 0.0001) return value.toExponential(2);
  return String(Number(value.toPrecision(4)));
}

export function formatNegLog10(value) {
  if (typeof value !== 'number' || !isFinite(value)) return 'n/a';
  return value.toFixed(2);
}
