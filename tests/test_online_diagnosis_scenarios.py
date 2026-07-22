from __future__ import annotations

import numpy as np

from d5freq.data import ExcitationSignals
from d5freq.evaluation.online_diagnosis_scenarios import (
    simulate_scheduled_ibr_trajectory,
)
from d5freq.models.hidden_mode_ibr import IBRModeParams, SinusoidalDelayProfile
from d5freq.simulation.mode_schedules import PiecewiseConstantModeSchedule


def _signals() -> ExcitationSignals:
    time = np.arange(0.0, 4.0 + 0.5, 0.5)
    return ExcitationSignals(
        family="steps",
        time_s=time,
        u_ibr_pu=np.where(time < 1.0, 0.03, -0.02),
        omega_pu=0.001 * np.sin(time),
    )


def _mode(name: str, *, delay_profile=None) -> IBRModeParams:
    return IBRModeParams(
        name=name,
        command_gain=1.0,
        frequency_gain=3.0,
        command_filter_time_s=0.2,
        power_response_time_s=0.3,
        delay_s=0.1,
        p_max_pos_pu=0.08,
        p_max_neg_pu=0.08,
        ramp_up_pu_per_s=0.05,
        ramp_down_pu_per_s=0.05,
        deadband_pu=0.0,
        delay_profile=delay_profile,
    )


def test_scheduled_evaluation_truth_is_separate_and_state_is_not_reset() -> None:
    modes = {"a": _mode("a"), "b": _mode("b")}
    schedule = PiecewiseConstantModeSchedule.from_pairs("a", [(2.0, "b")])
    public, truth = simulate_scheduled_ibr_trajectory(
        _signals(),
        modes,
        schedule,
        trajectory_id="a" * 32,
        integration_step_s=0.02,
        power_measurement_noise_std_pu=0.0,
        measurement_seed=7,
    )

    assert not hasattr(public, "mode_name_eval_only")
    assert truth.mode_name_eval_only[:4] == ("a",) * 4
    assert truth.mode_name_eval_only[4:] == ("b",) * 5
    # The physical power state at the switch is retained rather than reset.
    assert abs(float(public.p_ibr_pu[4])) > 1.0e-4


def test_time_varying_delay_trajectory_is_deterministic_for_a_seed() -> None:
    profile = SinusoidalDelayProfile(0.1, 0.7, 2.0)
    mode = _mode("dynamic", delay_profile=profile)
    arguments = dict(
        signals=_signals(),
        mode_params={"dynamic": mode},
        mode_schedule=PiecewiseConstantModeSchedule("dynamic"),
        trajectory_id="b" * 32,
        integration_step_s=0.02,
        power_measurement_noise_std_pu=2.0e-4,
        measurement_seed=11,
    )
    first, first_truth = simulate_scheduled_ibr_trajectory(**arguments)
    second, second_truth = simulate_scheduled_ibr_trajectory(**arguments)

    np.testing.assert_array_equal(first.p_ibr_pu, second.p_ibr_pu)
    assert first_truth == second_truth


def test_scheduled_simulator_rejects_mode_key_name_mismatch() -> None:
    try:
        simulate_scheduled_ibr_trajectory(
            _signals(),
            {"declared": _mode("different")},
            PiecewiseConstantModeSchedule("declared"),
            trajectory_id="c" * 32,
            integration_step_s=0.02,
            power_measurement_noise_std_pu=0.0,
            measurement_seed=0,
        )
    except ValueError as exc:
        assert "key must equal" in str(exc)
    else:
        raise AssertionError("mode key/name mismatch was accepted")
