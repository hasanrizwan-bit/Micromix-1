"""
Principal Coordinates Analysis (PCoA) — backend service module.

Ported from ``ClusteredHeatmap2/backend/pcoa_service.py``. The math, the
validation rules and the user-facing error messages are preserved verbatim so
the Micromix PCoA behaves identically to the proven reference implementation.
This module holds ALL of the PCoA numerical logic and input validation so the
Flask route in ``app.py`` stays thin (receive file -> call service -> return
JSON). Nothing here imports Flask, which keeps the module directly unit
testable (see ``backend/pcoa/tests/test_service.py``).

Scope of this iteration
-----------------------
* Input: a CSV/TSV sample-by-feature matrix
      first column  = sample id
      first row     = feature names
      all other cells = finite numeric values
* Distance: Euclidean only (but see ``DISTANCE_METRICS`` — adding
  Bray-Curtis / Jaccard later is a one-line registry entry).
* Ordination: classical multidimensional scaling (a.k.a. classical PCoA /
  Torgerson scaling).

Public API
----------
``run_pcoa(file_bytes_or_text, filename=None, metric="euclidean", sample_ids=None)``
    End-to-end: parse + validate + optional sample subsetting + distance +
    ordination, returning a plain JSON-serializable dict.
``run_pcoa_on_matrix(parsed, metric="euclidean", sample_ids=None)``
    Same as above for an ALREADY parsed matrix, so a subset recalculation can
    reuse the stored original upload instead of re-parsing (or, worse, trusting
    the client to re-send) the feature values.
``parse_matrix(text, filename=None)``
    Parse + validate only. Raises ``PcoaInputError`` with a user-facing
    message when the input is unusable.
``normalize_sample_ids(raw)``
    Coerce a client-supplied selection (JSON array, newline-separated text or a
    Python list) into a clean ``list[str]``.
``subset_matrix(parsed, sample_ids)``
    Filter a parsed matrix down to the selected samples, validating that the
    ids exist, de-duplicating them and refusing selections that cannot produce
    a meaningful PCoA.
``compute_distance_matrix(values, metric)``
    Pairwise sample x sample distance matrix.
``classical_mds(distances, n_components=2)``
    The eigen-decomposition step, independent of any file handling.

Subsetting is deliberately expressed as "filter the ORIGINAL matrix, then run
the whole pipeline again": the distance matrix and the eigendecomposition are
recomputed from the selected samples' feature rows, never derived from the
coordinates of a previous run.
"""

from __future__ import annotations

import io
import csv
import json
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Callable, Iterable, Sequence

import numpy as np
from scipy.spatial.distance import pdist, squareform

# ---------------------------------------------------------------------------
# Validation limits / tolerances
# ---------------------------------------------------------------------------

#: Classical MDS on fewer than 3 samples cannot produce a meaningful 2D plot.
MIN_SAMPLES = 3

#: A "matrix" needs at least two measured features to be worth ordinating.
MIN_FEATURES = 2

#: Classical MDS is O(n^3) in the number of samples. This cap keeps a single
#: request from pinning the dev server for minutes; raise it (or switch to a
#: truncated eigensolver) when large studies need to be supported. It is
#: enforced *while the upload is being read*, so an oversized file is rejected
#: before any cell is parsed.
MAX_SAMPLES = 2000

#: Companion cap on the feature count: total cell count, not row count, drives
#: parsing cost, so bounding rows alone would not bound the work per request.
MAX_FEATURES = 5000

#: Accepted upload extensions. Delimiter is derived from the extension when
#: possible and sniffed from the header line otherwise.
ALLOWED_EXTENSIONS = {".csv": ",", ".tsv": "\t"}

#: Eigenvalues whose magnitude is below ``EIGEN_ZERO_TOL * max|eigenvalue|``
#: are treated as numerical zero (they are the rank-deficiency directions that
#: always show up in a Euclidean double-centred matrix).
EIGEN_ZERO_TOL = 1e-10

#: A negative eigenvalue is only reported as *meaningful* (i.e. a real
#: non-Euclidean artefact rather than floating-point noise) when its magnitude
#: exceeds this fraction of the largest positive eigenvalue.
NEGATIVE_EIGEN_WARN_TOL = 1e-6

