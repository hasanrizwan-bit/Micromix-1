#--------------------------------
# Focused unit tests for the Step 4 expression matrix builder
#--------------------------------
#
# These tests exercise the pure matrix-building logic in
# orthology.expression_matrix against a tiny, hand-built dataset served by an
# in-memory FakeDB (no MongoDB required). They cover:
#   * matrix pivoting            (rows=orthogroup, cols=sample, vals=count)
#   * CPM calculation            (per-sample totals ~1,000,000)
#   * replicate aggregation      (mean/median grouped by strain+condition)
#   * paralog handling           (sum/mean/max/keep_separate)
#   * duplicate handling         (detect + sum/mean/first)
#   * missing values             (null internally; blank vs zero display)
#   * filtering                  (strain/sample/condition/replicate/search)
#   * export consistency         (export values equal preview values)
#
# Run with:  ./venv/bin/python -m pytest orthology/tests -q

import math

import pytest

from orthology.expression_matrix import (
    MatrixOptions,
    build_matrix,
    build_matrix_export,
    detect_duplicates,
    ExpressionMatrixError,
)
from orthology.schema import (
    EXPRESSION_COLLECTION_NAME,
    EXPRESSION_IMPORTS_COLLECTION_NAME,
    IMPORTS_COLLECTION_NAME,
)
from orthology.tests.fake_db import FakeDB


EXPR_SET = "es1"
REF_ID = "ref1"


def _row(og, strain, sample, count, condition=None, replicate=None,
         seed_peg=None, gene=None, product=None):
    return {
        "expression_set_id": EXPR_SET,
        "reference_import_id": REF_ID,
        "orthogroup_id": og,
        "strain": strain,
        "sample_id": sample,
        "count": count,
        "condition": condition,
        "replicate": replicate,
        "seed_peg": seed_peg,
        "gene": gene,
        "product": product,
    }


def make_db(rows):
    return FakeDB({
        EXPRESSION_COLLECTION_NAME: rows,
        EXPRESSION_IMPORTS_COLLECTION_NAME: [
            {"expression_set_id": EXPR_SET, "reference_import_id": REF_ID}
        ],
        IMPORTS_COLLECTION_NAME: [
            {"import_id": REF_ID}
        ],
    })


# ---------------------------------------------------------------------------
# Pivoting
# ---------------------------------------------------------------------------
def test_matrix_pivoting_basic():
    rows = [
        _row("OG1", "sA", "s1", "10", seed_peg="pA"),
        _row("OG1", "sB", "s2", "20", seed_peg="pB"),
        _row("OG2", "sA", "s1", "5", seed_peg="pC"),
    ]
    db = make_db(rows)
    res = build_matrix(db, EXPR_SET, MatrixOptions(), page=1, limit=50)

    assert res["summary"]["matrix_row_count"] == 2
    assert res["summary"]["matrix_column_count"] == 2
    assert res["columns"] == ["s1", "s2"]

    by_og = {r["orthogroup_id"]: r for r in res["rows"]}
    assert by_og["OG1"]["values"]["s1"] == 10
    assert by_og["OG1"]["values"]["s2"] == 20
    assert by_og["OG2"]["values"]["s1"] == 5
    # OG2 has no measurement in s2 -> missing (blank default -> None).
    assert by_og["OG2"]["values"]["s2"] is None


def test_unknown_expression_set_raises():
    db = make_db([])
    # No matching set manifest.
    db2 = FakeDB({EXPRESSION_IMPORTS_COLLECTION_NAME: []})
    with pytest.raises(ExpressionMatrixError):
        build_matrix(db2, "missing", MatrixOptions())


def test_missing_reference_raises():
    rows = [_row("OG1", "sA", "s1", "10")]
    db = FakeDB({
        EXPRESSION_COLLECTION_NAME: rows,
        EXPRESSION_IMPORTS_COLLECTION_NAME: [
            {"expression_set_id": EXPR_SET, "reference_import_id": REF_ID}
        ],
        IMPORTS_COLLECTION_NAME: [],  # reference deleted
    })
    with pytest.raises(ExpressionMatrixError):
        build_matrix(db, EXPR_SET, MatrixOptions())


