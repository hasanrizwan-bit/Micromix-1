#--------------------------------
# Phase 2A regression tests for the orthology expression matrix builder
#--------------------------------
#
# Purpose: freeze a validated numerical reference for
# orthology.expression_matrix (and the reference-strain display helpers in
# orthology.storage) BEFORE any performance optimization.
#
# Every expected value below is specified independently by hand (literal
# numbers or explicit arithmetic on hand-listed counts), NOT by calling the
# implementation. Data are small, deterministic, and served by the in-memory
# FakeDB (no MongoDB needed).
#
# Two kinds of tests live here:
#   * Reference tests (normal): pin current behaviour that matches the
#     documented / scientifically expected semantics. Any optimization must keep
#     these green.
#   * Specification tests marked xfail(strict=True): encode the behaviour the
#     module's own documentation (or basic scientific expectation) promises but
#     the current implementation does NOT deliver. They are documented in
#     SCALABILITY_REGRESSION_TEST_RESULTS.md. strict=True means that if a future
#     change alters that behaviour the suite flags it (XPASS -> failure), so the
#     change cannot slip in silently.
#
# Run with:
#   ~/Micromix-1/Website/backend/venv/bin/python -m pytest orthology/tests -q

import csv
import io
import math

import pytest

from orthology.expression_matrix import (
    MAX_PAGE_LIMIT,
    DEFAULT_PAGE_LIMIT,
    ExpressionMatrixError,
    MatrixOptions,
    build_matrix,
    build_matrix_export,
)
from orthology.schema import (
    COLLECTION_NAME,
    EXPRESSION_COLLECTION_NAME,
    EXPRESSION_IMPORTS_COLLECTION_NAME,
    IMPORTS_COLLECTION_NAME,
)
from orthology.storage import (
    MISSING_REFERENCE_LABEL,
    get_reference_preview,
    get_reference_strains,
)
from orthology.tests.fake_db import FakeDB


EXPR_SET = "es_reg"
REF_ID = "ref_reg"
NAN = float("nan")

# Sample columns (lexicographic order == expected column order).
A1, A2, A3 = "sA_c1_r1", "sA_c1_r2", "sA_c2_r1"
B1, B2 = "sB_c1_r1", "sB_c1_r2"
COLS = [A1, A2, A3, B1, B2]

SAMPLE_META = {
    A1: ("sA", "c1", "1"),
    A2: ("sA", "c1", "2"),
    A3: ("sA", "c2", "1"),
    B1: ("sB", "c1", "1"),
    B2: ("sB", "c1", "2"),
}


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


def _gene_rows(og, seed_peg, counts, gene=None, product=None):
    """One row per sample for a single gene. counts: {sample_id: count}."""
    out = []
    for sample, count in counts.items():
        strain, cond, rep = SAMPLE_META[sample]
        out.append(_row(og, strain, sample, count, condition=cond,
                        replicate=rep, seed_peg=seed_peg, gene=gene,
                        product=product))
    return out


# ---------------------------------------------------------------------------
# Canonical synthetic dataset
# ---------------------------------------------------------------------------
# Two strains (sA, sB); sA has samples A1, A2 (condition c1, reps 1/2) and A3
# (condition c2); sB has B1, B2 (condition c1, reps 1/2).
#
#   OG1: sA p1 (gA1, "kinase A")       A1=10 A2=20 A3=30
#        sB q1 (gB1, "kinase B")       B1=5  B2=15
#   OG2: sA p2 (dupA, "transporter")   A1=4  A2=6  A3=8      <- sA paralogs
#        sA p3 (-, "transporter copy") A1=2  A2=10 A3=0
#        sB q2 (dupB, -)               B1=1  B2=3
#   OG3: sA p4 (soloA, "sA-only")      A1=7        A3=1      <- A2 absent
#   OG4: sB q4 (-, -)                  B1=9                  <- sA-absent
#
# Counts are stored as strings (as the importer does).
def canonical_rows():
    rows = []
    rows += _gene_rows("OG1", "p1", {A1: "10", A2: "20", A3: "30"},
                       gene="gA1", product="kinase A")
    rows += _gene_rows("OG1", "q1", {B1: "5", B2: "15"},
                       gene="gB1", product="kinase B")
    rows += _gene_rows("OG2", "p2", {A1: "4", A2: "6", A3: "8"},
                       gene="dupA", product="transporter")
    rows += _gene_rows("OG2", "p3", {A1: "2", A2: "10", A3: "0"},
                       product="transporter copy")
    rows += _gene_rows("OG2", "q2", {B1: "1", B2: "3"}, gene="dupB")
    rows += _gene_rows("OG3", "p4", {A1: "7", A3: "1"},
                       gene="soloA", product="sA-only")
    rows += _gene_rows("OG4", "q4", {B1: "9"})
    return rows


# Orthogroup reference table (one doc per strain-specific gene). OG5 exists in
# the reference but has NO expression rows.
def reference_docs():
    def ref(og, strain, peg, gene=None, product=None, locus=None, **extra):
        d = {"import_id": REF_ID, "orthogroup_id": og, "strain": strain,
             "seed_peg": peg, "gene": gene, "product": product,
             "locus_tag": locus}
        d.update(extra)
        return d
    return [
        ref("OG1", "sA", "p1", "gA1", "kinase A", "A_0001"),
        ref("OG1", "sB", "q1", "gB1", "kinase B", "B_0001"),
        ref("OG2", "sA", "p2", "dupA", "transporter", "A_0002"),
        ref("OG2", "sA", "p3", None, "transporter copy", "A_0003"),
        ref("OG2", "sB", "q2", "dupB", None, "B_0002"),
        ref("OG3", "sA", "p4", "soloA", "sA-only", "A_0004"),
        ref("OG4", "sB", "q4", None, None, "B_0004"),
        ref("OG5", "sA", "p5", "refOnly", "reference only", "A_0005"),
    ]


