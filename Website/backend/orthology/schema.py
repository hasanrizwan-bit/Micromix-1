#--------------------------------
# Orthogroup reference table schema
#--------------------------------
#
# Central place that describes the expected shape of the multi-strain
# orthogroup metadata TSV (orthogroup_metadata_merged.tsv). Keeping the column
# contract in one module makes validation, storage and the frontend summary
# consistent and easy to evolve as the multi-strain pipeline grows.

# The name of the MongoDB collection that stores one document per
# strain-specific gene belonging to one orthogroup.
COLLECTION_NAME = "orthogroup_references"

# The name of the MongoDB collection that stores ONE manifest document per
# import (filename, timestamp, summary, preview). This powers the
# "Saved reference tables" list and lets a prior import be re-opened without
# re-uploading the original file.
IMPORTS_COLLECTION_NAME = "orthogroup_reference_imports"

# Columns that MUST be present in the uploaded TSV. Without these the file
# cannot be interpreted as an orthogroup reference table and the import fails.
REQUIRED_COLUMNS = [
    "orthogroup_id",  # shared comparison unit across strains
    "strain",         # which strain this gene belongs to
    "seed_peg",       # strain-specific gene / locus identifier (seed peg)
]

# Columns that are nice to have but not required. Missing optional columns are
# reported back to the user but never cause the import to fail.
OPTIONAL_COLUMNS = [
    "locus_tag",
    "gene",
    "product",
    "contig",
    "start",
    "end",
    "strand",
    "protein_length",
    "copy_index",
    "copies_in_strain",
    "species_count",
    "gene_count",
    "alg_conn",
]

# All columns we know about (used to keep a stable column ordering when
# building the preview and when persisting documents).
KNOWN_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS

# Optional column that, when present, indicates how many copies of a gene a
# strain has inside a single orthogroup. Used to detect paralogs / co-orthologs.
COPIES_COLUMN = "copies_in_strain"


#--------------------------------
# Step 3: Orthogroup expression table schema
#--------------------------------
#
# The multi-strain pipeline can also produce a "long"/tidy expression table
# (orthogroup_expression_long.tsv) where each row is ONE measurement of ONE
# orthogroup, in ONE strain, for ONE sample. The comparison unit remains
# `orthogroup_id`; expression values are always linked back to a previously
# saved orthogroup reference import via its `reference_import_id`.

# One MongoDB document per expression measurement (member row of an
# expression upload).
EXPRESSION_COLLECTION_NAME = "orthogroup_expression"

# ONE manifest document per expression upload (display name, filename,
# timestamp, summary, preview, and the linked reference_import_id). This powers
# the "Saved expression imports" list scoped to a reference import.
EXPRESSION_IMPORTS_COLLECTION_NAME = "orthogroup_expression_sets"

# Columns that MUST be present in the uploaded expression TSV. Without these the
# file cannot be interpreted as an orthogroup expression table and the import
# fails. seed_peg is strongly preferred (used for duplicate detection) but NOT
# required: import is still allowed using orthogroup_id + strain + sample_id +
# count only.
EXPRESSION_REQUIRED_COLUMNS = [
    "orthogroup_id",  # shared comparison unit across strains (links to reference)
    "strain",         # which strain this measurement belongs to
    "sample_id",      # the sample / column this measurement came from
    "count",          # the numeric expression value
]

# Columns that are nice to have but not required. Missing optional columns are
# reported back to the user but never cause the import to fail.
EXPRESSION_OPTIONAL_COLUMNS = [
    "seed_peg",       # strongly preferred: used for duplicate-row detection
    "condition",      # strongly preferred: experimental condition
    "replicate",      # strongly preferred: replicate identifier
    "copy_index",
    "copies_in_strain",
    "species_count",
    "gene_count",
    "alg_conn",
    "gene",
    "product",
    "contig",
    "start",
    "end",
    "strand",
    "protein_length",
]

# All expression columns we know about (used to keep a stable column ordering
# when building the preview and when persisting documents).
EXPRESSION_KNOWN_COLUMNS = EXPRESSION_REQUIRED_COLUMNS + EXPRESSION_OPTIONAL_COLUMNS

# The numeric expression column.
EXPRESSION_COUNT_COLUMN = "count"
