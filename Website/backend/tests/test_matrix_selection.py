"""Tests for matrix_selection.select_matrix().

These are pure pandas-level tests (no Flask app, no MongoDB) mirroring the
style of pcoa/tests/test_service.py. They exercise the core row/column
subsetting primitive that backs the new `POST /matrix_selection` route used
by the Clustered Heatmap's "Apply Selection to Matrix" button.
"""

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from matrix_selection import MatrixSelectionError, select_matrix  # noqa: E402


N_GENES = 100
N_SAMPLES = 20


def make_matrix(n_genes=N_GENES, n_samples=N_SAMPLES):
    """Build a `(n_genes) genes x (n_samples) samples` dataframe using the
    same "(Title) sample" value-column convention the real app uses, plus a
    'gene' row-id column and one metadata column (to prove metadata always
    survives a sample-only selection, and is never treated as a sample)."""
    data = {"gene": [f"g{i}" for i in range(n_genes)]}
    data["annotation"] = [f"anno{i}" for i in range(n_genes)]
    for s in range(n_samples):
        col = f"(TitleA) sample{s}"
        data[col] = [float(i * 100 + s) for i in range(n_genes)]
    return pd.DataFrame(data)


def value_columns(df):
    return [c for c in df.columns if c.startswith("(") and ") " in c]


class TestNoOp:
    def test_both_none_is_passthrough(self):
        df = make_matrix()
        working_df, meta = select_matrix(df, row_ids=None, sample_ids=None)
        assert working_df is df
        assert meta == {"active_row_ids": None, "active_sample_ids": None}


class TestRowAndColumnIntersection:
    def test_100x20_select_25_genes_and_8_samples_yields_25x8(self):
        df = make_matrix(100, 20)
        row_ids = [f"g{i}" for i in range(25)]
        sample_ids = [f"(TitleA) sample{i}" for i in range(8)]

        working_df, meta = select_matrix(df, row_ids=row_ids, sample_ids=sample_ids)

        assert len(working_df) == 25
        assert value_columns(working_df) == sample_ids
        # Metadata column always survives regardless of sample selection.
        assert "annotation" in working_df.columns
        assert set(working_df["gene"]) == set(row_ids)
        assert meta["active_row_ids"] == row_ids
        assert meta["active_sample_ids"] == sample_ids
        assert meta["row_id_column"] == "gene"

    def test_row_only_selection_preserves_all_current_samples(self):
        df = make_matrix(100, 20)
        row_ids = [f"g{i}" for i in range(25)]

        working_df, meta = select_matrix(df, row_ids=row_ids, sample_ids=None)

        assert len(working_df) == 25
        assert value_columns(working_df) == value_columns(df)
        assert meta["active_sample_ids"] is None
        assert meta["active_row_ids"] == row_ids

    def test_column_only_selection_preserves_all_current_genes(self):
        df = make_matrix(100, 20)
        sample_ids = [f"(TitleA) sample{i}" for i in range(8)]

        working_df, meta = select_matrix(df, row_ids=None, sample_ids=sample_ids)

        assert len(working_df) == 100
        assert value_columns(working_df) == sample_ids
        assert meta["active_row_ids"] is None
        assert meta["active_sample_ids"] == sample_ids


class TestOrderingIsStableRegardlessOfSelectionOrder:
    def test_row_order_follows_original_dataframe_not_request_order(self):
        df = make_matrix(10, 4)
        shuffled_request = ["g7", "g1", "g9", "g3"]

        working_df, meta = select_matrix(df, row_ids=shuffled_request, sample_ids=None)

        assert working_df["gene"].tolist() == ["g1", "g3", "g7", "g9"]
        assert meta["active_row_ids"] == ["g1", "g3", "g7", "g9"]

    def test_column_order_follows_original_dataframe_not_request_order(self):
        df = make_matrix(10, 6)
        shuffled_request = [
            "(TitleA) sample4",
            "(TitleA) sample0",
            "(TitleA) sample2",
        ]

        working_df, meta = select_matrix(df, row_ids=None, sample_ids=shuffled_request)

        assert value_columns(working_df) == [
            "(TitleA) sample0",
            "(TitleA) sample2",
            "(TitleA) sample4",
        ]


