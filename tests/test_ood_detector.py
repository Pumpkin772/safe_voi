from __future__ import annotations

import json

import numpy as np
from numpy.testing import assert_allclose
import pytest

from d5freq.estimation.ood_detector import (
    KNOWN_MODE_POPULATION,
    OOD_CALIBRATION_SCHEMA_VERSION,
    OOD_CALIBRATION_SPLIT,
    ConformalOODDetector,
    OODCalibrationArtifact,
    OODDetectorConfig,
    OODHysteresisStateMachine,
    OODState,
    calibration_scores_from_residuals,
    minimum_standardized_residual_score,
    split_conformal_pvalue,
)


def _hash(character: str) -> str:
    return character * 64


def _artifact(scores: tuple[float, ...] = (0.1, 0.2, 0.3, 0.4)) -> OODCalibrationArtifact:
    return OODCalibrationArtifact(
        calibration_scores=scores,
        dataset_sha256=_hash("a"),
        split_manifest_sha256=_hash("b"),
        mode_library_sha256=_hash("c"),
        mode_library_logical_sha256=_hash("1"),
        source_trajectory_sha256=(_hash("d"), _hash("e")),
        known_component_ids=(0, 1),
        covered_component_ids=(1, 0),
        measurement_noise_variance_pu2=4.0e-8,
        variance_floor_pu2=1.0e-8,
    )


def test_equations_48_and_49_use_minimum_standardized_residual_and_floor() -> None:
    residuals = np.array([0.6, -0.1, 0.4])
    variances = np.array([0.09, 0.0, 0.16])

    score = minimum_standardized_residual_score(
        residuals, variances, variance_floor=0.01
    )

    assert score == pytest.approx(1.0)


def test_calibration_scores_apply_equation_48_row_wise() -> None:
    residuals = np.array([[0.4, 0.3], [0.1, -0.9], [-0.8, 0.6]])
    variances = np.array([0.04, 0.09])

    scores = calibration_scores_from_residuals(residuals, variances)

    assert_allclose(scores, [1.0, 0.5, 2.0])


def test_equation_50_counts_ties_and_has_finite_sample_correction() -> None:
    calibration = np.array([0.1, 0.2, 0.2, 0.4])

    assert split_conformal_pvalue(0.2, calibration) == pytest.approx(4.0 / 5.0)
    assert split_conformal_pvalue(0.5, calibration) == pytest.approx(1.0 / 5.0)
    assert split_conformal_pvalue(0.0, calibration) == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("residuals", "variances", "message"),
    [
        ([1.0, np.nan], [1.0, 1.0], "finite"),
        ([1.0, 2.0], [1.0, np.inf], "finite"),
        ([1.0, 2.0], [1.0, -1.0], "non-negative"),
        ([1.0], [1.0, 2.0], "equal shape"),
        ([], [], "non-empty"),
    ],
)
def test_score_rejects_invalid_runtime_inputs(
    residuals: list[float], variances: list[float], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        minimum_standardized_residual_score(residuals, variances)


@pytest.mark.parametrize("variance_floor", [0.0, -1.0, np.inf])
def test_variance_floor_must_be_positive_and_finite(variance_floor: float) -> None:
    with pytest.raises(ValueError):
        minimum_standardized_residual_score(
            [0.1], [0.0], variance_floor=variance_floor
        )


def test_score_rejects_overflow_instead_of_emitting_infinity() -> None:
    with pytest.raises(FloatingPointError, match="non-finite"):
        minimum_standardized_residual_score([1.0e308], [0.0])


@pytest.mark.parametrize(
    "scores",
    [[], [np.nan], [np.inf], [-0.1]],
)
def test_conformal_calibration_must_be_nonempty_finite_nonnegative(
    scores: list[float],
) -> None:
    with pytest.raises(ValueError):
        split_conformal_pvalue(0.2, scores)


def test_calibration_artifact_round_trips_through_json() -> None:
    artifact = _artifact()

    payload = json.loads(json.dumps(artifact.to_dict(), allow_nan=False))
    restored = OODCalibrationArtifact.from_dict(payload)

    assert restored == artifact
    assert restored.schema_version == OOD_CALIBRATION_SCHEMA_VERSION
    assert restored.source_split == OOD_CALIBRATION_SPLIT
    assert restored.source_population == KNOWN_MODE_POPULATION


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("dataset_sha256", "A" * 64, "lowercase SHA-256"),
        ("split_manifest_sha256", "0" * 63, "lowercase SHA-256"),
        ("mode_library_sha256", "not-a-hash", "lowercase SHA-256"),
        ("mode_library_logical_sha256", "bad", "lowercase SHA-256"),
        ("source_trajectory_sha256", ("f" * 64, "f" * 64), "duplicates"),
        ("source_split", "test", "forbidden"),
        ("source_split", "ood", "forbidden"),
        ("source_population", "includes_ood", "known modes only"),
        ("calibration_scores", (), "non-empty"),
        ("calibration_scores", (0.1, np.nan), "finite"),
        ("covered_component_ids", (0,), "every and only"),
        ("measurement_noise_variance_pu2", -1.0, "non-negative"),
        ("variance_floor_pu2", 0.0, "strictly positive"),
        ("score_definition", "different_score", "score_definition"),
    ],
)
def test_calibration_artifact_rejects_bad_data_or_provenance(
    field: str, value: object, message: str
) -> None:
    kwargs = _artifact().to_dict()
    kwargs[field] = value
    with pytest.raises(ValueError, match=message):
        OODCalibrationArtifact.from_dict(kwargs)