#: How many offending sample ids to name in a validation message before
#: switching to "... and N more" (keeps the error readable for a big paste).
MAX_LISTED_IDS = 5


class PcoaInputError(ValueError):
    """Raised when the uploaded file cannot be used for PCoA.

    The message is written to be shown directly to the user, so it should
    always say *what* is wrong and *where* (row / column) when known.
    """


@dataclass(frozen=True)
class ParsedMatrix:
    """A validated sample-by-feature numeric matrix."""

    sample_ids: list[str]
    feature_names: list[str]
    values: np.ndarray  # shape (n_samples, n_features), dtype float64
    delimiter: str

    @property
    def n_samples(self) -> int:
        return int(self.values.shape[0])

    @property
    def n_features(self) -> int:
        return int(self.values.shape[1])


# ---------------------------------------------------------------------------
# Parsing / validation
# ---------------------------------------------------------------------------


def _decode(data) -> str:
    """Decode uploaded bytes to text, tolerating a UTF-8 BOM."""
    if isinstance(data, str):
        return data
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:  # pragma: no cover - binary upload
        raise PcoaInputError(
            "The file could not be read as text. Please upload a plain "
            "CSV or TSV file (UTF-8 encoded)."
        ) from exc


def validate_extension(filename: str | None) -> str | None:
    """Return the delimiter implied by ``filename``'s extension.

    Returns ``None`` when there is no filename at all (delimiter will then be
    sniffed). Raises ``PcoaInputError`` for an extension we do not accept, so
    a stray ``.xlsx`` / ``.pdf`` never reaches the parser.
    """
    if not filename:
        return None
    suffix = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
    if suffix in ALLOWED_EXTENSIONS:
        return ALLOWED_EXTENSIONS[suffix]
    raise PcoaInputError(
        f"Unsupported file type '{suffix or filename}'. "
        "Please upload a .csv or .tsv matrix."
    )


def sniff_delimiter(header_line: str) -> str:
    """Guess ',' vs '\\t' from the header line by simple field counting.

    Only used when there is no filename to derive the delimiter from. Field
    counting cannot distinguish a separator from separator characters *inside*
    a label, so when an extension is available it is trusted first and only
    overridden if it fails to produce a rectangular table (see
    ``_choose_delimiter``).
    """
    commas = header_line.count(",")
    tabs = header_line.count("\t")
    if tabs > commas:
        return "\t"
    if commas > 0:
        return ","
    # Neither separator present -> a single-column file; report it as such
    # rather than guessing.
    raise PcoaInputError(
        "Could not detect a CSV or TSV delimiter in the header row. The first "
        "row must list feature names separated by commas or tabs."
    )


def _non_empty_rows(
    text: str, delimiter: str, max_rows: int | None = None
) -> tuple[list[list[str]], bool]:
    """CSV-parse ``text``, dropping rows that are entirely blank.

    Returns ``(rows, truncated)``. When ``max_rows`` is given, reading stops as
    soon as one more row than that is found and ``truncated`` is ``True``, so an
    oversized upload is rejected without materializing the whole file (a 16 MB
    upload otherwise costs seconds of CPU and hundreds of MB of RSS before the
    sample-count limit is reached).
    """
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows: list[list[str]] = []
    for raw in reader:
        if not raw or all((cell or "").strip() == "" for cell in raw):
            continue
        if max_rows is not None and len(rows) >= max_rows:
            return rows, True
        rows.append([(cell or "").strip() for cell in raw])
    return rows, False


def _is_rectangular(rows: list[list[str]]) -> bool:
    """True when every row has the same width and there is at least one feature."""
    if len(rows) < 2:
        return False
    width = len(rows[0])
    return width >= 2 and all(len(row) == width for row in rows)


