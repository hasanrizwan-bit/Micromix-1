#--------------------------------
# Phase 2A: real-MongoDB integration subset for the orthology matrix builder
#--------------------------------
#
# Re-runs a representative subset of the FakeDB regression tests against a
# real, DISPOSABLE MongoDB via PyMongo, and checks that FakeDB and MongoDB give
# identical build_matrix / export / reference-preview results.
#
# Opt-in only. Skipped unless MICROMIX_TEST_MONGO_URI is set, e.g.
#
#   mongod --port 27099 --bind_ip 127.0.0.1 --dbpath <tmpdir>
#   MICROMIX_TEST_MONGO_URI=mongodb://127.0.0.1:27099/ \
#     ~/Micromix-1/Website/backend/venv/bin/python -m pytest \
#     orthology/tests/test_expression_matrix_mongo_integration.py -q
#
# Safety:
#   * Port 27017 (the regular Micromix database) is refused.
#   * Each test uses a brand-new database named micromix_regtest_<uuid>,
#     dropped after the test. Existing databases are never read or written.

import copy
import os
import uuid

import pytest

pymongo = pytest.importorskip("pymongo")

from orthology.expression_matrix import MatrixOptions, build_matrix, \
    build_matrix_export
from orthology.schema import (
    COLLECTION_NAME,
    EXPRESSION_COLLECTION_NAME,
    EXPRESSION_IMPORTS_COLLECTION_NAME,
    IMPORTS_COLLECTION_NAME,
)
from orthology.storage import get_reference_preview, get_reference_strains
from orthology.tests import test_expression_matrix_regression as reg


MONGO_URI = os.environ.get("MICROMIX_TEST_MONGO_URI")
DB_PREFIX = "micromix_regtest_"

pytestmark = pytest.mark.skipif(
    not MONGO_URI, reason="MICROMIX_TEST_MONGO_URI not set (opt-in integration)"
)


@pytest.fixture(scope="module")
def client():
    if ":27017" in MONGO_URI or MONGO_URI.rstrip("/").endswith("localhost") \
            or MONGO_URI.rstrip("/").endswith("127.0.0.1"):
        pytest.fail("Refusing to use the default MongoDB port 27017.")
    c = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
    c.admin.command("ping")
    yield c
    # Safety net: drop any leftover databases created by this module only.
    for name in c.list_database_names():
        if name.startswith(DB_PREFIX):
            c.drop_database(name)
    c.close()


@pytest.fixture
def mongo_make_db(client, monkeypatch):
    """Patch reg.make_db so the regression tests write to a fresh real DB."""
    created = []

    def _make(rows=None, ref_summary=None, refs=None):
        name = DB_PREFIX + uuid.uuid4().hex[:12]
        assert name not in client.list_database_names()
        db = client[name]
        created.append(name)
        data = {
            EXPRESSION_COLLECTION_NAME:
                reg.canonical_rows() if rows is None else rows,
            EXPRESSION_IMPORTS_COLLECTION_NAME: [
                {"expression_set_id": reg.EXPR_SET,
                 "reference_import_id": reg.REF_ID}],
            IMPORTS_COLLECTION_NAME: [
                {"import_id": reg.REF_ID, "summary": ref_summary or {}}],
            COLLECTION_NAME: reg.reference_docs() if refs is None else refs,
        }
        for coll, docs in data.items():
            if docs:
                # deepcopy: insert_many adds _id to the dicts in place.
                db[coll].insert_many(copy.deepcopy(docs))
        return db

    monkeypatch.setattr(reg, "make_db", _make)
    yield _make
    for name in created:
        client.drop_database(name)


# ---------------------------------------------------------------------------
# 1. Selected regression tests re-executed verbatim on real MongoDB
# ---------------------------------------------------------------------------
REUSED_TESTS = [
    "test_orthogroup_gene_mapping_metadata",
    "test_orthogroup_present_in_reference_but_absent_from_expression_not_in_matrix",
    "test_reference_strains_from_summary_and_fallback",
    "test_reference_preview_strain_sA",
    "test_reference_preview_strain_sB_and_pagination",
    "test_reference_preview_copies_in_strain_column_flags_paralog",
    "test_matrix_annotation_is_first_loaded_row_not_reference_strain",
    "test_missing_display_blank_vs_zero_full_matrix",
    "test_missing_stays_missing_after_transformations",
    "test_all_columns_zero_cpm_is_missing",
    "test_same_gene_different_samples_not_duplicates",
    "test_rows_without_seed_peg_collapse_as_duplicates_when_mixed",
    "test_cpm_hand_values_and_totals",
    "test_log2_cpm_hand_values",
    "test_cpm_library_size_depends_on_orthogroup_filter",
    "test_filter_strain",
    "test_filter_samples_drops_orthogroups_without_measurements",
    "test_filter_condition_and_replicate",
    "test_filter_orthogroup_ids",
    "test_filter_search_case_insensitive_fields",
    "test_filter_search_is_row_level_current_behaviour",
    "test_combined_filters_and_aggregation",
    "test_row_and_column_order_lexicographic_independent_of_insertion",
    "test_pagination_page_contents_and_bounds",
    "test_pagination_does_not_change_cpm",
    "test_export_tsv_exact_raw_blank",
    "test_export_csv_equals_tsv_and_quotes_commas",
    "test_export_missing_zero",
]


@pytest.mark.parametrize("name", REUSED_TESTS)
def test_regression_on_real_mongo(name, mongo_make_db):
    getattr(reg, name)()


@pytest.mark.parametrize("rule", ["sum", "mean", "max", "keep_separate"])
def test_paralog_rules_on_real_mongo(rule, mongo_make_db):
    reg.test_raw_matrix_paralog_rules(rule)


