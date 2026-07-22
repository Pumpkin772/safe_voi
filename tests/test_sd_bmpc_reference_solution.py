from __future__ import annotations

import cvxpy as cp
import numpy as np
import pytest

from d5freq.optimization.joint_prediction import JointARXPredictionModel
from d5freq.optimization.mpc_problem import (
    SDBMPCBounds,
    SDBMPCConfig,
    SDBMPCMode,
    SDBMPCProblem,
    SDBMPCWeights,
    build_sd_bmpc_problem,
)


def _mode(component_id: int, frequency_input: np.ndarray) -> SDBMPCMode:
    A = np.eye(10)
    B = np.zeros((10, 2))
    B[0] = frequency_input
    q95 = {1: 0.0}
    return SDBMPCMode(
        component_id=component_id,
        prediction_model=JointARXPredictionModel(A, B),
        frequency_q95_hz=q95,
        rocof_q95_hz_per_s=q95,
        power_q95_pu=q95,
        p_output_min_pu=-100.0,
        p_output_max_pu=100.0,
        ramp_down_pu_per_s=100.0,
        ramp_up_pu_per_s=100.0,
    )


def _solve_clarabel(bundle: SDBMPCProblem) -> None:
    problem = bundle.problem
    problem.solve(
        solver="CLARABEL",
        max_iter=1_000,
        tol_gap_abs=1.0e-7,
        tol_feas=1.0e-7,
    )
    assert problem.status == cp.OPTIMAL


def _assert_objective_matches_equations(bundle: SDBMPCProblem) -> None:
    mode_costs = np.asarray(
        [float(cost.value) for cost in bundle.mode_costs],
        dtype=float,
    )
    belief = bundle.belief
    active = bundle.risk_mode_indices
    settings = bundle.config
    weights = settings.weights
    slack_penalty = (
        weights.rho_freq_slack
        * float(np.sum(np.square(bundle.freq_slack_hz.value)))
        + weights.rho_rocof_slack
        * float(np.sum(np.square(bundle.rocof_slack_hz_per_s.value)))
        + weights.rho_power_slack
        * float(np.sum(np.square(bundle.power_slack_pu.value)))
    )
    expected = float(belief @ mode_costs)
    robust = bundle.lambda_worst * float(np.max(mode_costs[list(active)]))
    intended = expected + robust + slack_penalty
    assert float(bundle.problem.value) == pytest.approx(
        intended, rel=2.0e-6, abs=2.0e-7
    )
    if bundle.lambda_worst > 0.0:
        assert float(bundle.worst_case_epigraph.value) == pytest.approx(
            float(np.max(mode_costs[list(active)])), rel=2.0e-6, abs=2.0e-7
        )


def test_horizon_one_matches_direct_multimode_expected_cost_solution() -> None:
    gains = (
        np.array([0.20, -0.10]),
        np.array([-0.05, 0.30]),
    )
    belief = np.array([0.25, 0.75])
    modes = tuple(_mode(index, gain) for index, gain in enumerate(gains))
    weights = SDBMPCWeights(
        q_freq=0.0,
        q_integral=0.0,
        q_rocof=2.0,
        r_sg=3.0,
        r_ibr=4.0,
        s_delta_sg=5.0,
        s_delta_ibr=6.0,
        q_terminal_freq=7.0,
        q_terminal_integral=0.0,
        lambda_worst_base=0.0,
        lambda_worst_entropy=0.0,
        rho_freq_slack=1.0,
        rho_rocof_slack=1.0,
        rho_power_slack=1.0,
    )
    config = SDBMPCConfig(
        horizon_steps=1,
        sample_time_s=1.0,
        f0_hz=1.0,
        credible_mass=0.7,
        weights=weights,
        bounds=SDBMPCBounds(
            u_min_pu=(-100.0, -100.0),
            u_max_pu=(100.0, 100.0),
            ramp_pu_per_s=(100.0, 100.0),
            freq_limit_hz=100.0,
            rocof_limit_hz_per_s=100.0,
        ),
    )
    initial = np.zeros(10)
    initial[0] = 0.3
    initial[9] = 1.0
    previous = np.array([0.1, -0.2])
    bundle = build_sd_bmpc_problem(
        modes,
        initial,
        belief,
        previous,
        entropy_normalized=0.0,
        ood_suspect=False,
        config=config,
    )

    bundle.problem.solve(solver="SCS", eps=1.0e-8, max_iters=100_000)
    assert bundle.problem.status == cp.OPTIMAL

    expected_outer = sum(
        probability * np.outer(gain, gain)
        for probability, gain in zip(belief, gains, strict=True)
    )
    weighted_gain = sum(
        (probability * gain for probability, gain in zip(belief, gains, strict=True)),
        start=np.zeros(2),
    )
    curvature = (
        (weights.q_rocof + weights.q_terminal_freq) * expected_outer
        + np.diag(weights.input_weights + weights.delta_weights)
    )
    right_hand_side = (
        weights.delta_weights * previous
        - weights.q_terminal_freq * initial[0] * weighted_gain
    )
    expected = np.linalg.solve(curvature, right_hand_side)

    np.testing.assert_allclose(
        np.asarray(bundle.shared_input.value)[:, 0],
        expected,
        rtol=3.0e-7,
        atol=3.0e-8,
    )
    assert len(bundle.mode_costs) == 2
    # The 0.75-belief component alone reaches the requested credible mass.
    assert bundle.risk_component_ids == (1,)


