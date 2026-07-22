from __future__ import annotations

import json

import numpy as np
import pytest

from d5freq.evaluation.closed_loop_metrics import (
    ClosedLoopMetricConfig,
    ControlRateTrace,
    DetectionWindow,
    HighFrequencyTruthTrace,
    compute_closed_loop_metrics,
    evaluate_detection_delay,
)


def _control_trace(**overrides: object) -> ControlRateTrace:
    values: dict[str, object] = {
        "time_s": [0.0, 1.0, 2.0],
        "u_sg_pu": [0.0, 1.0, 1.0],
        "u_ibr_pu": [1.0, 0.0, 0.0],
        "p_ibr_pu": [0.5, 0.0, 0.0],
        "controller_state": ["KNOWN", "FALLBACK", "FALLBACK"],
        "solver_outcome": ["success", "timeout", "not_run"],
        "solver_status": ["optimal", "timeout", "not_run"],
        "solve_time_s": [0.1, 0.3, 0.0],
        "max_freq_slack_hz": [0.0, 0.2, 0.0],
        "max_rocof_slack_hz_s": [0.0, 0.4, 0.0],
        "max_power_slack_pu": [0.0, 0.1, 0.0],
        "u_sg_initial_pu": 0.0,
        "u_ibr_initial_pu": 0.0,
        "responsibility_event_time_s": 0.0,
    }
    values.update(overrides)
    return ControlRateTrace(**values)


def test_frequency_uses_high_frequency_truth_and_control_metrics_use_control_rate() -> None:
    truth = HighFrequencyTruthTrace(
        time_s=[0.0, 0.5, 1.5, 2.0],
        delta_frequency_hz=[0.0, -1.0, -1.0, 0.0],
        rocof_true_hz_per_s=[0.0, -2.0, 2.0, 0.0],
    )
    config = ClosedLoopMetricConfig(
        frequency_limit_hz=0.5,
        rocof_limit_hz_per_s=1.0,
        safety_frequency_limit_hz=2.0,
        settling_band_hz=0.1,
        ibr_command_min_pu=-0.1,
        ibr_command_max_pu=1.1,
        command_violation_persistence_s=0.5,
        responsibility_hold_s=0.5,
    )

    metrics = compute_closed_loop_metrics(
        truth,
        _control_trace(),
        config,
        run_completed=True,
    )

    assert metrics.metrics_complete
    assert metrics.max_abs_freq_hz == 1.0
    assert metrics.nadir_delta_hz == -1.0
    assert metrics.zenith_delta_hz == 0.0
    assert metrics.nadir_hz == 49.0
    assert metrics.zenith_hz == 50.0
    assert metrics.max_abs_rocof_hz_s == 2.0
    assert metrics.freq_iae == pytest.approx(1.5)
    assert metrics.freq_ise == pytest.approx(1.5)
    assert metrics.freq_violation_duration_s == pytest.approx(1.5)
    assert metrics.rocof_violation_duration_s == pytest.approx(1.0)
    assert metrics.constraint_violation_count == 1
    assert metrics.settling_time_s == pytest.approx(1.95)
    assert not metrics.settling_censored

    assert metrics.sg_mileage == 1.0
    assert metrics.ibr_mileage == 2.0
    assert metrics.ibr_tracking_error == pytest.approx(0.5)
    assert metrics.sg_abs_energy_pu_s == pytest.approx(1.0)
    assert metrics.ibr_abs_energy_pu_s == pytest.approx(0.5)
    assert metrics.peak_abs_sg_command_pu == 1.0
    assert metrics.peak_abs_ibr_command_pu == 1.0
    assert metrics.responsibility_transfer_time_s == 1.0
    assert metrics.responsibility_transfer_censored is False
    assert metrics.fallback_duration_s == 1.0

    assert metrics.solver_attempt_count == 2
    assert metrics.solve_time_mean_s == pytest.approx(0.2)
    assert metrics.solve_time_p95_s == pytest.approx(0.29)
    assert metrics.solve_time_max_s == 0.3
    assert metrics.solver_timeout_count == 1
    assert metrics.solver_timeout_rate == 0.5
    assert metrics.solver_fail_count == 1
    assert metrics.max_freq_slack_hz == 0.2
    assert not metrics.catastrophic_solver_without_fallback
    assert not metrics.catastrophic_failure
    json.dumps(metrics.to_dict(), allow_nan=False)


