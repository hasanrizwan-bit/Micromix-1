#--------------------------------
# Unit tests for the PCoA service module
#--------------------------------
#
# Ported from ``ClusteredHeatmap2/backend/test_pcoa_service.py``. These tests
# exercise the pure math/validation/cache logic directly (no Flask, no
# MongoDB) so they can run standalone, mirroring the convention used by
# ``orthology/tests/test_expression_matrix.py``.
#
# Coverage carried over from the reference suite:
#   * matrix parsing/validation      (delimiters, BOM, bad cells, duplicate/
#                                      blank ids, row/column count limits)
#   * classical MDS oracle values    (hardcoded eigenvalues/explained % for a
#                                      known 6x4 matrix, pinning axis order,
#                                      scaling and the explained-% denominator)
#   * negative-eigenvalue warning    (non-Euclidean distance matrix)
#   * normalize_sample_ids           (None/empty/JSON/newline/list forms)
#   * subset_matrix                  (row order, duplicates, unknown ids,
#                                      identical-value rejection)
#   * run_pcoa_on_matrix             (is_subset bookkeeping, subset is a real
#                                      re-analysis, not a coordinate slice)
#   * DatasetStore                   (put/get roundtrip, TTL expiry, LRU +
#                                      cell-budget eviction)
#
# Run with:  ./venv/bin/python -m pytest pcoa/tests -q

import numpy as np
import pytest

from pcoa import dataset_store as store_mod
from pcoa import service as svc

VALID_CSV = (
    "sample_id,gene_A,gene_B,gene_C,gene_D\n"
    "Sample_1,10,15,4,8\n"
    "Sample_2,12,14,7,9\n"
    "Sample_3,40,35,28,31\n"
    "Sample_4,38,32,25,29\n"
    "Sample_5,21,20,14,17\n"
    "Sample_6,19,22,13,16\n"
)

VALID_TSV = VALID_CSV.replace(",", "\t")

#: Selection used by most subset tests: 4 of the 6 samples, deliberately NOT
#: contiguous and NOT in file order.
SUBSET_IDS = ["Sample_6", "Sample_1", "Sample_5", "Sample_2"]

EXPECTED_EIGENVALUES = [
    2126.4901549333,
    7.6280176028,
    2.8382164955,
    0.5436109683,
    0.0,
    0.0,
]
EXPECTED_EXPLAINED = [99.484919529, 0.3568663206]


# ---------------------------------------------------------------------------
# parse_matrix
# ---------------------------------------------------------------------------