def _choose_delimiter(text: str, filename: str | None):
    """Pick the delimiter and return ``(delimiter, rows)``.

    The extension is authoritative and is tried first; the other delimiter is
    used only when the extension's delimiter does not yield a rectangular
    table. This matters because feature names legitimately contain commas
    (taxonomy strings such as ``k__Bacteria,p__Firmicutes``) — counting
    separator characters alone would misparse such a ``.tsv`` as CSV and then
    reject it with a misleading "wrong number of fields" error.

    When neither delimiter produces a rectangular table, the first candidate is
    returned so the normal validation messages describe the declared format.
    """
    from_extension = validate_extension(filename)
    if from_extension is not None:
        candidates = [from_extension, "\t" if from_extension == "," else ","]
    else:
        first_line = text.split("\n", 1)[0]
        sniffed = sniff_delimiter(first_line)
        candidates = [sniffed, "\t" if sniffed == "," else ","]

    fallback = None
    for candidate in candidates:
        rows, truncated = _non_empty_rows(text, candidate, max_rows=MAX_SAMPLES + 1)
        if truncated:
            raise PcoaInputError(
                f"The file contains more than {MAX_SAMPLES} samples, which "
                f"exceeds the current limit of {MAX_SAMPLES}. Please subset the "
                "matrix before uploading."
            )
        if _is_rectangular(rows):
            return candidate, rows
        if fallback is None:
            fallback = (candidate, rows)
    return fallback


def _parse_number(raw: str, sample_id: str, feature: str, line_no: int) -> float:
    """Convert one cell to a finite float or raise a user-facing error."""
    where = f"row {line_no} (sample '{sample_id}'), column '{feature}'"
    if raw == "":
        raise PcoaInputError(
            f"Missing value at {where}. Missing values are not supported in "
            "this version — every cell after the first column must contain a "
            "number."
        )
    try:
        value = float(raw)
    except ValueError:
        raise PcoaInputError(
            f"Non-numeric value '{raw}' at {where}. Every cell after the first "
            "column must be numeric."
        ) from None
    if not np.isfinite(value):
        raise PcoaInputError(
            f"Invalid value '{raw}' at {where}. NaN and infinite values are "
            "not supported."
        )
    return value


def parse_matrix(data, filename: str | None = None) -> ParsedMatrix:
    """Parse and fully validate an uploaded sample-by-feature matrix.

    Validation rules enforced here (each with its own message):
      1. extension is ``.csv`` or ``.tsv``
      2. file is not empty and the delimiter can be determined
      3. no more than ``MAX_SAMPLES`` rows (checked while reading, before any
         cell is parsed) and no more than ``MAX_FEATURES`` columns
      4. header row declares at least ``MIN_FEATURES`` feature columns
      5. every data row has exactly as many fields as the header
      6. sample identifiers are non-blank and unique
      7. at least ``MIN_SAMPLES`` data rows
      8. every cell after the first column is numeric, present and finite
    """
    text = _decode(data)

    if text.strip() == "":
        raise PcoaInputError("The uploaded file is empty.")

    # Picks the delimiter AND returns the parsed rows, rejecting an oversized
    # file before any numeric parsing happens.
    delimiter, rows = _choose_delimiter(text, filename)

    if len(rows) < 2:
        raise PcoaInputError(
            "The file needs a header row of feature names plus at least "
            f"{MIN_SAMPLES} sample rows."
        )

    header = rows[0]
    feature_names = header[1:]
    if len(feature_names) < MIN_FEATURES:
        raise PcoaInputError(
            f"Found {len(feature_names)} feature column(s). At least "
            f"{MIN_FEATURES} numeric feature columns are required (the first "
            "column is used for sample identifiers)."
        )
    if len(feature_names) > MAX_FEATURES:
        # Checked before the per-cell loop: total cell count, not row count,
        # drives parsing cost.
        raise PcoaInputError(
            f"Found {len(feature_names)} feature columns, which exceeds the "
            f"current limit of {MAX_FEATURES}. Please reduce the number of "
            "features before uploading."
        )
    # Give unnamed feature columns a stable placeholder name.
    feature_names = [
        name if name != "" else f"feature_{i + 1}"
        for i, name in enumerate(feature_names)
    ]

    expected_width = len(header)
    sample_ids: list[str] = []
    seen: dict[str, int] = {}
    values: list[list[float]] = []

    for offset, row in enumerate(rows[1:]):
        line_no = offset + 2  # 1-based, counting the header as row 1
        if len(row) != expected_width:
            raise PcoaInputError(
                f"Row {line_no} has {len(row)} field(s) but the header has "
                f"{expected_width}. Every row must have one sample id "
                "followed by one value per feature."
            )
        sample_id = row[0]
        if sample_id == "":
            raise PcoaInputError(
                f"Row {line_no} has a blank sample identifier. The first "
                "column must contain a sample name for every row."
            )
        if sample_id in seen:
            raise PcoaInputError(
                f"Duplicate sample identifier '{sample_id}' on rows "
                f"{seen[sample_id]} and {line_no}. Sample identifiers must be "
                "unique."
            )
        seen[sample_id] = line_no
        sample_ids.append(sample_id)
        values.append(
            [
                _parse_number(cell, sample_id, feature_names[i], line_no)
                for i, cell in enumerate(row[1:])
            ]
        )

    if len(sample_ids) < MIN_SAMPLES:
        raise PcoaInputError(
            f"Found {len(sample_ids)} sample row(s). At least {MIN_SAMPLES} "
            "samples are required to compute a 2D PCoA."
        )
    # NOTE: the upper sample bound is enforced in ``_non_empty_rows`` while the
    # file is being read, so there is deliberately no late check here.

    matrix = np.asarray(values, dtype=float)
    if not np.all(np.isfinite(matrix)):  # defensive; _parse_number checks each
        raise PcoaInputError(
            "The matrix contains missing, infinite or invalid values."
        )

    return ParsedMatrix(
        sample_ids=sample_ids,
        feature_names=feature_names,
        values=matrix,
        delimiter=delimiter,
    )


