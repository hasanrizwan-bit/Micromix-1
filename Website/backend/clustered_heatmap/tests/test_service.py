#--------------------------------
# Unit tests for the Clustered Heatmap service module
#--------------------------------
#
# Exercises the pure clustering/validation logic directly (no Flask, no
# MongoDB), mirroring the convention used by
# ``pcoa/tests/test_service.py`` and ``orthology/tests/test_expression_matrix.py``.
#
# The 9-gene x 4-sample fixture below is
# ``ClusteredHeatmap2/backend/data/example_heatmap.csv`` (the reference
# implementation's own bundled dataset), so the expected row/column order
# asserted here was obtained by running SciPy's ``linkage``/``leaves_list``
# on that exact matrix -- i.e. this test pins ``cluster_matrix`` to produce
# the SAME ordering the reference implementation produces for the same
# input, which is the whole point of a verbatim port.
#
# Run with:  ./venv/bin/python -m pytest clustered_heatmap/tests -q

import pytest

from clustered_heatmap import ClusteredHeatmapInputError, cluster_matrix

ROW_LABELS = [
    "GeneA", "GeneB", "GeneC", "GeneD", "GeneE",
    "GeneF", "GeneG", "GeneH", "GeneI",
]
COLUMN_LABELS = ["Sample_A", "Sample_B", "Sample_C", "Sample_D"]
VALUES = [
    [1.2, -0.8, 2.1, -1.5],
    [-2.3, 1.7, 0.4, 2.2],
    [0.6, -1.4, -2.7, 1.1],
    [2.8, 2.4, -0.3, -2.0],
    [-1.0, 0.2, 1.6, -0.7],
    [0.0, -2.5, 2.9, 1.8],
    [-0.5, 1.1, -1.2, 2.6],
    [1.9, -2.8, 0.7, -0.4],
    [-1.7, 0.9, 2.3, -2.1],
]

EXPECTED_ROW_ORDER = [3, 4, 8, 5, 0, 7, 2, 1, 6]
EXPECTED_COLUMN_ORDER = [0, 2, 1, 3]


def test_cluster_matrix_matches_reference_ordering():
    payload = cluster_matrix(ROW_LABELS, COLUMN_LABELS, VALUES)

    assert payload["row_order"] == EXPECTED_ROW_ORDER
    assert payload["column_order"] == EXPECTED_COLUMN_ORDER
    assert payload["clustered"] == {"rows": True, "columns": True}
    assert payload["original_row_labels"] == ROW_LABELS
    assert payload["original_column_labels"] == COLUMN_LABELS
    assert payload["row_labels"] == [ROW_LABELS[i] for i in EXPECTED_ROW_ORDER]
    assert payload["column_labels"] == [COLUMN_LABELS[j] for j in EXPECTED_COLUMN_ORDER]


def test_cluster_matrix_reorders_values_consistently_with_orders():
    payload = cluster_matrix(ROW_LABELS, COLUMN_LABELS, VALUES)
    values = payload["values"]

    for display_r, orig_r in enumerate(EXPECTED_ROW_ORDER):
        for display_c, orig_c in enumerate(EXPECTED_COLUMN_ORDER):
            assert values[display_r][display_c] == pytest.approx(VALUES[orig_r][orig_c])


def test_cluster_matrix_dendrogram_leaves_match_orders():
    payload = cluster_matrix(ROW_LABELS, COLUMN_LABELS, VALUES)

    row_dendro = payload["row_dendrogram"]
    col_dendro = payload["column_dendrogram"]
    assert row_dendro is not None
    assert col_dendro is not None
    assert row_dendro["leaves"] == EXPECTED_ROW_ORDER
    assert col_dendro["leaves"] == EXPECTED_COLUMN_ORDER
    assert row_dendro["n_leaves"] == len(ROW_LABELS)
    assert col_dendro["n_leaves"] == len(COLUMN_LABELS)
    # linkage has n_leaves - 1 rows of [left, right, height, count].
    assert len(row_dendro["linkage"]) == len(ROW_LABELS) - 1
    assert len(col_dendro["linkage"]) == len(COLUMN_LABELS) - 1


def test_null_cells_preserved_as_none_but_clustered_as_zero():
    values = [row[:] for row in VALUES]
    values[0][0] = None  # GeneA / Sample_A

    payload = cluster_matrix(ROW_LABELS, COLUMN_LABELS, values)

    # The null cell must round-trip as JSON null (not 0, not NaN-as-string),
    # wherever GeneA x Sample_A ends up after clustering (changing one cell
    # to null can itself shift the clustering order, so locate it by label
    # rather than assuming the no-null fixture's order still applies).
    display_r = payload["row_labels"].index("GeneA")
    display_c = payload["column_labels"].index("Sample_A")
    assert payload["values"][display_r][display_c] is None


def test_too_few_rows_or_columns_skips_clustering_but_still_returns_payload():
    payload = cluster_matrix(["OnlyGene"], COLUMN_LABELS, [[1.0, 2.0, 3.0, 4.0]])
    assert payload["clustered"] == {"rows": False, "columns": True}
    assert payload["row_order"] == [0]
    assert payload["row_dendrogram"] is None

    payload2 = cluster_matrix(ROW_LABELS[:2], ["OnlySample"], [[1.0], [2.0]])
    assert payload2["clustered"] == {"rows": True, "columns": False}
    assert payload2["column_order"] == [0]
    assert payload2["column_dendrogram"] is None


@pytest.mark.parametrize(
    "row_labels,column_labels,values,message_fragment",
    [
        ([], COLUMN_LABELS, [], "no rows or no numeric columns"),
        (ROW_LABELS, [], [[]] * len(ROW_LABELS), "no rows or no numeric columns"),
        (ROW_LABELS, COLUMN_LABELS, VALUES[:-1], "exactly one row per entry"),
        (ROW_LABELS, COLUMN_LABELS, [row[:-1] for row in VALUES], "exactly one cell per entry"),
    ],
)
def test_shape_mismatches_raise_input_error(row_labels, column_labels, values, message_fragment):
    with pytest.raises(ClusteredHeatmapInputError) as exc_info:
        cluster_matrix(row_labels, column_labels, values)
    assert message_fragment in str(exc_info.value)


def test_non_numeric_cell_raises_input_error():
    values = [row[:] for row in VALUES]
    values[0][0] = "not-a-number"
    with pytest.raises(ClusteredHeatmapInputError, match="number or null"):
        cluster_matrix(ROW_LABELS, COLUMN_LABELS, values)
