from __future__ import annotations

from pathlib import Path

import cvxpy as cp
import numpy as np
import pytest

from d5freq.identification.model_library import (
    ARXModeModel,
    BICRecord,
    DiscoveryMetadata,
    FeatureScalerState,
    ModeLibrary,
    sticky_transition_matrix,
)
from d5freq.models.grid_frequency import GridFrequencyModel, GridParams
from d5freq.optimization.joint_prediction import JointARXPredictionModel
from d5freq.optimization.mpc_problem import (
    SDBMPCBounds,
    SDBMPCConfig,
    SDBMPCMode,
    SDBMPCWeights,
    build_sd_bmpc_problem,
    credible_mode_indices,
    modes_from_library,
    SDBMPCProblemCache,
)


def _mode(component_id: int, horizon: int = 3) -> SDBMPCMode:
    quantiles = {lead: 0.0 for lead in range(1, horizon + 1)}
    A = np.eye(10)
    B = np.zeros((10, 2))
    B[0] = np.array([0.02 + component_id * 0.01, -0.01])
    return SDBMPCMode(
        component_id=component_id,
        prediction_model=JointARXPredictionModel(A, B),
        frequency_q95_hz=quantiles,
        rocof_q95_hz_per_s=quantiles,
        power_q95_pu=quantiles,
        p_output_min_pu=-1.0,
        p_output_max_pu=1.0,
        ramp_down_pu_per_s=1.0,
        ramp_up_pu_per_s=1.0,
    )


def _state() -> np.ndarray:
    state = np.zeros(10)
    state[9] = 1.0
    return state


def _library(component_count: int, horizon: int = 3) -> ModeLibrary:
    quantiles = {lead: 0.001 * lead for lead in range(1, horizon + 1)}
    models = tuple(
        ARXModeModel(
            component_id=index,
            theta=np.array([0.8, -0.1, 0.2, 0.03, -0.2, -0.05, 0.0]),
            residual_variance=1.0e-6,
            multi_step_power_error_quantiles_pu=quantiles,
            multi_step_frequency_error_quantiles_hz=quantiles,
            multi_step_rocof_error_quantiles_hz_per_s=quantiles,
            p_output_min_pu=-0.08,
            p_output_max_pu=0.08,
            ramp_down_pu_per_s=0.04,
            ramp_up_pu_per_s=0.04,
            training_episode_count=2,
            training_sample_count=100,
        )
        for index in range(component_count)
    )
    records = tuple(
        BICRecord(
            component_count=index,
            bic=float(component_count - index),
            delta_bic=float(component_count - index),
            converged=True,
            iterations=5,
        )
        for index in range(1, component_count + 1)
    )
    return ModeLibrary(
        models=models,
        transition_matrix=sticky_transition_matrix(component_count),
        feature_scaler=FeatureScalerState(
            mean=np.zeros(8),
            scale=np.ones(8),
            variance=np.ones(8),
            n_samples_seen=100,
        ),
        discovery_metadata=DiscoveryMetadata(
            selected_k=component_count,
            candidate_k_min=1,
            candidate_k_max=component_count,
            covariance_type="full",
            n_init=2,
            random_seed=7,
            bic_table=records,
        ),
    )