# ---------------------------------------------------------------------------
# Sample subsetting (shared by plot selection and any manual sample filter)
# ---------------------------------------------------------------------------


def _format_id_list(ids: Sequence[str]) -> str:
    """Render up to ``MAX_LISTED_IDS`` ids for a user-facing message."""
    shown = [f"'{i}'" for i in ids[:MAX_LISTED_IDS]]
    extra = len(ids) - len(shown)
    text = ", ".join(shown)
    if extra > 0:
        text += f" and {extra} more"
    return text


def normalize_sample_ids(raw) -> list[str] | None:
    """Coerce a client-supplied sample selection into a ``list[str]``.

    Accepted shapes (everything else is a ``PcoaInputError``):

      * ``None`` / empty string  -> ``None``, meaning "no subsetting requested".
        This is what keeps the original full-dataset request path unchanged.
      * a JSON array string, e.g. ``'["S1", "S2"]'`` (what the frontend sends,
        both as a form field and inside a JSON body)
      * a newline-separated string (convenient for pasting a list by hand;
        splitting on commas is deliberately NOT done because a sample id may
        legitimately contain a comma)
      * a Python/JSON list or tuple of strings or numbers

    An explicitly EMPTY selection (``[]`` / ``'[]'``) returns ``[]`` rather than
    ``None``, so "the user pressed rerun with nothing selected" is reported as a
    validation error instead of silently running on the full dataset.
    """
    if raw is None:
        return None

    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise PcoaInputError(
                "The selected sample list could not be read as text."
            ) from None

    if isinstance(raw, str):
        text = raw.strip()
        if text == "":
            return None
        if text[0] in "[{":
            try:
                decoded = json.loads(text)
            except ValueError:
                raise PcoaInputError(
                    "The selected sample list is not valid JSON. Expected an "
                    'array of sample ids, e.g. ["Sample_1", "Sample_2"].'
                ) from None
            if not isinstance(decoded, (list, tuple)):
                raise PcoaInputError(
                    "The selected sample list must be a JSON array of sample ids."
                )
            return normalize_sample_ids(decoded)
        return normalize_sample_ids(text.splitlines())

    if isinstance(raw, (list, tuple)):
        out: list[str] = []
        for item in raw:
            if isinstance(item, bool) or item is None:
                raise PcoaInputError(
                    "The selected sample list contains a value that is not a "
                    "sample id."
                )
            if isinstance(item, (int, float)):
                # Numeric sample ids survive a JSON round trip as numbers.
                item = repr(item) if isinstance(item, float) else str(item)
            if not isinstance(item, str):
                raise PcoaInputError(
                    "The selected sample list must contain only sample ids "
                    "(strings)."
                )
            item = item.strip()
            if item == "":
                continue  # blank line in a pasted list: ignore rather than fail
            out.append(item)
        return out

    raise PcoaInputError(
        "The selected sample list must be an array of sample ids."
    )