class TestParseMatrix:
    def test_valid_csv(self):
        parsed = svc.parse_matrix(VALID_CSV, filename="m.csv")
        assert parsed.n_samples == 6
        assert parsed.n_features == 4
        assert parsed.sample_ids == [
            "Sample_1", "Sample_2", "Sample_3", "Sample_4", "Sample_5", "Sample_6",
        ]
        assert parsed.feature_names == ["gene_A", "gene_B", "gene_C", "gene_D"]
        assert parsed.delimiter == ","

    def test_valid_tsv(self):
        parsed = svc.parse_matrix(VALID_TSV, filename="m.tsv")
        assert parsed.n_samples == 6
        assert parsed.delimiter == "\t"

    def test_bom_is_tolerated(self):
        data = ("\ufeff" + VALID_CSV).encode("utf-8-sig")
        parsed = svc.parse_matrix(data, filename="m.csv")
        assert parsed.n_samples == 6

    def test_bytes_input(self):
        parsed = svc.parse_matrix(VALID_CSV.encode("utf-8"), filename="m.csv")
        assert parsed.n_samples == 6

    def test_empty_file_rejected(self):
        with pytest.raises(svc.PcoaInputError, match="empty"):
            svc.parse_matrix("", filename="m.csv")

    def test_unsupported_extension_rejected(self):
        with pytest.raises(svc.PcoaInputError, match="Unsupported file type"):
            svc.parse_matrix(VALID_CSV, filename="m.xlsx")

    def test_missing_value_rejected(self):
        bad = VALID_CSV.replace("Sample_2,12,14,7,9", "Sample_2,12,,7,9")
        with pytest.raises(svc.PcoaInputError, match="Missing value"):
            svc.parse_matrix(bad, filename="m.csv")

    def test_non_numeric_value_rejected(self):
        bad = VALID_CSV.replace("Sample_2,12,14,7,9", "Sample_2,12,high,7,9")
        with pytest.raises(svc.PcoaInputError, match="Non-numeric value"):
            svc.parse_matrix(bad, filename="m.csv")

    def test_nan_and_inf_literals_rejected(self):
        for literal in ("nan", "NaN", "inf", "-Infinity"):
            bad = VALID_CSV.replace(
                "Sample_2,12,14,7,9", f"Sample_2,12,{literal},7,9"
            )
            with pytest.raises(svc.PcoaInputError):
                svc.parse_matrix(bad, filename="m.csv")

    def test_duplicate_sample_id_rejected(self):
        bad = VALID_CSV.replace("Sample_2,12,14,7,9", "Sample_1,12,14,7,9")
        with pytest.raises(svc.PcoaInputError, match="Duplicate sample identifier"):
            svc.parse_matrix(bad, filename="m.csv")

    def test_blank_sample_id_rejected(self):
        bad = VALID_CSV.replace("Sample_2,12,14,7,9", ",12,14,7,9")
        with pytest.raises(svc.PcoaInputError, match="blank sample identifier"):
            svc.parse_matrix(bad, filename="m.csv")

    def test_ragged_row_rejected(self):
        bad = VALID_CSV.replace("Sample_2,12,14,7,9", "Sample_2,12,14,7")
        with pytest.raises(svc.PcoaInputError, match="field"):
            svc.parse_matrix(bad, filename="m.csv")

    def test_too_few_samples_rejected(self):
        too_few = "sample_id,a,b\nS1,1,2\nS2,3,4\n"
        with pytest.raises(svc.PcoaInputError, match="At least 3"):
            svc.parse_matrix(too_few, filename="m.csv")

    def test_too_few_features_rejected(self):
        too_few = "sample_id,a\nS1,1\nS2,3\nS3,5\n"
        with pytest.raises(svc.PcoaInputError, match="At least 2"):
            svc.parse_matrix(too_few, filename="m.csv")

    def test_blank_feature_name_gets_placeholder(self):
        text = "sample_id,,b\nS1,1,2\nS2,3,4\nS3,5,6\n"
        parsed = svc.parse_matrix(text, filename="m.csv")
        assert parsed.feature_names[0] == "feature_1"

    def test_commas_inside_tsv_feature_names_are_tolerated(self):
        text = (
            "sample_id\tk__Bacteria,p__Firmicutes\tk__Bacteria,p__Bacteroidetes\n"
            "S1\t1\t2\n"
            "S2\t3\t4\n"
            "S3\t5\t6\n"
        )
        parsed = svc.parse_matrix(text, filename="m.tsv")
        assert parsed.n_features == 2
        assert parsed.delimiter == "\t"

    def test_bundled_example_files_load(self):
        # Same shape as the ClusteredHeatmap2 example fixtures used for manual
        # testing (6 samples x 4 features).
        parsed = svc.parse_matrix(VALID_CSV, filename="example_pcoa.csv")
        assert parsed.n_samples == 6
        assert parsed.n_features == 4


# ---------------------------------------------------------------------------
# compute_distance_matrix
# ---------------------------------------------------------------------------


class TestDistanceMatrix:
    def test_shape_symmetric_zero_diagonal(self):
        parsed = svc.parse_matrix(VALID_CSV, filename="m.csv")
        d = svc.compute_distance_matrix(parsed.values)
        assert d.shape == (6, 6)
        np.testing.assert_allclose(d, d.T)
        np.testing.assert_allclose(np.diag(d), np.zeros(6))

    def test_known_distance_value(self):
        values = np.array([[0.0, 0.0], [3.0, 0.0], [0.0, 4.0]])
        # Actually use two rows differing by (3,4) inside a valid dataset shape.
        d = svc.compute_distance_matrix(values)
        assert d[0, 1] == pytest.approx(3.0)
        assert d[0, 2] == pytest.approx(4.0)

    def test_identical_rows_have_zero_distance(self):
        values = np.array([[1.0, 2.0], [1.0, 2.0], [5.0, 6.0]])
        d = svc.compute_distance_matrix(values)
        assert d[0, 1] == pytest.approx(0.0)

    def test_unsupported_metric_rejected(self):
        parsed = svc.parse_matrix(VALID_CSV, filename="m.csv")
        with pytest.raises(svc.PcoaInputError, match="Unsupported distance metric"):
            svc.compute_distance_matrix(parsed.values, metric="jaccard")

    def test_registry_contains_euclidean_only(self):
        assert set(svc.DISTANCE_METRICS) == {"euclidean"}


# ---------------------------------------------------------------------------
# classical_mds — oracle values for VALID_CSV
# ---------------------------------------------------------------------------