def test_sg_and_ibr_constraints_include_initial_to_first_slew() -> None:
    truth = HighFrequencyTruthTrace(
        time_s=[0.0, 0.5, 1.0, 1.5],
        delta_frequency_hz=[0.0, 0.0, 0.0, 0.0],
        rocof_true_hz_per_s=[0.0, 0.0, 0.0, 0.0],
    )
    control = ControlRateTrace(
        time_s=[0.0, 0.5, 1.0, 1.5],
        u_sg_pu=[0.02, 0.02, 0.13, 0.13],
        u_ibr_pu=[0.02, 0.02, 0.05, 0.05],
        p_ibr_pu=[0.0, 0.0, 0.0, 0.0],
        u_sg_initial_pu=0.0,
        u_ibr_initial_pu=0.0,
    )
    config = ClosedLoopMetricConfig(
        safety_frequency_limit_hz=2.0,
        settling_band_hz=0.1,
        sg_command_min_pu=-0.12,
        sg_command_max_pu=0.12,
        sg_slew_limit_pu_per_s=0.02,
        ibr_command_min_pu=-0.04,
        ibr_command_max_pu=0.04,
        ibr_slew_limit_pu_per_s=0.03,
        command_sample_period_s=0.5,
        command_violation_persistence_s=0.5,
    )

    metrics = compute_closed_loop_metrics(
        truth,
        control,
        config,
        run_completed=True,
    )

    # Each resource violates on the initial-to-first transition and again on
    # the later rate/amplitude transition.  The final endpoint has no extra
    # exposure duration of its own.
    assert metrics.sg_command_violation_count == 2
    assert metrics.sg_command_violation_duration_s == pytest.approx(1.0)
    assert metrics.max_contiguous_sg_command_violation_s == pytest.approx(0.5)
    assert metrics.ibr_command_violation_count == 2
    assert metrics.ibr_command_violation_duration_s == pytest.approx(1.0)
    assert metrics.max_contiguous_ibr_command_violation_s == pytest.approx(0.5)
    assert metrics.catastrophic_persistent_command_violation

    missing_initial = ControlRateTrace(
        time_s=control.time_s,
        u_sg_pu=control.u_sg_pu,
        u_ibr_pu=control.u_ibr_pu,
        p_ibr_pu=control.p_ibr_pu,
        u_ibr_initial_pu=0.0,
    )
    with pytest.raises(ValueError, match="SG initial command"):
        compute_closed_loop_metrics(
            truth,
            missing_initial,
            config,
            run_completed=True,
        )


def test_command_constraint_audit_tolerates_only_binary64_roundoff() -> None:
    truth = HighFrequencyTruthTrace(
        time_s=[0.0, 0.5, 1.0],
        delta_frequency_hz=[0.0, 0.0, 0.0],
        rocof_true_hz_per_s=[0.0, 0.0, 0.0],
    )
    config = ClosedLoopMetricConfig(
        safety_frequency_limit_hz=2.0,
        settling_band_hz=0.1,
        sg_command_min_pu=-0.12,
        sg_command_max_pu=0.12,
        sg_slew_limit_pu_per_s=0.02,
        ibr_command_min_pu=-0.04,
        ibr_command_max_pu=0.04,
        command_sample_period_s=0.5,
        command_violation_persistence_s=0.5,
    )

    # These values are one representable binary64 step above the configured
    # limits.  The SG sequence also exercises both initial-to-first and later
    # slew transitions (0.010000000000000002 pu per 0.5 s).
    roundoff_only = ControlRateTrace(
        time_s=[0.0, 0.5, 1.0],
        u_sg_pu=[
            0.010000000000000002,
            0.020000000000000004,
            0.030000000000000006,
        ],
        u_ibr_pu=[np.nextafter(0.04, np.inf)] * 3,
        p_ibr_pu=[0.0, 0.0, 0.0],
        u_sg_initial_pu=0.0,
        u_ibr_initial_pu=0.0,
    )
    metrics = compute_closed_loop_metrics(
        truth,
        roundoff_only,
        config,
        run_completed=True,
    )
    assert metrics.sg_command_violation_count == 0
    assert metrics.ibr_command_violation_count == 0
    assert not metrics.catastrophic_persistent_command_violation

    # A still-tiny 1e-12 physical overrun remains far outside the narrow
    # round-off envelope and must be reported for both slew and magnitude.
    actual_overrun = ControlRateTrace(
        time_s=[0.0, 0.5, 1.0],
        u_sg_pu=[0.01 + 1e-12, 0.02 + 2e-12, 0.03 + 3e-12],
        u_ibr_pu=[0.04 + 1e-12] * 3,
        p_ibr_pu=[0.0, 0.0, 0.0],
        u_sg_initial_pu=0.0,
        u_ibr_initial_pu=0.0,
    )
    metrics = compute_closed_loop_metrics(
        truth,
        actual_overrun,
        config,
        run_completed=True,
    )
    assert metrics.sg_command_violation_count == 1
    assert metrics.ibr_command_violation_count == 1
    assert metrics.catastrophic_persistent_command_violation