# ---------------------------------------------------------------------------
# CPM
# ---------------------------------------------------------------------------
def test_cpm_per_sample_totals_million():
    rows = [
        _row("OG1", "sA", "s1", "10"),
        _row("OG2", "sA", "s1", "30"),
        _row("OG1", "sB", "s2", "1"),
        _row("OG2", "sB", "s2", "3"),
    ]
    db = make_db(rows)
    res = build_matrix(db, EXPR_SET, MatrixOptions(transformation="cpm"))
    totals = res["summary"]["cpm_column_totals"]
    for col, total in totals.items():
        assert abs(total - 1_000_000.0) < 1e-3

    # s1 OG1 = 10/40 * 1e6 = 250000
    by_og = {r["orthogroup_id"]: r for r in res["rows"]}
    assert abs(by_og["OG1"]["values"]["s1"] - 250000.0) < 1e-3


def test_log2_count():
    rows = [_row("OG1", "sA", "s1", "3")]
    db = make_db(rows)
    res = build_matrix(db, EXPR_SET, MatrixOptions(transformation="log2_count"))
    by_og = {r["orthogroup_id"]: r for r in res["rows"]}
    # log2(3+1) = 2.0
    assert abs(by_og["OG1"]["values"]["s1"] - 2.0) < 1e-6


# ---------------------------------------------------------------------------
# Replicate aggregation
# ---------------------------------------------------------------------------
def test_replicate_mean_aggregation():
    rows = [
        _row("OG1", "sA", "s1", "10", condition="low", replicate="1"),
        _row("OG1", "sA", "s2", "20", condition="low", replicate="2"),
        _row("OG1", "sA", "s3", "100", condition="high", replicate="1"),
    ]
    db = make_db(rows)
    res = build_matrix(
        db, EXPR_SET, MatrixOptions(replicate_aggregation="mean")
    )
    # Two groups: (sA, low) and (sA, high).
    assert res["summary"]["matrix_column_count"] == 2
    labels = res["columns"]
    low_label = [l for l in labels if "low" in l][0]
    high_label = [l for l in labels if "high" in l][0]
    assert low_label == "sA | low | mean"
    by_og = {r["orthogroup_id"]: r for r in res["rows"]}
    assert by_og["OG1"]["values"][low_label] == 15  # mean(10,20)
    assert by_og["OG1"]["values"][high_label] == 100


def test_replicate_median_aggregation():
    rows = [
        _row("OG1", "sA", "s1", "10", condition="low", replicate="1"),
        _row("OG1", "sA", "s2", "20", condition="low", replicate="2"),
        _row("OG1", "sA", "s3", "30", condition="low", replicate="3"),
    ]
    db = make_db(rows)
    res = build_matrix(
        db, EXPR_SET, MatrixOptions(replicate_aggregation="median")
    )
    label = res["columns"][0]
    by_og = {r["orthogroup_id"]: r for r in res["rows"]}
    assert by_og["OG1"]["values"][label] == 20  # median(10,20,30)


# ---------------------------------------------------------------------------
# Paralog handling
# ---------------------------------------------------------------------------
def test_paralog_sum_mean_max():
    # Two genes of strain sA in OG1 for sample s1: counts 10 and 30.
    rows = [
        _row("OG1", "sA", "s1", "10", seed_peg="p1"),
        _row("OG1", "sA", "s1", "30", seed_peg="p2"),
    ]

    db = make_db(rows)
    res_sum = build_matrix(db, EXPR_SET, MatrixOptions(paralog_rule="sum"))
    assert res_sum["rows"][0]["values"]["s1"] == 40

    res_mean = build_matrix(db, EXPR_SET, MatrixOptions(paralog_rule="mean"))
    assert res_mean["rows"][0]["values"]["s1"] == 20

    res_max = build_matrix(db, EXPR_SET, MatrixOptions(paralog_rule="max"))
    assert res_max["rows"][0]["values"]["s1"] == 30

    # The orthogroup should be flagged as having paralogs.
    assert res_sum["summary"]["orthogroups_with_paralogs"] == 1
    assert res_sum["rows"][0]["has_paralog"] is True
    assert res_sum["rows"][0]["gene_count"] == 2


