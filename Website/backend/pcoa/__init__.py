#--------------------------------
# PCoA (Principal Coordinates Analysis) module
#--------------------------------
#
# This package holds the backend logic for the native Micromix PCoA
# visualization. It is a behavioral port of the proven, read-only reference
# implementation in ``ClusteredHeatmap2/backend/pcoa_service.py`` and
# ``ClusteredHeatmap2/backend/dataset_store.py``: the math, the validation
# rules, the user-facing error messages and the in-memory dataset cache are
# preserved as closely as practical so this feature behaves identically to
# the reference.
#
# Scope for this iteration (see the PCoA porting plan):
#   - Parse and validate a standalone sample-by-feature CSV/TSV matrix
#     (first column = sample id, first row = feature names).
#   - Compute a pairwise distance matrix (Euclidean only, matching the
#     reference) and run classical multidimensional scaling (PCoA).
#   - Support "rerun on a selected subset of samples", filtering the ORIGINAL
#     uploaded matrix and recomputing everything from scratch — never
#     cropping previously computed coordinates.
#   - Keep an in-memory, bounded, LRU + TTL dataset cache so a subset rerun
#     does not require re-uploading the whole matrix (ported from
#     ``dataset_store.py`` as-is; replacing this with Mongo-backed storage is
#     left for a later iteration, per the plan).
#
# Deliberately kept separate from the existing single-dataset upload /
# visualization workflow (process_file.py, filter_dataframe.py, visualize.py,
# ...), mirroring how ``orthology/`` is organized: a self-contained,
# Flask-free package with thin routes added to ``app.py``.
#
# Metadata upload/coloring and sample selection/box-select are intentionally
# NOT implemented here: per the reference implementation, they are a
# client-side visualization concern (ported to
# ``frontend/src/lib/pcoaSubset.js``) that never affects the calculation.

from .service import (
    PcoaInputError,
    ParsedMatrix,
    MdsResult,
    MIN_SAMPLES,
    MIN_FEATURES,
    MAX_SAMPLES,
    MAX_FEATURES,
    ALLOWED_EXTENSIONS,
    DEFAULT_METRIC,
    DISTANCE_METRICS,
    parse_matrix,
    validate_extension,
    normalize_sample_ids,
    subset_matrix,
    compute_distance_matrix,
    classical_mds,
    run_pcoa_on_matrix,
    run_pcoa,
)
from .dataset_store import DatasetStore, StoredDataset

__all__ = [
    "PcoaInputError",
    "ParsedMatrix",
    "MdsResult",
    "MIN_SAMPLES",
    "MIN_FEATURES",
    "MAX_SAMPLES",
    "MAX_FEATURES",
    "ALLOWED_EXTENSIONS",
    "DEFAULT_METRIC",
    "DISTANCE_METRICS",
    "parse_matrix",
    "validate_extension",
    "normalize_sample_ids",
    "subset_matrix",
    "compute_distance_matrix",
    "classical_mds",
    "run_pcoa_on_matrix",
    "run_pcoa",
    "DatasetStore",
    "StoredDataset",
]