def test_rocof_is_derived_from_nonuniform_high_frequency_trace_not_control_steps() -> None:
    truth = HighFrequencyTruthTrace(
        time_s=[0.0, 0.1, 0.4, 1.0],
        omega_true_pu=np.asarray([0.0, 0.002, 0.008, 0.02]),
    )
    metrics = compute_closed_loop_metrics(
        truth,
        _control_trace(),
        ClosedLoopMetricConfig(
            rocof_limit_hz_per_s=2.0,
            safety_frequency_limit_hz=2.0,
            settling_band_hz=2.0,
        ),
        run_completed=True,
    )

    # delta f = 50 * omega = 1 Hz/s * t, exactly, despite non-uniform samples.
    assert metrics.max_abs_rocof_hz_s == pytest.approx(1.0)


def test_exact_rocof_truth_overrides_frequency_gradient_at_a_jump() -> None:
    truth = HighFrequencyTruthTrace(
        time_s=[0.0, 1.0, 2.0],
        delta_frequency_hz=[0.0, 0.0, 0.0],
        rocof_true_hz_per_s=[0.0, -0.5, 0.0],
    )
    metrics = compute_closed_loop_metrics(
        truth,
        _control_trace(
            u_sg_pu=[0.0, 0.0, 0.0],
            u_ibr_pu=[0.0, 0.0, 0.0],
            p_ibr_pu=[0.0, 0.0, 0.0],
        ),
        ClosedLoopMetricConfig(
            rocof_limit_hz_per_s=0.25,
            safety_frequency_limit_hz=2.0,
            settling_band_hz=0.1,
        ),
        run_completed=True,
    )

    # A gradient of the constant frequency samples is zero.  The evaluator
    # must instead retain the physical right-continuous derivative supplied by
    # the simulator at the disturbance boundary.
    assert metrics.max_abs_rocof_hz_s == pytest.approx(0.5)
    assert metrics.rocof_violation_duration_s == pytest.approx(1.0)


def test_settling_is_relative_to_explicit_last_event_but_iae_remains_full_episode() -> None:
    truth = HighFrequencyTruthTrace(
        time_s=[0.0, 50.0, 60.0, 70.0, 75.0, 180.0],
        delta_frequency_hz=[-0.2, 0.0, -0.3, -0.2, -0.1, 0.0],
    )
    control = _control_trace(
        time_s=[0.0, 60.0, 180.0],
        u_sg_pu=[0.0, 0.0, 0.0],
        u_ibr_pu=[0.0, 0.0, 0.0],
        p_ibr_pu=[0.0, 0.0, 0.0],
        responsibility_event_time_s=None,
    )
    config = ClosedLoopMetricConfig(
        settling_band_hz=0.1,
        safety_frequency_limit_hz=2.0,
    )

    from_start = compute_closed_loop_metrics(
        truth,
        control,
        config,
        run_completed=True,
    )
    from_event = compute_closed_loop_metrics(
        truth,
        control,
        config,
        run_completed=True,
        settling_reference_time_s=60.0,
    )

    assert from_event.settling_time_s == pytest.approx(15.0)
    assert from_event.settling_censoring_time_s == pytest.approx(120.0)
    assert from_event.freq_iae == from_start.freq_iae
    assert from_event.freq_ise == from_start.freq_ise


def test_incomplete_prefix_before_settling_reference_is_censored_not_discarded() -> None:
    truth = HighFrequencyTruthTrace(
        time_s=[0.0, 1.0, 2.0],
        delta_frequency_hz=[0.0, -0.2, -0.3],
    )
    metrics = compute_closed_loop_metrics(
        truth,
        _control_trace(),
        ClosedLoopMetricConfig(),
        run_completed=False,
        settling_reference_time_s=60.0,
    )

    assert metrics.freq_iae is not None
    assert metrics.settling_time_s is None
    assert metrics.settling_censored
    assert metrics.settling_censoring_time_s == 0.0
    assert not metrics.metrics_complete