def make_db(rows=None, ref_summary=None, refs=None):
    return FakeDB({
        EXPRESSION_COLLECTION_NAME: canonical_rows() if rows is None else rows,
        EXPRESSION_IMPORTS_COLLECTION_NAME: [
            {"expression_set_id": EXPR_SET, "reference_import_id": REF_ID}
        ],
        IMPORTS_COLLECTION_NAME: [
            {"import_id": REF_ID, "summary": ref_summary or {}}
        ],
        COLLECTION_NAME: reference_docs() if refs is None else refs,
    })


# Independently specified raw matrices (paralog rule varies only OG2/sA).
RAW_SUM = {
    "OG1": [10, 20, 30, 5, 15],
    "OG2": [6, 16, 8, 1, 3],          # p2 + p3 in sA
    "OG3": [7, NAN, 1, NAN, NAN],
    "OG4": [NAN, NAN, NAN, 9, NAN],
}
RAW_MEAN = dict(RAW_SUM, OG2=[3, 8, 4, 1, 3])     # (4+2)/2, (6+10)/2, (8+0)/2
RAW_MAX = dict(RAW_SUM, OG2=[4, 10, 8, 1, 3])
RAW_BY_RULE = {"sum": RAW_SUM, "mean": RAW_MEAN, "max": RAW_MAX,
               "keep_separate": RAW_SUM}
EXPECTED_ROWS = ["OG1", "OG2", "OG3", "OG4"]
EXPECTED_MISSING = 7  # OG3: A2,B1,B2 ; OG4: A1,A2,A3,B2


def _cpm(raw):
    """Hand CPM: count / column total * 1e6, NaN ignored in the total."""
    totals = []
    for j in range(len(COLS)):
        vals = [raw[og][j] for og in raw if not math.isnan(raw[og][j])]
        totals.append(sum(vals))
    out = {}
    for og, vals in raw.items():
        out[og] = [NAN if math.isnan(v) else v / totals[j] * 1e6
                   for j, v in enumerate(vals)]
    return out


def _log2p1(m):
    return {og: [NAN if math.isnan(v) else math.log2(v + 1) for v in vals]
            for og, vals in m.items()}


def _expected(transformation, paralog_rule="sum"):
    raw = RAW_BY_RULE[paralog_rule]
    if transformation == "raw":
        return raw
    if transformation == "log2_count":
        return _log2p1(raw)
    if transformation == "cpm":
        return _cpm(raw)
    if transformation == "log2_cpm":
        return _log2p1(_cpm(raw))
    raise AssertionError(transformation)


def _close(actual, expected, tol):
    if expected is None or (isinstance(expected, float) and math.isnan(expected)):
        return actual is None or (isinstance(actual, float) and math.isnan(actual))
    if actual is None or (isinstance(actual, float) and math.isnan(actual)):
        return False
    return abs(float(actual) - float(expected)) <= tol


def _assert_preview_matches(res, expected, tol=1e-4, missing=None):
    assert [r["orthogroup_id"] for r in res["rows"]] == list(expected.keys())
    for r in res["rows"]:
        for col, exp in zip(res["columns"], expected[r["orthogroup_id"]]):
            if isinstance(exp, float) and math.isnan(exp):
                exp = missing
            got = r["values"][col]
            assert _close(got, exp, tol), (r["orthogroup_id"], col, got, exp)


def _full_matrix(db, opts):
    return build_matrix(db, EXPR_SET, opts, for_export=True)


def _all_pages(db, opts, limit):
    rows, page = [], 1
    while True:
        res = build_matrix(db, EXPR_SET, opts, page=page, limit=limit)
        if not res["rows"]:
            return rows, res
        rows.extend(res["rows"])
        page += 1


def _parse_export(text, sep):
    return list(csv.reader(io.StringIO(text), delimiter=sep))


# ===========================================================================
# 1. Orthogroup-to-gene mapping
# ===========================================================================
def test_orthogroup_gene_mapping_metadata():
    res = build_matrix(make_db(), EXPR_SET, MatrixOptions())
    meta = {r["orthogroup_id"]: r for r in res["rows"]}

    assert meta["OG1"]["strains"] == ["sA", "sB"]
    assert meta["OG1"]["seed_pegs"] == {"sA": ["p1"], "sB": ["q1"]}
    assert meta["OG1"]["gene_count"] == 2
    assert meta["OG1"]["has_paralog"] is False
    assert meta["OG1"]["multi_strain"] is True

    assert meta["OG2"]["seed_pegs"] == {"sA": ["p2", "p3"], "sB": ["q2"]}
    assert meta["OG2"]["gene_count"] == 3
    assert meta["OG2"]["has_paralog"] is True
    assert meta["OG2"]["multi_strain"] is True

    assert meta["OG3"]["strains"] == ["sA"]
    assert meta["OG3"]["seed_pegs"] == {"sA": ["p4"]}
    assert meta["OG3"]["gene_count"] == 1
    assert meta["OG3"]["multi_strain"] is False

    assert meta["OG4"]["strains"] == ["sB"]
    assert meta["OG4"]["seed_pegs"] == {"sB": ["q4"]}

    s = res["summary"]
    assert s["orthogroups_multi_strain"] == 2      # OG1, OG2
    assert s["orthogroups_with_paralogs"] == 1     # OG2
    assert s["source_row_count"] == 16   # 5 + 8 + 2 + 1 expression rows
    assert s["matrix_row_count"] == 4
    assert s["matrix_column_count"] == 5


def test_orthogroup_present_in_reference_but_absent_from_expression_not_in_matrix():
    # OG5 is in the reference table only; the matrix is built purely from
    # expression rows, so OG5 must not appear (not even as an all-missing row).
    res = build_matrix(make_db(), EXPR_SET, MatrixOptions())
    assert "OG5" not in [r["orthogroup_id"] for r in res["rows"]]
    assert res["total_matrix_rows"] == 4