def test_paralog_keep_separate_sums_into_cell():
    rows = [
        _row("OG1", "sA", "s1", "10", seed_peg="p1"),
        _row("OG1", "sA", "s1", "30", seed_peg="p2"),
    ]
    db = make_db(rows)
    res = build_matrix(db, EXPR_SET, MatrixOptions(paralog_rule="keep_separate"))
    # keep_separate still sums into the single (og, sample) cell.
    assert res["rows"][0]["values"]["s1"] == 40


# ---------------------------------------------------------------------------
# Duplicate handling
# ---------------------------------------------------------------------------
def test_duplicate_detection_and_sum():
    # Same (og, strain, seed_peg, sample) twice -> duplicate.
    rows = [
        _row("OG1", "sA", "s1", "10", seed_peg="p1"),
        _row("OG1", "sA", "s1", "5", seed_peg="p1"),
    ]
    db = make_db(rows)
    res = build_matrix(db, EXPR_SET, MatrixOptions(duplicate_rule="sum"))
    assert res["summary"]["duplicate_key_count"] == 1
    assert res["rows"][0]["values"]["s1"] == 15  # 10 + 5


def test_duplicate_first_rule():
    rows = [
        _row("OG1", "sA", "s1", "10", seed_peg="p1"),
        _row("OG1", "sA", "s1", "5", seed_peg="p1"),
    ]
    db = make_db(rows)
    res = build_matrix(db, EXPR_SET, MatrixOptions(duplicate_rule="first"))
    assert res["rows"][0]["values"]["s1"] == 10


def test_duplicate_mean_rule():
    rows = [
        _row("OG1", "sA", "s1", "10", seed_peg="p1"),
        _row("OG1", "sA", "s1", "20", seed_peg="p1"),
    ]
    db = make_db(rows)
    res = build_matrix(db, EXPR_SET, MatrixOptions(duplicate_rule="mean"))
    assert res["rows"][0]["values"]["s1"] == 15


# ---------------------------------------------------------------------------
# Missing values
# ---------------------------------------------------------------------------
def test_missing_value_blank_vs_zero():
    rows = [
        _row("OG1", "sA", "s1", "10"),
        _row("OG2", "sB", "s2", "20"),
    ]
    db = make_db(rows)

    blank = build_matrix(db, EXPR_SET, MatrixOptions(missing_display="blank"))
    by_og = {r["orthogroup_id"]: r for r in blank["rows"]}
    assert by_og["OG1"]["values"]["s2"] is None
    assert blank["summary"]["missing_value_count"] == 2  # OG1/s2, OG2/s1

    zero = build_matrix(db, EXPR_SET, MatrixOptions(missing_display="zero"))
    by_og_z = {r["orthogroup_id"]: r for r in zero["rows"]}
    assert by_og_z["OG1"]["values"]["s2"] == 0
    # The missing count is unchanged; only the display differs.
    assert zero["summary"]["missing_value_count"] == 2


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------
def test_strain_and_condition_filter():
    rows = [
        _row("OG1", "sA", "s1", "10", condition="low"),
        _row("OG1", "sB", "s2", "20", condition="high"),
        _row("OG2", "sA", "s1", "5", condition="low"),
    ]
    db = make_db(rows)
    res = build_matrix(
        db, EXPR_SET, MatrixOptions(strains=["sA"], conditions=["low"])
    )
    assert res["columns"] == ["s1"]
    assert res["summary"]["matrix_row_count"] == 2  # OG1, OG2 (both in sA/low)


