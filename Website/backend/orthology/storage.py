#--------------------------------
# Orthogroup reference table storage
#--------------------------------
#
# Persists the validated orthogroup reference table into its own MongoDB
# collection (`orthogroup_references`). Each stored document represents ONE
# strain-specific gene belonging to ONE orthogroup, e.g.:
#
#   {
#     "import_id": "<uuid grouping all rows of one upload>",
#     "orthogroup_id": "OG00045",
#     "strain": "Pa.B12",
#     "seed_peg": "peg.123",
#     "gene": "geneX",
#     "product": "example protein",
#     ...optional columns when present...
#   }
#
# All rows from a single upload share an `import_id` so an import can be
# referenced, previewed, or removed as a unit later.

import uuid
import math
import datetime

import numpy as np

from .schema import (
    COLLECTION_NAME,
    IMPORTS_COLLECTION_NAME,
    KNOWN_COLUMNS,
    COPIES_COLUMN,
    EXPRESSION_COLLECTION_NAME,
    EXPRESSION_IMPORTS_COLLECTION_NAME,
    EXPRESSION_KNOWN_COLUMNS,
)


#---
# FUNCTION: _clean_value
# PURPOSE: Convert a raw cell value into something safe for MongoDB / JSON.
#          NaN / None become None; everything else is kept as-is (values were
#          read as strings during parsing).
#---
def _clean_value(value):
    if value is None:
        return None
    # pandas NaN (float) or numpy NaN
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
# FUNCTION: dataframe_to_documents
# PURPOSE: Convert the validated DataFrame into a list of MongoDB documents,
#          one document per strain-specific gene (row).
# PARAMETERS:
#   df: validated pandas DataFrame.
#   import_id: shared identifier for every row of this upload.
# RETURNS: list of dicts ready for insert_many.
#---
def dataframe_to_documents(df, import_id):
    documents = []
    # Preserve a stable, known column ordering first, then append any extra
    # columns the pipeline may have added that we do not explicitly know about.
    ordered_columns = [c for c in KNOWN_COLUMNS if c in df.columns]
    extra_columns = [c for c in df.columns if c not in KNOWN_COLUMNS]
    columns = ordered_columns + extra_columns

    for _, row in df.iterrows():
        doc = {"import_id": import_id}
        for col in columns:
            doc[col] = _clean_value(row[col])
        documents.append(doc)
    return documents


#---
# FUNCTION: store_orthogroup_reference
# PURPOSE: Insert all rows of one upload into the orthogroup_references
#          collection under a shared import_id, and record a single "manifest"
#          document in the orthogroup_reference_imports collection describing
#          the import (filename, timestamp, summary, preview). The manifest is
#          what powers the "Saved reference tables" list and lets an import be
#          re-opened later without re-uploading the file.
# PARAMETERS:
#   db: the MongoDB database handle (client.micromix).
#   df: validated pandas DataFrame.
#   filename: original uploaded filename (or None for pasted text).
#   summary: summary dict produced by validation.build_summary.
#   preview: preview dict produced by import_orthogroups.build_preview.
# RETURNS: (import_id, inserted_count)
#---
def store_orthogroup_reference(db, df, filename=None, summary=None, preview=None):
    collection = db[COLLECTION_NAME]
    import_id = uuid.uuid4().hex
    imported_at = datetime.datetime.utcnow()

    documents = dataframe_to_documents(df, import_id)
    # Tag every member row with the filename + timestamp so the rows remain
    # self-describing even independent of the manifest document.
    for doc in documents:
        doc["filename"] = filename
        doc["imported_at"] = imported_at
    if documents:
        collection.insert_many(documents)

    # Store one manifest document per import for the saved-imports list.
    # The member rows and the manifest are inserted in two separate operations
    # (no multi-document transaction is assumed). If the manifest insert fails
    # we would otherwise be left with orphaned member rows that no manifest
    # references (invisible to the saved list, and un-openable / un-deletable
    # via import_id). To avoid that, roll back the just-inserted rows on error.
    manifest = {
        "import_id": import_id,
        "filename": filename,
        "imported_at": imported_at,
        "inserted_count": len(documents),
        "summary": summary or {},
        "preview": preview or {},
    }
    try:
        db[IMPORTS_COLLECTION_NAME].insert_one(manifest)
    except Exception:
        # Best-effort rollback of the orphaned member rows before re-raising.
        if documents:
            collection.delete_many({"import_id": import_id})
        raise

    return import_id, len(documents)