@pytest.mark.parametrize("dup_rule,paralog_rule,expected_s1", [
    ("sum", "sum", 22), ("mean", "sum", 10), ("first", "sum", 14),
    ("sum", "max", 18), ("mean", "mean", 5), ("first", "max", 10),
])
def test_duplicate_rules_on_real_mongo(dup_rule, paralog_rule, expected_s1,
                                       mongo_make_db):
    reg.test_duplicate_rules(dup_rule, paralog_rule, expected_s1)


@pytest.mark.parametrize("rule", ["mean", "median"])
def test_replicate_aggregation_on_real_mongo(rule, mongo_make_db):
    reg.test_replicate_aggregation_values_and_columns(rule)


@pytest.mark.parametrize("limit", [1, 3, 50])
def test_pages_concatenate_on_real_mongo(limit, mongo_make_db):
    reg.test_pages_concatenate_to_full_matrix(
        limit, {"transformation": "log2_cpm", "paralog_rule": "mean"})


def test_export_equals_full_matrix_and_pages_on_real_mongo(mongo_make_db):
    reg.test_export_equals_full_matrix_and_pages(
        {"replicate_aggregation": "median", "transformation": "cpm"})


# The four known discrepancies must reproduce identically on real MongoDB.
@pytest.mark.xfail(strict=True, reason="Issue I-1 (null count -> 0)")
def test_spec_null_count_on_real_mongo(mongo_make_db):
    reg.test_spec_null_count_cell_stays_missing()


@pytest.mark.xfail(strict=True, reason="Issue I-1 (null count -> 0 after log2 CPM)")
def test_spec_null_count_log2_cpm_on_real_mongo(mongo_make_db):
    reg.test_spec_null_count_cell_missing_after_log2_cpm()


@pytest.mark.xfail(strict=True, raises=KeyError,
                   reason="Issue I-2 (duplicates without seed_peg crash)")
def test_spec_duplicates_without_seed_peg_on_real_mongo(mongo_make_db):
    reg.test_spec_duplicates_without_seed_peg_do_not_crash()


@pytest.mark.xfail(strict=True, reason="Issue I-3 (CPM after replicate mean)")
def test_spec_cpm_before_aggregation_on_real_mongo(mongo_make_db):
    reg.test_spec_cpm_computed_per_sample_before_replicate_aggregation()


# ---------------------------------------------------------------------------
# 2. Direct FakeDB <-> MongoDB equivalence of full outputs
# ---------------------------------------------------------------------------
EQUIV_OPTIONS = [
    {},
    {"transformation": "cpm", "paralog_rule": "max"},
    {"transformation": "log2_cpm", "replicate_aggregation": "mean",
     "missing_display": "zero"},
    {"strains": ["sA"], "conditions": ["c1"], "paralog_rule": "mean"},
    {"replicates": [2], "transformation": "log2_count"},
    {"orthogroup_ids": ["OG2", "OG4"], "search": "q"},
]


def _fake_db():
    return reg.FakeDB({
        EXPRESSION_COLLECTION_NAME: reg.canonical_rows(),
        EXPRESSION_IMPORTS_COLLECTION_NAME: [
            {"expression_set_id": reg.EXPR_SET,
             "reference_import_id": reg.REF_ID}],
        IMPORTS_COLLECTION_NAME: [{"import_id": reg.REF_ID, "summary": {}}],
        COLLECTION_NAME: reg.reference_docs(),
    })


@pytest.mark.parametrize("opts_kw", EQUIV_OPTIONS)
def test_fakedb_and_mongo_identical_outputs(opts_kw, mongo_make_db):
    fake, real = _fake_db(), mongo_make_db()
    for page, limit in ((1, 50), (2, 2)):
        f = build_matrix(fake, reg.EXPR_SET, MatrixOptions(**opts_kw),
                         page=page, limit=limit)
        r = build_matrix(real, reg.EXPR_SET, MatrixOptions(**opts_kw),
                         page=page, limit=limit)
        assert f == r
    for fmt in ("tsv", "csv"):
        ft, fs = build_matrix_export(fake, reg.EXPR_SET,
                                     MatrixOptions(**opts_kw), fmt)
        rt, rs = build_matrix_export(real, reg.EXPR_SET,
                                     MatrixOptions(**opts_kw), fmt)
        assert ft == rt and fs == rs


@pytest.mark.parametrize("strain", ["sA", "sB", "absent"])
def test_fakedb_and_mongo_identical_reference_preview(strain, mongo_make_db):
    fake, real = _fake_db(), mongo_make_db()
    assert get_reference_strains(fake, reg.REF_ID) == \
        get_reference_strains(real, reg.REF_ID)
    for page, limit in ((1, 50), (2, 2)):
        assert get_reference_preview(fake, reg.REF_ID, strain, page, limit) == \
            get_reference_preview(real, reg.REF_ID, strain, page, limit)


def test_projection_excludes_id_and_unrequested_fields(mongo_make_db):
    # _load_rows uses an inclusion projection; get_reference_preview uses
    # {"_id": 0}. Confirm real PyMongo returns the same key sets as FakeDB.
    real, fake = mongo_make_db(), _fake_db()
    proj = {"_id": 0, "orthogroup_id": 1, "count": 1}
    q = {"expression_set_id": reg.EXPR_SET}
    r = list(real[EXPRESSION_COLLECTION_NAME].find(q, proj))
    f = list(fake[EXPRESSION_COLLECTION_NAME].find(q, proj))
    assert r == f
    r = list(real[COLLECTION_NAME].find({"import_id": reg.REF_ID}, {"_id": 0}))
    f = list(fake[COLLECTION_NAME].find({"import_id": reg.REF_ID}, {"_id": 0}))
    assert r == f