def test_masked_worst_cost_is_exact_with_zero_and_near_zero_beliefs() -> None:
    modes = (
        _mode(0, np.array([0.20, -0.10])),
        _mode(1, np.array([-0.05, 0.30])),
    )
    weights = SDBMPCWeights(
        q_freq=1.0,
        q_integral=2.0,
        q_rocof=3.0,
        r_sg=4.0,
        r_ibr=5.0,
        s_delta_sg=6.0,
        s_delta_ibr=7.0,
        q_terminal_freq=8.0,
        q_terminal_integral=9.0,
        lambda_worst_base=0.4,
        lambda_worst_entropy=0.0,
        rho_freq_slack=10.0,
        rho_rocof_slack=10.0,
        rho_power_slack=10.0,
    )
    config = SDBMPCConfig(
        horizon_steps=1,
        sample_time_s=1.0,
        f0_hz=1.0,
        credible_mass=0.99,
        weights=weights,
        bounds=SDBMPCBounds(
            u_min_pu=(-10.0, -10.0),
            u_max_pu=(10.0, 10.0),
            ramp_pu_per_s=(10.0, 10.0),
            freq_limit_hz=10.0,
            rocof_limit_hz_per_s=10.0,
        ),
    )
    initial = np.zeros(10)
    initial[0] = 0.3
    initial[3] = -0.2
    initial[9] = 1.0
    bundle = build_sd_bmpc_problem(
        modes,
        initial,
        np.array([1.0, 0.0]),
        np.array([0.1, -0.2]),
        entropy_normalized=0.0,
        ood_suspect=False,
        config=config,
    )
    problem_identity = id(bundle.problem)
    assert bundle.problem.is_dcp(dpp=True)
    assert "expected_mode_cost_epigraphs" not in {
        variable.name() for variable in bundle.problem.variables()
    }

    _solve_clarabel(bundle)
    assert bundle.risk_mode_indices == (0,)
    _assert_objective_matches_equations(bundle)

    bundle.update_parameters(
        initial,
        np.array([1.0e-12, 1.0 - 1.0e-12]),
        np.array([0.1, -0.2]),
        entropy_normalized=0.0,
        ood_suspect=False,
    )
    assert id(bundle.problem) == problem_identity
    assert bundle.risk_mode_indices == (1,)
    _solve_clarabel(bundle)
    _assert_objective_matches_equations(bundle)

    bundle.update_parameters(
        initial,
        np.array([0.5, 0.5]),
        np.array([0.1, -0.2]),
        entropy_normalized=1.0,
        ood_suspect=False,
    )
    assert id(bundle.problem) == problem_identity
    assert bundle.risk_mode_indices == (0, 1)
    _solve_clarabel(bundle)
    _assert_objective_matches_equations(bundle)


def test_lambda_zero_has_exact_expected_cost_without_expected_cost_epigraphs() -> None:
    modes = (
        _mode(0, np.array([0.20, -0.10])),
        _mode(1, np.array([-0.05, 0.30])),
    )
    weights = SDBMPCWeights(
        lambda_worst_base=0.0,
        lambda_worst_entropy=0.0,
    )
    config = SDBMPCConfig(
        horizon_steps=1,
        sample_time_s=1.0,
        f0_hz=1.0,
        weights=weights,
        bounds=SDBMPCBounds(freq_limit_hz=10.0, rocof_limit_hz_per_s=10.0),
    )
    initial = np.zeros(10)
    initial[0] = 0.1
    initial[9] = 1.0
    bundle = build_sd_bmpc_problem(
        modes,
        initial,
        np.array([1.0, 0.0]),
        np.zeros(2),
        entropy_normalized=0.0,
        ood_suspect=False,
        config=config,
    )

    _solve_clarabel(bundle)

    assert bundle.lambda_worst == 0.0
    assert "expected_mode_cost_epigraphs" not in {
        variable.name() for variable in bundle.problem.variables()
    }
    assert all(
        np.all(np.isfinite(np.asarray(variable.value)))
        for variable in bundle.problem.variables()
    )
    _assert_objective_matches_equations(bundle)