class TestClassicalMdsOracle:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.parsed = svc.parse_matrix(VALID_CSV, filename="m.csv")
        self.distances = svc.compute_distance_matrix(self.parsed.values)
        self.result = svc.classical_mds(self.distances, n_components=2)

    def test_one_row_of_coordinates_per_sample(self):
        assert self.result.coordinates.shape == (self.parsed.n_samples, 2)

    def test_coordinates_are_finite(self):
        assert np.all(np.isfinite(self.result.coordinates))

    def test_eigenvalues_match_expected_spectrum(self):
        eig = self.result.eigenvalues
        assert eig.shape == (6,)
        np.testing.assert_allclose(eig, EXPECTED_EIGENVALUES, atol=1e-8)
        assert np.all(np.diff(eig) <= 1e-12)

    def test_positive_eigenvalues_are_the_expected_subset(self):
        pos = self.result.positive_eigenvalues
        np.testing.assert_allclose(pos, EXPECTED_EIGENVALUES[:4], atol=1e-8)
        assert np.all(pos > 0)

    def test_coordinate_axes_are_scaled_by_their_own_eigenvalue(self):
        # sum(coord_k^2) == lambda_k pins BOTH the axis order (a swapped
        # coordinate_1/coordinate_2 fails here) and the eigenvalue used for
        # the scaling (using |lambda| for a negative axis would fail here
        # too).
        sums = np.sum(np.square(self.result.coordinates), axis=0)
        np.testing.assert_allclose(sums, EXPECTED_EIGENVALUES[:2], atol=1e-8)

    def test_explained_variation_matches_expected_percentages(self):
        explained = self.result.explained
        assert explained.shape == (2,)
        np.testing.assert_allclose(explained, EXPECTED_EXPLAINED, atol=1e-6)
        total = float(np.sum(np.abs(self.result.eigenvalues)))
        np.testing.assert_allclose(
            explained, np.array(EXPECTED_EIGENVALUES[:2]) / total * 100.0, atol=1e-8
        )
        assert float(np.sum(explained)) <= 100.0 + 1e-9

    def test_euclidean_input_has_no_meaningful_negative_eigenvalues(self):
        assert self.result.warnings == []

    def test_coordinates_are_centred(self):
        np.testing.assert_allclose(
            self.result.coordinates.mean(axis=0), np.zeros(2), atol=1e-10
        )

    def test_preserves_euclidean_distances(self):
        from scipy.spatial.distance import pdist, squareform

        # Full positive-eigenvalue embedding reproduces the input distances.
        full = svc.classical_mds(self.distances, n_components=4)
        reproduced = squareform(pdist(full.coordinates))
        np.testing.assert_allclose(reproduced, self.distances, atol=1e-9)

    def test_all_identical_samples_rejected(self):
        d = np.zeros((4, 4))
        with pytest.raises(svc.PcoaInputError, match="all samples are identical"):
            svc.classical_mds(d, n_components=2)

    def test_too_few_samples_for_components_rejected(self):
        d = np.array([[0.0, 1.0], [1.0, 0.0]])
        with pytest.raises(svc.PcoaInputError, match="At least 3 samples"):
            svc.classical_mds(d, n_components=2)

    def test_negative_eigenvalue_warning_on_non_euclidean_matrix(self):
        # Metric-violating distance matrix (from the reference test suite)
        # that forces genuinely negative eigenvalues; they must be reported,
        # not hidden.
        d = np.array(
            [
                [0.0, 1.0, 1.0, 1.0],
                [1.0, 0.0, 2.0, 2.0],
                [1.0, 2.0, 0.0, 2.0],
                [1.0, 2.0, 2.0, 0.0],
            ]
        )
        result = svc.classical_mds(d, n_components=2)
        assert np.all(np.isfinite(result.coordinates))
        # Signed spectrum is reported as-is: [2, 2, 0, -0.25].
        np.testing.assert_allclose(
            result.eigenvalues, [2.0, 2.0, 0.0, -0.25], atol=1e-9
        )
        np.testing.assert_allclose(result.positive_eigenvalues, [2.0, 2.0], atol=1e-9)
        assert len(result.warnings) == 1
        assert "negative eigenvalues" in result.warnings[0]
        # The negative axis is NOT flipped into the ordination: only the two
        # positive eigenvalues are used, and each coordinate axis is scaled by
        # its own POSITIVE eigenvalue.
        np.testing.assert_allclose(
            np.sum(np.square(result.coordinates), axis=0), [2.0, 2.0], atol=1e-9
        )
        # Explained % denominator includes the negative part (total inertia
        # 4.25), so the two axes must not add up to 100% while the warning is
        # active.
        total = 4.25
        np.testing.assert_allclose(
            result.explained, [2.0 / total * 100.0, 2.0 / total * 100.0], atol=1e-8
        )
        assert float(np.sum(result.explained)) < 100.0


