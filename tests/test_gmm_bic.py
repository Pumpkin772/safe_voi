from __future__ import annotations

import inspect

import numpy as np
import pytest

from d5freq.identification.mode_discovery import select_gmm_by_bic


def _four_cluster_features() -> np.ndarray:
    rng = np.random.default_rng(20260722)
    centers = np.array(
        [
            [-6.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, -3.0],
            [6.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, -1.0],
            [0.0, -6.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
            [0.0, 6.0, 0.0, 0.0, 0.0, 0.0, 0.0, 3.0],
        ]
    )
    return np.vstack([center + rng.normal(scale=0.18, size=(70, 8)) for center in centers])


def test_bic_search_uses_all_k_one_through_six_and_recovers_four() -> None:
    features = _four_cluster_features()
    result = select_gmm_by_bic(
        features,
        k_min=1,
        k_max=6,
        covariance_type="diag",
        n_init=5,
        random_seed=19,
    )

    assert [score.component_count for score in result.candidate_scores] == list(range(1, 7))
    assert result.selected_k == 4
    assert sum(result.cluster_sizes) == features.shape[0]
    assert result.silhouette is not None and result.silhouette > 0.8
    selected_score = next(
        score for score in result.candidate_scores if score.component_count == result.selected_k
    )
    assert selected_score.bic == pytest.approx(result.model.bic(features))
    assert selected_score.delta_bic == pytest.approx(0.0)


def test_gmm_multirestart_is_deterministic_without_external_labels() -> None:
    features = _four_cluster_features()
    kwargs = dict(
        k_min=1,
        k_max=6,
        covariance_type="diag",
        n_init=4,
        random_seed=321,
    )
    first = select_gmm_by_bic(features, **kwargs)
    second = select_gmm_by_bic(features, **kwargs)

    np.testing.assert_array_equal(first.labels, second.labels)
    np.testing.assert_allclose(first.component_centers, second.component_centers)
    np.testing.assert_allclose(
        [score.bic for score in first.candidate_scores],
        [score.bic for score in second.candidate_scores],
    )
    signature = inspect.signature(select_gmm_by_bic)
    assert all("label" not in name and "true" not in name for name in signature.parameters)


def test_candidate_range_is_capped_by_episode_count() -> None:
    rng = np.random.default_rng(8)
    result = select_gmm_by_bic(
        rng.normal(size=(3, 8)),
        k_min=1,
        k_max=6,
        covariance_type="diag",
        n_init=2,
        random_seed=4,
    )
    assert [score.component_count for score in result.candidate_scores] == [1, 2, 3]


def test_candidate_failure_is_recorded_and_does_not_abort_search(monkeypatch: pytest.MonkeyPatch) -> None:
    from d5freq.identification import mode_discovery

    original_fit = mode_discovery.GaussianMixture.fit

    def fail_two(self: object, values: np.ndarray) -> object:
        if self.n_components == 2:  # type: ignore[attr-defined]
            raise ValueError("synthetic candidate failure")
        return original_fit(self, values)

    monkeypatch.setattr(mode_discovery.GaussianMixture, "fit", fail_two)
    result = select_gmm_by_bic(
        _four_cluster_features(),
        k_min=1,
        k_max=4,
        covariance_type="diag",
        n_init=2,
        random_seed=5,
    )
    failed = result.candidate_scores[1]
    assert failed.component_count == 2
    assert failed.bic is None
    assert failed.delta_bic is None
    assert failed.failure_reason is not None
    assert "synthetic candidate failure" in failed.failure_reason
