from __future__ import annotations

import cvxpy as cp
import numpy as np

from d5freq.optimization.joint_prediction import JointARXPredictionModel
from d5freq.optimization.mpc_problem import (
    SDBMPCBounds,
    SDBMPCConfig,
    SDBMPCMode,
    SDBMPCWeights,
    build_sd_bmpc_problem,
)


def _state() -> np.ndarray:
    state = np.zeros(10)
    state[9] = 1.0
    return state


def _mode(
    component_id: int,
    A: np.ndarray,
    B: np.ndarray,
    *,
    frequency_q95_hz: dict[int, float],
    rocof_q95_hz_per_s: dict[int, float],
    p_min: float = -0.02,
    p_max: float = 0.02,
    power_ramp: float = 100.0,
) -> SDBMPCMode:
    power_q95 = {lead: 0.0 for lead in frequency_q95_hz}
    return SDBMPCMode(
        component_id=component_id,
        prediction_model=JointARXPredictionModel(A, B),
        frequency_q95_hz=frequency_q95_hz,
        rocof_q95_hz_per_s=rocof_q95_hz_per_s,
        power_q95_pu=power_q95,
        p_output_min_pu=p_min,
        p_output_max_pu=p_max,
        ramp_down_pu_per_s=power_ramp,
        ramp_up_pu_per_s=power_ramp,
    )


def _zero_control_weights() -> SDBMPCWeights:
    return SDBMPCWeights(
        q_freq=0.0,
        q_integral=0.0,
        q_rocof=0.0,
        r_sg=0.0,
        r_ibr=0.0,
        s_delta_sg=0.0,
        s_delta_ibr=0.0,
        q_terminal_freq=0.0,
        q_terminal_integral=0.0,
        lambda_worst_base=0.0,
        lambda_worst_entropy=0.0,
        rho_freq_slack=1.0,
        rho_rocof_slack=1.0,
        rho_power_slack=1.0,
    )


def test_q95_uses_future_leads_and_physical_units_without_double_conversion() -> None:
    A = np.eye(10)
    # Each future frequency is 0.006 pu = 0.3 Hz at f0=50 Hz.
    A[0] = 0.0
    A[0, 9] = 0.006
    # Each future IBR output is 0.05 pu, outside the learned +0.02 boundary.
    A[5] = 0.0
    A[5, 9] = 0.05
    mode = _mode(
        0,
        A,
        np.zeros((10, 2)),
        frequency_q95_hz={1: 0.10, 2: 0.20},
        rocof_q95_hz_per_s={1: 0.10, 2: 0.20},
    )
    bundle = build_sd_bmpc_problem(
        (mode,),
        _state(),
        np.ones(1),
        np.zeros(2),
        entropy_normalized=0.0,
        ood_suspect=False,
        config=SDBMPCConfig(
            horizon_steps=2,
            sample_time_s=0.5,
            f0_hz=50.0,
            weights=_zero_control_weights(),
            bounds=SDBMPCBounds(
                u_min_pu=(-1.0, -1.0),
                u_max_pu=(1.0, 1.0),
                ramp_pu_per_s=(10.0, 10.0),
                freq_limit_hz=0.25,
                rocof_limit_hz_per_s=0.50,
            ),
        ),
    )

    bundle.problem.solve(solver="SCS", eps=1.0e-8, max_iters=100_000)
    assert bundle.problem.status == cp.OPTIMAL
    # Tightening tables are already Hz and Hz/s; they are not multiplied by 50.
    np.testing.assert_array_equal(bundle.frequency_tightening_hz[0], [0.10, 0.20])
    np.testing.assert_array_equal(
        bundle.rocof_tightening_hz_per_s[0], [0.10, 0.20]
    )
    # Frequency margin is [0.15, 0.05] Hz for a 0.30 Hz prediction.
    np.testing.assert_allclose(bundle.freq_slack_hz.value, [0.15, 0.25], atol=2.0e-7)
    # First RoCoF is 0.6 Hz/s and its tightened margin is 0.4 Hz/s.
    np.testing.assert_allclose(
        bundle.rocof_slack_hz_per_s.value, [0.20, 0.0], atol=2.0e-7
    )
    np.testing.assert_allclose(bundle.power_slack_pu.value, [0.03, 0.03], atol=2.0e-7)