#---
# FUNCTION: _serialize_import
# PURPOSE: Convert a stored manifest document into a JSON-safe list-item dict.
#          Drops the Mongo _id and turns the timestamp into an ISO string.
#---
def _serialize_import(doc):
    if doc is None:
        return None
    summary = doc.get("summary") or {}
    imported_at = doc.get("imported_at")
    if isinstance(imported_at, datetime.datetime):
        imported_at = imported_at.isoformat() + "Z"
    return {
        "import_id": doc.get("import_id"),
        "filename": doc.get("filename"),
        "imported_at": imported_at,
        "inserted_count": doc.get("inserted_count"),
        "total_orthogroups": summary.get("total_orthogroups"),
        "total_strains": summary.get("total_strains"),
        "strain_names": summary.get("strain_names", []),
        "total_member_rows": summary.get(
            "total_member_rows", doc.get("inserted_count")
        ),
    }


#---
# FUNCTION: list_orthogroup_imports
# PURPOSE: Return a JSON-safe list of all saved orthogroup imports (manifest
#          documents), newest first, for the "Saved reference tables" tab.
#---
def list_orthogroup_imports(db):
    cursor = db[IMPORTS_COLLECTION_NAME].find().sort("imported_at", -1)
    return [_serialize_import(doc) for doc in cursor]


#---
# FUNCTION: get_orthogroup_import
# PURPOSE: Load a single saved import's full summary + preview from the
#          database (no re-upload required). Returns None when not found.
# RETURNS: dict { import_id, filename, imported_at, inserted_count,
#                 summary, preview } or None.
#---
def get_orthogroup_import(db, import_id):
    doc = db[IMPORTS_COLLECTION_NAME].find_one({"import_id": import_id})
    if doc is None:
        return None
    imported_at = doc.get("imported_at")
    if isinstance(imported_at, datetime.datetime):
        imported_at = imported_at.isoformat() + "Z"
    return {
        "import_id": doc.get("import_id"),
        "filename": doc.get("filename"),
        "imported_at": imported_at,
        "inserted_count": doc.get("inserted_count"),
        "summary": doc.get("summary") or {},
        "preview": doc.get("preview") or {},
    }


#---
# FUNCTION: delete_orthogroup_import
# PURPOSE: Remove a saved import: its manifest document plus every member row
#          sharing the import_id. Returns the number of member rows removed
#          (or None when the import did not exist).
#---
def delete_orthogroup_import(db, import_id):
    manifest = db[IMPORTS_COLLECTION_NAME].find_one({"import_id": import_id})
    if manifest is None:
        return None
    rows_result = db[COLLECTION_NAME].delete_many({"import_id": import_id})
    db[IMPORTS_COLLECTION_NAME].delete_one({"import_id": import_id})
    return rows_result.deleted_count


#--------------------------------
# Step 2: reference strain selection + dynamic label preview
#--------------------------------
#
# The functions below let the user pick a "reference strain" purely for DISPLAY
# purposes. The stable comparison unit is always `orthogroup_id`; the selected
# reference strain only changes which strain-specific member's metadata
# (seed_peg / locus_tag / gene / product) is shown as the label for each
# orthogroup. The orthogroup_id is never replaced or lost.


# A clear, human-readable label to show when the selected reference strain has
# no member gene inside a given orthogroup.
MISSING_REFERENCE_LABEL = "missing in selected reference"


#---
# FUNCTION: get_reference_strains
# PURPOSE: Return the list of strains available in a saved import so the
#          frontend can populate the "Reference strain" dropdown.
#          Strains are read from the saved manifest summary when present
#          (fast, no scan of member rows); otherwise they are derived by a
#          distinct() query over the member rows as a fallback.
# PARAMETERS:
#   db: the MongoDB database handle.
#   import_id: the import to inspect.
# RETURNS: dict { import_id, strains: [sorted strain names], default_strain }
#          or None when the import does not exist.
#---
def get_reference_strains(db, import_id):
    manifest = db[IMPORTS_COLLECTION_NAME].find_one({"import_id": import_id})
    if manifest is None:
        return None

    summary = manifest.get("summary") or {}
    strains = summary.get("strain_names")
    if not strains:
        # Fallback: derive distinct strains straight from the member rows.
        raw = db[COLLECTION_NAME].distinct("strain", {"import_id": import_id})
        strains = sorted(str(s) for s in raw if s is not None and str(s) != "")
    else:
        strains = [str(s) for s in strains]

    return {
        "import_id": import_id,
        "strains": strains,
        "default_strain": _pick_default_strain(strains),
    }


