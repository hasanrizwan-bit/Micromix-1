"""matrix_selection.py — the row-axis counterpart to `/sample_selection`.

This module is intentionally Flask-free (mirrors `pcoa/service.py`'s style) so
its core function, `select_matrix()`, can be unit tested directly against
plain pandas DataFrames without needing a running Flask app or a MongoDB
connection.

Background / why this exists
-----------------------------
Micromix already has `POST /sample_selection` (see `app.py`), which subsets
the *columns* (samples) of the current working matrix by an explicit id list.
That is exactly the mechanism PCoA's "Use Selected Samples" button drives.
There was previously no equivalent for the *rows* (genes/orthogroups) axis —
which the Clustered Heatmap visualization needs, since a heatmap selection is
naturally row-based, column-based, or both (an intersection of the two).

Rather than duplicating (or risking a regression in) the already-working
`/sample_selection` route, this module provides a single, general
`select_matrix(df, row_ids, sample_ids)` primitive that can filter by row id,
sample id, or both at once, and the new `POST /matrix_selection` route in
`app.py` is a thin wrapper around it (see that route's docstring for the full
request/response contract). `/sample_selection` itself is untouched.

Identity rules (see also `frontend/src/lib/matrix.js` and
`frontend/src/lib/heatmapSelection.js`, which mirror these rules client-side):
  - A ROW is identified by the string value of the first column of the
    dataframe (`row_id_column`, defaulting to `df.columns[0]`) — this is the
    same convention `lib/matrix.js`'s `rowIdKey = Object.keys(record)[0]`
    already uses for display. It is *not* the row's positional index, so
    clustering/reordering upstream can never desync a selection.
  - A SAMPLE/COLUMN is identified by its exact column name, using the same
    `"(<matrix title>) <sample>"` convention already validated by
    `process_file.is_value_column()` and already used by `/sample_selection`.
"""

from __future__ import annotations

import pandas as pd

try:
    import process_file
except ImportError:  # pragma: no cover - defensive, mirrors process_file.py's own guard
    process_file = None


class MatrixSelectionError(Exception):
    """Raised for any user-fixable problem with a requested selection.

    Callers (the Flask route) are expected to catch this and turn it into a
    4xx JSON error response, exactly like `pcoa.PcoaInputError` is handled by
    the PCoA route.
    """


def _is_value_column(column_name):
    if process_file is not None:
        return process_file.is_value_column(column_name)
    # Fallback (kept in lock-step with process_file.is_value_column /
    # frontend lib/matrix.js's detectValueColumns), only used if process_file
    # could not be imported (e.g. a narrow unit-test environment).
    name = str(column_name)
    return name.startswith('(') and ') ' in name


def _format_id_list(ids, limit=10):
    shown = list(ids)[:limit]
    text = ", ".join(str(i) for i in shown)
    if len(ids) > limit:
        text += f", and {len(ids) - limit} more"
    return text


def select_matrix(df: pd.DataFrame, row_ids=None, sample_ids=None, row_id_column=None):
    """Subset ``df`` to ``row_ids`` and/or ``sample_ids``.

    Returns ``(working_df, meta)`` where ``meta`` is
    ``{"active_row_ids": [...] | None, "active_sample_ids": [...] | None,
    "row_id_column": str}``.

    - ``row_ids is None`` and ``sample_ids is None``: no-op, returns ``df``
      unchanged (this is the "restore"/"close without applying" case).
    - Only ``row_ids`` given: every currently-present sample column is kept
      (matches the task requirement "if only genes are selected, preserve all
      currently active samples").
    - Only ``sample_ids`` given: every row is kept (the column-only mirror of
      the above).
    - Both given: the result is the intersection (selected rows AND selected
      columns).

    ``df`` is never mutated — every returned frame is either ``df`` itself
    (the no-op case) or a fresh frame built via boolean/label indexing.

    Row order in the result always follows ``df``'s own original order, not
    the order ids were supplied in, so a selection is deterministic regardless
    of click order (mirrors `pcoa.subset_matrix`'s same guarantee for
    samples).
    """
    if row_ids is None and sample_ids is None:
        return df, {"active_row_ids": None, "active_sample_ids": None}

    working_df = df

    resolved_row_id_column = row_id_column or (df.columns[0] if len(df.columns) > 0 else None)
    active_row_ids = None
    active_sample_ids = None

    if row_ids is not None:
        if resolved_row_id_column is None:
            raise MatrixSelectionError(
                "The current dataset has no columns, so no row selection can be applied."
            )
        requested = [str(r) for r in row_ids]
        if not requested:
            raise MatrixSelectionError(
                "No rows were selected. Select at least one row before applying."
            )

        available = working_df[resolved_row_id_column].astype(str)
        available_set = set(available)
        unknown = []
        unknown_seen = set()
        for r in requested:
            if r not in available_set and r not in unknown_seen:
                unknown_seen.add(r)
                unknown.append(r)
        if unknown:
            raise MatrixSelectionError(
                f"The following selected row id(s) do not exist in the current "
                f"dataset: {_format_id_list(unknown)}"
            )

        # De-duplicate while preserving nothing selection-order-dependent —
        # membership is all that matters for a boolean mask.
        requested_set = set(requested)
        mask = available.isin(requested_set)
        working_df = working_df[mask]
        # Report the de-duplicated set actually applied, in the ORIGINAL
        # dataframe's row order (not the order ids were requested in).
        active_row_ids = [v for v in available[mask].tolist()]
        # Preserve first-occurrence order but drop exact duplicate raw ids
        # (e.g. two rows sharing an id both remain in working_df, but the
        # reported active_row_ids list stays de-duplicated for display).
        seen = set()
        deduped_active = []
        for rid in active_row_ids:
            if rid not in seen:
                seen.add(rid)
                deduped_active.append(rid)
        active_row_ids = deduped_active

    if sample_ids is not None:
        requested = [str(s) for s in sample_ids]
        if not requested:
            raise MatrixSelectionError(
                "No samples were selected. Select at least one sample column "
                "before applying."
            )

        value_columns = [c for c in working_df.columns if _is_value_column(c)]
        meta_columns = [c for c in working_df.columns if c not in value_columns]
        value_column_set = set(value_columns)

        unknown = [s for s in requested if s not in value_column_set]
        if unknown:
            raise MatrixSelectionError(
                "The following selected sample column(s) do not exist in the "
                f"current dataset: {_format_id_list(unknown)}"
            )

        selected_set = set(requested)
        keep_columns = [c for c in working_df.columns if c in meta_columns or c in selected_set]
        working_df = working_df[keep_columns]
        active_sample_ids = [c for c in value_columns if c in selected_set]

    return working_df, {
        "active_row_ids": active_row_ids,
        "active_sample_ids": active_sample_ids,
        "row_id_column": resolved_row_id_column,
    }