def test_problem_is_dcp_qcqp_with_one_shared_input_and_all_mode_states() -> None:
    modes = tuple(_mode(index) for index in range(3))
    config = SDBMPCConfig(
        horizon_steps=3,
        sample_time_s=0.5,
        f0_hz=50.0,
        credible_mass=0.8,
        bounds=SDBMPCBounds(freq_limit_hz=5.0, rocof_limit_hz_per_s=5.0),
    )
    bundle = build_sd_bmpc_problem(
        modes,
        _state(),
        np.array([0.6, 0.3, 0.1]),
        np.zeros(2),
        entropy_normalized=0.2,
        ood_suspect=False,
        config=config,
    )

    assert bundle.problem.is_dcp()
    assert bundle.shared_input.shape == (2, 3)
    assert len(bundle.mode_states) == len(modes)
    assert all(state.shape == (10, 4) for state in bundle.mode_states)
    assert len(bundle.mode_costs) == len(modes)
    assert bundle.freq_slack_hz.shape == (3,)
    assert bundle.rocof_slack_hz_per_s.shape == (3,)
    assert bundle.power_slack_pu.shape == (3,)
    assert list(bundle.solution_variables()).count("shared_input") == 1

    bundle.problem.solve(solver="SCS", eps=1.0e-8, max_iters=100_000)
    assert bundle.problem.status == cp.OPTIMAL
    controls = np.asarray(bundle.shared_input.value)
    for mode, state_variable in zip(modes, bundle.mode_states, strict=True):
        states = np.asarray(state_variable.value)
        np.testing.assert_allclose(states[:, 0], _state(), atol=2.0e-8)
        np.testing.assert_allclose(states[9], 1.0, atol=2.0e-8)
        for index in range(3):
            np.testing.assert_allclose(
                states[:, index + 1],
                mode.prediction_model.A @ states[:, index]
                + mode.prediction_model.B @ controls[:, index],
                atol=2.0e-8,
            )


def test_credible_set_has_minimal_mass_and_component_id_stable_ties() -> None:
    belief = np.array([0.35, 0.35, 0.20, 0.10])
    # Positions 0 and 1 tie; native component 3 precedes component 8.
    selected = credible_mode_indices(
        belief,
        0.70,
        component_ids=(8, 3, 7, 4),
    )
    assert selected == (1, 0)
    assert belief[list(selected)].sum() >= 0.70
    assert belief[list(selected[:-1])].sum() < 0.70


@pytest.mark.parametrize(
    ("entropy", "ood_suspect", "numerical_issue"),
    [(0.70, False, False), (0.1, True, False), (0.1, False, True)],
)
def test_high_entropy_suspect_or_numerical_issue_selects_all_modes(
    entropy: float,
    ood_suspect: bool,
    numerical_issue: bool,
) -> None:
    bundle = build_sd_bmpc_problem(
        tuple(_mode(index) for index in range(3)),
        _state(),
        np.array([0.98, 0.01, 0.01]),
        np.zeros(2),
        entropy_normalized=entropy,
        ood_suspect=ood_suspect,
        diagnostic_numerical_issue=numerical_issue,
        config=SDBMPCConfig(horizon_steps=3),
    )
    assert bundle.risk_mode_indices == (0, 1, 2)
    assert bundle.risk_component_ids == (0, 1, 2)


def test_normal_low_entropy_uses_minimal_credible_set() -> None:
    bundle = build_sd_bmpc_problem(
        tuple(_mode(index) for index in range(3)),
        _state(),
        np.array([0.995, 0.003, 0.002]),
        np.zeros(2),
        entropy_normalized=0.1,
        ood_suspect=False,
        config=SDBMPCConfig(horizon_steps=3, credible_mass=0.99),
    )
    assert bundle.risk_mode_indices == (0,)


def test_canonical_factory_preserves_native_k6_joint_arx_library() -> None:
    grid = GridFrequencyModel(
        GridParams(50.0, 8.0, 1.0, 0.5, 0.2, 0.08, 0.5, 0.02)
    )
    modes = modes_from_library(grid, _library(6))

    assert len(modes) == 6
    assert tuple(mode.component_id for mode in modes) == tuple(range(6))
    assert all(mode.prediction_model.A.shape == (10, 10) for mode in modes)
    assert all(mode.prediction_model.B.shape == (10, 2) for mode in modes)
    assert all(mode.prediction_model.A[9, 9] == 1.0 for mode in modes)
    with pytest.raises(ValueError, match="frozen native K=6"):
        modes_from_library(grid, _library(2))