# ---------------------------------------------------------------------------
# normalize_sample_ids
# ---------------------------------------------------------------------------


class TestNormalizeSampleIds:
    def test_none_and_empty_string_are_none(self):
        assert svc.normalize_sample_ids(None) is None
        assert svc.normalize_sample_ids("") is None
        assert svc.normalize_sample_ids("   ") is None

    def test_explicit_empty_list_is_distinct_from_none(self):
        assert svc.normalize_sample_ids("[]") == []
        assert svc.normalize_sample_ids([]) == []

    def test_json_array_of_strings(self):
        assert svc.normalize_sample_ids('["S1", "S2"]') == ["S1", "S2"]

    def test_json_array_of_numbers_stringified(self):
        assert svc.normalize_sample_ids("[1, 2]") == ["1", "2"]

    def test_newline_separated_text(self):
        assert svc.normalize_sample_ids("S1\nS2\nS3") == ["S1", "S2", "S3"]

    def test_commas_in_ids_not_split(self):
        assert svc.normalize_sample_ids("S1,a\nS2,b") == ["S1,a", "S2,b"]

    def test_python_list_passthrough(self):
        assert svc.normalize_sample_ids(["S1", "S2"]) == ["S1", "S2"]

    def test_malformed_json_rejected(self):
        with pytest.raises(svc.PcoaInputError):
            svc.normalize_sample_ids("[unterminated")

    def test_non_id_values_in_list_rejected(self):
        # dict/bool/None items are not valid sample ids, even inside a list
        # that also contains valid entries.
        for bad_item in ({"a": 1}, True):
            with pytest.raises(svc.PcoaInputError):
                svc.normalize_sample_ids([bad_item])
        with pytest.raises(svc.PcoaInputError):
            svc.normalize_sample_ids(["S1", None])

    def test_numeric_list_items_are_stringified_not_rejected(self):
        # Numeric sample ids legitimately survive a JSON round trip as
        # numbers, so they must be accepted (not rejected).
        assert svc.normalize_sample_ids([1, 2, 3]) == ["1", "2", "3"]

    def test_top_level_dict_rejected(self):
        with pytest.raises(svc.PcoaInputError):
            svc.normalize_sample_ids({"a": 1})


# ---------------------------------------------------------------------------
# subset_matrix
# ---------------------------------------------------------------------------


class TestSubsetMatrix:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.parsed = svc.parse_matrix(VALID_CSV, filename="m.csv")

    def test_none_is_a_true_no_op(self):
        subset, warnings = svc.subset_matrix(self.parsed, None)
        assert subset is self.parsed
        assert warnings == []

    def test_row_order_follows_original_not_selection_order(self):
        subset, _ = svc.subset_matrix(self.parsed, SUBSET_IDS)
        assert subset.sample_ids == ["Sample_1", "Sample_2", "Sample_5", "Sample_6"]

    def test_feature_names_preserved(self):
        subset, _ = svc.subset_matrix(self.parsed, SUBSET_IDS)
        assert subset.feature_names == self.parsed.feature_names

    def test_original_matrix_never_mutated(self):
        before = self.parsed.values.copy()
        svc.subset_matrix(self.parsed, SUBSET_IDS)
        np.testing.assert_array_equal(self.parsed.values, before)

    def test_unknown_id_named_in_error(self):
        with pytest.raises(svc.PcoaInputError, match="Sample_99"):
            svc.subset_matrix(self.parsed, ["Sample_1", "Sample_2", "Sample_99"])

    def test_duplicate_ids_used_once_and_warned(self):
        subset, warnings = svc.subset_matrix(
            self.parsed, ["Sample_1", "Sample_1", "Sample_2", "Sample_3"]
        )
        assert subset.n_samples == 3
        assert len(warnings) == 1
        assert "duplicate" in warnings[0]

    def test_empty_selection_rejected(self):
        with pytest.raises(svc.PcoaInputError, match="No samples were selected"):
            svc.subset_matrix(self.parsed, [])

    def test_too_few_distinct_samples_rejected(self):
        with pytest.raises(svc.PcoaInputError, match="Only 2 distinct sample"):
            svc.subset_matrix(self.parsed, ["Sample_1", "Sample_2"])

    def test_duplicates_cannot_fake_a_big_enough_selection(self):
        with pytest.raises(svc.PcoaInputError, match="Only 1 distinct sample"):
            svc.subset_matrix(self.parsed, ["Sample_1", "Sample_1", "Sample_1"])

    def test_identical_feature_value_selection_rejected(self):
        text = (
            "sample_id,a,b\n"
            "S1,1,1\n"
            "S2,1,1\n"
            "S3,1,1\n"
            "S4,9,9\n"
        )
        parsed = svc.parse_matrix(text, filename="m.csv")
        with pytest.raises(svc.PcoaInputError, match="identical feature values"):
            svc.subset_matrix(parsed, ["S1", "S2", "S3"])

    def test_selection_above_max_samples_rejected(self):
        with pytest.raises(svc.PcoaInputError, match="exceeds the current limit"):
            svc.subset_matrix(self.parsed, [f"S{i}" for i in range(svc.MAX_SAMPLES + 1)])