def subset_matrix(
    parsed: ParsedMatrix, sample_ids: Iterable[str] | None
) -> tuple[ParsedMatrix, list[str]]:
    """Filter ``parsed`` down to ``sample_ids``, in the ORIGINAL row order.

    Returns ``(subset, warnings)``. ``sample_ids is None`` is a no-op and
    returns the input unchanged, which is what makes this the single
    sample-subsetting entry point for both the full-dataset run and every
    filtered/selected run.

    Validation (each with its own user-facing message):
      1. the selection is not empty
      2. no more than ``MAX_SAMPLES`` ids were requested
      3. every requested id exists in the uploaded matrix
      4. duplicates are collapsed (kept once) and reported as a warning
      5. at least ``MIN_SAMPLES`` distinct samples remain
      6. the retained rows are finite and not all identical, i.e. the filtered
         matrix still carries usable numeric variation

    Row ORDER follows the original matrix, not the order the ids arrived in, so
    the same selection always produces byte-identical coordinates regardless of
    the order in which the user clicked the points.
    """
    if sample_ids is None:
        return parsed, []

    requested = list(sample_ids)
    if not requested:
        raise PcoaInputError(
            "No samples were selected. Select at least "
            f"{MIN_SAMPLES} points in the plot before rerunning the PCoA."
        )
    if len(requested) > MAX_SAMPLES:
        raise PcoaInputError(
            f"{len(requested)} samples were selected, which exceeds the current "
            f"limit of {MAX_SAMPLES}."
        )

    index_of = {sid: i for i, sid in enumerate(parsed.sample_ids)}

    unknown: list[str] = []
    duplicates: list[str] = []
    keep_indices: list[int] = []
    seen: set[str] = set()
    for sid in requested:
        if sid not in index_of:
            if sid not in unknown:
                unknown.append(sid)
            continue
        if sid in seen:
            if sid not in duplicates:
                duplicates.append(sid)
            continue
        seen.add(sid)
        keep_indices.append(index_of[sid])

    if unknown:
        raise PcoaInputError(
            f"{len(unknown)} selected sample id(s) are not in the uploaded "
            f"dataset: {_format_id_list(unknown)}. The selection may refer to a "
            "different dataset — rerun the PCoA on the full dataset and select "
            "again."
        )

    warnings: list[str] = []
    if duplicates:
        warnings.append(
            f"{len(duplicates)} duplicate sample id(s) in the selection were "
            f"used once each: {_format_id_list(duplicates)}."
        )

    if len(keep_indices) < MIN_SAMPLES:
        raise PcoaInputError(
            f"Only {len(keep_indices)} distinct sample(s) were selected. At "
            f"least {MIN_SAMPLES} samples are required to compute a 2D PCoA."
        )

    keep_indices.sort()
    values = parsed.values[keep_indices, :]

    if not np.all(np.isfinite(values)):  # defensive; parsing already checks
        raise PcoaInputError(
            "The selected samples contain missing or non-numeric values, so no "
            "PCoA can be computed for them."
        )
    if values.shape[1] < MIN_FEATURES:
        raise PcoaInputError(
            f"The selected samples have {values.shape[1]} numeric feature(s); "
            f"at least {MIN_FEATURES} are required."
        )
    if np.all(values == values[0]):
        raise PcoaInputError(
            f"All {values.shape[0]} selected samples have identical feature "
            "values, so the distance matrix carries no variation. Select a more "
            "varied set of points."
        )

    subset = ParsedMatrix(
        sample_ids=[parsed.sample_ids[i] for i in keep_indices],
        feature_names=list(parsed.feature_names),
        values=values,
        delimiter=parsed.delimiter,
    )
    return subset, warnings


# ---------------------------------------------------------------------------
# Distance metrics (registry so more metrics can be added later)
# ---------------------------------------------------------------------------


def _euclidean(values: np.ndarray) -> np.ndarray:
    return squareform(pdist(values, metric="euclidean"))


#: name -> callable(values (n x m)) -> distances (n x n).
#: Later iterations add "braycurtis" / "jaccard" here and expose a selector;
#: nothing else in this module needs to change.
DISTANCE_METRICS: dict[str, Callable[[np.ndarray], np.ndarray]] = {
    "euclidean": _euclidean,
}

DEFAULT_METRIC = "euclidean"


