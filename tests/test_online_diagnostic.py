from __future__ import annotations

from dataclasses import replace
import inspect

import numpy as np
import pytest

from d5freq.estimation.online_diagnostic import OnlineModeDiagnostic
from d5freq.estimation.ood_detector import OODCalibrationArtifact, OODDetectorConfig
from d5freq.identification.model_library import (
    ARXModeModel,
    BICRecord,
    DiscoveryMetadata,
    FeatureScalerState,
    ModeLibrary,
)
from d5freq.interfaces import Measurement
from d5freq.utils.hashing import sha256_json


def _library() -> ModeLibrary:
    models = []
    for component_id, command_gain in enumerate((1.0, -1.0)):
        models.append(
            ARXModeModel(
                component_id=component_id,
                theta=np.array([0.0, 0.0, command_gain, 0.0, 0.0, 0.0, 0.0]),
                residual_variance=1.0e-5,
                multi_step_power_error_quantiles_pu={1: 0.001},
                multi_step_frequency_error_quantiles_hz={1: 0.01},
                multi_step_rocof_error_quantiles_hz_per_s={1: 0.02},
                p_output_min_pu=-0.08,
                p_output_max_pu=0.08,
                ramp_down_pu_per_s=0.05,
                ramp_up_pu_per_s=0.05,
                training_episode_count=10,
                training_sample_count=100,
            )
        )
    return ModeLibrary(
        models=tuple(models),
        transition_matrix=np.array([[0.99, 0.01], [0.01, 0.99]]),
        feature_scaler=FeatureScalerState(
            mean=np.zeros(8),
            scale=np.ones(8),
            variance=np.ones(8),
            n_samples_seen=20,
        ),
        discovery_metadata=DiscoveryMetadata(
            selected_k=2,
            candidate_k_min=1,
            candidate_k_max=2,
            covariance_type="full",
            n_init=2,
            random_seed=1,
            bic_table=(
                BICRecord(1, 10.0, 2.0, True, 2),
                BICRecord(2, 8.0, 0.0, True, 3),
            ),
        ),
    )


def _calibration(library: ModeLibrary) -> OODCalibrationArtifact:
    return OODCalibrationArtifact(
        calibration_scores=(0.1, 0.5, 1.0, 2.0),
        dataset_sha256="a" * 64,
        split_manifest_sha256="b" * 64,
        mode_library_sha256="c" * 64,
        mode_library_logical_sha256=sha256_json(library.to_dict()),
        source_trajectory_sha256=("d" * 64, "e" * 64),
        known_component_ids=(0, 1),
        covered_component_ids=(0, 1),
        measurement_noise_variance_pu2=0.0,
        variance_floor_pu2=1.0e-8,
    )


def _measurement(time_s: float, p_ibr_pu: float, u_prev: float) -> Measurement:
    return Measurement(time_s, 0.0, 0.0, p_ibr_pu, 0.0, u_prev)


def test_online_facade_warms_up_then_uses_already_applied_command() -> None:
    library = _library()
    diagnostic = OnlineModeDiagnostic(
        library,
        _calibration(library),
        measurement_noise_variance_pu2=0.0,
        belief_floor=1.0e-12,
        variance_floor_pu2=1.0e-8,
        ood_config=OODDetectorConfig(variance_floor=1.0e-8),
    )
    first = diagnostic.step(_measurement(0.0, 0.0, 0.0))
    second = diagnostic.step(_measurement(0.5, 0.0, 0.0))
    third = diagnostic.step(_measurement(1.0, 0.03, 0.03))

    assert not first.valid_update and not second.valid_update
    assert third.valid_update
    assert third.map_mode == 0
    assert third.mode_belief[0] > 0.99
    assert np.isclose(third.mode_predictions_pu[0], 0.03)
    assert np.isclose(third.residuals_pu[0], 0.0)


def test_runtime_log_and_signature_expose_no_simulator_metadata() -> None:
    library = _library()
    diagnostic = OnlineModeDiagnostic(
        library,
        _calibration(library),
        measurement_noise_variance_pu2=0.0,
        belief_floor=1.0e-12,
        variance_floor_pu2=1.0e-8,
        ood_config=OODDetectorConfig(variance_floor=1.0e-8),
    )
    record = diagnostic.step(_measurement(0.0, 0.0, 0.0)).to_log_record()
    forbidden = "true" + "_mode"
    assert all(forbidden not in key.lower() for key in record)
    assert all(
        forbidden not in name.lower()
        for name in inspect.signature(OnlineModeDiagnostic.step).parameters
    )
    assert {"time_s", "map_mode", "belief_0", "residual_0_pu", "ood_state"} <= set(record)


def test_diagnostic_output_enforces_state_and_integer_invariants() -> None:
    library = _library()
    diagnostic = OnlineModeDiagnostic(
        library,
        _calibration(library),
        measurement_noise_variance_pu2=0.0,
        belief_floor=1.0e-12,
        variance_floor_pu2=1.0e-8,
        ood_config=OODDetectorConfig(variance_floor=1.0e-8),
    )
    output = diagnostic.step(_measurement(0.0, 0.0, 0.0))
    with pytest.raises(ValueError, match="agree"):
        replace(output, ood_active=True)
    with pytest.raises(TypeError, match="map_mode"):
        replace(output, map_mode=0.0)
    with pytest.raises(TypeError, match="sample_index"):
        replace(output, sample_index=0.0)


def test_online_facade_rejects_nonincreasing_measurement_time() -> None:
    library = _library()
    diagnostic = OnlineModeDiagnostic(
        library,
        _calibration(library),
        measurement_noise_variance_pu2=0.0,
        belief_floor=1.0e-12,
        variance_floor_pu2=1.0e-8,
        ood_config=OODDetectorConfig(variance_floor=1.0e-8),
    )
    diagnostic.step(_measurement(0.0, 0.0, 0.0))
    try:
        diagnostic.step(_measurement(0.0, 0.0, 0.0))
    except ValueError as exc:
        assert "strictly increasing" in str(exc)
    else:
        raise AssertionError("nonincreasing measurement time was accepted")


def test_online_facade_rejects_calibration_runtime_provenance_mismatch() -> None:
    library = _library()
    artifact = _calibration(library)
    cases = (
        (
            replace(
                artifact,
                known_component_ids=(0,),
                covered_component_ids=(0,),
            ),
            0.0,
            1.0e-8,
            OODDetectorConfig(variance_floor=1.0e-8),
            "component IDs",
        ),
        (
            replace(artifact, mode_library_logical_sha256="f" * 64),
            0.0,
            1.0e-8,
            OODDetectorConfig(variance_floor=1.0e-8),
            "different mode library",
        ),
        (
            artifact,
            1.0e-7,
            1.0e-8,
            OODDetectorConfig(variance_floor=1.0e-8),
            "measurement-noise variance",
        ),
        (
            artifact,
            0.0,
            1.0e-7,
            OODDetectorConfig(variance_floor=1.0e-7),
            "variance floor",
        ),
        (
            artifact,
            0.0,
            1.0e-8,
            OODDetectorConfig(variance_floor=1.0e-7),
            "detector variance floor",
        ),
    )
    for calibration, measurement_variance, variance_floor, config, message in cases:
        try:
            OnlineModeDiagnostic(
                library,
                calibration,
                measurement_noise_variance_pu2=measurement_variance,
                belief_floor=1.0e-12,
                variance_floor_pu2=variance_floor,
                ood_config=config,
            )
        except ValueError as exc:
            assert message in str(exc)
        else:
            raise AssertionError(f"calibration mismatch was accepted: {message}")
