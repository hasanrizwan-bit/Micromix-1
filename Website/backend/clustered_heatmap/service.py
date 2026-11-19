"""
Clustered Heatmap — backend service module.

Ported from ``ClusteredHeatmap2/backend/app.py`` (the ``_dendrogram_payload``
helper and the ``/api/clustered-heatmap-data`` route). The clustering math —
SciPy hierarchical clustering with average linkage on Euclidean distance,
applied independently to rows and to columns — and the dendrogram payload
shape (``icoord``/``dcoord``/``leaves``/``color_list``/``linkage``/``n_leaves``)
are preserved VERBATIM so the Micromix Clustered Heatmap produces identical
clustering/dendrogram output to the proven reference implementation.

The only behavioral difference from the reference route is the SOURCE of the
matrix: the reference always clustered a bundled example CSV
(``backend/data/example_heatmap.csv``); this module clusters whatever
``row_labels`` / ``column_labels`` / ``values`` the caller supplies, which is
the Micromix session's currently active matrix (see
``frontend/src/lib/clusteredHeatmapFromMicromix.js``). Nothing here imports
Flask, which keeps this module directly unit-testable and mirrors the
Flask-free style of ``Website/backend/pcoa/service.py``.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.cluster.hierarchy import dendrogram, leaves_list, linkage


class ClusteredHeatmapInputError(ValueError):
    """Raised when the posted matrix cannot be clustered.

    The message is safe to show to the user (mirrors ``PcoaInputError``'s
    contract in ``pcoa/service.py``).
    """


def _values_to_jsonable(matrix):
    """Convert a 2D numpy array to JSON-safe Python lists.

    NaNs become ``None`` so the response is valid JSON. Ported verbatim from
    the reference ``_values_to_jsonable``.
    """
    return [
        [None if (v is None or (isinstance(v, float) and math.isnan(v))) else float(v) for v in row]
        for row in matrix
    ]


def _dendrogram_payload(linkage_matrix):
    """Compute a dendrogram from a SciPy linkage matrix and return a
    JSON-serializable dict containing the coordinates the frontend needs to
    draw it. Ported verbatim from the reference ``_dendrogram_payload``; see
    that function's docstring in ``ClusteredHeatmap2/backend/app.py`` for the
    full field-by-field explanation (``icoord``/``dcoord``/``leaves``/
    ``color_list``/``linkage``/``n_leaves``).
    """
    dendro = dendrogram(linkage_matrix, no_plot=True)
    # ``linkage_matrix`` has shape (n_leaves - 1, 4); n_leaves = rows + 1.
    n_leaves = int(linkage_matrix.shape[0]) + 1
    return {
        "icoord": [list(map(float, xs)) for xs in dendro["icoord"]],
        "dcoord": [list(map(float, ys)) for ys in dendro["dcoord"]],
        "leaves": [int(i) for i in dendro["leaves"]],
        "color_list": list(dendro["color_list"]),
        "linkage": [
            [float(row[0]), float(row[1]), float(row[2]), float(row[3])]
            for row in linkage_matrix
        ],
        "n_leaves": n_leaves,
    }


def _validate_shape(row_labels, column_labels, values):
    if not isinstance(row_labels, list) or not isinstance(column_labels, list):
        raise ClusteredHeatmapInputError(
            "'row_labels' and 'column_labels' must both be arrays."
        )
    if not isinstance(values, list):
        raise ClusteredHeatmapInputError("'values' must be an array of rows.")

    n_rows = len(row_labels)
    n_cols = len(column_labels)
    if n_rows == 0 or n_cols == 0:
        raise ClusteredHeatmapInputError(
            "The current matrix has no rows or no numeric columns to cluster."
        )
    if len(values) != n_rows:
        raise ClusteredHeatmapInputError(
            "'values' must have exactly one row per entry in 'row_labels'."
        )
    for row in values:
        if not isinstance(row, list) or len(row) != n_cols:
            raise ClusteredHeatmapInputError(
                "Every row of 'values' must have exactly one cell per entry "
                "in 'column_labels'."
            )
    return n_rows, n_cols


def cluster_matrix(row_labels, column_labels, values):
    """
    Cluster the rows and columns of ``values`` independently and return the
    SAME payload shape as the reference ``/api/clustered-heatmap-data``
    route:

        {
            "row_labels":            [...clustered row order...],
            "column_labels":         [...clustered column order...],
            "values":                [[float | null, ...], ...],
            "original_row_labels":   [...caller order...],
            "original_column_labels":[...caller order...],
            "row_order":             [int, ...],   # indices into original rows
            "column_order":          [int, ...],   # indices into original cols
            "clustered": {
                "rows":    bool,    # True iff hierarchical clustering ran
                "columns": bool,    # True iff hierarchical clustering ran
            },
            "row_dendrogram":    {icoord, dcoord, leaves, color_list,
                                   linkage, n_leaves} | null,
            "column_dendrogram": {...} | null,
        }

    ``row_labels`` / ``column_labels``: ``list[str]``.
    ``values``: ``list[list[float | None]]``, shape
    ``(len(row_labels), len(column_labels))``. ``None`` cells are treated as
    missing (JSON ``null``) exactly like the reference's NaN handling: they
    are replaced with 0.0 ONLY for the clustering math (via
    ``np.nan_to_num``), while the returned ``values`` preserve them as
    ``None``.

    Raises :class:`ClusteredHeatmapInputError` for a user-fixable problem
    (wrong shape, non-numeric cell, ...).
    """
    n_rows, n_cols = _validate_shape(row_labels, column_labels, values)

    try:
        original_matrix = np.array(
            [
                [np.nan if cell is None else float(cell) for cell in row]
                for row in values
            ],
            dtype=float,
        )
    except (TypeError, ValueError) as exc:
        raise ClusteredHeatmapInputError(
            "Every cell of 'values' must be a number or null."
        ) from exc

    # SciPy's linkage cannot handle NaN, so use a NaN-free copy *only* for
    # the clustering math (ported verbatim from the reference).
    clean_matrix = np.nan_to_num(original_matrix, nan=0.0)

    # ---- Cluster rows -------------------------------------------------
    if n_rows >= 2:
        row_linkage = linkage(clean_matrix, method="average", metric="euclidean")
        row_order = leaves_list(row_linkage).tolist()
        rows_clustered = True
        row_dendro = _dendrogram_payload(row_linkage)
        assert row_dendro["leaves"] == row_order, (
            "row dendrogram leaves do not match leaves_list(row_linkage); "
            "the dendrogram would no longer align with the heat map"
        )
    else:
        row_order = list(range(n_rows))
        rows_clustered = False
        row_dendro = None

    # ---- Cluster columns ------------------------------------------------
    if n_cols >= 2:
        col_linkage = linkage(clean_matrix.T, method="average", metric="euclidean")
        column_order = leaves_list(col_linkage).tolist()
        cols_clustered = True
        col_dendro = _dendrogram_payload(col_linkage)
        assert col_dendro["leaves"] == column_order, (
            "column dendrogram leaves do not match leaves_list(col_linkage); "
            "the dendrogram would no longer align with the heat map"
        )
    else:
        column_order = list(range(n_cols))
        cols_clustered = False
        col_dendro = None

    # ---- Reorder labels and values --------------------------------------
    reordered_matrix = original_matrix[np.ix_(row_order, column_order)]
    reordered_row_labels = [row_labels[i] for i in row_order]
    reordered_column_labels = [column_labels[j] for j in column_order]

    return {
        "row_labels": reordered_row_labels,
        "column_labels": reordered_column_labels,
        "values": _values_to_jsonable(reordered_matrix),
        "original_row_labels": list(row_labels),
        "original_column_labels": list(column_labels),
        "row_order": row_order,
        "column_order": column_order,
        "clustered": {"rows": rows_clustered, "columns": cols_clustered},
        "row_dendrogram": row_dendro,
        "column_dendrogram": col_dendro,
    }
