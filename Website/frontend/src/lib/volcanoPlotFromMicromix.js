// volcanoPlotFromMicromix.js — adapts the CURRENTLY ACTIVE Micromix dataset
// (the same `pickActiveDataframe()` records PCoA and the native Clustered
// Heatmap already use) into the column-oriented shape the Volcano Plot
// needs, and suggests which columns look like the gene/feature id, the
// log2 fold-change and the significance (p-value/padj) column.
//
// Why this file exists
// ---------------------------------------------------------------------
// Unlike PCoA/Clustered Heatmap, a Volcano Plot does not consume the
// "(matrix title) sample" numeric *value* columns detected by
// buildMatrix() in ./matrix.js -- it needs differential-expression
// STATISTICS (log2 fold change, p-value/padj), which may or may not be
// present among a dataset's columns at all, and are not identified by the
// "(prefix) sample" convention. This module therefore works directly on
// the raw record columns (every key of the active dataframe's records)
// rather than going through buildMatrix().
//
// The column-role heuristics below are a straight port of
// ClusteredHeatmap2's `backend/volcano_service.py::suggest_columns()` /
// `_first_match()` / `_normalize_name()` (that project is a read-only
// reference and is never modified) -- only the input differs: the
// reference guesses roles from freshly-uploaded CSV/TSV columns, this
// guesses roles from the already-parsed Micromix active dataframe's
// columns, so there is no file upload or server round trip required.

/** Raised when the current Micromix dataset has no rows at all to plot. */
export class MicromixVolcanoConversionError extends Error {}

const ID_KEYWORDS = new Set([
  'gene', 'geneid', 'geneidentifier', 'genename', 'genesymbol',
  'locustag', 'feature', 'featureid', 'featurename', 'id', 'name',
  'symbol', 'identifier', 'transcript', 'transcriptid',
]);

const LOG2FC_KEYWORDS = new Set([
  'log2foldchange', 'log2fc', 'logfc', 'lfc', 'log2ratio',
  'foldchange', 'fc', 'log2fold',
]);

// Adjusted-p-value-like names are preferred over raw p-values when both
// are present, because that is the more common choice for a significance
// axis.
const PADJ_KEYWORDS = new Set([
  'padj', 'adjustedpvalue', 'adjpvalue', 'adjustedp', 'adjp',
  'qvalue', 'q', 'fdr', 'padjusted', 'bhadjustedpvalue',
]);

const PVALUE_KEYWORDS = new Set([
  'pvalue', 'pval', 'p', 'praw', 'rawpvalue', 'nominalpvalue',
]);

const MISSING_TOKENS = new Set(['na', 'n/a', 'nan', 'null', 'none', '-', '.']);

/** A column "looks numeric" when at least this fraction of its non-blank
 * cells parse as a finite number. Used only for suggestions/UI hints --
 * the real per-selection validation happens in volcanoCalc.js once a
 * column is actually picked. */
const NUMERIC_LOOKS_LIKE_FRACTION = 0.9;

function tryFloat(raw) {
  if (raw === null || raw === undefined) return null;
  const cell = String(raw).trim();
  if (cell === '') return null;
  const value = Number(cell);
  if (!isFinite(value)) return null;
  return value;
}

/** Lowercase and strip everything but letters/digits, so 'Log2 Fold
 * Change', 'log2FoldChange' and 'log2_fold_change' all compare equal. */
function normalizeName(name) {
  return String(name).toLowerCase().replace(/[^a-z0-9]/g, '');
}

/**
 * Return every column name present on the active dataframe's records, in
 * first-record order (same convention as buildMatrix(): the first key is
 * treated as the row/feature identifier by every other Micromix
 * visualization).
 */
export function getColumnNames(records) {
  if (!records || records.length === 0) return [];
  return Object.keys(records[0]);
}

/**
 * Per-column stats used for both the column-role suggestion and to give
 * the user a quick "does this look numeric?" hint in the column selector.
 */