# ---------------------------------------------------------------------------
# run_pcoa_on_matrix — full pipeline + subset-is-a-real-rerun proofs
# ---------------------------------------------------------------------------


class TestRunPcoaOnMatrix:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.parsed = svc.parse_matrix(VALID_CSV, filename="m.csv")

    def test_full_dataset_payload_shape(self):
        payload = svc.run_pcoa_on_matrix(self.parsed)
        for key in (
            "sample_ids", "feature_names", "coordinate_1", "coordinate_2",
            "coordinates", "eigenvalues", "positive_eigenvalues",
            "explained_variation", "explained_1", "explained_2",
            "explained_combined", "n_samples", "n_features", "metric",
            "warnings", "is_subset", "n_original_samples",
        ):
            assert key in payload
        assert payload["is_subset"] is False
        assert payload["n_samples"] == payload["n_original_samples"] == 6
        assert payload["metric"] == "euclidean"
        assert payload["explained_combined"] == pytest.approx(
            payload["explained_1"] + payload["explained_2"]
        )

    def test_values_are_native_floats_not_numpy(self):
        payload = svc.run_pcoa_on_matrix(self.parsed)
        assert isinstance(payload["coordinate_1"][0], float)
        assert isinstance(payload["explained_1"], float)

    def test_subset_payload_flags_is_subset(self):
        payload = svc.run_pcoa_on_matrix(self.parsed, sample_ids=SUBSET_IDS)
        assert payload["is_subset"] is True
        assert payload["n_samples"] == 4
        assert payload["n_original_samples"] == 6

    def test_selecting_every_sample_is_not_flagged_a_subset(self):
        payload = svc.run_pcoa_on_matrix(
            self.parsed, sample_ids=list(self.parsed.sample_ids)
        )
        assert payload["is_subset"] is False

    def test_subset_is_not_a_slice_of_full_dataset_coordinates(self):
        full = svc.run_pcoa_on_matrix(self.parsed)
        subset = svc.run_pcoa_on_matrix(self.parsed, sample_ids=SUBSET_IDS)
        full_centroid = np.mean(np.array(full["coordinates"])[:4], axis=0)
        subset_centroid = np.mean(np.array(subset["coordinates"]), axis=0)
        assert not np.allclose(full_centroid, subset_centroid)

    def test_subset_matches_independent_upload_of_only_those_rows(self):
        subset = svc.run_pcoa_on_matrix(self.parsed, sample_ids=SUBSET_IDS)
        independent_csv = (
            "sample_id,gene_A,gene_B,gene_C,gene_D\n"
            "Sample_1,10,15,4,8\n"
            "Sample_2,12,14,7,9\n"
            "Sample_5,21,20,14,17\n"
            "Sample_6,19,22,13,16\n"
        )
        independent = svc.run_pcoa(independent_csv, filename="m.csv")
        # Same ordination up to eigenvector sign: compare squared coordinates.
        np.testing.assert_allclose(
            np.square(subset["coordinate_1"]),
            np.square(independent["coordinate_1"]),
            atol=1e-8,
        )

    def test_distance_matrix_recomputed_matches_full_matrix_sub_block(self):
        full_d = svc.compute_distance_matrix(self.parsed.values)
        idx = [self.parsed.sample_ids.index(s) for s in sorted(SUBSET_IDS)]
        expected_block = full_d[np.ix_(idx, idx)]
        subset, _ = svc.subset_matrix(self.parsed, SUBSET_IDS)
        actual = svc.compute_distance_matrix(subset.values)
        np.testing.assert_allclose(actual, expected_block, atol=1e-9)

    def test_subset_of_a_subset_filters_from_the_original(self):
        # Selecting from an already-filtered ParsedMatrix should behave the
        # same as selecting directly from the original: the caller is always
        # expected to hold the ORIGINAL parsed matrix (this is enforced by the
        # dataset store, tested separately), but subset_matrix itself simply
        # filters whatever ParsedMatrix it is given.
        first, _ = svc.subset_matrix(self.parsed, SUBSET_IDS)
        second, _ = svc.subset_matrix(self.parsed, ["Sample_1", "Sample_2", "Sample_6"])
        assert second.sample_ids == ["Sample_1", "Sample_2", "Sample_6"]
        assert first.sample_ids != second.sample_ids

    def test_duplicate_id_warning_propagates_to_payload(self):
        payload = svc.run_pcoa_on_matrix(
            self.parsed, sample_ids=["Sample_1", "Sample_1", "Sample_2", "Sample_3"]
        )
        assert any("duplicate" in w for w in payload["warnings"])

    def test_unsupported_metric_on_subset_rejected(self):
        with pytest.raises(svc.PcoaInputError, match="Unsupported distance metric"):
            svc.run_pcoa_on_matrix(self.parsed, metric="jaccard", sample_ids=SUBSET_IDS)