# ===========================================================================
# 2. Reference-strain selection and displayed annotations
# ===========================================================================
def test_reference_strains_from_summary_and_fallback():
    db = make_db(ref_summary={"strain_names": ["sB", "Pa.PA14", "sA"]})
    out = get_reference_strains(db, REF_ID)
    assert out["strains"] == ["sB", "Pa.PA14", "sA"]   # manifest order kept
    assert out["default_strain"] == "Pa.PA14"          # PA14 preferred

    db = make_db()  # no summary -> distinct() fallback, sorted
    out = get_reference_strains(db, REF_ID)
    assert out["strains"] == ["sA", "sB"]
    assert out["default_strain"] == "sA"

    assert get_reference_strains(db, "nope") is None


def test_reference_preview_strain_sA():
    res = get_reference_preview(make_db(), REF_ID, "sA", page=1, limit=50)
    assert res["total_orthogroups"] == 5
    assert res["summary"] == {
        "reference_strain": "sA",
        "orthogroups_total": 5,
        "orthogroups_with_member": 4,    # OG1, OG2, OG3, OG5
        "orthogroups_missing": 1,        # OG4
        "orthogroups_with_paralogs": 1,  # OG2 (p2, p3)
    }
    rows = {r["orthogroup_id"]: r for r in res["rows"]}
    assert [r["orthogroup_id"] for r in res["rows"]] == \
        ["OG1", "OG2", "OG3", "OG4", "OG5"]

    og1 = rows["OG1"]
    assert og1["reference_seed_peg"] == "p1"
    assert og1["reference_locus_tag"] == "A_0001"
    assert og1["reference_gene"] == "gA1"
    assert og1["reference_product"] == "kinase A"
    assert og1["reference_label"] == "p1"
    assert og1["copies_in_reference_strain"] == 1
    assert og1["species_count"] == 2
    assert og1["gene_count"] == 2
    assert og1["present_count"] == 2
    assert og1["has_paralog_in_reference"] is False

    og2 = rows["OG2"]
    assert og2["reference_seed_peg"] == "p2; p3"
    assert og2["reference_locus_tag"] == "A_0002; A_0003"
    assert og2["reference_gene"] == "dupA"        # p3 has no gene
    assert og2["reference_product"] == "transporter; transporter copy"
    assert og2["reference_label"] == "p2 (+1 copies)"
    assert og2["copies_in_reference_strain"] == 2
    assert og2["gene_count"] == 3
    assert og2["has_paralog_in_reference"] is True

    og4 = rows["OG4"]
    assert og4["has_reference_member"] is False
    assert og4["reference_label"] == MISSING_REFERENCE_LABEL
    assert og4["reference_seed_peg"] is None
    assert og4["copies_in_reference_strain"] == 0
    assert og4["orthogroup_id"] == "OG4"          # id never lost


def test_reference_preview_strain_sB_and_pagination():
    db = make_db()
    res = get_reference_preview(db, REF_ID, "sB", page=1, limit=50)
    rows = {r["orthogroup_id"]: r for r in res["rows"]}
    assert rows["OG1"]["reference_gene"] == "gB1"
    assert rows["OG1"]["reference_product"] == "kinase B"
    assert rows["OG2"]["reference_seed_peg"] == "q2"
    assert rows["OG2"]["has_paralog_in_reference"] is False
    assert rows["OG3"]["reference_label"] == MISSING_REFERENCE_LABEL
    assert rows["OG5"]["reference_label"] == MISSING_REFERENCE_LABEL
    assert res["summary"]["orthogroups_with_member"] == 3   # OG1, OG2, OG4

    p1 = get_reference_preview(db, REF_ID, "sB", page=1, limit=2)
    p2 = get_reference_preview(db, REF_ID, "sB", page=2, limit=2)
    p3 = get_reference_preview(db, REF_ID, "sB", page=3, limit=2)
    ids = [r["orthogroup_id"] for p in (p1, p2, p3) for r in p["rows"]]
    assert ids == ["OG1", "OG2", "OG3", "OG4", "OG5"]
    assert [r for p in (p1, p2, p3) for r in p["rows"]] == res["rows"]


def test_reference_preview_copies_in_strain_column_flags_paralog():
    refs = [{"import_id": REF_ID, "orthogroup_id": "OGX", "strain": "sA",
             "seed_peg": "px", "copies_in_strain": "3"}]
    res = get_reference_preview(make_db(refs=refs), REF_ID, "sA")
    row = res["rows"][0]
    assert row["copies_in_reference_strain"] == 3
    assert row["has_paralog_in_reference"] is True
    assert row["reference_label"] == "px (+2 copies)"


def test_matrix_annotation_is_first_loaded_row_not_reference_strain():
    # CURRENT BEHAVIOUR (documented ambiguity): the matrix builder has no
    # reference-strain option. gene/product = first non-null value in load
    # (insertion) order across ALL strains.
    res = build_matrix(make_db(), EXPR_SET, MatrixOptions())
    meta = {r["orthogroup_id"]: r for r in res["rows"]}
    assert (meta["OG1"]["gene"], meta["OG1"]["product"]) == ("gA1", "kinase A")
    # OG2: p2 has gene dupA + product transporter; p3/q2 later.
    assert (meta["OG2"]["gene"], meta["OG2"]["product"]) == ("dupA", "transporter")
    assert (meta["OG4"]["gene"], meta["OG4"]["product"]) == (None, None)

    # Same data, sB rows inserted first -> annotation switches to sB. This
    # order-dependence must be preserved (or deliberately fixed) by any
    # optimization that changes query/aggregation order.
    rows = canonical_rows()
    rows = [r for r in rows if r["strain"] == "sB"] + \
           [r for r in rows if r["strain"] == "sA"]
    res2 = build_matrix(make_db(rows), EXPR_SET, MatrixOptions())
    meta2 = {r["orthogroup_id"]: r for r in res2["rows"]}
    assert (meta2["OG1"]["gene"], meta2["OG1"]["product"]) == ("gB1", "kinase B")
    # OG2: q2 gene dupB (no product) -> product falls through to p2.
    assert (meta2["OG2"]["gene"], meta2["OG2"]["product"]) == ("dupB", "transporter")
    # Numerical values are unaffected by row order.
    _assert_preview_matches(res2, RAW_SUM)


