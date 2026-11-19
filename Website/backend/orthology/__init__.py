#--------------------------------
# Multi-strain orthology module
#--------------------------------
#
# This package groups together all backend logic related to the multi-strain
# orthogroup reference/mapping table. It is deliberately kept separate from the
# existing single-dataset upload / visualization workflow (process_file.py,
# filter_dataframe.py, visualize.py, ...) so that multi-strain work can evolve
# independently without touching the core pipeline.
#
# Scope for this first step:
#   - Parse and validate an orthogroup metadata TSV
#     (orthogroup_metadata_merged.tsv produced by an external Proteinortho/PoFF
#     pipeline).
#   - Store each strain-specific gene as one row/document in the
#     `orthogroup_references` MongoDB collection.
#   - Produce a summary of the imported table (counts, strains, paralogs,
#     missing optional columns) plus a small preview of imported rows.
#
# Also in scope (Step 3):
#   - Expression data import (orthogroup_expression_long.tsv) linked to a saved
#     orthogroup reference import via reference_import_id. Stored in the
#     `orthogroup_expression` collection with a manifest in
#     `orthogroup_expression_sets`. See expression_import.py / storage.py.
#
# Also in scope (Step 4):
#   - Building an analysis-ready orthogroup-by-sample expression matrix from the
#     stored long-form rows, with filtering, value transformations (raw /
#     log2(count+1) / CPM / log2(CPM+1)), replicate aggregation, paralog and
#     duplicate handling, missing-value control, pagination and TSV/CSV export.
#     See expression_matrix.py.
#
# Out of scope (intentionally NOT implemented here):
#   - Heatmap / PCoA / line plot / differential-expression visualizations
#     (they will consume the Step 4 matrix).
#   - Running Proteinortho/PoFF inside Micromix.
#
# The public entry points are `import_orthogroup_reference` in
# orthology.import_orthogroups and `import_expression_reference` in
# orthology.expression_import.

from .import_orthogroups import import_orthogroup_reference
from .expression_import import (
    import_expression_reference,
    ExpressionReferenceError,
)
from .storage import (
    list_orthogroup_imports,
    get_orthogroup_import,
    delete_orthogroup_import,
    get_reference_strains,
    get_reference_preview,
    list_expression_imports,
    get_expression_import,
    get_expression_preview,
    delete_expression_import,
)
# Step 4: expression matrix building (long rows -> orthogroup x sample matrix).
from .expression_matrix import (
    build_matrix,
    build_matrix_export,
    ensure_expression_indexes,
    MatrixOptions,
    ExpressionMatrixError,
)

__all__ = [
    "import_orthogroup_reference",
    "list_orthogroup_imports",
    "get_orthogroup_import",
    "delete_orthogroup_import",
    "get_reference_strains",
    "get_reference_preview",
    # Step 3: expression imports
    "import_expression_reference",
    "ExpressionReferenceError",
    "list_expression_imports",
    "get_expression_import",
    "get_expression_preview",
    "delete_expression_import",
    # Step 4: expression matrix building
    "build_matrix",
    "build_matrix_export",
    "ensure_expression_indexes",
    "MatrixOptions",
    "ExpressionMatrixError",
]
