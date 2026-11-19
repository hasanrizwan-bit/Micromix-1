#--------------------------------
# Orthogroup expression table validation & summary
#--------------------------------
#
# Pure(-ish) validation helpers that operate on a pandas DataFrame produced from
# the uploaded expression TSV (orthogroup_expression_long.tsv). These functions
# never touch the database directly; they only inspect the parsed data plus a
# set of reference orthogroup_ids (loaded by the caller from the linked saved
# reference import). They either raise ExpressionValidationError for fatal
# problems or return a summary dictionary describing the expression table.
#
# Key concept: orthogroup_id remains the stable comparison unit. Every
# expression row is checked against the orthogroup_ids that exist in the
# selected reference import so we can report how many orthogroups / rows match
# and how many are unmatched. Unmatched rows are still stored (so nothing is
# silently dropped) but they are counted and surfaced to the user.

import pandas as pd

from .schema import (
    EXPRESSION_REQUIRED_COLUMNS,
    EXPRESSION_OPTIONAL_COLUMNS,
    EXPRESSION_COUNT_COLUMN,
)


class ExpressionValidationError(Exception):
    """Raised when the uploaded orthogroup expression table is invalid.

    The message is user-facing and is surfaced back to the frontend so the
    user understands why the import failed.
    """
    pass


#---
# FUNCTION: check_required_columns
# PURPOSE: Ensure every required column is present. Fails the import otherwise.
#          Required = orthogroup_id, strain, sample_id, count.
#---
def check_required_columns(df):
    present = set(df.columns)
    missing = [col for col in EXPRESSION_REQUIRED_COLUMNS if col not in present]
    if missing:
        raise ExpressionValidationError(
            "Missing required column(s): {}. Required columns are: {}.".format(
                ", ".join(missing), ", ".join(EXPRESSION_REQUIRED_COLUMNS)
            )
        )


#---
# FUNCTION: check_required_not_empty
# PURPOSE: Ensure orthogroup_id, strain, sample_id and count are not empty for
#          any row. Empty means NaN or a blank/whitespace-only string.
#---
def check_required_not_empty(df):
    for col in EXPRESSION_REQUIRED_COLUMNS:
        col_series = df[col]
        is_empty = col_series.isna() | (
            col_series.astype(str).str.strip() == ""
        )
        empty_count = int(is_empty.sum())
        if empty_count > 0:
            offending_rows = [int(i) + 1 for i in df.index[is_empty][:5].tolist()]
            raise ExpressionValidationError(
                "Column '{}' has {} empty value(s) (e.g. row(s): {}). "
                "orthogroup_id, strain, sample_id and count must not be "
                "empty.".format(
                    col, empty_count, ", ".join(str(r) for r in offending_rows)
                )
            )


#---
# FUNCTION: check_count_numeric
# PURPOSE: Ensure every value in the `count` column can be parsed as a number.
#          Fails the import (with the first few offending rows) otherwise.
#---
def check_count_numeric(df):
    numeric = pd.to_numeric(df[EXPRESSION_COUNT_COLUMN], errors="coerce")
    # A value is "unparseable" if it was non-empty originally but became NaN.
    original = df[EXPRESSION_COUNT_COLUMN]
    non_empty = original.notna() & (original.astype(str).str.strip() != "")
    bad_mask = non_empty & numeric.isna()
    bad_count = int(bad_mask.sum())
    if bad_count > 0:
        offending_rows = [int(i) + 1 for i in df.index[bad_mask][:5].tolist()]
        raise ExpressionValidationError(
            "Column 'count' has {} value(s) that are not numeric "
            "(e.g. row(s): {}). Every count must be parseable as a "
            "number.".format(
                bad_count, ", ".join(str(r) for r in offending_rows)
            )
        )


#---
# FUNCTION: find_missing_optional_columns
# PURPOSE: Report (but do not fail on) any optional columns that are absent.
#---
def find_missing_optional_columns(df):
    present = set(df.columns)
    return [col for col in EXPRESSION_OPTIONAL_COLUMNS if col not in present]


#---
# FUNCTION: count_duplicate_rows
# PURPOSE: Count duplicate expression rows. A duplicate is the same
#          (orthogroup_id, strain, seed_peg, sample_id) appearing more than
#          once. When seed_peg is absent, the key falls back to
#          (orthogroup_id, strain, sample_id) as required.
# RETURNS: the number of EXTRA rows beyond the first occurrence of each key
#          (i.e. total rows - unique keys among duplicated keys).
#---
def count_duplicate_rows(df):
    has_seed_peg = "seed_peg" in df.columns
    if has_seed_peg:
        key_cols = ["orthogroup_id", "strain", "seed_peg", "sample_id"]
    else:
        key_cols = ["orthogroup_id", "strain", "sample_id"]

    # keep=False marks every member of a duplicated key group as True; the
    # number of *extra* rows is total duplicated rows minus the unique keys.
    dup_mask = df.duplicated(subset=key_cols, keep=False)
    duplicated_rows = df[dup_mask]
    if len(duplicated_rows) == 0:
        return 0
    unique_dup_keys = duplicated_rows.drop_duplicates(subset=key_cols)
    return int(len(duplicated_rows) - len(unique_dup_keys))