# ===========================================================================
# 3. Raw matrix, paralog aggregation (sum / mean / max / keep_separate)
# ===========================================================================
@pytest.mark.parametrize("rule", ["sum", "mean", "max", "keep_separate"])
def test_raw_matrix_paralog_rules(rule):
    res = build_matrix(make_db(), EXPR_SET, MatrixOptions(paralog_rule=rule))
    assert res["columns"] == COLS
    _assert_preview_matches(res, RAW_BY_RULE[rule], tol=0)
    assert res["summary"]["paralog_rule"] == rule
    assert res["summary"]["missing_value_count"] == EXPECTED_MISSING


def test_cross_strain_cell_is_sum_of_strain_values_when_samples_shared():
    # If two strains ever shared a sample_id, the cell is the SUM of the
    # per-strain (paralog-collapsed) values. paralog mean applies per strain:
    # sA mean(10, 30)=20, sB 7 -> 27.
    rows = [
        _row("OG1", "sA", "s1", "10", seed_peg="a1"),
        _row("OG1", "sA", "s1", "30", seed_peg="a2"),
        _row("OG1", "sB", "s1", "7", seed_peg="b1"),
    ]
    db = make_db(rows)
    assert build_matrix(db, EXPR_SET, MatrixOptions(paralog_rule="mean")
                        )["rows"][0]["values"]["s1"] == 27
    assert build_matrix(db, EXPR_SET, MatrixOptions(paralog_rule="max")
                        )["rows"][0]["values"]["s1"] == 37
    assert build_matrix(db, EXPR_SET, MatrixOptions(paralog_rule="sum")
                        )["rows"][0]["values"]["s1"] == 47


def test_paralog_mean_float_rounding_preview_vs_export():
    # mean(1, 1, 2) = 4/3. Preview rounds to 4 dp, export to 6 dp.
    rows = [_row("OG1", "sA", "s1", c, seed_peg=p)
            for p, c in (("a", "1"), ("b", "1"), ("c", "2"))]
    db = make_db(rows)
    opts = MatrixOptions(paralog_rule="mean")
    assert build_matrix(db, EXPR_SET, opts)["rows"][0]["values"]["s1"] == 1.3333
    full = _full_matrix(db, opts)["matrix"]
    assert abs(full.loc["OG1", "s1"] - 4.0 / 3.0) < 1e-12
    text, _ = build_matrix_export(db, EXPR_SET, opts)
    assert _parse_export(text, "\t")[1][-1] == "1.333333"


def test_paralog_mean_skips_missing_member():
    # CURRENT BEHAVIOUR (ambiguity): a paralog with an unparseable/NA count is
    # ignored by mean/max/sum (pandas skipna), not treated as 0.
    rows = [_row("OG1", "sA", "s1", "NA", seed_peg="p1"),
            _row("OG1", "sA", "s1", "10", seed_peg="p2")]
    db = make_db(rows)
    for rule in ("sum", "mean", "max", "keep_separate"):
        res = build_matrix(db, EXPR_SET, MatrixOptions(paralog_rule=rule))
        assert res["rows"][0]["values"]["s1"] == 10, rule


# ===========================================================================
# 4. Replicate aggregation (mean / median)
# ===========================================================================
AGG_COLS = ["sA | c1 | {r}", "sA | c2 | {r}", "sB | c1 | {r}"]
# Raw (paralog sum) aggregated per (strain, condition); NaN skipped.
AGG_RAW = {
    "OG1": [15, 30, 10],    # mean(10,20), 30, mean(5,15)
    "OG2": [11, 8, 2],      # mean(6,16), 8, mean(1,3)
    "OG3": [7, 1, NAN],     # mean(7, NaN) = 7  (missing replicate skipped)
    "OG4": [NAN, NAN, 9],   # mean(9, NaN) = 9
}


@pytest.mark.parametrize("rule", ["mean", "median"])
def test_replicate_aggregation_values_and_columns(rule):
    res = build_matrix(make_db(), EXPR_SET,
                       MatrixOptions(replicate_aggregation=rule))
    cols = [c.format(r=rule) for c in AGG_COLS]
    assert res["columns"] == cols
    _assert_preview_matches(res, AGG_RAW, tol=0)
    assert res["column_info"][cols[0]]["samples"] == [A1, A2]
    assert res["column_info"][cols[1]]["samples"] == [A3]
    assert res["column_info"][cols[2]]["samples"] == [B1, B2]
    assert res["summary"]["missing_value_count"] == 3   # OG3/sB, OG4/sA x2


def test_replicate_median_odd_count_differs_from_mean():
    rows = [_row("OG1", "sA", s, c, condition="c")
            for s, c in (("s1", "1"), ("s2", "2"), ("s3", "9"))]
    db = make_db(rows)
    med = build_matrix(db, EXPR_SET, MatrixOptions(replicate_aggregation="median"))
    mean = build_matrix(db, EXPR_SET, MatrixOptions(replicate_aggregation="mean"))
    assert med["rows"][0]["values"]["sA | c | median"] == 2
    assert mean["rows"][0]["values"]["sA | c | mean"] == 4


def test_replicate_without_condition_grouped_under_placeholder():
    rows = [_row("OG1", "sA", "s1", "4"), _row("OG1", "sA", "s2", "8")]
    res = build_matrix(make_db(rows), EXPR_SET,
                       MatrixOptions(replicate_aggregation="mean"))
    assert res["columns"] == ["sA | (no condition) | mean"]
    assert res["rows"][0]["values"]["sA | (no condition) | mean"] == 6