#---
# FUNCTION: _pick_default_strain
# PURPOSE: Choose a sensible default reference strain. Prefer "Pa.PA14" when it
#          is available (the common reference genome), otherwise the first
#          available strain.
#---
def _pick_default_strain(strains):
    if not strains:
        return None
    if "Pa.PA14" in strains:
        return "Pa.PA14"
    return strains[0]


#---
# FUNCTION: _to_int
# PURPOSE: Best-effort convert a stored (string) value into an int, returning
#          None when it cannot be parsed. Values were stored as strings during
#          parsing so numeric-looking columns need coercing for display/counts.
#---
def _to_int(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int,)):
        return value
    try:
        if isinstance(value, float):
            if math.isnan(value):
                return None
            return int(value)
    except (TypeError, ValueError):
        return None
    try:
        text = str(value).strip()
        if text == "":
            return None
        return int(float(text))
    except (TypeError, ValueError):
        return None


#---
# FUNCTION: _first_non_empty
# PURPOSE: Return the first non-empty value for `key` across a list of member
#          documents (used to pick a representative label for paralogs).
#---
def _first_non_empty(members, key):
    for m in members:
        val = m.get(key)
        if val is not None and str(val).strip() != "":
            return val
    return None


#---
# FUNCTION: _join_values
# PURPOSE: Join the values of `key` across member docs into a readable string
#          (used when an orthogroup has multiple copies in the reference
#          strain, so the UI can show e.g. "peg.1; peg.2").
#---
def _join_values(members, key, sep="; "):
    seen = []
    for m in members:
        val = m.get(key)
        if val is not None and str(val).strip() != "":
            text = str(val)
            if text not in seen:
                seen.append(text)
    if not seen:
        return None
    return sep.join(seen)


#---
# FUNCTION: _build_reference_row
# PURPOSE: Build ONE display row for a single orthogroup given the selected
#          reference strain and that orthogroup's members in that strain.
#          The orthogroup_id is always preserved. When the strain has no member
#          the row is flagged has_reference_member=False and label fields are
#          blank with a clear fallback label. When multiple members exist
#          (paralogs / co-orthologs) the row is flagged has_paralog_in_reference
#          and the label fields join / count the copies.
# PARAMETERS:
#   orthogroup_id: the stable comparison unit.
#   ref_members: list of member docs for this orthogroup in the selected strain
#                (may be empty).
#   reference_strain: the selected strain name.
#   any_member: any one member doc of this orthogroup (from any strain), used to
#               source strain-independent stats like species_count / gene_count.
#   species_count / gene_count / present_count: precomputed stats for this
#               orthogroup (may be None).
# RETURNS: a JSON-safe display row dict.
#---
def _build_reference_row(
    orthogroup_id,
    ref_members,
    reference_strain,
    species_count=None,
    gene_count=None,
    present_count=None,
):
    has_member = len(ref_members) > 0
    has_paralog = len(ref_members) > 1

    if not has_member:
        return {
            "orthogroup_id": orthogroup_id,
            "reference_strain": reference_strain,
            "reference_seed_peg": None,
            "reference_locus_tag": None,
            "reference_gene": None,
            "reference_product": None,
            "reference_label": MISSING_REFERENCE_LABEL,
            "copies_in_reference_strain": 0,
            "species_count": species_count,
            "gene_count": gene_count,
            "present_count": present_count,
            "has_reference_member": False,
            "has_paralog_in_reference": False,
        }

    # Prefer an explicit copies_in_strain value if present on any member;
    # otherwise fall back to the number of member rows we found.
    copies_from_column = None
    for m in ref_members:
        copies_from_column = _to_int(m.get(COPIES_COLUMN))
        if copies_from_column is not None:
            break
    copies = copies_from_column if copies_from_column is not None else len(ref_members)
    # A single row could still declare copies_in_strain > 1, and multiple rows
    # clearly mean paralogs too.
    has_paralog = has_paralog or (copies is not None and copies > 1)

    if has_paralog:
        # Show the joined copies so the user can see all of them, and keep a
        # representative single value available too.
        seed_peg = _join_values(ref_members, "seed_peg")
        locus_tag = _join_values(ref_members, "locus_tag")
        gene = _join_values(ref_members, "gene")
        product = _join_values(ref_members, "product")
        primary_seed = _first_non_empty(ref_members, "seed_peg")
        label = "{} (+{} copies)".format(
            primary_seed if primary_seed is not None else MISSING_REFERENCE_LABEL,
            max(copies - 1, len(ref_members) - 1),
        )
    else:
        seed_peg = _first_non_empty(ref_members, "seed_peg")
        locus_tag = _first_non_empty(ref_members, "locus_tag")
        gene = _first_non_empty(ref_members, "gene")
        product = _first_non_empty(ref_members, "product")
        label = seed_peg

    # copy_index is preserved when available (from the first member declaring it).
    copy_index = None
    for m in ref_members:
        copy_index = _to_int(m.get("copy_index"))
        if copy_index is not None:
            break

    return {
        "orthogroup_id": orthogroup_id,
        "reference_strain": reference_strain,
        "reference_seed_peg": seed_peg,
        "reference_locus_tag": locus_tag,
        "reference_gene": gene,
        "reference_product": product,
        "reference_label": label,
        "copies_in_reference_strain": copies,
        "copy_index": copy_index,
        "species_count": species_count,
        "gene_count": gene_count,
        "present_count": present_count,
        "has_reference_member": True,
        "has_paralog_in_reference": has_paralog,
    }