export function computeColumnStats(records, columnNames) {
  const stats = {};
  for (const col of columnNames) {
    let nTotal = 0;
    let nBlank = 0;
    let nNumeric = 0;
    for (const rec of records) {
      nTotal += 1;
      const raw = rec[col];
      const cell = raw === null || raw === undefined ? '' : String(raw).trim();
      if (cell === '' || MISSING_TOKENS.has(cell.toLowerCase())) {
        nBlank += 1;
        continue;
      }
      if (tryFloat(cell) !== null) nNumeric += 1;
    }
    const nNonBlank = nTotal - nBlank;
    const numericFraction = nNonBlank > 0 ? nNumeric / nNonBlank : 0;
    stats[col] = {
      name: col,
      nValues: nTotal,
      nMissing: nBlank,
      numericFraction,
      looksNumeric: nNonBlank > 0 && numericFraction >= NUMERIC_LOOKS_LIKE_FRACTION,
    };
  }
  return stats;
}

/** First column (in header order) whose normalized name exactly matches
 * one of `keywords` (checked first), or contains one of them (checked
 * second), optionally required to look numeric, excluding already-claimed
 * names. Mirrors `volcano_service.py::_first_match()`. */
function firstMatch(columnNames, statsByName, keywords, requireNumeric, exclude) {
  const normalized = {};
  columnNames.forEach((c) => {
    normalized[c] = normalizeName(c);
  });

  for (const col of columnNames) {
    if (exclude.has(col)) continue;
    if (keywords.has(normalized[col])) {
      if (!requireNumeric || statsByName[col].looksNumeric) return col;
    }
  }
  for (const col of columnNames) {
    if (exclude.has(col)) continue;
    const norm = normalized[col];
    let matched = false;
    keywords.forEach((keyword) => {
      if (norm.includes(keyword)) matched = true;
    });
    if (matched && (!requireNumeric || statsByName[col].looksNumeric)) return col;
  }
  return null;
}

/**
 * Best-effort guess at which column is the gene/feature id, which is the
 * log2 fold-change, and which is the significance (p-value or adjusted
 * p-value) column. Mirrors `volcano_service.py::suggest_columns()`
 * verbatim (same keyword sets, same exact-match-then-substring-match
 * strategy, same "id defaults to the first non-numeric column, else the
 * first column" fallback). This is only a starting point for the column
 * selectors -- the user can always override it.
 *
 * @returns {{id: string|null, log2fc: string|null, significance: string|null, significanceType: 'adjusted'|'raw'|null}}
 */
export function suggestVolcanoColumns(columnNames, columnStats) {
  const exclude = new Set();

  let idCol = firstMatch(columnNames, columnStats, ID_KEYWORDS, false, exclude);
  if (idCol === null) {
    idCol = columnNames.find((col) => !columnStats[col].looksNumeric) || null;
  }
  if (idCol === null && columnNames.length > 0) idCol = columnNames[0];
  if (idCol !== null) exclude.add(idCol);

  const log2fcCol = firstMatch(columnNames, columnStats, LOG2FC_KEYWORDS, true, exclude);
  if (log2fcCol !== null) exclude.add(log2fcCol);

  let sigCol = firstMatch(columnNames, columnStats, PADJ_KEYWORDS, true, exclude);
  let sigType = sigCol !== null ? 'adjusted' : null;
  if (sigCol === null) {
    sigCol = firstMatch(columnNames, columnStats, PVALUE_KEYWORDS, true, exclude);
    sigType = sigCol !== null ? 'raw' : null;
  }

  return { id: idCol, log2fc: log2fcCol, significance: sigCol, significanceType: sigType };
}

/**
 * Raw string values for one column, index-aligned with `records`. Blank
 * Micromix cell values (null/undefined) become `''`, matching what the
 * reference prototype's CSV parser would have produced for an empty cell;
 * volcanoCalc.js's `parseNumericColumn()` already treats `''` as missing.
 */
export function extractColumnValues(records, columnName) {
  return records.map((rec) => {
    const v = rec[columnName];
    return v === null || v === undefined ? '' : String(v);
  });
}

/**
 * Convenience wrapper: validate there is an active dataset at all and
 * return its column names + per-column stats + suggested roles in one
 * call, for VolcanoPlotCanvas.vue.
 *
 * @throws {MicromixVolcanoConversionError} when there is no active dataset.
 */
export function inspectMicromixRecordsForVolcano(records) {
  if (!records || records.length === 0) {
    throw new MicromixVolcanoConversionError('No active Micromix dataset is available for the Volcano Plot.');
  }
  const columnNames = getColumnNames(records);
  const columnStats = computeColumnStats(records, columnNames);
  const suggestion = suggestVolcanoColumns(columnNames, columnStats);
  return { columnNames, columnStats, suggestion, rowCount: records.length };
}
