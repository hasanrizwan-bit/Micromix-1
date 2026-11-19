#--------------------------------
# Step 4: Orthogroup expression matrix builder
#--------------------------------
#
# Turns the stored long-form expression rows (one document per measurement in
# the `orthogroup_expression` collection) into an analysis-ready cross-strain
# matrix:
#
#     rows    = orthogroup_id
#     columns = sample_id
#     values  = expression count (raw / transformed)
#
# The heavy lifting is done with pandas on the (filtered) rows loaded from
# MongoDB. Everything here is deliberately kept inside the orthology package so
# multi-strain work stays isolated from the single-dataset pipeline.
#
# Key design points:
#   * orthogroup_id is always the stable comparison unit.
#   * Missing measurements stay NULL internally (never silently coerced to 0);
#     the caller chooses how to *display* them (blank vs zero).
#   * CPM is computed independently per sample column (before any replicate
#     aggregation) against that sample's own total.
#   * Replicates are separate by default; optional mean/median aggregation
#     groups the sample columns by (strain, condition).
#   * Multiple genes of the same strain inside one orthogroup (paralogs /
#     co-orthologs) are collapsed with a selectable rule (sum/mean/max/keep).
#   * Duplicate measurement keys are detected before pivoting and collapsed
#     with a required rule (sum/mean/first).
#   * A rich summary is returned describing every setting and derived stat.
#
# Nothing here builds a heatmap / PCoA / DE analysis; it only produces the
# reusable matrix + summary that those future visualizations will consume.

import io
import math

import numpy as np
import pandas as pd

from .schema import (
    EXPRESSION_COLLECTION_NAME,
    EXPRESSION_IMPORTS_COLLECTION_NAME,
    IMPORTS_COLLECTION_NAME,
)


#--------------------------------
# Allowed option values (validated so bad input fails fast and clearly).
#--------------------------------

# Selectable value transformations applied to the count matrix.
TRANSFORMATIONS = ("raw", "log2_count", "cpm", "log2_cpm")

# Optional replicate aggregation rules (group by strain + condition).
REPLICATE_AGGREGATIONS = ("none", "mean", "median")

# Paralog / co-ortholog collapse rule (multiple genes of one strain in one
# orthogroup, for a single sample).
PARALOG_RULES = ("sum", "mean", "max", "keep_separate")

# Duplicate measurement-key resolution rule.
DUPLICATE_RULES = ("sum", "mean", "first")

# Missing-value *display* options (internal representation is always null).
MISSING_DISPLAYS = ("blank", "zero")

# Human-readable labels for the transformation, used in the summary + UI.
TRANSFORMATION_LABELS = {
    "raw": "Raw counts",
    "log2_count": "log2(count + 1)",
    "cpm": "CPM",
    "log2_cpm": "log2(CPM + 1)",
}

# Separator used to build an aggregated column label, e.g.
# "Pa.B12 | low density | mean".
AGG_LABEL_SEP = " | "

# Default rows-per-page for the matrix preview (matrix rows = orthogroups).
DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 500

# Metadata columns kept alongside the numeric matrix, in a stable order.
METADATA_COLUMNS = [
    "orthogroup_id",
    "gene",
    "product",
    "strains",
    "seed_pegs",
    "gene_count",
]


class ExpressionMatrixError(Exception):
    """Raised for user-actionable problems while building a matrix.

    Examples: unknown expression set, missing linked reference import,
    unresolved duplicate keys, an unknown option value, or an empty selection
    that yields no data. The message is user-facing.
    """
    pass


#---
# FUNCTION: _to_number
# PURPOSE: Best-effort convert a stored (string) count into a float, returning
#          NaN when it cannot be parsed. Counts were stored as strings during
#          import, so numeric coercion is needed before any maths.
#---
def _to_number(value):
    if value is None:
        return np.nan
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return np.nan
        return float(value)
    text = str(value).strip()
    if text == "":
        return np.nan
    try:
        return float(text)
    except (TypeError, ValueError):
        return np.nan