def test_search_filter_matches_product():
    rows = [
        _row("OG1", "sA", "s1", "10", product="transferase X"),
        _row("OG2", "sA", "s1", "5", product="kinase Y"),
    ]
    db = make_db(rows)
    res = build_matrix(db, EXPR_SET, MatrixOptions(search="transferase"))
    assert res["summary"]["matrix_row_count"] == 1
    assert res["rows"][0]["orthogroup_id"] == "OG1"


def test_empty_selection_raises():
    rows = [_row("OG1", "sA", "s1", "10")]
    db = make_db(rows)
    with pytest.raises(ExpressionMatrixError):
        build_matrix(db, EXPR_SET, MatrixOptions(strains=["nope"]))


def test_invalid_option_raises():
    with pytest.raises(ExpressionMatrixError):
        MatrixOptions(transformation="bogus")


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def test_pagination():
    rows = [_row("OG%02d" % i, "sA", "s1", str(i)) for i in range(10)]
    db = make_db(rows)
    res = build_matrix(db, EXPR_SET, MatrixOptions(), page=2, limit=3)
    assert res["total_matrix_rows"] == 10
    assert res["returned_rows"] == 3
    assert res["page"] == 2
    # Rows are ordered alphabetically: page 2 (limit 3) -> OG03..OG05.
    ids = [r["orthogroup_id"] for r in res["rows"]]
    assert ids == ["OG03", "OG04", "OG05"]


# ---------------------------------------------------------------------------
# Export consistency
# ---------------------------------------------------------------------------
def test_export_matches_preview():
    rows = [
        _row("OG1", "sA", "s1", "10", seed_peg="p1", gene="gX",
             product="prot X"),
        _row("OG1", "sB", "s2", "20", seed_peg="p2"),
        _row("OG2", "sA", "s1", "5", seed_peg="p3"),
    ]
    db = make_db(rows)
    opts = MatrixOptions(transformation="raw", missing_display="zero")

    preview = build_matrix(db, EXPR_SET, opts, page=1, limit=50)
    text, summary = build_matrix_export(db, EXPR_SET, opts, file_format="tsv")

    lines = text.strip().split("\n")
    header = lines[0].split("\t")
    # Metadata columns first, then sample columns.
    assert header[:6] == [
        "orthogroup_id", "gene", "product", "strains", "seed_pegs", "gene_count"
    ]
    assert header[6:] == preview["columns"]

    # Build a lookup of export values by orthogroup.
    export_by_og = {}
    for line in lines[1:]:
        parts = line.split("\t")
        export_by_og[parts[0]] = parts

    for row in preview["rows"]:
        og = row["orthogroup_id"]
        parts = export_by_og[og]
        for idx, col in enumerate(preview["columns"]):
            exported = parts[6 + idx]
            expected = row["values"][col]
            # missing_display=zero -> both should be 0.
            assert float(exported) == float(expected)


def test_export_csv_format():
    rows = [_row("OG1", "sA", "s1", "10")]
    db = make_db(rows)
    text, _ = build_matrix_export(
        db, EXPR_SET, MatrixOptions(), file_format="csv"
    )
    assert "," in text.split("\n")[0]


def test_detect_duplicates_helper():
    import pandas as pd
    df = pd.DataFrame([
        {"orthogroup_id": "OG1", "strain": "sA", "seed_peg": "p1",
         "sample_id": "s1", "count": 1.0, "condition": None,
         "replicate": None, "gene": None, "product": None},
        {"orthogroup_id": "OG1", "strain": "sA", "seed_peg": "p1",
         "sample_id": "s1", "count": 2.0, "condition": None,
         "replicate": None, "gene": None, "product": None},
    ])
    extra, examples = detect_duplicates(df)
    assert extra == 1
    assert len(examples) == 1