#---
# FUNCTION: _unique_non_empty
# PURPOSE: Return a sorted list of unique, non-empty string values for a column
#          (or [] when the column is absent).
#---
def _unique_non_empty(df, col):
    if col not in df.columns:
        return []
    series = df[col].dropna().astype(str)
    series = series[series.str.strip() != ""]
    return sorted(series.unique().tolist())


#---
# FUNCTION: build_summary
# PURPOSE: Produce the summary dictionary shown in the frontend expression
#          summary panel. Assumes required columns exist and are non-empty and
#          that count is numeric (validated earlier).
# PARAMETERS:
#   df: validated expression DataFrame.
#   missing_optional_columns: list of absent optional columns.
#   reference_orthogroup_ids: set of orthogroup_ids present in the linked saved
#       reference import (used to compute matched / unmatched counts).
#   reference_import_id: the linked reference import id (echoed into summary).
#---
def build_summary(
    df, missing_optional_columns, reference_orthogroup_ids, reference_import_id
):
    strain_names = _unique_non_empty(df, "strain")
    sample_names = _unique_non_empty(df, "sample_id")
    conditions = _unique_non_empty(df, "condition")
    replicates = _unique_non_empty(df, "replicate")

    # Normalise reference ids to strings for a like-for-like comparison.
    ref_ids = {str(x) for x in (reference_orthogroup_ids or set())}

    expr_ogs_series = df["orthogroup_id"].dropna().astype(str)
    expr_ogs_series = expr_ogs_series[expr_ogs_series.str.strip() != ""]
    expr_orthogroups = set(expr_ogs_series.unique().tolist())

    matched_orthogroups = expr_orthogroups & ref_ids
    unmatched_orthogroups = expr_orthogroups - ref_ids

    # Row-level unmatched count: rows whose orthogroup_id is not in the
    # reference set.
    if ref_ids:
        unmatched_row_mask = ~expr_ogs_series.isin(ref_ids)
        unmatched_row_count = int(unmatched_row_mask.sum())
    else:
        # No reference ids available: treat everything as unmatched but never
        # fail the import (rows are still stored).
        unmatched_row_count = int(len(expr_ogs_series))

    duplicate_row_count = count_duplicate_rows(df)

    summary = {
        "reference_import_id": reference_import_id,
        "total_expression_rows": int(len(df.index)),
        "total_orthogroups": len(expr_orthogroups),
        "total_strains": len(strain_names),
        "strain_names": strain_names,
        "total_samples": len(sample_names),
        "sample_names": sample_names,
        "conditions": conditions,
        "replicates": replicates,
        "matched_orthogroup_count": len(matched_orthogroups),
        "unmatched_orthogroup_count": len(unmatched_orthogroups),
        "unmatched_row_count": unmatched_row_count,
        "duplicate_row_count": duplicate_row_count,
        "missing_optional_columns": list(missing_optional_columns),
        # Whether duplicate detection used seed_peg in the key.
        "duplicate_key_includes_seed_peg": "seed_peg" in df.columns,
        # A sample of unmatched orthogroup ids to help the user diagnose
        # mismatches (capped so the summary stays small).
        "unmatched_orthogroup_sample": sorted(unmatched_orthogroups)[:25],
    }
    return summary


#---
# FUNCTION: validate
# PURPOSE: Run the full expression validation pipeline and return a summary.
#          Raises ExpressionValidationError for fatal problems.
# STEPS:
#   1. Check required columns exist (orthogroup_id, strain, sample_id, count).
#   2. Check required values not empty.
#   3. Check count is numeric.
#   4-8. Compute matched / unmatched orthogroups & rows, samples, conditions,
#        replicates.
#   9. Report missing optional columns (non-fatal).
#   10. Detect duplicate rows.
#   11. seed_peg optional (import allowed without it).
#---
def validate(df, reference_orthogroup_ids, reference_import_id):
    check_required_columns(df)
    check_required_not_empty(df)
    check_count_numeric(df)
    missing_optional_columns = find_missing_optional_columns(df)
    return build_summary(
        df,
        missing_optional_columns,
        reference_orthogroup_ids,
        reference_import_id,
    )