def test_calibration_artifact_strict_schema_rejects_extra_and_missing_keys() -> None:
    extra = _artifact().to_dict()
    extra["true_mode"] = "forbidden"
    with pytest.raises(ValueError, match="extra=.*true_mode"):
        OODCalibrationArtifact.from_dict(extra)

    missing = _artifact().to_dict()
    del missing["dataset_sha256"]
    with pytest.raises(ValueError, match="missing=.*dataset_sha256"):
        OODCalibrationArtifact.from_dict(missing)


def test_calibration_hashes_must_be_disjoint_from_test_and_ood() -> None:
    artifact = _artifact()
    artifact.assert_disjoint_from(
        test_trajectory_sha256=(_hash("f"),),
        ood_trajectory_sha256=(_hash("0"),),
    )

    with pytest.raises(ValueError, match="test trajectory hashes overlap"):
        artifact.assert_disjoint_from(
            test_trajectory_sha256=(_hash("d"),),
            ood_trajectory_sha256=(_hash("0"),),
        )
    with pytest.raises(ValueError, match="OOD trajectory hashes overlap"):
        artifact.assert_disjoint_from(
            test_trajectory_sha256=(_hash("f"),),
            ood_trajectory_sha256=(_hash("e"),),
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"alpha_on": 0.0},
        {"alpha_off": 1.0},
        {"alpha_on": 0.2, "alpha_off": 0.1},
        {"L_on": 0},
        {"L_off": -1},
        {"variance_floor": 0.0},
    ],
)
def test_detector_configuration_is_strict(kwargs: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        OODDetectorConfig(**kwargs)


def test_default_configuration_matches_phase4_specification() -> None:
    config = OODDetectorConfig()
    assert config.alpha_on == 0.01
    assert config.alpha_off == 0.10
    assert config.L_on == 3
    assert config.L_off == 5


def test_known_to_suspect_to_active_has_literal_step_semantics() -> None:
    machine = OODHysteresisStateMachine(
        OODDetectorConfig(alpha_on=0.1, alpha_off=0.5, L_on=3, L_off=2)
    )

    updates = [machine.update(0.09) for _ in range(4)]

    assert [update.state for update in updates] == [
        OODState.KNOWN,
        OODState.KNOWN,
        OODState.SUSPECT,
        OODState.OOD_ACTIVE,
    ]
    assert [update.low_count for update in updates] == [1, 2, 3, 0]
    assert [update.ood_active for update in updates] == [False, False, False, True]


def test_known_low_counter_resets_and_threshold_comparison_is_strict() -> None:
    machine = OODHysteresisStateMachine(
        OODDetectorConfig(alpha_on=0.1, alpha_off=0.5, L_on=2, L_off=2)
    )
    assert machine.update(0.09).low_count == 1
    exact = machine.update(0.1)
    assert exact.state is OODState.KNOWN
    assert exact.low_count == 0
    assert machine.update(0.09).state is OODState.KNOWN
    assert machine.update(0.09).state is OODState.SUSPECT


def test_suspect_hysteresis_band_holds_and_high_value_recovers() -> None:
    machine = OODHysteresisStateMachine(
        OODDetectorConfig(alpha_on=0.1, alpha_off=0.5, L_on=1, L_off=1)
    )
    assert machine.update(0.09).state is OODState.SUSPECT
    assert machine.update(0.2).state is OODState.SUSPECT
    assert machine.update(0.5).state is OODState.SUSPECT
    assert machine.update(0.51).state is OODState.KNOWN


def test_active_to_recovery_to_known_has_literal_step_semantics() -> None:
    machine = OODHysteresisStateMachine(
        OODDetectorConfig(alpha_on=0.1, alpha_off=0.5, L_on=1, L_off=2)
    )
    machine.update(0.01)
    machine.update(0.01)
    assert machine.state is OODState.OOD_ACTIVE

    first = machine.update(0.51)
    second = machine.update(0.51)
    third = machine.update(0.51)

    assert first.state is OODState.OOD_ACTIVE
    assert first.high_count == 1
    assert second.state is OODState.RECOVERY
    assert second.high_count == 2
    assert third.state is OODState.KNOWN
    assert third.high_count == 0


def test_active_high_counter_resets_on_threshold_or_band_value() -> None:
    machine = OODHysteresisStateMachine(
        OODDetectorConfig(alpha_on=0.1, alpha_off=0.5, L_on=1, L_off=2)
    )
    machine.update(0.01)
    machine.update(0.01)
    assert machine.update(0.8).high_count == 1
    exact = machine.update(0.5)
    assert exact.state is OODState.OOD_ACTIVE
    assert exact.high_count == 0


def test_recovery_reabnormal_returns_immediately_to_active() -> None:
    machine = OODHysteresisStateMachine(
        OODDetectorConfig(alpha_on=0.1, alpha_off=0.5, L_on=1, L_off=1)
    )
    machine.update(0.01)
    machine.update(0.01)
    assert machine.update(0.9).state is OODState.RECOVERY
    assert machine.update(0.3).state is OODState.RECOVERY
    update = machine.update(0.01)
    assert update.previous_state is OODState.RECOVERY
    assert update.state is OODState.OOD_ACTIVE
    assert update.ood_active


def test_state_machine_rejects_nonfinite_or_out_of_range_pvalues() -> None:
    machine = OODHysteresisStateMachine()
    for value in (np.nan, np.inf, -0.01, 1.01):
        with pytest.raises(ValueError):
            machine.update(value)
    assert machine.state is OODState.KNOWN


def test_end_to_end_detector_uses_only_runtime_residuals_and_variances() -> None:
    # With 100 calibration scores and a runtime score above all of them,
    # p=1/101 < the default alpha_on=0.01.
    detector = ConformalOODDetector(
        _artifact(tuple(np.linspace(0.0, 1.0, 100)))
    )

    results = [detector.update([2.0, -3.0], [1.0, 1.0]) for _ in range(4)]

    assert [result.step_index for result in results] == [0, 1, 2, 3]
    assert all(result.ood_score == pytest.approx(2.0) for result in results)
    assert all(result.ood_pvalue == pytest.approx(1.0 / 101.0) for result in results)
    assert results[-2].diagnostic_state is OODState.SUSPECT
    assert results[-1].diagnostic_state is OODState.OOD_ACTIVE
    assert results[-1].ood_active
    serialized_fields = set(results[-1].__dataclass_fields__)
    assert not any("true" in field.lower() or "mode" in field.lower() for field in serialized_fields)


def test_detector_reset_clears_state_and_step_index() -> None:
    config = OODDetectorConfig(alpha_on=0.5, alpha_off=0.8, L_on=1, L_off=1)
    detector = ConformalOODDetector(_artifact(), config)
    detector.update([1.0, 1.0], [1.0, 1.0])
    detector.update([1.0, 1.0], [1.0, 1.0])
    detector.reset()

    assert detector.state is OODState.KNOWN
    assert not detector.ood_active
    assert detector.update([0.0, 0.0], [1.0, 1.0]).step_index == 0


def test_detector_requires_one_runtime_entry_per_calibrated_component() -> None:
    detector = ConformalOODDetector(_artifact())
    with pytest.raises(ValueError, match="per calibrated component"):
        detector.update([0.1], [1.0])
    with pytest.raises(ValueError, match="per calibrated component"):
        detector.update([0.1, 0.2, 0.3], [1.0, 1.0, 1.0])