def test_replicate_mean_then_cpm_current_order():
    # CURRENT BEHAVIOUR: raw counts are averaged across replicates FIRST, and
    # CPM is computed on the averaged column.
    # A1 col (OG1..OG4) = 15, 11, 7, NaN -> total 33
    res = build_matrix(make_db(), EXPR_SET, MatrixOptions(
        replicate_aggregation="mean", transformation="cpm"))
    v = {r["orthogroup_id"]: r["values"]["sA | c1 | mean"] for r in res["rows"]}
    assert _close(v["OG1"], 15 / 33 * 1e6, 1e-4)
    assert _close(v["OG2"], 11 / 33 * 1e6, 1e-4)
    assert _close(v["OG3"], 7 / 33 * 1e6, 1e-4)
    assert v["OG4"] is None


@pytest.mark.xfail(strict=True, reason=(
    "Module header says CPM is computed per sample BEFORE replicate "
    "aggregation; build_matrix aggregates raw counts first. See results doc "
    "issue I-3."))
def test_spec_cpm_computed_per_sample_before_replicate_aggregation():
    res = build_matrix(make_db(), EXPR_SET, MatrixOptions(
        replicate_aggregation="mean", transformation="cpm"))
    v = {r["orthogroup_id"]: r["values"]["sA | c1 | mean"] for r in res["rows"]}
    cpm = _cpm(RAW_SUM)
    expected_og1 = (cpm["OG1"][0] + cpm["OG1"][1]) / 2  # mean of A1, A2 CPMs
    assert _close(v["OG1"], expected_og1, 1e-3)


# ===========================================================================
# 5. Missing values and absent orthogroups
# ===========================================================================
def test_missing_display_blank_vs_zero_full_matrix():
    blank = build_matrix(make_db(), EXPR_SET, MatrixOptions(missing_display="blank"))
    zero = build_matrix(make_db(), EXPR_SET, MatrixOptions(missing_display="zero"))
    _assert_preview_matches(blank, RAW_SUM, tol=0, missing=None)
    _assert_preview_matches(zero, RAW_SUM, tol=0, missing=0)
    assert blank["summary"]["missing_value_count"] == EXPECTED_MISSING
    assert zero["summary"]["missing_value_count"] == EXPECTED_MISSING


def test_missing_stays_missing_after_transformations():
    for t in ("log2_count", "cpm", "log2_cpm"):
        res = build_matrix(make_db(), EXPR_SET, MatrixOptions(transformation=t))
        row = {r["orthogroup_id"]: r for r in res["rows"]}["OG3"]
        assert row["values"][A2] is None, t     # not log2(0+1)=0
        assert row["values"][B1] is None, t
        z = build_matrix(make_db(), EXPR_SET,
                         MatrixOptions(transformation=t, missing_display="zero"))
        assert {r["orthogroup_id"]: r for r in z["rows"]}["OG3"]["values"][A2] == 0


def test_true_zero_count_is_not_missing():
    # p3 A3 = "0" is a real zero; OG2 A3 under paralog max = max(8, 0) = 8 and
    # under log2_count p3-only would be 0. Check a lone zero directly.
    rows = [_row("OG1", "sA", "s1", "0"), _row("OG2", "sA", "s1", "5")]
    res = build_matrix(make_db(rows), EXPR_SET, MatrixOptions())
    assert res["rows"][0]["values"]["s1"] == 0
    assert res["summary"]["missing_value_count"] == 0


def test_all_columns_zero_cpm_is_missing():
    rows = [_row("OG1", "sA", "s1", "0"), _row("OG1", "sA", "s2", "4")]
    res = build_matrix(make_db(rows), EXPR_SET, MatrixOptions(transformation="cpm"))
    assert res["rows"][0]["values"] == {"s1": None, "s2": 1000000}
    assert res["summary"]["cpm_column_totals"] == {"s1": 0.0, "s2": 1000000.0}


@pytest.mark.xfail(strict=True, reason=(
    "Explicitly NULL/unparseable count for a present (og, sample) is turned "
    "into 0 by pivot_table(aggfunc='sum'), contradicting 'missing never "
    "silently coerced to 0'. See results doc issue I-1."))
def test_spec_null_count_cell_stays_missing():
    rows = [_row("OG1", "sA", "s1", None, seed_peg="p1"),
            _row("OG2", "sA", "s1", "4", seed_peg="p2")]
    res = build_matrix(make_db(rows), EXPR_SET, MatrixOptions())
    assert res["rows"][0]["values"]["s1"] is None
    assert res["summary"]["missing_value_count"] == 1


@pytest.mark.xfail(strict=True, reason=(
    "Null count coerced to 0 also distorts log2 / CPM (log2(0+1)=0 shown "
    "instead of missing). See results doc issue I-1."))
def test_spec_null_count_cell_missing_after_log2_cpm():
    rows = [_row("OG1", "sA", "s1", "", seed_peg="p1"),
            _row("OG2", "sA", "s1", "4", seed_peg="p2")]
    res = build_matrix(make_db(rows), EXPR_SET,
                       MatrixOptions(transformation="log2_cpm"))
    assert res["rows"][0]["values"]["s1"] is None


# ===========================================================================
# 6. Duplicate expression measurements
# ===========================================================================
def _dup_rows():
    # (OG1, sA, p1, s1) appears 3x: 10, 5, 3. Paralog p2 = 4. s2 not duplicated.
    return [
        _row("OG1", "sA", "s1", "10", seed_peg="p1", gene=None),
        _row("OG1", "sA", "s1", "5", seed_peg="p1", gene="late_gene"),
        _row("OG1", "sA", "s1", "3", seed_peg="p1"),
        _row("OG1", "sA", "s1", "4", seed_peg="p2"),
        _row("OG1", "sA", "s2", "10", seed_peg="p1"),
    ]