def test_missing_future_q95_lead_is_rejected_unless_tightening_is_disabled() -> None:
    mode = _mode(0, horizon=2)
    with pytest.raises(ValueError, match="future leads 1..3"):
        build_sd_bmpc_problem(
            (mode,),
            _state(),
            np.ones(1),
            np.zeros(2),
            entropy_normalized=0.0,
            ood_suspect=False,
            config=SDBMPCConfig(horizon_steps=3),
        )

    bundle = build_sd_bmpc_problem(
        (mode,),
        _state(),
        np.ones(1),
        np.zeros(2),
        entropy_normalized=0.0,
        ood_suspect=False,
        config=SDBMPCConfig(horizon_steps=3, use_constraint_tightening=False),
    )
    np.testing.assert_array_equal(bundle.frequency_tightening_hz[0], 0.0)
    np.testing.assert_array_equal(bundle.rocof_tightening_hz_per_s[0], 0.0)


def test_initial_affine_constant_and_warm_start_are_strictly_validated() -> None:
    state = _state()
    state[9] = 0.0
    with pytest.raises(ValueError, match=r"initial_state\[9\]"):
        build_sd_bmpc_problem(
            (_mode(0),),
            state,
            np.ones(1),
            np.zeros(2),
            entropy_normalized=0.0,
            ood_suspect=False,
            config=SDBMPCConfig(horizon_steps=3),
        )

    bundle = build_sd_bmpc_problem(
        (_mode(0),),
        _state(),
        np.ones(1),
        np.zeros(2),
        entropy_normalized=0.0,
        ood_suspect=False,
        config=SDBMPCConfig(horizon_steps=3),
    )
    warm = np.arange(6, dtype=float).reshape(2, 3) / 100.0
    bundle.set_warm_start(warm)
    np.testing.assert_array_equal(bundle.shared_input.value, warm)
    warm[:] = 99.0
    assert not np.any(np.asarray(bundle.shared_input.value) == 99.0)
    with pytest.raises(ValueError, match="shape"):
        bundle.set_warm_start(np.zeros((3, 2)))


def test_dpp_cache_reuses_one_template_across_exact_risk_mask_changes() -> None:
    modes = tuple(_mode(index) for index in range(3))
    config = SDBMPCConfig(horizon_steps=3, credible_mass=0.8)
    cache = SDBMPCProblemCache(modes, config=config)
    initial = _state()
    first = cache.prepare(
        initial,
        np.array([0.60, 0.30, 0.10]),
        np.zeros(2),
        entropy_normalized=0.2,
        ood_suspect=False,
    )
    assert first.problem.is_dcp(dpp=True)
    assert first.risk_mode_indices == (0, 1)
    np.testing.assert_array_equal(first.risk_mask, [1.0, 1.0, 0.0])

    updated_state = initial.copy()
    updated_state[0] = -0.001
    second = cache.prepare(
        updated_state,
        np.array([0.55, 0.35, 0.10]),
        np.array([0.01, -0.02]),
        entropy_normalized=0.3,
        ood_suspect=False,
    )
    assert second is first
    np.testing.assert_array_equal(second.initial_state_parameter.value, updated_state)
    np.testing.assert_allclose(second.belief, [0.55, 0.35, 0.10])
    assert second.lambda_worst == pytest.approx(
        config.weights.lambda_worst_base
        + config.weights.lambda_worst_entropy * 0.3
    )

    third = cache.prepare(
        updated_state,
        np.array([0.10, 0.10, 0.80]),
        np.zeros(2),
        entropy_normalized=0.1,
        ood_suspect=False,
    )
    assert third is first
    assert third.risk_mode_indices == (2,)
    assert third.risk_component_ids == (2,)
    np.testing.assert_array_equal(third.risk_mask, [0.0, 0.0, 1.0])
    assert cache.cached_risk_sets == ((2,),)

    all_modes = cache.prepare(
        updated_state,
        np.array([0.10, 0.10, 0.80]),
        np.zeros(2),
        entropy_normalized=0.8,
        ood_suspect=False,
    )
    assert all_modes is first
    assert all_modes.problem.is_dcp(dpp=True)
    assert all_modes.risk_mode_indices == (0, 1, 2)
    np.testing.assert_array_equal(all_modes.risk_mask, 1.0)


