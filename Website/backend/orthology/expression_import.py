#--------------------------------
# Orthogroup expression table import entry point
#--------------------------------
#
# Orchestrates the full import of a "long"/tidy expression table
# (orthogroup_expression_long.tsv) that is linked to a previously saved
# orthogroup reference import:
#   1. Confirm the linked reference import exists and load its orthogroup_ids.
#   2. Parse the uploaded source into a DataFrame.
#   3. Validate it (required columns, non-empty required values, numeric count)
#      and compute a summary (matched / unmatched orthogroups & rows, samples,
#      conditions, replicates, duplicates, missing optional columns).
#   4. Store one document per measurement in `orthogroup_expression`, each
#      linked to the reference_import_id, plus a manifest document in
#      `orthogroup_expression_sets`.
#   5. Build a small preview of the imported rows.
#
# This is the only function app.py needs to call for an expression upload. It
# reuses the shared TSV parser from parse.py (expression tables are also
# tab-separated and must not rewrite '.' -> '_'), keeping all expression logic
# inside the orthology package.

import math

import numpy as np

from .parse import read_orthogroup_table
from .expression_validation import validate, ExpressionValidationError
from .storage import (
    store_expression_import,
    get_reference_orthogroup_ids,
)
from .schema import EXPRESSION_KNOWN_COLUMNS


# How many rows to include in the preview persisted with the manifest.
PREVIEW_ROW_LIMIT = 25

# The columns shown, in order, in the expression preview table.
PREVIEW_COLUMNS = [
    "orthogroup_id",
    "strain",
    "seed_peg",
    "sample_id",
    "condition",
    "replicate",
    "count",
    "gene",
    "product",
]


#---
# FUNCTION: ExpressionReferenceError
# PURPOSE: Raised when the linked reference import cannot be found. Surfaced as
#          a user-actionable error (the user must open a saved reference first).
#---
class ExpressionReferenceError(Exception):
    pass


#---
# FUNCTION: _jsonify_value
# PURPOSE: Make a single cell value safe for JSON serialization in the preview.
#---
def _jsonify_value(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        if isinstance(value, (np.floating,)) and np.isnan(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


#---
# FUNCTION: build_preview
# PURPOSE: Build a small, ordered preview (columns + rows) of the imported
#          expression table for display in the frontend preview table. Only the
#          standard expression preview columns that are present are included.
#---
def build_preview(df):
    columns = [c for c in PREVIEW_COLUMNS if c in df.columns]

    preview_df = df.head(PREVIEW_ROW_LIMIT)
    rows = []
    for _, row in preview_df.iterrows():
        rows.append({col: _jsonify_value(row[col]) for col in columns})

    return {"columns": columns, "rows": rows}


#---
# FUNCTION: import_expression_reference
# PURPOSE: Full import pipeline for a multi-strain orthogroup expression table
#          linked to a saved reference import.
# PARAMETERS:
#   db: MongoDB database handle (client.micromix).
#   reference_import_id: the saved reference import this expression set links to.
#   source: uploaded file object, static path string, or pasted text.
#   extension: file extension (".tsv", ".txt", ".csv", ".xlsx") or "string".
#   filename: original uploaded filename (recorded for the saved-imports list).
#   display_name: optional human-friendly name (defaults to filename).
# RETURNS: dict with keys:
#   { "expression_set_id", "reference_import_id", "inserted_count",
#     "summary", "preview" }
# RAISES:
#   ExpressionReferenceError when the linked reference import does not exist.
#   ExpressionValidationError for invalid data (caller maps to an error
#     response). Other exceptions bubble up for generic error handling.
#---
def import_expression_reference(
    db, reference_import_id, source, extension, filename=None, display_name=None
):
    # 1. Confirm the linked reference import exists and load its orthogroup_ids.
    reference_orthogroup_ids = get_reference_orthogroup_ids(
        db, reference_import_id
    )
    if reference_orthogroup_ids is None:
        raise ExpressionReferenceError(
            "No saved orthogroup reference import found with id {}. Open a "
            "saved reference table before importing expression data.".format(
                reference_import_id
            )
        )

    # 2. Parse
    df = read_orthogroup_table(source, extension)

    if df is None or len(df.columns) == 0:
        raise ExpressionValidationError(
            "The uploaded file could not be read or contained no columns."
        )

    # 3. Validate + summarise (raises ExpressionValidationError on fatal issues).
    #    Matching against the reference orthogroup_ids happens here.
    summary = validate(df, reference_orthogroup_ids, reference_import_id)

    # 4. Preview (built before storage so it can be persisted in the manifest).
    preview = build_preview(df)

    # 5. Store one document per measurement + a manifest document so the import
    #    can be re-opened later without re-uploading the file.
    expression_set_id, inserted_count = store_expression_import(
        db,
        df,
        reference_import_id,
        filename=filename,
        display_name=display_name,
        summary=summary,
        preview=preview,
    )

    return {
        "expression_set_id": expression_set_id,
        "reference_import_id": reference_import_id,
        "inserted_count": inserted_count,
        "summary": summary,
        "preview": preview,
    }