@pytest.mark.parametrize("dup_rule,paralog_rule,expected_s1", [
    ("sum", "sum", 22),       # (10+5+3) + 4
    ("mean", "sum", 10),      # 6 + 4
    ("first", "sum", 14),     # 10 + 4
    ("sum", "max", 18),       # max(18, 4)
    ("mean", "mean", 5),      # mean(6, 4)
    ("first", "max", 10),     # max(10, 4)
])
def test_duplicate_rules(dup_rule, paralog_rule, expected_s1):
    res = build_matrix(make_db(_dup_rows()), EXPR_SET, MatrixOptions(
        duplicate_rule=dup_rule, paralog_rule=paralog_rule))
    assert res["rows"][0]["values"] == {"s1": expected_s1, "s2": 10}
    s = res["summary"]
    assert s["duplicate_key_count"] == 2
    assert s["duplicate_examples"] == [
        {"orthogroup_id": "OG1", "strain": "sA", "seed_peg": "p1",
         "sample_id": "s1"}]
    # Duplicates are not paralogs: still 2 genes (p1, p2).
    assert res["rows"][0]["gene_count"] == 2
    assert res["rows"][0]["gene"] == "late_gene"   # first non-null kept


def test_same_gene_different_samples_not_duplicates():
    res = build_matrix(make_db(), EXPR_SET, MatrixOptions())
    assert res["summary"]["duplicate_key_count"] == 0
    assert res["summary"]["duplicate_examples"] == []


def test_rows_without_seed_peg_collapse_as_duplicates_when_mixed():
    # CURRENT BEHAVIOUR (ambiguity, issue I-5): when SOME rows have seed_peg,
    # rows lacking it share a NaN seed_peg key and are treated as duplicates of
    # each other (30 + 5 = 35) rather than as distinct genes.
    rows = [_row("OG1", "sA", "s1", "10", seed_peg="p1"),
            _row("OG1", "sA", "s1", "30"),
            _row("OG1", "sA", "s1", "5")]
    res = build_matrix(make_db(rows), EXPR_SET, MatrixOptions(paralog_rule="max"))
    assert res["summary"]["duplicate_key_count"] == 1
    assert res["rows"][0]["values"]["s1"] == 35
    assert res["rows"][0]["gene_count"] == 1


@pytest.mark.xfail(strict=True, raises=KeyError, reason=(
    "When no row has a seed_peg and a duplicate key exists, "
    "_resolve_duplicates drops the seed_peg column and _build_row_metadata "
    "raises KeyError('seed_peg') -> HTTP 500. See results doc issue I-2."))
def test_spec_duplicates_without_seed_peg_do_not_crash():
    rows = [_row("OG1", "sA", "s1", "10"), _row("OG1", "sA", "s1", "30")]
    res = build_matrix(make_db(rows), EXPR_SET, MatrixOptions())
    assert res["rows"][0]["values"]["s1"] == 40


# ===========================================================================
# 7. CPM and log2(CPM + 1) normalization
# ===========================================================================
@pytest.mark.parametrize("transformation", ["raw", "log2_count", "cpm", "log2_cpm"])
@pytest.mark.parametrize("rule", ["sum", "mean", "max"])
def test_transformations_full_matrix(transformation, rule):
    db = make_db()
    opts = MatrixOptions(transformation=transformation, paralog_rule=rule)
    expected = _expected(transformation, rule)

    # Unrounded internal matrix: tight tolerance.
    full = _full_matrix(db, opts)
    m = full["matrix"]
    assert full["ordered_orthogroups"] == EXPECTED_ROWS
    assert list(m.columns) == COLS
    for og in EXPECTED_ROWS:
        for j, col in enumerate(COLS):
            assert _close(m.loc[og, col], expected[og][j], 1e-9), (og, col)

    # Preview (rounded to 4 dp).
    res = build_matrix(db, EXPR_SET, opts)
    _assert_preview_matches(res, expected, tol=5.1e-5)


def test_cpm_hand_values_and_totals():
    # Column totals (paralog sum): A1=23, A2=36, A3=39, B1=15, B2=18.
    res = build_matrix(make_db(), EXPR_SET, MatrixOptions(transformation="cpm"))
    v = {r["orthogroup_id"]: r["values"] for r in res["rows"]}
    assert v["OG1"][A1] == 434782.6087       # 10/23e6
    assert v["OG2"][A1] == 260869.5652       # 6/23e6
    assert v["OG3"][A1] == 304347.8261       # 7/23e6
    assert v["OG3"][A3] == 25641.0256        # 1/39e6
    assert v["OG4"][B1] == 600000            # 9/15e6 (integral -> int)
    assert v["OG1"][B2] == 833333.3333       # 15/18e6
    assert res["summary"]["cpm_column_totals"] == {c: 1000000.0 for c in COLS}
    assert res["summary"]["transformation_label"] == "CPM"


def test_log2_cpm_hand_values():
    res = build_matrix(make_db(), EXPR_SET, MatrixOptions(transformation="log2_cpm"))
    v = {r["orthogroup_id"]: r["values"] for r in res["rows"]}
    assert _close(v["OG4"][B1], math.log2(600001), 1e-4)        # 19.194...
    assert _close(v["OG1"][A1], math.log2(10 / 23 * 1e6 + 1), 1e-4)
    # cpm_column_totals report the PRE-log CPM totals.
    assert res["summary"]["cpm_column_totals"] == {c: 1000000.0 for c in COLS}
    assert res["summary"]["transformation_label"] == "log2(CPM + 1)"


def test_log2_count_hand_values():
    res = build_matrix(make_db(), EXPR_SET, MatrixOptions(transformation="log2_count"))
    v = {r["orthogroup_id"]: r["values"] for r in res["rows"]}
    assert v["OG1"][A3] == 4.9542      # log2(31)
    assert v["OG2"][B2] == 2           # log2(4)
    assert res["summary"]["cpm_column_totals"] is None


def test_cpm_library_size_depends_on_orthogroup_filter():
    # CURRENT BEHAVIOUR (issue I-4): CPM uses the total of the FILTERED rows.
    # With orthogroup_ids=[OG1, OG3] the A1 total is 10+7=17, not 23.
    res = build_matrix(make_db(), EXPR_SET, MatrixOptions(
        transformation="cpm", orthogroup_ids=["OG1", "OG3"]))
    v = {r["orthogroup_id"]: r["values"] for r in res["rows"]}
    assert _close(v["OG1"][A1], 10 / 17 * 1e6, 1e-4)
    assert _close(v["OG3"][A1], 7 / 17 * 1e6, 1e-4)