def test_shared_command_input_and_rate_constraints_hold_for_every_stage() -> None:
    horizon = 4
    A = np.eye(10)
    B = np.zeros((10, 2))
    B[0] = np.array([0.2, 0.1])
    zero_q95 = {lead: 0.0 for lead in range(1, horizon + 1)}
    modes = tuple(
        _mode(
            component_id,
            A,
            B * (component_id + 1),
            frequency_q95_hz=zero_q95,
            rocof_q95_hz_per_s=zero_q95,
            p_min=-1.0,
            p_max=1.0,
        )
        for component_id in range(2)
    )
    previous = np.array([0.03, -0.02])
    config = SDBMPCConfig(
        horizon_steps=horizon,
        sample_time_s=0.5,
        f0_hz=1.0,
        bounds=SDBMPCBounds(
            u_min_pu=(-0.04, -0.03),
            u_max_pu=(0.04, 0.03),
            ramp_pu_per_s=(0.01, 0.02),
            freq_limit_hz=10.0,
            rocof_limit_hz_per_s=10.0,
        ),
    )
    initial = _state()
    initial[0] = -0.2
    bundle = build_sd_bmpc_problem(
        modes,
        initial,
        np.array([0.5, 0.5]),
        previous,
        entropy_normalized=0.0,
        ood_suspect=False,
        config=config,
    )

    bundle.problem.solve(
        solver="CLARABEL",
        max_iter=1_000,
        tol_gap_abs=1.0e-6,
        tol_feas=1.0e-6,
    )
    assert bundle.problem.status == cp.OPTIMAL
    controls = np.asarray(bundle.shared_input.value)
    assert np.all(controls >= config.bounds.lower[:, None] - 2.0e-7)
    assert np.all(controls <= config.bounds.upper[:, None] + 2.0e-7)
    changes = np.diff(np.column_stack((previous, controls)), axis=1)
    assert np.all(
        np.abs(changes)
        <= config.bounds.ramp[:, None] * config.sample_time_s + 2.0e-7
    )
    for mode, state_variable in zip(modes, bundle.mode_states, strict=True):
        states = np.asarray(state_variable.value)
        for index in range(horizon):
            np.testing.assert_allclose(
                states[:, index + 1],
                mode.prediction_model.A @ states[:, index]
                + mode.prediction_model.B @ controls[:, index],
                atol=2.0e-8,
            )


def test_power_and_rate_constraints_share_one_nonnegative_slack_vector() -> None:
    A = np.eye(10)
    A[5, 9] = 0.04
    zero_q95 = {1: 0.0}
    mode = _mode(
        0,
        A,
        np.zeros((10, 2)),
        frequency_q95_hz=zero_q95,
        rocof_q95_hz_per_s=zero_q95,
        p_min=-0.01,
        p_max=0.01,
        power_ramp=0.02,
    )
    bundle = build_sd_bmpc_problem(
        (mode,),
        _state(),
        np.ones(1),
        np.zeros(2),
        entropy_normalized=0.0,
        ood_suspect=False,
        config=SDBMPCConfig(
            horizon_steps=1,
            sample_time_s=0.5,
            f0_hz=1.0,
            weights=_zero_control_weights(),
            bounds=SDBMPCBounds(freq_limit_hz=10.0, rocof_limit_hz_per_s=10.0),
        ),
    )

    bundle.problem.solve(solver="SCS", eps=1.0e-8, max_iters=100_000)
    assert bundle.problem.status == cp.OPTIMAL
    # p1=0.04: output upper bound needs .03 and ramp bound .01 needs .03.
    np.testing.assert_allclose(bundle.power_slack_pu.value, [0.03], atol=2.0e-7)
    assert np.all(np.asarray(bundle.freq_slack_hz.value) >= -1.0e-10)
    assert np.all(np.asarray(bundle.rocof_slack_hz_per_s.value) >= -1.0e-10)


def test_zero_risk_mask_exactly_disables_then_reactivates_mode_constraints() -> None:
    horizon = 1
    zero_q95 = {1: 0.0}
    nominal_A = np.eye(10)
    violating_A = np.eye(10)
    violating_A[0] = 0.0
    violating_A[0, 9] = 1.0
    modes = (
        _mode(
            0,
            nominal_A,
            np.zeros((10, 2)),
            frequency_q95_hz=zero_q95,
            rocof_q95_hz_per_s=zero_q95,
            p_min=-1.0,
            p_max=1.0,
        ),
        _mode(
            1,
            violating_A,
            np.zeros((10, 2)),
            frequency_q95_hz=zero_q95,
            rocof_q95_hz_per_s=zero_q95,
            p_min=-1.0,
            p_max=1.0,
        ),
    )
    config = SDBMPCConfig(
        horizon_steps=horizon,
        sample_time_s=1.0,
        f0_hz=1.0,
        weights=_zero_control_weights(),
        bounds=SDBMPCBounds(
            u_min_pu=(-1.0, -1.0),
            u_max_pu=(1.0, 1.0),
            ramp_pu_per_s=(1.0, 1.0),
            freq_limit_hz=0.1,
            rocof_limit_hz_per_s=0.1,
        ),
    )
    bundle = build_sd_bmpc_problem(
        modes,
        _state(),
        np.array([1.0, 0.0]),
        np.zeros(2),
        entropy_normalized=0.0,
        ood_suspect=False,
        config=config,
    )
    problem_identity = id(bundle.problem)
    np.testing.assert_array_equal(bundle.risk_mask, [1.0, 0.0])
    bundle.problem.solve(solver="SCS", eps=1.0e-8, max_iters=100_000)
    assert bundle.problem.status == cp.OPTIMAL
    np.testing.assert_allclose(bundle.freq_slack_hz.value, 0.0, atol=2.0e-7)
    np.testing.assert_allclose(
        bundle.rocof_slack_hz_per_s.value, 0.0, atol=2.0e-7
    )

    bundle.update_parameters(
        _state(),
        np.array([1.0, 0.0]),
        np.zeros(2),
        entropy_normalized=1.0,
        ood_suspect=False,
    )
    assert id(bundle.problem) == problem_identity
    np.testing.assert_array_equal(bundle.risk_mask, [1.0, 1.0])
    bundle.problem.solve(solver="SCS", eps=1.0e-8, max_iters=100_000)
    assert bundle.problem.status == cp.OPTIMAL
    np.testing.assert_allclose(bundle.freq_slack_hz.value, [0.9], atol=2.0e-6)
    np.testing.assert_allclose(
        bundle.rocof_slack_hz_per_s.value, [0.9], atol=2.0e-6
    )