#---
# FUNCTION: get_reference_preview
# PURPOSE: Build a display preview of a saved import using a selected reference
#          strain. Returns ONE row per orthogroup, labelled with that strain's
#          member(s) where available. orthogroup_id is always preserved.
#          Also returns a small summary (counts of present / missing / paralog
#          orthogroups for the selected strain) plus pagination metadata.
# PARAMETERS:
#   db: the MongoDB database handle.
#   import_id: the saved import to read.
#   reference_strain: the selected display reference strain.
#   page: 1-based page number for the preview table (default 1).
#   limit: rows per page (default 50, capped to a sane maximum).
# RETURNS: dict {
#            import_id, reference_strain, page, limit, total_orthogroups,
#            summary: { reference_strain, orthogroups_total,
#                       orthogroups_with_member, orthogroups_missing,
#                       orthogroups_with_paralogs },
#            rows: [ display row, ... ]
#          }
#          or None when the import does not exist.
#---
def get_reference_preview(db, import_id, reference_strain, page=1, limit=50):
    manifest = db[IMPORTS_COLLECTION_NAME].find_one({"import_id": import_id})
    if manifest is None:
        return None

    # Normalise pagination inputs.
    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 1
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 50
    if page < 1:
        page = 1
    if limit < 1:
        limit = 50
    if limit > 500:
        limit = 500

    collection = db[COLLECTION_NAME]

    # --- Whole-import summary counts for the selected strain -----------------
    # The full ordered list of orthogroups in this import (stable ordering by
    # first appearance is preferred; we sort ids so pagination is deterministic).
    all_orthogroups = collection.distinct("orthogroup_id", {"import_id": import_id})
    all_orthogroups = sorted(
        str(og) for og in all_orthogroups if og is not None and str(og) != ""
    )
    total_orthogroups = len(all_orthogroups)

    # Which orthogroups have >=1 member in the selected strain, and how many.
    strain_counts = {}
    for doc in collection.find(
        {"import_id": import_id, "strain": reference_strain},
        {"orthogroup_id": 1, "copies_in_strain": 1, "_id": 0},
    ):
        og = doc.get("orthogroup_id")
        if og is None:
            continue
        og = str(og)
        entry = strain_counts.setdefault(og, {"rows": 0, "copies": None})
        entry["rows"] += 1
        copies = _to_int(doc.get(COPIES_COLUMN))
        if copies is not None:
            entry["copies"] = max(entry["copies"] or 0, copies)

    orthogroups_with_member = len(strain_counts)
    orthogroups_missing = total_orthogroups - orthogroups_with_member
    orthogroups_with_paralogs = 0
    for og, entry in strain_counts.items():
        effective = entry["copies"] if entry["copies"] is not None else entry["rows"]
        if entry["rows"] > 1 or (effective is not None and effective > 1):
            orthogroups_with_paralogs += 1

    summary = {
        "reference_strain": reference_strain,
        "orthogroups_total": total_orthogroups,
        "orthogroups_with_member": orthogroups_with_member,
        "orthogroups_missing": orthogroups_missing,
        "orthogroups_with_paralogs": orthogroups_with_paralogs,
    }

    # --- Page of display rows ------------------------------------------------
    start = (page - 1) * limit
    end = start + limit
    page_ogs = all_orthogroups[start:end]

    rows = []
    if page_ogs:
        # Fetch all member rows (any strain) for the orthogroups on this page,
        # so we can source both the selected-strain label and the shared stats
        # (species_count / gene_count) in a single query.
        members_by_og = {}
        for doc in collection.find(
            {"import_id": import_id, "orthogroup_id": {"$in": page_ogs}},
            {"_id": 0},
        ):
            og = doc.get("orthogroup_id")
            if og is None:
                continue
            members_by_og.setdefault(str(og), []).append(doc)

        for og in page_ogs:
            members = members_by_og.get(og, [])
            ref_members = [m for m in members if m.get("strain") == reference_strain]

            # Shared, strain-independent stats: prefer explicit columns, fall
            # back to derived counts.
            species_count = None
            gene_count = None
            for m in members:
                if species_count is None:
                    species_count = _to_int(m.get("species_count"))
                if gene_count is None:
                    gene_count = _to_int(m.get("gene_count"))
            if species_count is None:
                species_count = len({
                    m.get("strain") for m in members if m.get("strain") is not None
                }) or None
            if gene_count is None:
                gene_count = len(members) or None
            # present_count = number of strains this orthogroup appears in.
            present_count = len({
                m.get("strain") for m in members if m.get("strain") is not None
            }) or None

            rows.append(
                _build_reference_row(
                    og,
                    ref_members,
                    reference_strain,
                    species_count=species_count,
                    gene_count=gene_count,
                    present_count=present_count,
                )
            )

    return {
        "import_id": import_id,
        "reference_strain": reference_strain,
        "page": page,
        "limit": limit,
        "total_orthogroups": total_orthogroups,
        "returned_rows": len(rows),
        "summary": summary,
        "rows": rows,
    }


