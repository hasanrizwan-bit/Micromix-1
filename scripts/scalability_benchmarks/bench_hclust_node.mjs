// Benchmarks the browser-side clustering code (unmodified) under Node.js:
//   Website/frontend/src/lib/distances.js  pairwise()  (full n x n matrix)
//   Website/frontend/src/lib/hclust.js     cluster()   (naive UPGMA, O(n^3))
//
// The frontend files are ES modules in a package without "type":"module",
// so they are copied verbatim into .work/js/*.mjs before import.
//
// Usage: node bench_hclust_node.mjs --n 500 --dim 32 --reps 3 --timeout-s 600 --out file.jsonl
// Each (n, dim) runs in its own process; run_benchmarks.py enforces a wall
// timeout and a memory limit (--max-old-space-size).

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const src = path.resolve(here, '../../Website/frontend/src/lib');
const dst = path.join(here, '.work', 'js');
fs.mkdirSync(dst, { recursive: true });
for (const f of ['distances.js', 'hclust.js']) {
  fs.copyFileSync(path.join(src, f), path.join(dst, f.replace('.js', '.mjs')));
}
const { pairwise } = await import(pathToFileURL(path.join(dst, 'distances.mjs')));
const { cluster } = await import(pathToFileURL(path.join(dst, 'hclust.mjs')));

const args = Object.fromEntries(process.argv.slice(2).reduce((a, v, i, arr) => {
  if (v.startsWith('--')) a.push([v.slice(2), arr[i + 1]]);
  return a;
}, []));
const n = Number(args.n);
const dim = Number(args.dim);
const reps = Number(args.reps || 3);
const out = args.out;
const label = args.label || 'hclust_js';
const samplesForRecord = Number(args.samples || n);

// Deterministic LCG vectors (log-scale-like values).
let seed = 20261119;
const rnd = () => ((seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296);
const vectors = Array.from({ length: n }, () => Array.from({ length: dim }, () => 10 * rnd()));

function write(row) {
  fs.appendFileSync(out, JSON.stringify({
    workflow: 'numerical', run_id: args['run-id'], timestamp: new Date().toISOString(), ...row,
  }) + '\n');
}

for (let rep = 1; rep <= reps; rep++) {
  const h0 = process.memoryUsage().heapUsed;
  let t = performance.now();
  const d = pairwise(vectors, 'euclidean');
  const tDist = (performance.now() - t) / 1000;
  t = performance.now();
  cluster(d, {});
  const tClust = (performance.now() - t) / 1000;
  const mu = process.memoryUsage();
  write({
    operation: label, samples: samplesForRecord, rep, cold: rep === 1, status: 'ok',
    n_items: n, vector_dim: dim, seconds: +(tDist + tClust).toFixed(5),
    stage_pairwise_s: +tDist.toFixed(5), stage_hclust_s: +tClust.toFixed(5),
    peak_rss_mb: +(mu.rss / 1e6).toFixed(1), heap_used_mb: +(mu.heapUsed / 1e6).toFixed(1),
    heap_delta_mb: +((mu.heapUsed - h0) / 1e6).toFixed(1), node: process.version,
  });
  if (tDist + tClust > 120) break; // one rep is enough for very slow cases
}