def test_detection_delay_requires_new_edge_after_preexisting_alarm_and_retains_censoring() -> None:
    summary = evaluate_detection_delay(
        [0.0, 1.0, 2.0, 3.0, 4.0],
        [True, True, False, True, True],
        [
            DetectionWindow("switch", onset_time_s=1.0, end_time_s=4.0),
            DetectionWindow("late", onset_time_s=4.0, end_time_s=4.0),
        ],
    )

    first, second = summary.events
    assert first.preexisting_alarm
    assert first.detected
    assert first.detection_time_s == 3.0
    assert first.delay_s == 2.0
    assert second.preexisting_alarm
    assert second.censored
    assert second.delay_s is None
    assert second.censoring_time_s == 0.0
    assert summary.event_count == 2
    assert summary.detected_count == 1
    assert summary.censored_count == 1


def test_closed_loop_detection_and_censored_ood_are_flattened_with_risk_integral() -> None:
    truth = HighFrequencyTruthTrace(
        time_s=[0.0, 1.0, 2.0, 3.0],
        delta_frequency_hz=[0.0, -1.0, -1.0, 0.0],
    )
    control = _control_trace(
        time_s=[0.0, 1.0, 2.0, 3.0],
        u_sg_pu=[0.0, 0.0, 1.0, 1.0],
        u_ibr_pu=[1.0, 1.0, 0.0, 0.0],
        p_ibr_pu=[1.0, 1.0, 0.0, 0.0],
        controller_state=["KNOWN"] * 4,
        solver_outcome=["success"] * 4,
        solver_status=["optimal"] * 4,
        solve_time_s=[0.1] * 4,
        max_freq_slack_hz=[0.0] * 4,
        max_rocof_slack_hz_s=[0.0] * 4,
        max_power_slack_pu=[0.0] * 4,
        diagnostic_alarm_active=[False, False, True, True],
        ood_alarm_active=[True, True, True, True],
        responsibility_event_time_s=1.0,
    )
    metrics = compute_closed_loop_metrics(
        truth,
        control,
        ClosedLoopMetricConfig(settling_band_hz=0.1, safety_frequency_limit_hz=2.0),
        run_completed=True,
        diagnostic_event_windows=[DetectionWindow("switch", 1.0, 3.0)],
        ood_event_windows=[DetectionWindow("ood", 1.0, 3.0)],
    )

    assert metrics.detection_delay_s == 1.0
    assert metrics.detection_event_count == 1
    assert metrics.detection_censored_count == 0
    assert metrics.ood_detected is False
    assert metrics.ood_detection_delay_s is None
    assert metrics.ood_detection_censored_count == 1
    assert metrics.ood_detection_censoring_time_s == 2.0
    # From t=1 to t=2, |delta f| is one throughout.
    assert metrics.diagnostic_risk_iae == pytest.approx(1.0)


def test_nan_returns_explicit_prefix_metrics_and_all_catastrophic_subflags_are_separate() -> None:
    nan_truth = HighFrequencyTruthTrace(
        time_s=[0.0, 1.0, 2.0, 3.0],
        delta_frequency_hz=[0.0, -0.2, np.nan, 0.0],
    )
    control = _control_trace(
        u_ibr_pu=[2.0, 2.0, 2.0],
        controller_state=["KNOWN", "KNOWN", "KNOWN"],
        solver_outcome=["success", "error", "not_run"],
        solver_status=["optimal", "solver_error", "not_run"],
    )
    metrics = compute_closed_loop_metrics(
        nan_truth,
        control,
        ClosedLoopMetricConfig(
            settling_band_hz=0.05,
            ibr_command_max_pu=1.0,
            command_violation_persistence_s=1.0,
        ),
        run_completed=True,
    )

    assert not metrics.metrics_complete
    assert metrics.truth_sample_count == 2
    assert metrics.freq_iae == pytest.approx(0.1)
    assert metrics.catastrophic_nan_detected
    assert metrics.catastrophic_solver_without_fallback
    assert metrics.catastrophic_persistent_command_violation
    assert metrics.catastrophic_not_recovered
    assert metrics.catastrophic_failure