#--------------------------------
# Step 3: expression import storage (linked to a saved reference import)
#--------------------------------
#
# The functions below persist a "long"/tidy expression table
# (orthogroup_expression_long.tsv) into its own MongoDB collection
# (`orthogroup_expression`). Each stored document represents ONE expression
# measurement of ONE orthogroup, in ONE strain, for ONE sample. Every row (and
# the accompanying manifest document in `orthogroup_expression_sets`) is linked
# to the previously saved orthogroup reference import via `reference_import_id`,
# so an expression import always belongs to exactly one reference set.
#
# orthogroup_id remains the stable comparison unit; the reference link lets us
# report how many expression orthogroups matched / did not match the reference.


# How many preview rows to build for the expression preview table.
EXPRESSION_PREVIEW_ROW_LIMIT = 25

# Columns shown, in order, in the expression preview table.
EXPRESSION_PREVIEW_COLUMNS = [
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
# FUNCTION: get_reference_orthogroup_ids
# PURPOSE: Return the set of orthogroup_id values present in a saved reference
#          import, so an expression import can be matched against it. Returns
#          None when the reference import does not exist.
# PARAMETERS:
#   db: the MongoDB database handle.
#   reference_import_id: the saved reference import to read.
# RETURNS: set of orthogroup_id strings, or None when the import is missing.
#---
def get_reference_orthogroup_ids(db, reference_import_id):
    manifest = db[IMPORTS_COLLECTION_NAME].find_one(
        {"import_id": reference_import_id}
    )
    if manifest is None:
        return None
    raw = db[COLLECTION_NAME].distinct(
        "orthogroup_id", {"import_id": reference_import_id}
    )
    return {str(og) for og in raw if og is not None and str(og) != ""}


#---
# FUNCTION: expression_dataframe_to_documents
# PURPOSE: Convert the validated expression DataFrame into a list of MongoDB
#          documents, one document per measurement (row). Each document carries
#          the expression_set_id and the linked reference_import_id so rows are
#          self-describing.
# PARAMETERS:
#   df: validated expression pandas DataFrame.
#   expression_set_id: shared identifier for every row of this upload.
#   reference_import_id: the linked saved reference import id.
# RETURNS: list of dicts ready for insert_many.
#---
def expression_dataframe_to_documents(df, expression_set_id, reference_import_id):
    documents = []
    ordered_columns = [c for c in EXPRESSION_KNOWN_COLUMNS if c in df.columns]
    extra_columns = [c for c in df.columns if c not in EXPRESSION_KNOWN_COLUMNS]
    columns = ordered_columns + extra_columns

    for _, row in df.iterrows():
        doc = {
            "expression_set_id": expression_set_id,
            "reference_import_id": reference_import_id,
        }
        for col in columns:
            doc[col] = _clean_value(row[col])
        documents.append(doc)
    return documents


#---
# FUNCTION: store_expression_import
# PURPOSE: Insert all rows of one expression upload into the
#          orthogroup_expression collection under a shared expression_set_id,
#          and record a single manifest document in the
#          orthogroup_expression_sets collection describing the import
#          (display name, filename, timestamp, summary, preview, linked
#          reference_import_id). The manifest powers the "Saved expression
#          imports" list and lets an import be re-opened without re-uploading.
# PARAMETERS:
#   db: the MongoDB database handle (client.micromix).
#   df: validated expression DataFrame.
#   reference_import_id: the linked saved reference import id.
#   filename: original uploaded filename (or None for pasted text).
#   display_name: human-friendly name for the import (defaults to filename).
#   summary: summary dict produced by expression_validation.build_summary.
#   preview: preview dict produced by expression_import.build_preview.
# RETURNS: (expression_set_id, inserted_count)
#---
def store_expression_import(
    db,
    df,
    reference_import_id,
    filename=None,
    display_name=None,
    summary=None,
    preview=None,
):
    collection = db[EXPRESSION_COLLECTION_NAME]
    expression_set_id = uuid.uuid4().hex
    imported_at = datetime.datetime.utcnow()

    documents = expression_dataframe_to_documents(
        df, expression_set_id, reference_import_id
    )
    # Tag every row with filename + timestamp so rows remain self-describing
    # even independent of the manifest document.
    for doc in documents:
        doc["filename"] = filename
        doc["imported_at"] = imported_at
    if documents:
        collection.insert_many(documents)

    summary = summary or {}
    manifest = {
        "expression_set_id": expression_set_id,
        "reference_import_id": reference_import_id,
        "display_name": display_name or filename or "Expression import",
        "original_filename": filename,
        "import_timestamp": imported_at,
        "total_expression_rows": len(documents),
        "total_orthogroups": summary.get("total_orthogroups"),
        "total_strains": summary.get("total_strains"),
        "strain_names": summary.get("strain_names", []),
        "total_samples": summary.get("total_samples"),
        "sample_names": summary.get("sample_names", []),
        "conditions": summary.get("conditions", []),
        "replicates": summary.get("replicates", []),
        "matched_orthogroup_count": summary.get("matched_orthogroup_count"),
        "unmatched_orthogroup_count": summary.get("unmatched_orthogroup_count"),
        "unmatched_row_count": summary.get("unmatched_row_count"),
        "duplicate_row_count": summary.get("duplicate_row_count"),
        "missing_optional_columns": summary.get("missing_optional_columns", []),
        "summary": summary,
        "preview": preview or {},
    }
    try:
        db[EXPRESSION_IMPORTS_COLLECTION_NAME].insert_one(manifest)
    except Exception:
        # Best-effort rollback of the orphaned member rows before re-raising.
        if documents:
            collection.delete_many({"expression_set_id": expression_set_id})
        raise

    return expression_set_id, len(documents)


#---
# FUNCTION: _serialize_expression_import
# PURPOSE: Convert a stored expression manifest document into a JSON-safe
#          list-item dict for the "Saved expression imports" table.
#---
def _serialize_expression_import(doc):
    if doc is None:
        return None
    imported_at = doc.get("import_timestamp")
    if isinstance(imported_at, datetime.datetime):
        imported_at = imported_at.isoformat() + "Z"
    return {
        "expression_set_id": doc.get("expression_set_id"),
        "reference_import_id": doc.get("reference_import_id"),
        "display_name": doc.get("display_name"),
        "original_filename": doc.get("original_filename"),
        "import_timestamp": imported_at,
        "total_expression_rows": doc.get("total_expression_rows"),
        "total_orthogroups": doc.get("total_orthogroups"),
        "total_strains": doc.get("total_strains"),
        "total_samples": doc.get("total_samples"),
        "matched_orthogroup_count": doc.get("matched_orthogroup_count"),
        "unmatched_orthogroup_count": doc.get("unmatched_orthogroup_count"),
    }


#---
# FUNCTION: list_expression_imports
# PURPOSE: Return a JSON-safe list of saved expression imports linked to a
#          given reference import, newest first, for the "Saved expression
#          imports" list.
#---
def list_expression_imports(db, reference_import_id):
    cursor = (
        db[EXPRESSION_IMPORTS_COLLECTION_NAME]
        .find({"reference_import_id": reference_import_id})
        .sort("import_timestamp", -1)
    )
    return [_serialize_expression_import(doc) for doc in cursor]


#---
# FUNCTION: _expression_manifest_to_detail
# PURPOSE: Build the full detail payload (summary + preview + metadata) for one
#          expression manifest document.
#---
def _expression_manifest_to_detail(doc):
    imported_at = doc.get("import_timestamp")
    if isinstance(imported_at, datetime.datetime):
        imported_at = imported_at.isoformat() + "Z"
    return {
        "expression_set_id": doc.get("expression_set_id"),
        "reference_import_id": doc.get("reference_import_id"),
        "display_name": doc.get("display_name"),
        "original_filename": doc.get("original_filename"),
        "import_timestamp": imported_at,
        "total_expression_rows": doc.get("total_expression_rows"),
        "summary": doc.get("summary") or {},
        "preview": doc.get("preview") or {},
    }


#---
# FUNCTION: get_expression_import
# PURPOSE: Load a single saved expression import's full summary + preview from
#          the database (no re-upload required). Returns None when not found.
#---
def get_expression_import(db, expression_set_id):
    doc = db[EXPRESSION_IMPORTS_COLLECTION_NAME].find_one(
        {"expression_set_id": expression_set_id}
    )
    if doc is None:
        return None
    return _expression_manifest_to_detail(doc)


#---
# FUNCTION: get_expression_preview
# PURPOSE: Build a fresh preview of a saved expression import straight from the
#          stored member rows (rather than the cached manifest preview). Returns
#          up to `limit` rows with the standard expression preview columns, plus
#          basic pagination metadata. Returns None when the import is missing.
# PARAMETERS:
#   db: the MongoDB database handle.
#   expression_set_id: the saved expression import to read.
#   page: 1-based page number (default 1).
#   limit: rows per page (default 25, capped to a sane maximum).
#---
def get_expression_preview(db, expression_set_id, page=1, limit=25):
    manifest = db[EXPRESSION_IMPORTS_COLLECTION_NAME].find_one(
        {"expression_set_id": expression_set_id}
    )
    if manifest is None:
        return None

    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 1
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 25
    if page < 1:
        page = 1
    if limit < 1:
        limit = 25
    if limit > 500:
        limit = 500

    collection = db[EXPRESSION_COLLECTION_NAME]
    total_rows = collection.count_documents(
        {"expression_set_id": expression_set_id}
    )

    start = (page - 1) * limit
    projection = {"_id": 0}
    for col in EXPRESSION_PREVIEW_COLUMNS:
        projection[col] = 1

    cursor = (
        collection.find({"expression_set_id": expression_set_id}, projection)
        .skip(start)
        .limit(limit)
    )

    rows = []
    for doc in cursor:
        rows.append({col: doc.get(col) for col in EXPRESSION_PREVIEW_COLUMNS})

    return {
        "expression_set_id": expression_set_id,
        "reference_import_id": manifest.get("reference_import_id"),
        "page": page,
        "limit": limit,
        "total_rows": total_rows,
        "returned_rows": len(rows),
        "columns": list(EXPRESSION_PREVIEW_COLUMNS),
        "rows": rows,
    }


#---
# FUNCTION: delete_expression_import
# PURPOSE: Remove a saved expression import: its manifest document plus every
#          member row sharing the expression_set_id. Returns the number of
#          member rows removed (or None when the import did not exist).
#---
def delete_expression_import(db, expression_set_id):
    manifest = db[EXPRESSION_IMPORTS_COLLECTION_NAME].find_one(
        {"expression_set_id": expression_set_id}
    )
    if manifest is None:
        return None
    rows_result = db[EXPRESSION_COLLECTION_NAME].delete_many(
        {"expression_set_id": expression_set_id}
    )
    db[EXPRESSION_IMPORTS_COLLECTION_NAME].delete_one(
        {"expression_set_id": expression_set_id}
    )
    return rows_result.deleted_count
