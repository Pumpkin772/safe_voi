"""Safety, pairing, and continuous-test-bench tests for ID data."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from d5freq.data import (
    EXCITATION_FAMILIES,
    ExcitationSignals,
    IdentificationGenerationConfig,
    SplitCounts,
    audit_safe_excitation,
    generate_identification_dataset,
    generate_safe_excitation,
    simulate_identification_trajectory,
)
from d5freq.models.hidden_mode_ibr import IBRModeParams


def _config(**overrides: object) -> IdentificationGenerationConfig:
    values: dict[str, object] = {
        "master_seed": 20260722,
        "trajectories_per_mode": 4,
        "trajectory_duration_s": 30.0,
        "control_period_s": 0.5,
        "integration_step_s": 0.02,
        "f0_hz": 50.0,
        "command_abs_limit_pu": 0.06,
        "command_rate_limit_pu_per_s": 0.03,
        "frequency_abs_limit_hz": 0.10,
        "power_measurement_noise_std_pu": 2.0e-4,
        "minimum_command_std_pu": 5.0e-3,
        "minimum_frequency_std_hz": 1.0e-2,
        "maximum_regression_condition_number": 1.0e10,
        "split_counts_per_mode": SplitCounts(1, 1, 1, 1),
    }
    values.update(overrides)
    return IdentificationGenerationConfig(**values)  # type: ignore[arg-type]


def _mode(name: str, *, delay_s: float, time_scale: float) -> IBRModeParams:
    return IBRModeParams(
        name=name,
        command_gain=1.0,
        frequency_gain=4.0,
        command_filter_time_s=0.10 * time_scale,
        power_response_time_s=0.20 * time_scale,
        delay_s=delay_s,
        p_max_pos_pu=0.08,
        p_max_neg_pu=0.08,
        ramp_up_pu_per_s=0.05,
        ramp_down_pu_per_s=0.05,
        deadband_pu=0.0005,
    )


@pytest.mark.parametrize("family", EXCITATION_FAMILIES)
def test_all_excitation_families_satisfy_command_rate_and_frequency_audits(
    family: str,
) -> None:
    config = _config()
    signals = generate_safe_excitation(config, family=family, seed=4321)
    audit = audit_safe_excitation(signals, config)

    assert audit.passed
    assert audit.max_abs_command_pu <= config.command_abs_limit_pu + 1.0e-12
    assert (
        audit.max_abs_command_rate_pu_per_s
        <= config.command_rate_limit_pu_per_s + 1.0e-12
    )
    assert audit.max_abs_frequency_hz <= config.frequency_abs_limit_hz + 1.0e-12
    assert signals.u_ibr_pu[0] == 0.0
    assert len(signals.time_s) == config.sample_count


def test_unsafe_manual_excitation_is_detected() -> None:
    config = _config(
        trajectory_duration_s=1.5,
        minimum_command_std_pu=1.0e-6,
        minimum_frequency_std_hz=1.0e-6,
    )
    signals = ExcitationSignals(
        family="steps",
        time_s=[0.0, 0.5, 1.0, 1.5],
        u_ibr_pu=[0.0, 0.061, -0.061, 0.0],
        omega_pu=[0.0, 0.003, -0.003, 0.0],
    )

    audit = audit_safe_excitation(signals, config)

    assert not audit.passed
    assert not audit.amplitude_safe
    assert not audit.rate_safe
    assert not audit.frequency_safe


def test_every_mode_receives_the_exact_same_paired_exogenous_signals() -> None:
    config = _config()
    result = generate_identification_dataset(
        {
            "fast_resource": _mode("fast_resource", delay_s=0.10, time_scale=1.0),
            "slow_resource": _mode("slow_resource", delay_s=0.50, time_scale=4.0),
        },
        config,
    )
    trajectories = {
        item.trajectory_id: item for item in result.public_trajectories
    }
    grouped: dict[str, list[str]] = {}
    for metadata in result.private_evaluation_metadata:
        grouped.setdefault(metadata.excitation_pair_id_eval_only, []).append(
            metadata.trajectory_id
        )

    assert len(grouped) == config.trajectories_per_mode
    for identifiers in grouped.values():
        assert len(identifiers) == 2
        first, second = (trajectories[item] for item in identifiers)
        np.testing.assert_array_equal(first.time_s, second.time_s)
        np.testing.assert_array_equal(first.u_ibr_pu, second.u_ibr_pu)
        np.testing.assert_array_equal(first.omega_pu, second.omega_pu)
        assert not np.array_equal(first.p_ibr_pu, second.p_ibr_pu)


def test_delayed_zoh_transition_is_not_applied_before_its_physical_time() -> None:
    config = _config(
        trajectories_per_mode=1,
        trajectory_duration_s=1.5,
        integration_step_s=0.05,
        command_rate_limit_pu_per_s=0.04,
        power_measurement_noise_std_pu=0.0,
        minimum_command_std_pu=1.0e-3,
        minimum_frequency_std_hz=1.0e-12,
        split_counts_per_mode=SplitCounts(1, 0, 0, 0),
    )
    signals = ExcitationSignals(
        family="steps",
        time_s=[0.0, 0.5, 1.0, 1.5],
        u_ibr_pu=[0.0, 0.02, 0.02, 0.02],
        omega_pu=[0.0, 0.0, 0.0, 0.0],
    )
    params = IBRModeParams(
        name="fixed_delay_resource",
        command_gain=1.0,
        frequency_gain=0.0,
        command_filter_time_s=0.10,
        power_response_time_s=0.20,
        delay_s=0.60,
        p_max_pos_pu=0.08,
        p_max_neg_pu=0.08,
        ramp_up_pu_per_s=1.0,
        ramp_down_pu_per_s=1.0,
        deadband_pu=0.0,
    )

    coarse = simulate_identification_trajectory(
        params,
        signals,
        config,
        trajectory_id="0" * 32,
        measurement_seed=1,
    )
    fine = simulate_identification_trajectory(
        params,
        signals,
        replace(config, integration_step_s=0.01),
        trajectory_id="1" * 32,
        measurement_seed=1,
    )

    # The command changes at 0.5 s and a 0.6 s delay makes it visible at 1.1 s.
    assert coarse.p_ibr_pu[1] == pytest.approx(0.0, abs=1.0e-15)
    assert coarse.p_ibr_pu[2] == pytest.approx(0.0, abs=1.0e-15)
    assert coarse.p_ibr_pu[3] > 0.0
    # A 0.05 s RK4 step is already within 1e-6 pu of the 0.01 s reference for
    # this 0.1 s command filter; this is a numerical check separate from the
    # exact zero-output event-timing assertions above.
    np.testing.assert_allclose(coarse.p_ibr_pu, fine.p_ibr_pu, atol=1.0e-6)