# ===========================================================================
# 8. Gene and sample filtering
# ===========================================================================
def test_filter_strain():
    res = build_matrix(make_db(), EXPR_SET, MatrixOptions(strains=["sB"]))
    assert res["columns"] == [B1, B2]
    _assert_preview_matches(res, {"OG1": [5, 15], "OG2": [1, 3],
                                  "OG4": [9, NAN]}, tol=0)
    # Strain-specific columns -> CPM identical to unfiltered for sB columns.
    cpm = build_matrix(make_db(), EXPR_SET,
                       MatrixOptions(strains=["sB"], transformation="cpm"))
    full = _cpm(RAW_SUM)
    _assert_preview_matches(cpm, {og: full[og][3:] for og in ("OG1", "OG2", "OG4")})


def test_filter_samples_drops_orthogroups_without_measurements():
    res = build_matrix(make_db(), EXPR_SET, MatrixOptions(samples=[A2, B1]))
    assert res["columns"] == [A2, B1]
    # OG3 has nothing in A2 or B1 -> absent row.
    _assert_preview_matches(res, {"OG1": [20, 5], "OG2": [16, 1],
                                  "OG4": [NAN, 9]}, tol=0)


def test_filter_condition_and_replicate():
    res = build_matrix(make_db(), EXPR_SET, MatrixOptions(conditions=["c2"]))
    assert res["columns"] == [A3]
    _assert_preview_matches(res, {"OG1": [30], "OG2": [8], "OG3": [1]}, tol=0)

    res = build_matrix(make_db(), EXPR_SET, MatrixOptions(replicates=["2"]))
    assert res["columns"] == [A2, B2]
    _assert_preview_matches(res, {"OG1": [20, 15], "OG2": [16, 3]}, tol=0)

    # Integer replicate in the request is stringified for the query.
    res = build_matrix(make_db(), EXPR_SET, MatrixOptions(replicates=[2]))
    assert res["columns"] == [A2, B2]


def test_filter_orthogroup_ids():
    res = build_matrix(make_db(), EXPR_SET,
                       MatrixOptions(orthogroup_ids=["OG3", "OG1"]))
    _assert_preview_matches(res, {"OG1": RAW_SUM["OG1"], "OG3": RAW_SUM["OG3"]},
                            tol=0)


def test_filter_search_case_insensitive_fields():
    db = make_db()
    def ids(search):
        return [r["orthogroup_id"] for r in
                build_matrix(db, EXPR_SET, MatrixOptions(search=search))["rows"]]
    assert ids("KINASE") == ["OG1"]       # product
    assert ids("solo") == ["OG3"]         # gene
    assert ids("q4") == ["OG4"]           # seed_peg
    assert ids("og2") == ["OG2"]          # orthogroup_id
    with pytest.raises(ExpressionMatrixError):
        build_matrix(db, EXPR_SET, MatrixOptions(search="zzz"))


def test_filter_search_is_row_level_current_behaviour():
    # CURRENT BEHAVIOUR (issue I-4): search filters individual expression rows,
    # not orthogroups. "dup" matches p2 (dupA) and q2 (dupB) but not paralog p3,
    # so p3's counts silently drop out of OG2 and the paralog flag disappears.
    res = build_matrix(make_db(), EXPR_SET, MatrixOptions(search="dup"))
    row = res["rows"][0]
    assert row["orthogroup_id"] == "OG2"
    assert row["values"] == {A1: 4, A2: 6, A3: 8, B1: 1, B2: 3}
    assert row["gene_count"] == 2
    assert row["has_paralog"] is False

    # Searching a strain-specific gene name drops the other strain's columns.
    res = build_matrix(make_db(), EXPR_SET, MatrixOptions(search="gA1"))
    assert res["columns"] == [A1, A2, A3]


def test_combined_filters_and_aggregation():
    res = build_matrix(make_db(), EXPR_SET, MatrixOptions(
        strains=["sA"], conditions=["c1"], replicate_aggregation="mean",
        paralog_rule="max"))
    assert res["columns"] == ["sA | c1 | mean"]
    # OG1 mean(10,20)=15; OG2 max-collapsed (4,10) -> mean 7; OG3 mean(7)=7
    _assert_preview_matches(res, {"OG1": [15], "OG2": [7], "OG3": [7]}, tol=0)


# ===========================================================================
# 9. Row ordering and column ordering
# ===========================================================================
def test_row_and_column_order_lexicographic_independent_of_insertion():
    rows = []
    for og in ("OG10", "OG2", "OG1", "og0", "OG9"):
        for s in ("s10", "s2", "S1"):
            rows.append(_row(og, "sA", s, "1"))
    res = build_matrix(make_db(list(reversed(rows))), EXPR_SET, MatrixOptions())
    # Plain string sort: uppercase before lowercase, "OG10" < "OG2".
    assert [r["orthogroup_id"] for r in res["rows"]] == \
        ["OG1", "OG10", "OG2", "OG9", "og0"]
    assert res["columns"] == ["S1", "s10", "s2"]


def test_aggregated_column_order_sorted_by_strain_then_condition():
    rows = [_row("OG1", st, smp, "1", condition=c)
            for st, smp, c in (("sB", "x1", "alpha"), ("sA", "x2", "zeta"),
                               ("sA", "x3", "beta"))]
    res = build_matrix(make_db(rows), EXPR_SET,
                       MatrixOptions(replicate_aggregation="mean"))
    assert res["columns"] == ["sA | beta | mean", "sA | zeta | mean",
                              "sB | alpha | mean"]


