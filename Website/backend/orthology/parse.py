#--------------------------------
# Orthogroup reference table parsing
#--------------------------------
#
# Turns an uploaded source (file object, pasted text, or a path to a static
# file) into a pandas DataFrame. This is intentionally separate from
# process_file.convert_to_df because the orthogroup table has different needs:
#   - It is always tab-separated (a TSV from the multi-strain pipeline).
#   - Column names and cell values (locus tags, seed pegs like "peg.123") may
#     legitimately contain dots, so we must NOT rewrite '.' -> '_' the way the
#     single-dataset workflow does.

import pandas as pd
from io import StringIO


#---
# FUNCTION: read_orthogroup_table
# PURPOSE: Read the orthogroup metadata TSV into a DataFrame.
# PARAMETERS:
#   source: one of
#     - a werkzeug FileStorage object (uploaded file),
#     - a str path to a file on disk (e.g. "static/..."),
#     - raw pasted text (when extension == "string").
#   extension: file extension including the dot (e.g. ".tsv", ".txt", ".csv",
#     ".xlsx") or the literal "string" for pasted text.
# RETURNS: A pandas DataFrame with columns and values preserved as-is (aside
#          from stripping surrounding whitespace from column names).
#---
def read_orthogroup_table(source, extension):
    ext = (extension or "").lower()

    if ext == ".xlsx":
        df = pd.read_excel(source, dtype=str)
    elif ext == ".csv":
        # Some pipelines export CSV; default to comma but tolerate bad lines.
        df = pd.read_csv(source, sep=",", dtype=str, on_bad_lines="skip")
    elif ext in (".tsv", ".txt"):
        df = pd.read_csv(source, sep="\t", dtype=str, on_bad_lines="skip")
    elif ext == "string":
        df = pd.read_csv(StringIO(source), sep="\t", dtype=str, on_bad_lines="skip")
    else:
        raise ValueError(
            "Unsupported file type '{}'. Please upload a .tsv, .txt, .csv or "
            ".xlsx orthogroup metadata file.".format(extension)
        )

    # Normalise column names (strip whitespace) but keep dots intact.
    df.columns = [str(c).strip() for c in df.columns]

    return df
