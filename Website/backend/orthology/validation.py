#--------------------------------
# Orthogroup reference table validation & summary
#--------------------------------
#
# Pure(-ish) validation helpers that operate on a pandas DataFrame produced
# from the uploaded orthogroup metadata TSV. These functions never touch the
# database; they only inspect the data and either raise OrthogroupValidationError
# for fatal problems or return a summary dictionary describing the table.

import pandas as pd

from .schema import (
    REQUIRED_COLUMNS,
    OPTIONAL_COLUMNS,
    COPIES_COLUMN,
)


class OrthogroupValidationError(Exception):
    """Raised when the uploaded orthogroup reference table is invalid.

    The message is user-facing and is surfaced back to the frontend so the
    user understands why the import failed.
    """
    pass


#---
# FUNCTION: check_required_columns
# PURPOSE: Ensure every required column is present. Fails the import otherwise.
#---
def check_required_columns(df):
    present = set(df.columns)
    missing = [col for col in REQUIRED_COLUMNS if col not in present]
    if missing:
        raise OrthogroupValidationError(
            "Missing required column(s): {}. Required columns are: {}.".format(
                ", ".join(missing), ", ".join(REQUIRED_COLUMNS)
            )
        )


#---
# FUNCTION: check_required_not_empty
# PURPOSE: Ensure orthogroup_id, strain and seed_peg are not empty for any row.
#          Empty means NaN or a blank/whitespace-only string.
#---
def check_required_not_empty(df):
    for col in REQUIRED_COLUMNS:
        # Treat NaN and blank strings as empty.
        col_series = df[col]
        is_empty = col_series.isna() | (
            col_series.astype(str).str.strip() == ""
        )
        empty_count = int(is_empty.sum())
        if empty_count > 0:
            # Report the first few offending (1-based) row numbers to help the user.
            offending_rows = [int(i) + 1 for i in df.index[is_empty][:5].tolist()]
            raise OrthogroupValidationError(
                "Column '{}' has {} empty value(s) (e.g. row(s): {}). "
                "orthogroup_id, strain and seed_peg must not be empty.".format(
                    col, empty_count, ", ".join(str(r) for r in offending_rows)
                )
            )


#---
# FUNCTION: find_missing_optional_columns
# PURPOSE: Report (but do not fail on) any optional columns that are absent.
#---
def find_missing_optional_columns(df):
    present = set(df.columns)
    return [col for col in OPTIONAL_COLUMNS if col not in present]


#---
# FUNCTION: count_orthogroups_in_all_strains
# PURPOSE: Count orthogroups that have at least one member in every strain.
#---
def count_orthogroups_in_all_strains(df):
    total_strains = df["strain"].nunique()
    if total_strains == 0:
        return 0
    # For each orthogroup, count how many distinct strains it appears in.
    strains_per_og = df.groupby("orthogroup_id")["strain"].nunique()
    return int((strains_per_og == total_strains).sum())


#---
# FUNCTION: count_orthogroups_with_paralogs
# PURPOSE: Count orthogroups that have more than one gene in the same strain
#          (paralogs / co-orthologs).
#          Uses `copies_in_strain` when available (any value > 1 counts),
#          otherwise falls back to counting duplicate (orthogroup_id, strain)
#          pairs in the table itself.
#---
def count_orthogroups_with_paralogs(df):
    if COPIES_COLUMN in df.columns:
        copies = pd.to_numeric(df[COPIES_COLUMN], errors="coerce")
        mask = copies > 1
        if mask.any():
            return int(df.loc[mask, "orthogroup_id"].nunique())
        # If the column exists but has no usable (>1) values, fall through to
        # the structural count below so we still detect obvious paralogs.

    # Fallback: an orthogroup has paralogs if some (orthogroup_id, strain)
    # combination occurs more than once in the table.
    members_per_og_strain = df.groupby(["orthogroup_id", "strain"]).size()
    paralog_pairs = members_per_og_strain[members_per_og_strain > 1]
    if len(paralog_pairs) == 0:
        return 0
    orthogroups_with_paralogs = {og for (og, _strain) in paralog_pairs.index}
    return len(orthogroups_with_paralogs)


#---
# FUNCTION: build_summary
# PURPOSE: Produce the summary dictionary shown in the frontend summary panel.
#          Assumes required columns exist and are non-empty (validated earlier).
#---
def build_summary(df, missing_optional_columns):
    strain_names = sorted(df["strain"].astype(str).unique().tolist())
    summary = {
        "total_orthogroups": int(df["orthogroup_id"].nunique()),
        "total_strains": int(df["strain"].nunique()),
        "strain_names": strain_names,
        "total_member_rows": int(len(df.index)),
        "orthogroups_in_all_strains": count_orthogroups_in_all_strains(df),
        "orthogroups_with_paralogs": count_orthogroups_with_paralogs(df),
        "missing_optional_columns": list(missing_optional_columns),
        # Indicates whether paralog detection relied on the copies_in_strain
        # column or on structural duplicate detection.
        "paralog_detection_source": (
            COPIES_COLUMN if COPIES_COLUMN in df.columns else "row_counts"
        ),
    }
    return summary


#---
# FUNCTION: validate
# PURPOSE: Run the full validation pipeline and return a summary dictionary.
#          Raises OrthogroupValidationError for fatal problems.
# STEPS:
#   1. Check required columns exist.
#   2. Check orthogroup_id / strain / seed_peg not empty.
#   3-7. Compute counts (orthogroups, strains, rows, in-all-strains, paralogs).
#   8. Report missing optional columns (non-fatal).
#---
def validate(df):
    check_required_columns(df)
    check_required_not_empty(df)
    missing_optional_columns = find_missing_optional_columns(df)
    return build_summary(df, missing_optional_columns)