# ===========================================================================
# 10. Pagination consistency
# ===========================================================================
@pytest.mark.parametrize("limit", [1, 2, 3, 4, 50])
@pytest.mark.parametrize("opts_kw", [
    {}, {"transformation": "log2_cpm", "paralog_rule": "mean"},
    {"replicate_aggregation": "mean", "missing_display": "zero"},
])
def test_pages_concatenate_to_full_matrix(limit, opts_kw):
    db = make_db()
    opts = MatrixOptions(**opts_kw)
    one_page = build_matrix(db, EXPR_SET, opts, page=1, limit=50)
    paged, last = _all_pages(db, opts, limit)
    assert paged == one_page["rows"]
    assert len(paged) == 4
    # Summary is identical regardless of page.
    assert last["summary"] == one_page["summary"]
    assert last["columns"] == one_page["columns"]


def test_pagination_page_contents_and_bounds():
    db = make_db()
    p2 = build_matrix(db, EXPR_SET, MatrixOptions(), page=2, limit=3)
    assert [r["orthogroup_id"] for r in p2["rows"]] == ["OG4"]
    assert p2["returned_rows"] == 1 and p2["total_matrix_rows"] == 4

    beyond = build_matrix(db, EXPR_SET, MatrixOptions(), page=9, limit=3)
    assert beyond["rows"] == [] and beyond["total_matrix_rows"] == 4

    assert build_matrix(db, EXPR_SET, MatrixOptions(), page=0)["page"] == 1
    assert build_matrix(db, EXPR_SET, MatrixOptions(), page="x")["page"] == 1
    assert build_matrix(db, EXPR_SET, MatrixOptions(), limit=0)["limit"] == \
        DEFAULT_PAGE_LIMIT
    assert build_matrix(db, EXPR_SET, MatrixOptions(), limit="x")["limit"] == \
        DEFAULT_PAGE_LIMIT
    assert build_matrix(db, EXPR_SET, MatrixOptions(), limit=10**6)["limit"] == \
        MAX_PAGE_LIMIT


def test_pagination_does_not_change_cpm():
    # CPM uses whole-matrix column totals, not page totals.
    db = make_db()
    opts = MatrixOptions(transformation="cpm")
    page2 = build_matrix(db, EXPR_SET, opts, page=2, limit=1)
    assert page2["rows"][0]["orthogroup_id"] == "OG2"
    assert page2["rows"][0]["values"][A1] == 260869.5652   # 6/23e6


# ===========================================================================
# 11. Matrix export values
# ===========================================================================
EXPECTED_EXPORT_RAW_BLANK = [
    ["orthogroup_id", "gene", "product", "strains", "seed_pegs", "gene_count",
     A1, A2, A3, B1, B2],
    ["OG1", "gA1", "kinase A", "sA; sB", "sA:p1; sB:q1", "2",
     "10", "20", "30", "5", "15"],
    ["OG2", "dupA", "transporter", "sA; sB", "sA:p2,p3; sB:q2", "3",
     "6", "16", "8", "1", "3"],
    ["OG3", "soloA", "sA-only", "sA", "sA:p4", "1", "7", "", "1", "", ""],
    ["OG4", "", "", "sB", "sB:q4", "1", "", "", "", "9", ""],
]


def test_export_tsv_exact_raw_blank():
    text, summary = build_matrix_export(make_db(), EXPR_SET, MatrixOptions())
    assert _parse_export(text, "\t") == EXPECTED_EXPORT_RAW_BLANK
    assert summary["matrix_row_count"] == 4


def test_export_csv_equals_tsv_and_quotes_commas():
    db = make_db()
    tsv, _ = build_matrix_export(db, EXPR_SET, MatrixOptions(), file_format="tsv")
    csv_text, _ = build_matrix_export(db, EXPR_SET, MatrixOptions(),
                                      file_format="CSV")
    assert '"sA:p2,p3; sB:q2"' in csv_text
    assert _parse_export(csv_text, ",") == _parse_export(tsv, "\t")
    with pytest.raises(ExpressionMatrixError):
        build_matrix_export(db, EXPR_SET, MatrixOptions(), file_format="xlsx")


def test_export_missing_zero():
    text, _ = build_matrix_export(make_db(), EXPR_SET,
                                  MatrixOptions(missing_display="zero"))
    rows = _parse_export(text, "\t")
    assert rows[3][6:] == ["7", "0", "1", "0", "0"]
    assert rows[4][6:] == ["0", "0", "0", "9", "0"]


@pytest.mark.parametrize("opts_kw", [
    {"transformation": "cpm"},
    {"transformation": "log2_cpm", "paralog_rule": "max"},
    {"transformation": "log2_count", "paralog_rule": "mean"},
    {"replicate_aggregation": "median", "transformation": "cpm"},
    {"strains": ["sA"], "transformation": "log2_cpm", "missing_display": "zero"},
])
def test_export_equals_full_matrix_and_pages(opts_kw):
    db = make_db()
    opts = MatrixOptions(**opts_kw)
    full = _full_matrix(db, opts)
    text, _ = build_matrix_export(db, EXPR_SET, opts)
    exported = _parse_export(text, "\t")
    header, body = exported[0], exported[1:]
    assert header[6:] == full["columns"]
    assert [r[0] for r in body] == full["ordered_orthogroups"]

    pages, _ = _all_pages(db, opts, limit=2)
    by_og = {r["orthogroup_id"]: r for r in pages}
    missing_text = "0" if opts.missing_display == "zero" else ""
    for row in body:
        og = row[0]
        for col, cell in zip(header[6:], row[6:]):
            internal = full["matrix"].loc[og, col]
            preview = by_og[og]["values"][col]
            if isinstance(internal, float) and math.isnan(internal):
                # Zero-filled missing cells serialise as "0" in all-integer
                # columns but "0.0" in float columns (pandas dtype upcast);
                # compare numerically. Blank stays the empty string.
                if missing_text == "":
                    assert cell == ""
                else:
                    assert float(cell) == 0.0
                assert preview == (0 if missing_text == "0" else None)
            else:
                # export = round(x, 6); preview = round(x, 4)
                assert abs(float(cell) - internal) <= 5.1e-7
                assert abs(float(preview) - internal) <= 5.1e-5
                assert abs(float(cell) - float(preview)) <= 5.1e-5