def test_safety_boundary_and_not_recovered_flags_do_not_hide_completed_run() -> None:
    truth = HighFrequencyTruthTrace(
        time_s=[0.0, 1.0, 2.0],
        delta_frequency_hz=[0.0, -2.1, -1.0],
    )
    metrics = compute_closed_loop_metrics(
        truth,
        _control_trace(),
        ClosedLoopMetricConfig(safety_frequency_limit_hz=2.0),
        run_completed=True,
    )

    assert metrics.metrics_complete
    assert metrics.catastrophic_safety_boundary
    assert metrics.catastrophic_not_recovered


def test_method_prefixed_fallback_state_covers_solver_failure_and_duration() -> None:
    truth = HighFrequencyTruthTrace(
        time_s=[0.0, 1.0, 2.0],
        delta_frequency_hz=[0.0, 0.0, 0.0],
    )
    control = _control_trace(
        controller_state=[
            "FIXED_REFERENCE_ARX_MPC_FALLBACK",
            "FIXED_REFERENCE_ARX_MPC_FALLBACK",
            "KNOWN",
        ],
        solver_outcome=["error", "not_run", "not_run"],
        solver_status=["solver_error", "not_run", "not_run"],
    )

    metrics = compute_closed_loop_metrics(
        truth,
        control,
        ClosedLoopMetricConfig(),
        run_completed=True,
    )

    assert metrics.fallback_duration_s == 2.0
    assert metrics.solver_fail_count == 1
    assert not metrics.catastrophic_solver_without_fallback


def test_truth_point_builder_coalesces_consistent_control_step_boundaries() -> None:
    class Point:
        def __init__(self, time_s: float, omega_true_pu: float) -> None:
            self.time_s = time_s
            self.omega_true_pu = omega_true_pu

    trace = HighFrequencyTruthTrace.from_points(
        [
            Point(0.0, 0.0),
            Point(0.1, 0.001),
            {"time_s": 0.1, "omega_true_pu": 0.001},
            {"time_s": 0.2, "omega_true_pu": 0.002},
        ]
    )
    assert trace.time_s.tolist() == [0.0, 0.1, 0.2]
    assert trace.rocof_true_hz_per_s is None

    exact = HighFrequencyTruthTrace.from_points(
        [
            {
                "time_s": 0.0,
                "omega_true_pu": 0.0,
                "rocof_true_hz_per_s": -0.5,
            },
            {
                "time_s": 0.1,
                "omega_true_pu": 0.001,
                "rocof_true_hz_per_s": -0.4,
            },
            {
                "time_s": 0.1,
                "omega_true_pu": 0.001,
                "rocof_true_hz_per_s": -0.4,
            },
            {
                "time_s": 0.2,
                "omega_true_pu": 0.002,
                "rocof_true_hz_per_s": -0.3,
            },
        ]
    )
    assert exact.rocof_true_hz_per_s.tolist() == [-0.5, -0.4, -0.3]

    with pytest.raises(ValueError, match="consistently include or omit"):
        HighFrequencyTruthTrace.from_points(
            [
                {
                    "time_s": 0.0,
                    "omega_true_pu": 0.0,
                    "rocof_true_hz_per_s": 0.0,
                },
                {"time_s": 0.1, "omega_true_pu": 0.0},
            ]
        )
    with pytest.raises(ValueError, match="inconsistent exact RoCoF"):
        HighFrequencyTruthTrace.from_points(
            [
                {
                    "time_s": 0.0,
                    "omega_true_pu": 0.0,
                    "rocof_true_hz_per_s": 0.0,
                },
                {
                    "time_s": 0.0,
                    "omega_true_pu": 0.0,
                    "rocof_true_hz_per_s": 0.1,
                },
            ]
        )
    with pytest.raises(ValueError, match="inconsistent"):
        HighFrequencyTruthTrace.from_points(
            [
                {"time_s": 0.0, "omega_true_pu": 0.0},
                {"time_s": 0.0, "omega_true_pu": 0.1},
            ]
        )


def test_truth_point_builder_preserves_strictly_later_event_boundary() -> None:
    left_time = 1.0 - 1.0e-14
    trace = HighFrequencyTruthTrace.from_points(
        [
            {
                "time_s": left_time,
                "omega_true_pu": 0.0,
                "rocof_true_hz_per_s": 0.0,
            },
            {
                "time_s": 1.0,
                "omega_true_pu": 0.0,
                "rocof_true_hz_per_s": -0.25,
            },
        ]
    )

    assert trace.time_s.tolist() == [left_time, 1.0]
    assert trace.rocof_true_hz_per_s.tolist() == [0.0, -0.25]
