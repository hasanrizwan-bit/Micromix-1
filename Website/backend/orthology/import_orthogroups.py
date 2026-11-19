#--------------------------------
# Orthogroup reference table import entry point
#--------------------------------
#
# Orchestrates the full import of a multi-strain orthogroup reference table:
#   1. Parse the uploaded source into a DataFrame.
#   2. Validate it (required columns, non-empty required values) and compute a
#      summary (counts, strains, paralogs, missing optional columns).
#   3. Store one document per strain-specific gene in `orthogroup_references`.
#   4. Build a small preview of the imported rows.
#
# This is the only function app.py needs to call. It is deliberately decoupled
# from the single-dataset upload path in process_file.py.

import math

import numpy as np

from .parse import read_orthogroup_table
from .validation import validate, OrthogroupValidationError
from .storage import store_orthogroup_reference
from .schema import KNOWN_COLUMNS


# How many rows to include in the preview returned to the frontend.
PREVIEW_ROW_LIMIT = 25


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
#          table for display in the frontend preview table.
#---
def build_preview(df):
    ordered_columns = [c for c in KNOWN_COLUMNS if c in df.columns]
    extra_columns = [c for c in df.columns if c not in KNOWN_COLUMNS]
    columns = ordered_columns + extra_columns

    preview_df = df.head(PREVIEW_ROW_LIMIT)
    rows = []
    for _, row in preview_df.iterrows():
        rows.append({col: _jsonify_value(row[col]) for col in columns})

    return {"columns": columns, "rows": rows}


#---
# FUNCTION: import_orthogroup_reference
# PURPOSE: Full import pipeline for the multi-strain orthogroup reference table.
# PARAMETERS:
#   db: MongoDB database handle (client.micromix).
#   source: uploaded file object, static path string, or pasted text.
#   extension: file extension (".tsv", ".txt", ".csv", ".xlsx") or "string".
#   filename: original uploaded filename (recorded for the saved-imports list).
# RETURNS: dict with keys:
#   { "import_id", "inserted_count", "summary", "preview" }
# RAISES: OrthogroupValidationError for invalid data (caller maps to an error
#         response). Other exceptions bubble up for generic error handling.
#---
def import_orthogroup_reference(db, source, extension, filename=None):
    # 1. Parse
    df = read_orthogroup_table(source, extension)

    if df is None or len(df.columns) == 0:
        raise OrthogroupValidationError(
            "The uploaded file could not be read or contained no columns."
        )

    # 2. Validate + summarise (raises OrthogroupValidationError on fatal issues)
    summary = validate(df)

    # 3. Preview (built before storage so it can be persisted in the manifest)
    preview = build_preview(df)

    # 4. Store one document per strain-specific gene + a manifest document
    #    (filename, timestamp, summary, preview) so the import can be re-opened
    #    later without re-uploading the file.
    import_id, inserted_count = store_orthogroup_reference(
        db, df, filename=filename, summary=summary, preview=preview
    )

    return {
        "import_id": import_id,
        "inserted_count": inserted_count,
        "summary": summary,
        "preview": preview,
    }
