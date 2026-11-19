// pcoaRender.js — PURE rendering/formatting helpers for the PCoA scatter plot.
// Ported from the pure-helper section of ClusteredHeatmap2's
// backend/static/js/pcoa.js (the DOM-building parts of that file were
// re-implemented as native Vue/SVG templates in PcoaScatterPlot.vue; these
// helpers are unchanged pure functions extracted so they stay unit-testable
// independent of any component).

export const COORD_DECIMALS = 4;

/** Round for display only; the payload keeps full precision. */
export function formatCoord(value, decimals) {
  const d = decimals === undefined ? COORD_DECIMALS : decimals;
  if (typeof value !== 'number' || !isFinite(value)) return 'n/a';
  return value.toFixed(d);
}

/** Percentage with one decimal, e.g. 52.3. */
export function formatPercent(value) {
  if (typeof value !== 'number' || !isFinite(value)) return 'n/a';
  return value.toFixed(1) + '%';
}

/** Axis label text, e.g. "Coordinate 1 (52.3%)". */
export function axisLabel(index, percent) {
  return 'Coordinate ' + index + ' (' + formatPercent(percent) + ')';
}

/**
 * Tooltip / aria text for one plotted point.
 *
 * Always the stable sample id plus its CURRENT coordinates (so the text
 * follows a recalculation automatically), then any metadata values as
 * ``field: value`` pairs.
 */
export function pointTooltip(id, x, y, pairs) {
  let tip = id + ' (Coordinate 1: ' + formatCoord(x) + ', Coordinate 2: ' + formatCoord(y) + ')';
  (pairs || []).forEach(function (pair) {
    tip += ' • ' + pair[0] + ': ' + pair[1];
  });
  return tip;
}

/**
 * Escape one CSV field.
 *
 * Two separate concerns:
 *   1. Separator/quote/newline characters need CSV quoting.
 *   2. Sample IDs come from an untrusted uploaded matrix, so a value starting
 *      with `=`, `+`, `-`, `@`, tab or CR must not be handed to a spreadsheet
 *      as a formula (CSV injection: DDE, WEBSERVICE exfiltration). Such
 *      values are prefixed with an apostrophe, which spreadsheets treat as
 *      "this is text".
 */
export function csvField(text) {
  let value = String(text);
  if (/^[=+\-@\t\r]/.test(value)) value = "'" + value;
  if (/[",\n\r]/.test(value)) return '"' + value.replace(/"/g, '""') + '"';
  return value;
}

/**
 * Build the coordinates download CSV. Full precision is preserved: the
 * numbers are serialized exactly as the server sent them.
 */
export function buildCoordinatesCsv(result) {
  const lines = ['sample_id,coordinate_1,coordinate_2'];
  const ids = result.sample_ids || [];
  for (let i = 0; i < ids.length; i += 1) {
    lines.push(
      [csvField(String(ids[i])), String(result.coordinate_1[i]), String(result.coordinate_2[i])].join(',')
    );
  }
  return lines.join('\n') + '\n';
}

/**
 * Padded [min, max] for one axis. A degenerate range (all values equal)
 * is widened so points are not stacked on the border.
 */
export function niceExtent(values) {
  let min = Infinity;
  let max = -Infinity;
  for (let i = 0; i < values.length; i += 1) {
    const v = values[i];
    if (typeof v !== 'number' || !isFinite(v)) continue;
    if (v < min) min = v;
    if (v > max) max = v;
  }
  if (min === Infinity) return [-1, 1];
  if (min === max) {
    const pad = Math.abs(min) > 0 ? Math.abs(min) * 0.1 : 1;
    return [min - pad, max + pad];
  }
  const pad = (max - min) * 0.08;
  return [min - pad, max + pad];
}

/** Linear mapping from a data range onto a pixel range. */
export function makeScale(domain, range) {
  const d0 = domain[0];
  const d1 = domain[1];
  const r0 = range[0];
  const r1 = range[1];
  const span = d1 - d0 || 1;
  return function scale(value) {
    return r0 + ((value - d0) / span) * (r1 - r0);
  };
}

/** "Nice" tick values (1/2/5 x 10^k steps) covering [min, max]. */
export function ticks(min, max, target) {
  const count = target || 5;
  const span = max - min;
  if (!(span > 0)) return [min];
  const rough = span / count;
  const magnitude = Math.pow(10, Math.floor(Math.log10(rough)));
  const candidates = [1, 2, 5, 10];
  let step = magnitude;
  for (let i = 0; i < candidates.length; i += 1) {
    if (magnitude * candidates[i] >= rough) {
      step = magnitude * candidates[i];
      break;
    }
  }
  const out = [];
  const start = Math.ceil(min / step) * step;
  for (let v = start; v <= max + step * 1e-9; v += step) {
    // Kill float noise like 0.30000000000000004.
    out.push(Math.abs(v) < step * 1e-9 ? 0 : Number(v.toPrecision(12)));
  }
  return out;
}

/** Tick label formatting: compact but readable. */
export function formatTick(value) {
  if (value === 0) return '0';
  const abs = Math.abs(value);
  if (abs >= 1000 || abs < 0.01) return value.toExponential(1);
  if (Number.isInteger(value)) return String(value);
  return String(Number(value.toPrecision(4)));
}

/** Smallest drag (in plot pixels) treated as a box selection, not a click. */
export const BOX_DRAG_THRESHOLD = 4;

/** Trigger a client-side CSV download via a temporary anchor + Blob URL. */
export function downloadCsv(text, filename) {
  const blob = new Blob([text], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  // Give the browser a tick to start the download before revoking.
  setTimeout(function () {
    URL.revokeObjectURL(url);
  }, 0);
}