def test_precompile_api_canonicalizes_without_creating_an_action() -> None:
    bundle = build_sd_bmpc_problem(
        (_mode(0),),
        _state(),
        np.ones(1),
        np.zeros(2),
        entropy_normalized=0.0,
        ood_suspect=False,
        config=SDBMPCConfig(horizon_steps=3),
    )
    elapsed_s = bundle.precompile("SCS")

    assert elapsed_s >= 0.0
    assert bundle.shared_input.value is None
    bundle.problem.solve(solver="SCS", eps=1.0e-8, max_iters=100_000)
    assert bundle.problem.status == cp.OPTIMAL


@pytest.mark.skipif("MOSEK" not in cp.installed_solvers(), reason="MOSEK not installed")
def test_native_k6_n20_production_solver_regression_for_degenerate_beliefs() -> None:
    repository = Path(__file__).resolve().parents[1]
    library = ModeLibrary.load_json(
        repository / "artifacts" / "mode_discovery" / "mode_library.json"
    )
    grid = GridFrequencyModel(
        GridParams(50.0, 8.0, 1.0, 0.5, 0.2, 0.08, 0.5, 0.02)
    )
    modes = modes_from_library(grid, library)
    weights = SDBMPCWeights(
        lambda_worst_base=0.0,
        lambda_worst_entropy=0.5,
    )
    config = SDBMPCConfig(horizon_steps=20, weights=weights)
    initial = _state()
    initial[0] = -0.002
    initial[3] = -0.001
    previous = np.array([0.001, -0.001])
    exact_zero = np.zeros(6)
    exact_zero[0] = 1.0
    bundle = build_sd_bmpc_problem(
        modes,
        initial,
        exact_zero,
        previous,
        entropy_normalized=0.0,
        ood_suspect=False,
        config=config,
    )
    problem_identity = id(bundle.problem)
    assert bundle.problem.is_dcp(dpp=True)
    assert "expected_mode_cost_epigraphs" not in {
        variable.name() for variable in bundle.problem.variables()
    }
    bundle.precompile("MOSEK")

    near_zero = np.full(6, 1.0e-12)
    near_zero[0] = 1.0 - 5.0e-12
    cases = (
        (exact_zero, 0.0, (0,)),
        (near_zero, 0.0, (0,)),
        (np.full(6, 1.0 / 6.0), 1.0, tuple(range(6))),
    )
    for belief, entropy, expected_risk in cases:
        bundle.update_parameters(
            initial,
            belief,
            previous,
            entropy_normalized=entropy,
            ood_suspect=False,
        )
        assert id(bundle.problem) == problem_identity
        assert bundle.risk_mode_indices == expected_risk
        bundle.problem.solve(
            solver="MOSEK",
            warm_start=True,
            mosek_params={"MSK_DPAR_OPTIMIZER_MAX_TIME": 2.0},
        )
        assert bundle.problem.status == cp.OPTIMAL
        assert all(
            variable.value is not None
            and np.all(np.isfinite(np.asarray(variable.value, dtype=float)))
            for variable in bundle.problem.variables()
        )

        mode_costs = np.asarray(
            [float(cost.value) for cost in bundle.mode_costs], dtype=float
        )
        slack_penalty = (
            weights.rho_freq_slack
            * float(np.sum(np.square(bundle.freq_slack_hz.value)))
            + weights.rho_rocof_slack
            * float(np.sum(np.square(bundle.rocof_slack_hz_per_s.value)))
            + weights.rho_power_slack
            * float(np.sum(np.square(bundle.power_slack_pu.value)))
        )
        intended = (
            float(bundle.belief @ mode_costs)
            + bundle.lambda_worst
            * float(np.max(mode_costs[list(bundle.risk_mode_indices)]))
            + slack_penalty
        )
        assert float(bundle.problem.value) == pytest.approx(
            intended, rel=2.0e-5, abs=2.0e-6
        )
        if bundle.lambda_worst > 0.0:
            assert float(bundle.worst_case_epigraph.value) == pytest.approx(
                float(np.max(mode_costs[list(bundle.risk_mode_indices)])),
                rel=2.0e-5,
                abs=2.0e-6,
            )