def compute_distance_matrix(
    values: np.ndarray, metric: str = DEFAULT_METRIC
) -> np.ndarray:
    """Pairwise sample x sample distance matrix for ``values``."""
    key = (metric or DEFAULT_METRIC).lower()
    if key not in DISTANCE_METRICS:
        raise PcoaInputError(
            f"Unsupported distance metric '{metric}'. Supported metrics: "
            + ", ".join(sorted(DISTANCE_METRICS))
        )
    distances = DISTANCE_METRICS[key](np.asarray(values, dtype=float))
    # Guard against a degenerate matrix producing non-finite distances.
    if not np.all(np.isfinite(distances)):
        raise PcoaInputError(
            "The distance matrix contains non-finite values; please check the "
            "input matrix for extreme values."
        )
    return distances


# ---------------------------------------------------------------------------
# Classical multidimensional scaling (PCoA)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MdsResult:
    """Output of :func:`classical_mds`."""

    coordinates: np.ndarray       # (n_samples, n_components)
    eigenvalues: np.ndarray       # all eigenvalues, sorted descending
    positive_eigenvalues: np.ndarray
    explained: np.ndarray         # % variation per returned component
    warnings: list[str]


def classical_mds(distances: np.ndarray, n_components: int = 2) -> MdsResult:
    """Classical MDS / PCoA on a square symmetric distance matrix.

    Steps (the standard Torgerson/Gower procedure):
      1. square the distances
      2. double-centre with ``J = I - (1/n) * 11'``  ->  ``B = -1/2 J D^2 J``
      3. symmetric eigendecomposition of ``B``
      4. sort eigenvalues (and eigenvectors) descending
      5. keep the eigenvalues that are positive beyond numerical noise
      6. coordinates for axis k = eigenvector_k * sqrt(eigenvalue_k)

    Negative eigenvalues:
      Tiny negatives are unavoidable floating-point noise and are ignored.
      Genuinely negative eigenvalues (magnitude above
      ``NEGATIVE_EIGEN_WARN_TOL`` times the largest positive eigenvalue) are
      NOT flipped, clamped or otherwise hidden: they are reported through
      ``warnings`` while the first ``n_components`` *positive* axes are still
      returned so the plot can be drawn.

    Explained variation:
      Percentages are ``lambda_k / sum(|lambda|) * 100``. The denominator uses
      the sum of the ABSOLUTE eigenvalues, i.e. the total inertia including the
      non-Euclidean part, for two reasons: it stays bounded by 100%, and it does
      not claim that two axes explain everything in exactly the case where the
      negative-eigenvalue warning says the ordination is imperfect. For clean
      Euclidean input the negatives are numerical noise, so this is identical
      (to ~1e-14) to dividing by the sum of the positive eigenvalues.
    """
    d = np.asarray(distances, dtype=float)
    if d.ndim != 2 or d.shape[0] != d.shape[1]:
        raise ValueError("distances must be a square 2D matrix")

    n = d.shape[0]
    if n < n_components + 1:
        raise PcoaInputError(
            f"At least {n_components + 1} samples are required for a "
            f"{n_components}-dimensional PCoA; got {n}."
        )

    # 1 + 2: double-centre the squared distances.
    squared = d ** 2
    centering = np.eye(n) - np.ones((n, n)) / n
    b = -0.5 * centering @ squared @ centering
    # ``eigh`` requires exact symmetry; centring can leave ~1e-16 asymmetry.
    b = (b + b.T) / 2.0

    # 3 + 4: eigendecomposition, largest first.
    eigenvalues, eigenvectors = np.linalg.eigh(b)
    order = np.argsort(eigenvalues)[::-1]
    eigenvalues = eigenvalues[order]
    eigenvectors = eigenvectors[:, order]

    scale = float(np.max(np.abs(eigenvalues))) if n else 0.0
    if scale <= 0:
        raise PcoaInputError(
            "PCoA could not be computed: all samples are identical, so the "
            "distance matrix carries no variation."
        )

    zero_tol = EIGEN_ZERO_TOL * scale
    positive_mask = eigenvalues > zero_tol
    positive_eigenvalues = eigenvalues[positive_mask]

    warnings: list[str] = []
    largest_positive = (
        float(positive_eigenvalues[0]) if positive_eigenvalues.size else 0.0
    )
    most_negative = float(eigenvalues[-1])
    if largest_positive > 0 and most_negative < -(
        NEGATIVE_EIGEN_WARN_TOL * largest_positive
    ):
        warnings.append(
            "Euclidean PCoA produced negative eigenvalues (most negative: "
            f"{most_negative:.6g}). The first positive coordinates are still "
            "plotted, but the ordination does not represent the distances "
            "perfectly."
        )

    if positive_eigenvalues.size < n_components:
        raise PcoaInputError(
            "PCoA produced only "
            f"{positive_eigenvalues.size} positive eigenvalue(s); at least "
            f"{n_components} are needed to plot {n_components} coordinates. "
            "The input matrix has too little independent variation."
        )

    # 5 + 6: coordinates from the leading positive axes.
    kept = eigenvectors[:, positive_mask][:, :n_components]
    kept_values = positive_eigenvalues[:n_components]
    coordinates = kept * np.sqrt(kept_values)

    # Total inertia INCLUDING the non-Euclidean (negative) part, so the
    # percentages never sum to 100% while a negative-eigenvalue warning is
    # active. See the docstring for the rationale.
    total_variation = float(np.sum(np.abs(eigenvalues)))
    explained = (kept_values / total_variation) * 100.0

    return MdsResult(
        coordinates=coordinates,
        eigenvalues=eigenvalues,
        positive_eigenvalues=positive_eigenvalues,
        explained=explained,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# End-to-end entry point used by the Flask route
# ---------------------------------------------------------------------------


def _floats(seq: Sequence[float]) -> list[float]:
    return [float(v) for v in seq]


def run_pcoa_on_matrix(
    parsed: ParsedMatrix,
    metric: str = DEFAULT_METRIC,
    n_components: int = 2,
    sample_ids: Iterable[str] | None = None,
) -> dict:
    """Run the full PCoA pipeline over an already parsed matrix.

    When ``sample_ids`` is given the matrix is first filtered to those samples
    (see :func:`subset_matrix`) and then the ENTIRE pipeline runs again on the
    filtered feature values: a fresh pairwise distance matrix, a fresh
    eigendecomposition and fresh explained-variation percentages. No part of the
    result is carried over from a previous run, which is exactly what makes a
    subset ordination a real re-analysis of the selected samples rather than a
    cropped view of the full one.

    Returns a plain dict that is safe to pass straight to ``jsonify``.
    """
    original_n_samples = parsed.n_samples
    active, subset_warnings = subset_matrix(parsed, sample_ids)

    distances = compute_distance_matrix(active.values, metric=metric)
    result = classical_mds(distances, n_components=n_components)

    coords = result.coordinates
    explained = result.explained
    is_subset = sample_ids is not None and active.n_samples != original_n_samples

    return {
        "sample_ids": list(active.sample_ids),
        "feature_names": list(active.feature_names),
        "coordinate_1": _floats(coords[:, 0]),
        "coordinate_2": _floats(coords[:, 1]),
        "coordinates": [_floats(row) for row in coords],
        "eigenvalues": _floats(result.eigenvalues),
        "positive_eigenvalues": _floats(result.positive_eigenvalues),
        "explained_variation": _floats(explained),
        "explained_1": float(explained[0]),
        "explained_2": float(explained[1]),
        "explained_combined": float(explained[0] + explained[1]),
        "n_samples": active.n_samples,
        "n_features": active.n_features,
        "metric": (metric or DEFAULT_METRIC).lower(),
        "delimiter": "tab" if active.delimiter == "\t" else "comma",
        "warnings": list(subset_warnings) + list(result.warnings),
        # Subset bookkeeping. ``n_original_samples`` is the size of the matrix
        # the subset was filtered OUT OF, so the frontend can say
        # "Showing 14 of 40 original samples" without guessing.
        "is_subset": bool(is_subset),
        "n_original_samples": original_n_samples,
    }


def run_pcoa(
    data,
    filename: str | None = None,
    metric: str = DEFAULT_METRIC,
    n_components: int = 2,
    sample_ids: Iterable[str] | None = None,
) -> dict:
    """Parse ``data``, optionally filter it to ``sample_ids``, and run PCoA.

    Returns a plain dict that is safe to pass straight to ``jsonify``.
    Raises ``PcoaInputError`` (with a user-facing message) for any invalid
    input.
    """
    parsed = parse_matrix(data, filename=filename)
    return run_pcoa_on_matrix(
        parsed,
        metric=metric,
        n_components=n_components,
        sample_ids=sample_ids,
    )