class TestUnknownIdsAndImmutability:
    def test_unknown_row_id_raises_and_never_mutates_original(self):
        df = make_matrix(10, 4)
        before = df.copy(deep=True)

        with pytest.raises(MatrixSelectionError):
            select_matrix(df, row_ids=["g0", "does-not-exist"], sample_ids=None)

        pd.testing.assert_frame_equal(df, before)

    def test_unknown_sample_id_raises_and_never_mutates_original(self):
        df = make_matrix(10, 4)
        before = df.copy(deep=True)

        with pytest.raises(MatrixSelectionError):
            select_matrix(df, row_ids=None, sample_ids=["(TitleA) sample0", "(Bogus) nope"])

        pd.testing.assert_frame_equal(df, before)

    def test_empty_row_selection_raises(self):
        df = make_matrix(10, 4)
        with pytest.raises(MatrixSelectionError):
            select_matrix(df, row_ids=[], sample_ids=None)

    def test_empty_sample_selection_raises(self):
        df = make_matrix(10, 4)
        with pytest.raises(MatrixSelectionError):
            select_matrix(df, row_ids=None, sample_ids=[])

    def test_successful_selection_does_not_mutate_original(self):
        df = make_matrix(10, 4)
        before = df.copy(deep=True)

        select_matrix(df, row_ids=["g0", "g1"], sample_ids=["(TitleA) sample0"])

        pd.testing.assert_frame_equal(df, before)


class TestDuplicateIdsCollapse:
    def test_duplicate_row_ids_in_request_are_deduplicated(self):
        df = make_matrix(10, 4)
        working_df, meta = select_matrix(df, row_ids=["g0", "g0", "g1"], sample_ids=None)
        assert working_df["gene"].tolist() == ["g0", "g1"]
        assert meta["active_row_ids"] == ["g0", "g1"]

    def test_two_rows_sharing_the_same_raw_id_are_both_kept(self):
        # Simulates the Micromix frontend's dedup-suffix convention: two rows
        # sharing the same *raw* backend id ("dup") are displayed as "dup"
        # and "dup#2" but the backend column still literally contains "dup"
        # twice. Selecting "dup" must select BOTH underlying rows.
        df = pd.DataFrame({
            "gene": ["dup", "dup", "unique"],
            "(TitleA) sample0": [1.0, 2.0, 3.0],
        })
        working_df, meta = select_matrix(df, row_ids=["dup"], sample_ids=None)
        assert len(working_df) == 2
        assert meta["active_row_ids"] == ["dup"]


class TestChainedSubsetting:
    """Models PCoA subset -> Heatmap subset -> further subset interoperability:
    the working matrix is always just a plain dataframe, so applying a second
    selection to the result of a first one composes naturally with no special
    casing."""

    def test_applying_a_selection_to_an_already_subset_matrix_composes(self):
        df = make_matrix(100, 20)

        first_pass, first_meta = select_matrix(
            df, row_ids=[f"g{i}" for i in range(25)], sample_ids=None
        )
        assert len(first_pass) == 25
        assert len(value_columns(first_pass)) == 20

        second_pass, second_meta = select_matrix(
            first_pass, row_ids=None, sample_ids=[f"(TitleA) sample{i}" for i in range(8)]
        )
        assert len(second_pass) == 25
        assert len(value_columns(second_pass)) == 8
        assert second_meta["active_sample_ids"] == [f"(TitleA) sample{i}" for i in range(8)]

        # The original, full matrix is untouched by either step.
        assert len(df) == 100
        assert len(value_columns(df)) == 20