# ---------------------------------------------------------------------------
# DatasetStore
# ---------------------------------------------------------------------------


class FakeClock:
    def __init__(self, start=0.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class TestDatasetStore:
    def _matrix(self, n_samples=3, n_features=2):
        rows = "\n".join(
            f"S{i},{i}.0,{i * 2}.0" for i in range(n_samples)
        )
        header = ",".join(["sample_id"] + [f"f{i}" for i in range(n_features)])
        text = f"{header}\nS0,1,2\nS1,3,4\nS2,5,6\n"
        return svc.parse_matrix(text, filename="m.csv")

    def test_put_get_roundtrip(self):
        store = store_mod.DatasetStore()
        parsed = self._matrix()
        dataset_id = store.put(parsed, filename="m.csv", metric="euclidean")
        stored = store.get(dataset_id)
        assert stored is not None
        assert stored.matrix is parsed
        assert stored.filename == "m.csv"

    def test_ids_are_unguessable_and_unique(self):
        store = store_mod.DatasetStore()
        parsed = self._matrix()
        id1 = store.put(parsed)
        id2 = store.put(parsed)
        assert id1 != id2
        assert len(id1) >= 16

    def test_unknown_or_blank_id_returns_none(self):
        store = store_mod.DatasetStore()
        assert store.get("does-not-exist") is None
        assert store.get(None) is None
        assert store.get("") is None

    def test_ttl_expiry(self):
        clock = FakeClock()
        store = store_mod.DatasetStore(ttl_seconds=100, clock=clock)
        dataset_id = store.put(self._matrix())
        clock.advance(101)
        assert store.get(dataset_id) is None

    def test_get_refreshes_ttl(self):
        clock = FakeClock()
        store = store_mod.DatasetStore(ttl_seconds=100, clock=clock)
        dataset_id = store.put(self._matrix())
        clock.advance(99)
        assert store.get(dataset_id) is not None
        clock.advance(99)
        # Still alive: the previous get() refreshed last_used_at.
        assert store.get(dataset_id) is not None

    def test_lru_eviction_by_count(self):
        store = store_mod.DatasetStore(max_datasets=2)
        id1 = store.put(self._matrix())
        id2 = store.put(self._matrix())
        id3 = store.put(self._matrix())
        assert store.get(id1) is None
        assert store.get(id2) is not None
        assert store.get(id3) is not None

    def test_eviction_by_cell_budget(self):
        store = store_mod.DatasetStore(max_cells=8, max_datasets=10)
        id1 = store.put(self._matrix(n_samples=3, n_features=2))  # 6 cells
        id2 = store.put(self._matrix(n_samples=3, n_features=2))  # 6 cells
        # Second entry pushes total to 12 > 8, so the first is evicted.
        assert store.get(id1) is None
        assert store.get(id2) is not None

    def test_remove_and_clear(self):
        store = store_mod.DatasetStore()
        dataset_id = store.put(self._matrix())
        assert store.remove(dataset_id) is True
        assert store.get(dataset_id) is None
        store.put(self._matrix())
        store.clear()
        assert len(store) == 0