#---
# FUNCTION: _clean_str
# PURPOSE: Normalise a raw cell into a clean string or None (NaN / blank -> None).
#---
def _clean_str(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    if text == "":
        return None
    return text


#---
# FUNCTION: _normalise_option
# PURPOSE: Validate a single option value against its allowed set (raising a
#          clear ExpressionMatrixError otherwise) and return it. `None`/empty
#          falls back to `default`.
#---
def _normalise_option(name, value, allowed, default):
    if value is None or value == "":
        return default
    value = str(value)
    if value not in allowed:
        raise ExpressionMatrixError(
            "Invalid {} '{}'. Allowed values: {}.".format(
                name, value, ", ".join(allowed)
            )
        )
    return value


#---
# FUNCTION: _as_str_list
# PURPOSE: Coerce a filter argument into a list of non-empty strings. Accepts a
#          list/tuple or a single scalar; None -> [].
#---
def _as_str_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        items = [value]
    out = []
    for item in items:
        s = _clean_str(item)
        if s is not None:
            out.append(s)
    return out


#--------------------------------
# Options container
#--------------------------------
class MatrixOptions:
    """Validated bundle of the matrix-building settings requested by the user."""

    def __init__(
        self,
        strains=None,
        samples=None,
        conditions=None,
        replicates=None,
        orthogroup_ids=None,
        search=None,
        transformation="raw",
        replicate_aggregation="none",
        paralog_rule="sum",
        duplicate_rule="sum",
        missing_display="blank",
    ):
        self.strains = _as_str_list(strains)
        self.samples = _as_str_list(samples)
        self.conditions = _as_str_list(conditions)
        self.replicates = _as_str_list(replicates)
        self.orthogroup_ids = _as_str_list(orthogroup_ids)
        self.search = _clean_str(search)

        self.transformation = _normalise_option(
            "transformation", transformation, TRANSFORMATIONS, "raw"
        )
        self.replicate_aggregation = _normalise_option(
            "replicate_aggregation",
            replicate_aggregation,
            REPLICATE_AGGREGATIONS,
            "none",
        )
        self.paralog_rule = _normalise_option(
            "paralog_rule", paralog_rule, PARALOG_RULES, "sum"
        )
        self.duplicate_rule = _normalise_option(
            "duplicate_rule", duplicate_rule, DUPLICATE_RULES, "sum"
        )
        self.missing_display = _normalise_option(
            "missing_display", missing_display, MISSING_DISPLAYS, "blank"
        )

    @classmethod
    def from_payload(cls, payload):
        payload = payload or {}
        return cls(
            strains=payload.get("strains"),
            samples=payload.get("samples"),
            conditions=payload.get("conditions"),
            replicates=payload.get("replicates"),
            orthogroup_ids=payload.get("orthogroup_ids"),
            search=payload.get("search"),
            transformation=payload.get("transformation"),
            replicate_aggregation=payload.get("replicate_aggregation"),
            paralog_rule=payload.get("paralog_rule"),
            duplicate_rule=payload.get("duplicate_rule"),
            missing_display=payload.get("missing_display"),
        )


#---
# FUNCTION: _build_query
# PURPOSE: Build the MongoDB query used to load the (filtered) expression rows
#          for one expression set. Strain/sample/condition/replicate/orthogroup
#          filters map directly to $in clauses; the free-text search is applied
#          in pandas afterwards (spans several columns / is case-insensitive).
#---
def _build_query(expression_set_id, options):
    query = {"expression_set_id": expression_set_id}
    if options.strains:
        query["strain"] = {"$in": options.strains}
    if options.samples:
        query["sample_id"] = {"$in": options.samples}
    if options.conditions:
        query["condition"] = {"$in": options.conditions}
    if options.replicates:
        query["replicate"] = {"$in": [str(r) for r in options.replicates]}
    if options.orthogroup_ids:
        query["orthogroup_id"] = {"$in": options.orthogroup_ids}
    return query


# Columns loaded from each expression document for matrix building.
_LOAD_COLUMNS = [
    "orthogroup_id",
    "strain",
    "sample_id",
    "condition",
    "replicate",
    "count",
    "seed_peg",
    "gene",
    "product",
]


#---
# FUNCTION: _load_rows
# PURPOSE: Load the filtered expression rows into a pandas DataFrame with the
#          columns required for matrix building. Applies the optional free-text
#          search across gene / product / seed_peg / orthogroup_id in pandas.
#---
def _load_rows(db, expression_set_id, options):
    collection = db[EXPRESSION_COLLECTION_NAME]
    query = _build_query(expression_set_id, options)

    projection = {"_id": 0}
    for col in _LOAD_COLUMNS:
        projection[col] = 1

    records = list(collection.find(query, projection))
    df = pd.DataFrame.from_records(records)

    # Guarantee all expected columns exist even when the collection omits some
    # optional fields, so downstream code can rely on them.
    for col in _LOAD_COLUMNS:
        if col not in df.columns:
            df[col] = None

    if df.empty:
        return df

    # Normalise identifier columns to clean strings.
    for col in ["orthogroup_id", "strain", "sample_id", "condition",
                "replicate", "seed_peg", "gene", "product"]:
        df[col] = df[col].map(_clean_str)

    # Numeric count column.
    df["count"] = df["count"].map(_to_number)

    # Optional free-text search across gene, product, seed_peg, orthogroup_id.
    if options.search:
        needle = options.search.lower()

        def _match(row):
            for col in ("gene", "product", "seed_peg", "orthogroup_id"):
                val = row.get(col)
                if val is not None and needle in str(val).lower():
                    return True
            return False

        mask = df.apply(_match, axis=1)
        df = df[mask].reset_index(drop=True)

    return df


#---
# FUNCTION: detect_duplicates
# PURPOSE: Detect duplicate measurement keys BEFORE matrix creation. A
#          duplicate is the same (orthogroup_id, strain, seed_peg, sample_id)
#          appearing more than once (seed_peg dropped from the key when the
#          column is entirely absent). Returns (duplicate_extra_count,
#          example_keys) where duplicate_extra_count is the number of rows
#          beyond the first occurrence of each duplicated key.
#---
def detect_duplicates(df):
    if df.empty:
        return 0, []

    has_seed_peg = df["seed_peg"].notna().any()
    if has_seed_peg:
        key_cols = ["orthogroup_id", "strain", "seed_peg", "sample_id"]
    else:
        key_cols = ["orthogroup_id", "strain", "sample_id"]

    dup_mask = df.duplicated(subset=key_cols, keep=False)
    if not dup_mask.any():
        return 0, []

    dup_rows = df[dup_mask]
    unique_keys = dup_rows.drop_duplicates(subset=key_cols)
    extra = int(len(dup_rows) - len(unique_keys))

    examples = []
    for _, row in unique_keys.head(10).iterrows():
        examples.append(
            {col: row[col] for col in key_cols}
        )
    return extra, examples


#---
# FUNCTION: _resolve_duplicates
# PURPOSE: Collapse duplicate measurement keys using the chosen rule so each
#          (orthogroup_id, strain, seed_peg, sample_id) appears once. Metadata
#          (gene / product / condition / replicate) is carried from the first
#          occurrence. Returns the de-duplicated DataFrame.
#---
def _resolve_duplicates(df, duplicate_rule):
    if df.empty:
        return df

    has_seed_peg = df["seed_peg"].notna().any()
    if has_seed_peg:
        key_cols = ["orthogroup_id", "strain", "seed_peg", "sample_id"]
    else:
        key_cols = ["orthogroup_id", "strain", "sample_id"]

    # Fill a stable placeholder for grouping so NaN keys group together rather
    # than being dropped by groupby.
    grp = df.copy()
    for col in key_cols:
        grp[col] = grp[col].fillna("\x00__na__")

    # Aggregate the numeric count per key using the chosen rule; carry the
    # first non-null metadata value for the descriptive columns.
    meta_cols = ["condition", "replicate", "gene", "product"]

    def _first_valid(series):
        for v in series:
            if v is not None and not (isinstance(v, float) and math.isnan(v)):
                return v
        return None

    agg = {"count": duplicate_rule if duplicate_rule != "first" else "first"}
    for col in meta_cols:
        agg[col] = _first_valid

    grouped = grp.groupby(key_cols, dropna=False, sort=False).agg(agg)
    grouped = grouped.reset_index()

    # Restore NaN placeholders.
    for col in key_cols:
        grouped[col] = grouped[col].replace("\x00__na__", np.nan)

    return grouped


#---
# FUNCTION: _sample_metadata
# PURPOSE: Build a mapping sample_id -> {condition, replicate} using the most
#          frequent (mode) value seen for each sample. Used to label / group
#          samples for replicate aggregation.
#---
def _sample_metadata(df):
    meta = {}
    for sample_id, group in df.groupby("sample_id", dropna=True, sort=True):
        condition = None
        replicate = None
        cond_vals = group["condition"].dropna()
        if not cond_vals.empty:
            condition = str(cond_vals.mode().iloc[0])
        rep_vals = group["replicate"].dropna()
        if not rep_vals.empty:
            replicate = str(rep_vals.mode().iloc[0])
        meta[sample_id] = {"condition": condition, "replicate": replicate}
    return meta


#---
# FUNCTION: _collapse_paralogs
# PURPOSE: Collapse multiple genes of the SAME strain within one orthogroup for
#          each sample using the chosen paralog rule. Operates on the long
#          (orthogroup_id, strain, sample_id) grouping of counts.
#
#          For sum/mean/max the strain's per-sample value is reduced to a single
#          number. For keep_separate no reduction happens: each seed_peg keeps
#          its own contribution, which for the matrix means the strain's genes
#          are simply summed into the orthogroup cell like any other measurement
#          (rows are already per-measurement); keep_separate therefore preserves
#          every individual measurement without collapsing, effectively summing
#          at the (orthogroup, sample) cell. To keep the matrix well-defined we
#          still sum keep_separate contributions into the cell but flag that no
#          paralog collapse was applied.
# RETURNS: DataFrame with columns [orthogroup_id, sample_id, value] giving the
#          per (orthogroup, sample) numeric value after strain-level collapse.
#---
def _collapse_paralogs(df, paralog_rule):
    # Step 1: reduce multiple genes of the same strain in the same orthogroup
    # for the same sample to a single per-strain value.
    strain_group_cols = ["orthogroup_id", "strain", "sample_id"]

    if paralog_rule == "keep_separate":
        # No strain-level reduction beyond summing identical measurements; every
        # gene contributes its own value which is then summed into the cell.
        strain_level = (
            df.groupby(strain_group_cols, dropna=False, sort=False)["count"]
            .sum(min_count=1)
            .reset_index()
        )
    elif paralog_rule == "sum":
        strain_level = (
            df.groupby(strain_group_cols, dropna=False, sort=False)["count"]
            .sum(min_count=1)
            .reset_index()
        )
    elif paralog_rule == "mean":
        strain_level = (
            df.groupby(strain_group_cols, dropna=False, sort=False)["count"]
            .mean()
            .reset_index()
        )
    elif paralog_rule == "max":
        strain_level = (
            df.groupby(strain_group_cols, dropna=False, sort=False)["count"]
            .max()
            .reset_index()
        )
    else:  # pragma: no cover - guarded by option validation
        raise ExpressionMatrixError(
            "Unknown paralog rule '{}'.".format(paralog_rule)
        )

    # Step 2: combine strains into the single (orthogroup, sample) cell. A cell
    # is the SUM of the per-strain values (each strain contributes one value).
    cell_level = (
        strain_level.groupby(["orthogroup_id", "sample_id"], dropna=False,
                             sort=False)["count"]
        .sum(min_count=1)
        .reset_index()
    )
    cell_level = cell_level.rename(columns={"count": "value"})
    return cell_level


#---
# FUNCTION: _apply_cpm
# PURPOSE: Convert a raw-count matrix (orthogroups x samples) to CPM,
#          independently per sample column:
#              CPM = count / (sum of counts in that sample) * 1e6
#          NaN cells stay NaN. Columns whose total is 0 (or all-NaN) yield NaN.
#---
def _apply_cpm(matrix):
    col_sums = matrix.sum(axis=0, skipna=True)
    cpm = matrix.copy()
    for col in matrix.columns:
        total = col_sums[col]
        if total and not math.isnan(total) and total != 0:
            cpm[col] = matrix[col] / total * 1_000_000.0
        else:
            cpm[col] = np.nan
    return cpm


#---
# FUNCTION: _apply_transformation
# PURPOSE: Apply the selected value transformation to a raw-count matrix.
#          raw        -> unchanged
#          log2_count -> log2(count + 1)
#          cpm        -> per-sample CPM
#          log2_cpm   -> log2(CPM + 1)
#          Missing (NaN) values are preserved as NaN.
# RETURNS: (transformed_matrix, cpm_column_totals_or_None). The CPM column
#          totals are returned for validation/reporting when a CPM-based
#          transform is used (each should be ~1,000,000).
#---
def _apply_transformation(matrix, transformation):
    if transformation == "raw":
        return matrix, None
    if transformation == "log2_count":
        return np.log2(matrix + 1.0), None
    if transformation == "cpm":
        cpm = _apply_cpm(matrix)
        return cpm, cpm.sum(axis=0, skipna=True)
    if transformation == "log2_cpm":
        cpm = _apply_cpm(matrix)
        totals = cpm.sum(axis=0, skipna=True)
        return np.log2(cpm + 1.0), totals
    # pragma: no cover - guarded by option validation
    raise ExpressionMatrixError(
        "Unknown transformation '{}'.".format(transformation)
    )


#---
# FUNCTION: _aggregate_replicates
# PURPOSE: Optionally aggregate replicate sample-columns into one column per
#          (strain, condition) using mean or median. The raw-count matrix is
#          aggregated BEFORE transformation so CPM totals stay meaningful.
#
#          A column belongs to a (strain, condition) group. Strain is derived
#          from the sample rows; condition from the sample metadata. Columns
#          that lack a condition are grouped under a "(no condition)" label so
#          they are never silently dropped.
# PARAMETERS:
#   matrix: raw-count matrix (orthogroups x sample_id columns).
#   sample_strain: dict sample_id -> strain (a sample belongs to one strain).
#   sample_meta:   dict sample_id -> {condition, replicate}.
#   rule: "mean" or "median".
# RETURNS: (aggregated_matrix, column_info) where column_info maps the NEW
#          column label -> {strain, condition, samples: [...]}.
#---
def _aggregate_replicates(matrix, sample_strain, sample_meta, rule):
    # Build the (strain, condition) -> [sample columns] grouping.
    groups = {}
    for sample_id in matrix.columns:
        strain = sample_strain.get(sample_id) or "(unknown strain)"
        condition = (sample_meta.get(sample_id) or {}).get("condition") \
            or "(no condition)"
        groups.setdefault((strain, condition), []).append(sample_id)

    new_columns = {}
    column_info = {}
    # Sort groups for a stable, readable column ordering.
    for (strain, condition) in sorted(groups.keys()):
        samples = groups[(strain, condition)]
        label = AGG_LABEL_SEP.join([strain, condition, rule])
        block = matrix[samples]
        if rule == "mean":
            new_columns[label] = block.mean(axis=1, skipna=True)
        elif rule == "median":
            new_columns[label] = block.median(axis=1, skipna=True)
        else:  # pragma: no cover
            raise ExpressionMatrixError(
                "Unknown replicate aggregation '{}'.".format(rule)
            )
        column_info[label] = {
            "strain": strain,
            "condition": condition,
            "rule": rule,
            "samples": list(samples),
        }

    aggregated = pd.DataFrame(new_columns, index=matrix.index)
    return aggregated, column_info


#---
# FUNCTION: _build_row_metadata
# PURPOSE: Build the per-orthogroup metadata rows kept alongside the matrix:
#          gene (first available), product (first available), strains
#          represented, strain-specific seed_pegs, and the number of genes
#          (measurement rows deduped by seed_peg per strain) contributing to
#          the orthogroup. Also derives multi-strain / paralog flags.
# RETURNS: (metadata_by_og, n_multi_strain, n_with_paralogs)
#---
def _build_row_metadata(df):
    metadata = {}
    n_multi_strain = 0
    n_with_paralogs = 0

    for og, group in df.groupby("orthogroup_id", dropna=True, sort=True):
        strains = sorted(
            {s for s in group["strain"].dropna().tolist()}
        )

        # Strain-specific seed_pegs: { strain: [sorted unique seed_pegs] }.
        seed_pegs = {}
        for strain, sgroup in group.groupby("strain", dropna=True, sort=True):
            pegs = sorted(
                {p for p in sgroup["seed_peg"].dropna().tolist()}
            )
            if pegs:
                seed_pegs[strain] = pegs

        # Number of distinct genes contributing: distinct (strain, seed_peg)
        # pairs when seed_peg is available, else distinct strains.
        if group["seed_peg"].notna().any():
            gene_pairs = group.dropna(subset=["seed_peg"]) \
                .drop_duplicates(subset=["strain", "seed_peg"])
            gene_count = int(len(gene_pairs))
            # A paralog/co-ortholog exists when a single strain contributes more
            # than one distinct seed_peg to this orthogroup.
            per_strain = gene_pairs.groupby("strain").size()
            has_paralog = bool((per_strain > 1).any())
        else:
            gene_count = len(strains)
            has_paralog = False

        gene = None
        gene_vals = group["gene"].dropna()
        if not gene_vals.empty:
            gene = str(gene_vals.iloc[0])
        product = None
        product_vals = group["product"].dropna()
        if not product_vals.empty:
            product = str(product_vals.iloc[0])

        if len(strains) > 1:
            n_multi_strain += 1
        if has_paralog:
            n_with_paralogs += 1

        metadata[og] = {
            "orthogroup_id": og,
            "gene": gene,
            "product": product,
            "strains": strains,
            "seed_pegs": seed_pegs,
            "gene_count": gene_count,
            "has_paralog": has_paralog,
            "multi_strain": len(strains) > 1,
        }

    return metadata, n_multi_strain, n_with_paralogs


#---
# FUNCTION: _cell_for_display
# PURPOSE: Convert a numeric matrix cell into a JSON-safe display value honoring
#          the missing-value display option. Internal NaN -> None ("blank") or
#          0 ("zero"). Real numbers are rounded to a sensible precision.
#---
def _cell_for_display(value, missing_display):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return 0 if missing_display == "zero" else None
    # Keep integers integral for readability; round floats.
    fval = float(value)
    if fval.is_integer():
        return int(fval)
    return round(fval, 4)


#---
# FUNCTION: build_matrix
# PURPOSE: The main entry point. Loads filtered expression rows for one
#          expression set, resolves duplicates, collapses paralogs, pivots to
#          an orthogroup x sample matrix, optionally aggregates replicates,
#          applies the value transformation, builds row metadata, and returns a
#          structured result. Pagination is applied to the matrix ROWS only.
# PARAMETERS:
#   db: MongoDB database handle.
#   expression_set_id: the saved expression import to read.
#   options: a MatrixOptions instance.
#   page / limit: 1-based row pagination for the returned matrix rows.
#   for_export: when True, ignore pagination and return every matrix row (used
#               by the TSV/CSV export path).
# RETURNS: dict {
#     summary, columns (sample/aggregated column labels), column_info,
#     metadata_columns, rows (list of {metadata..., values: {col: val}}),
#     page, limit, total_matrix_rows, matrix (only when for_export)
#   }
# RAISES: ExpressionMatrixError for unknown set/reference, unresolved
#         duplicates, or an empty selection.
#---
def build_matrix(db, expression_set_id, options, page=1, limit=DEFAULT_PAGE_LIMIT,
                 for_export=False):
    # 1. Confirm the expression set exists and its linked reference still does.
    manifest = db[EXPRESSION_IMPORTS_COLLECTION_NAME].find_one(
        {"expression_set_id": expression_set_id}
    )
    if manifest is None:
        raise ExpressionMatrixError(
            "No saved expression import found with id {}.".format(
                expression_set_id
            )
        )
    reference_import_id = manifest.get("reference_import_id")
    ref_manifest = db[IMPORTS_COLLECTION_NAME].find_one(
        {"import_id": reference_import_id}
    )
    if ref_manifest is None:
        raise ExpressionMatrixError(
            "The linked orthogroup reference import ({}) no longer exists. "
            "The expression set cannot be analysed without its reference."
            .format(reference_import_id)
        )

    # 2. Load filtered rows.
    df = _load_rows(db, expression_set_id, options)
    source_row_count = int(len(df.index))
    if df.empty:
        raise ExpressionMatrixError(
            "No expression rows match the selected filters. Adjust the "
            "strain / sample / condition / replicate / search selection."
        )

    # 3. Detect duplicate measurement keys BEFORE building the matrix.
    duplicate_extra, duplicate_examples = detect_duplicates(df)
    if duplicate_extra > 0:
        df = _resolve_duplicates(df, options.duplicate_rule)

    # 4. Build per-orthogroup metadata (before paralog collapse so seed_pegs /
    #    strains / paralog flags reflect the underlying genes).
    metadata, n_multi_strain, n_with_paralogs = _build_row_metadata(df)

    # 5. Collapse paralogs / co-orthologs into a per (orthogroup, sample) value.
    cell_level = _collapse_paralogs(df, options.paralog_rule)

    # 6. Pivot to the raw-count matrix (orthogroups x samples). Missing cells
    #    stay NaN (never silently 0).
    matrix = cell_level.pivot_table(
        index="orthogroup_id",
        columns="sample_id",
        values="value",
        aggfunc="sum",
        dropna=False,
    )
    # Stable ordering: orthogroups alphabetically, samples alphabetically.
    matrix = matrix.sort_index(axis=0).sort_index(axis=1)

    # Map sample_id -> strain (each sample belongs to one strain) for replicate
    # aggregation labelling.
    sample_strain = {}
    for sample_id, sgroup in df.groupby("sample_id", dropna=True):
        strain_vals = sgroup["strain"].dropna()
        if not strain_vals.empty:
            sample_strain[sample_id] = str(strain_vals.mode().iloc[0])
    sample_meta = _sample_metadata(df)

    # 7. Optional replicate aggregation (on raw counts, before transformation).
    column_info = None
    if options.replicate_aggregation != "none":
        matrix, column_info = _aggregate_replicates(
            matrix, sample_strain, sample_meta, options.replicate_aggregation
        )
        matrix = matrix.sort_index(axis=1)

    # 8. Missing-value count (before transformation, on the assembled matrix).
    missing_value_count = int(matrix.isna().sum().sum())

    # 9. Apply the value transformation.
    transformed, cpm_totals = _apply_transformation(
        matrix, options.transformation
    )

    columns = [str(c) for c in transformed.columns.tolist()]
    all_orthogroups = [str(og) for og in transformed.index.tolist()]
    total_matrix_rows = len(all_orthogroups)
    total_matrix_cols = len(columns)

    # 10. CPM per-column totals for validation/reporting (raw CPM, pre-log).
    cpm_column_totals = None
    if cpm_totals is not None:
        cpm_column_totals = {
            str(col): (None if math.isnan(float(val)) else round(float(val), 2))
            for col, val in cpm_totals.items()
        }

    # 11. Build the summary.
    summary = {
        "expression_set_id": expression_set_id,
        "reference_import_id": reference_import_id,
        "source_row_count": source_row_count,
        "matrix_row_count": total_matrix_rows,
        "matrix_column_count": total_matrix_cols,
        "selected_strains": options.strains,
        "selected_samples": options.samples,
        "selected_conditions": options.conditions,
        "selected_replicates": options.replicates,
        "selected_orthogroup_ids": options.orthogroup_ids,
        "search": options.search,
        "transformation": options.transformation,
        "transformation_label": TRANSFORMATION_LABELS.get(
            options.transformation, options.transformation
        ),
        "replicate_aggregation": options.replicate_aggregation,
        "paralog_rule": options.paralog_rule,
        "duplicate_rule": options.duplicate_rule,
        "missing_display": options.missing_display,
        "missing_value_count": missing_value_count,
        "duplicate_key_count": duplicate_extra,
        "duplicate_examples": duplicate_examples,
        "orthogroups_multi_strain": n_multi_strain,
        "orthogroups_with_paralogs": n_with_paralogs,
        "cpm_column_totals": cpm_column_totals,
    }

    # 12. Assemble the result. For export we keep the full transformed matrix;
    #     for preview we paginate the ROWS.
    result = {
        "summary": summary,
        "columns": columns,
        "column_info": column_info,
        "metadata_columns": list(METADATA_COLUMNS),
        "total_matrix_rows": total_matrix_rows,
        "total_matrix_columns": total_matrix_cols,
    }

    if for_export:
        result["matrix"] = transformed
        result["metadata"] = metadata
        result["ordered_orthogroups"] = all_orthogroups
        return result

    # Pagination over the matrix rows.
    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 1
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = DEFAULT_PAGE_LIMIT
    if page < 1:
        page = 1
    if limit < 1:
        limit = DEFAULT_PAGE_LIMIT
    if limit > MAX_PAGE_LIMIT:
        limit = MAX_PAGE_LIMIT

    start = (page - 1) * limit
    end = start + limit
    page_ogs = all_orthogroups[start:end]

    rows = []
    for og in page_ogs:
        meta = metadata.get(og, {"orthogroup_id": og})
        # Build the value dict for this row honoring missing display.
        row_series = transformed.loc[og]
        values = {}
        for col in columns:
            values[col] = _cell_for_display(
                row_series.get(col), options.missing_display
            )
        rows.append({
            "orthogroup_id": og,
            "gene": meta.get("gene"),
            "product": meta.get("product"),
            "strains": meta.get("strains", []),
            "seed_pegs": meta.get("seed_pegs", {}),
            "gene_count": meta.get("gene_count"),
            "has_paralog": meta.get("has_paralog", False),
            "multi_strain": meta.get("multi_strain", False),
            "values": values,
        })

    result["page"] = page
    result["limit"] = limit
    result["returned_rows"] = len(rows)
    result["rows"] = rows
    return result


#---
# FUNCTION: _seed_pegs_to_str
# PURPOSE: Flatten the strain-specific seed_pegs dict into a compact string for
#          the exported metadata column, e.g. "Pa.B12:peg.1,peg.2; Pa.PA14:peg.9".
#---
def _seed_pegs_to_str(seed_pegs):
    if not seed_pegs:
        return ""
    parts = []
    for strain in sorted(seed_pegs.keys()):
        pegs = seed_pegs[strain]
        parts.append("{}:{}".format(strain, ",".join(pegs)))
    return "; ".join(parts)


#---
# FUNCTION: build_matrix_export
# PURPOSE: Build the full (un-paginated) matrix and serialise it to TSV or CSV
#          text using the SAME settings as the preview, so exports contain the
#          same values as what the user sees. Metadata columns are emitted first
#          (orthogroup_id, gene, product, strains, seed_pegs, gene_count),
#          followed by every sample / aggregated column.
# PARAMETERS:
#   db, expression_set_id, options: as build_matrix.
#   file_format: "tsv" (default) or "csv".
# RETURNS: (text, summary) where text is the serialised matrix content.
#---
def build_matrix_export(db, expression_set_id, options, file_format="tsv"):
    file_format = (file_format or "tsv").lower()
    if file_format not in ("tsv", "csv"):
        raise ExpressionMatrixError(
            "Invalid export format '{}'. Use 'tsv' or 'csv'.".format(file_format)
        )

    built = build_matrix(db, expression_set_id, options, for_export=True)
    matrix = built["matrix"]
    metadata = built["metadata"]
    columns = built["columns"]
    ordered = built["ordered_orthogroups"]

    # Assemble a display DataFrame: metadata columns + value columns.
    records = []
    for og in ordered:
        meta = metadata.get(og, {})
        row = {
            "orthogroup_id": og,
            "gene": meta.get("gene") or "",
            "product": meta.get("product") or "",
            "strains": "; ".join(meta.get("strains", [])),
            "seed_pegs": _seed_pegs_to_str(meta.get("seed_pegs", {})),
            "gene_count": meta.get("gene_count"),
        }
        row_series = matrix.loc[og]
        for col in columns:
            val = row_series.get(col)
            if val is None or (isinstance(val, float) and math.isnan(val)):
                # Honor missing-value display for exports too.
                row[col] = 0 if options.missing_display == "zero" else ""
            else:
                fval = float(val)
                row[col] = int(fval) if fval.is_integer() else round(fval, 6)
        records.append(row)

    header = list(METADATA_COLUMNS) + columns
    out_df = pd.DataFrame.from_records(records, columns=header)

    sep = "\t" if file_format == "tsv" else ","
    buffer = io.StringIO()
    out_df.to_csv(buffer, sep=sep, index=False)
    text = buffer.getvalue()

    return text, built["summary"]


#--------------------------------
# Index management
#--------------------------------
#
# Appropriate indexes for the current scale. Called once at startup (best
# effort) so matrix queries that filter by expression_set_id (+ orthogroup_id /
# sample_id) and reference lookups stay fast. create_index is idempotent.


#---
# FUNCTION: ensure_expression_indexes
# PURPOSE: Create the MongoDB indexes used by the expression matrix queries.
#          Idempotent and best-effort: index creation errors are swallowed so a
#          transient DB issue never prevents the app from starting. Returns the
#          list of index specs that were requested.
#---
def ensure_expression_indexes(db):
    collection = db[EXPRESSION_COLLECTION_NAME]
    specs = [
        # Single-field indexes covering the required fields.
        ([("expression_set_id", 1)], "expression_set_id_idx"),
        ([("reference_import_id", 1)], "reference_import_id_idx"),
        ([("orthogroup_id", 1)], "orthogroup_id_idx"),
        ([("sample_id", 1)], "sample_id_idx"),
        # Compound indexes matching the matrix filter access patterns: rows are
        # always scoped by expression_set_id first, then narrowed by orthogroup
        # or sample.
        ([("expression_set_id", 1), ("orthogroup_id", 1)],
         "expr_set_orthogroup_idx"),
        ([("expression_set_id", 1), ("sample_id", 1)],
         "expr_set_sample_idx"),
        ([("expression_set_id", 1), ("strain", 1)],
         "expr_set_strain_idx"),
    ]
    created = []
    for keys, name in specs:
        try:
            collection.create_index(keys, name=name, background=True)
            created.append(name)
        except Exception as exc:  # pragma: no cover - best effort
            print("[expression] index creation skipped ({}): {}".format(
                name, exc))
    return created
