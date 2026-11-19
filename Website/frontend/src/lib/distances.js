/**
 * Euclidean distance between two vectors.
 */
export function euclidean(a, b) {
  let sum = 0;
  let count = 0;
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== null && b[i] !== null) {
      sum += (a[i] - b[i]) ** 2;
      count++;
    }
  }
  return count === 0 ? 0 : Math.sqrt(sum / count);
}

/**
 * Correlation distance (1 - Pearson r) between two vectors.
 */
export function correlationDistance(a, b) {
  let sumA = 0, sumB = 0, sumAA = 0, sumBB = 0, sumAB = 0;
  let count = 0;
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== null && b[i] !== null) {
      sumA += a[i];
      sumB += b[i];
      sumAA += a[i] * a[i];
      sumBB += b[i] * b[i];
      sumAB += a[i] * b[i];
      count++;
    }
  }
  if (count < 2) return 1;
  const meanA = sumA / count;
  const meanB = sumB / count;
  const num = sumAB - count * meanA * meanB;
  const denA = sumAA - count * meanA * meanA;
  const denB = sumBB - count * meanB * meanB;
  const den = Math.sqrt(denA * denB);
  if (den === 0) return 1;
  const r = num / den;
  return Math.max(0, Math.min(2, 1 - r)); // Clamp to [0, 2]
}

/**
 * Jaccard distance between two binary vectors.
 * Treats non-zero finite values as 1, zero/null as 0.
 * Jaccard distance = 1 - |A ∩ B| / |A ∪ B|
 */
export function jaccard(a, b) {
  let intersection = 0;
  let union = 0;
  for (let i = 0; i < a.length; i++) {
    const va = a[i] !== null && a[i] !== 0 ? 1 : 0;
    const vb = b[i] !== null && b[i] !== 0 ? 1 : 0;
    if (va && vb) intersection++;
    if (va || vb) union++;
  }
  return union === 0 ? 0 : 1 - intersection / union;
}

/**
 * Compute a pairwise distance matrix from a list of vectors.
 *
 * @param {number[][]} vectors - array of vectors (each vector is an array of numbers or null)
 * @param {string} metric - 'euclidean' | 'correlation' | 'jaccard'
 * @returns {number[][]} symmetric distance matrix
 */
export function pairwise(vectors, metric = 'euclidean') {
  const n = vectors.length;
  const distFn = metric === 'correlation' ? correlationDistance
    : metric === 'jaccard' ? jaccard
    : euclidean;

  const dist = [];
  for (let i = 0; i < n; i++) {
    dist[i] = new Float64Array(n);
    for (let j = 0; j < i; j++) {
      const d = distFn(vectors[i], vectors[j]);
      dist[i][j] = d;
      dist[j][i] = d;
    }
  }
  return dist;
}
