from __future__ import annotations

from dataclasses import FrozenInstanceError
import inspect

import cvxpy as cp
import numpy as np
import pytest

from d5freq.controllers.final_arx_mpc import (
    FinalARXMPCController,
    FixedReferenceSelectionArtifact,
    MutableSingletonProblemCache,
    ReferenceCandidateScore,
    single_model_mpc_config,
    singleton_mode_from_arx,
    singleton_mode_from_theta,
)
from d5freq.controllers.sd_bmpc import SDBMPCControllerConfig
from d5freq.identification.model_library import ARXModeModel
from d5freq.interfaces import FrequencyController, Measurement
from d5freq.models.grid_frequency import GridFrequencyModel, GridParams
from d5freq.optimization.mpc_problem import SDBMPCConfig
from d5freq.optimization.solver_utils import SolverOutcome, SolverResult


def _grid() -> GridFrequencyModel:
    return GridFrequencyModel(GridParams(50.0, 8.0, 1.0, 0.5, 0.2, 0.08, 0.5, 0.02))


def _model(component_id: int = 0, horizon: int = 3) -> ARXModeModel:
    q = {lead: 0.0 for lead in range(1, horizon + 1)}
    return ARXModeModel(
        component_id=component_id,
        theta=np.array([0.7, -0.1, 0.25, 0.05, -0.2, -0.1, 0.0]),
        residual_variance=1.0e-6,
        multi_step_power_error_quantiles_pu=q,
        multi_step_frequency_error_quantiles_hz=q,
        multi_step_rocof_error_quantiles_hz_per_s=q,
        p_output_min_pu=-0.08,
        p_output_max_pu=0.08,
        ramp_down_pu_per_s=0.04,
        ramp_up_pu_per_s=0.04,
        training_episode_count=4,
        training_sample_count=100,
    )


def _mpc() -> SDBMPCConfig:
    return SDBMPCConfig(horizon_steps=3, sample_time_s=0.5, f0_hz=50.0)


def _policy() -> SDBMPCControllerConfig:
    return SDBMPCControllerConfig(
        solver_priority=("CLARABEL",),
        solve_timeout_s=2.0,
        precompile_on_reset=False,
        recovery_hold_steps=0,
        return_blend_steps=1,
    )


def test_fixed_reference_selection_is_deterministic_frozen_and_label_free() -> None:
    scores = tuple(
        ReferenceCandidateScore(index, score, 10, 10, index % 2)
        for index, score in enumerate((3.0, 1.0, 1.0))
    )
    artifact = FixedReferenceSelectionArtifact(
        mode_library_file_sha256="1" * 64,
        mode_library_logical_sha256="2" * 64,
        component_count=3,
        selected_component_id=1,
        selection_split="closed_loop_validation",
        criterion="registered_episode_mean_cost",
        direction="minimize",
        selection_dataset_sha256="3" * 64,
        protocol_sha256="4" * 64,
        label_access="none",
        candidate_scores=scores,
    )
    assert artifact.selected_component_id == 1  # stable component-ID tie break
    assert artifact.to_dict()["label_access"] == "none"
    with pytest.raises(FrozenInstanceError):
        artifact.selected_component_id = 2  # type: ignore[misc]
    with pytest.raises(ValueError, match="deterministic score optimum"):
        FixedReferenceSelectionArtifact(
            mode_library_file_sha256="1" * 64,
            mode_library_logical_sha256="2" * 64,
            component_count=3,
            selected_component_id=2,
            selection_split="closed_loop_validation",
            criterion="cost",
            direction="minimize",
            selection_dataset_sha256="3" * 64,
            protocol_sha256="4" * 64,
            label_access="none",
            candidate_scores=scores,
        )
    with pytest.raises(ValueError, match="retain every"):
        ReferenceCandidateScore(0, 1.0, 10, 9, 1)


def test_parameterized_singleton_reuses_one_dpp_graph_across_arx_updates() -> None:
    grid = _grid()
    mode = singleton_mode_from_arx(grid, _model())
    cache = MutableSingletonProblemCache(mode, single_model_mpc_config(_mpc()))
    state = np.zeros(10)
    state[9] = 1.0
    first = cache.prepare(
        state,
        np.ones(1),
        np.zeros(2),
        entropy_normalized=0.0,
        ood_suspect=False,
    )
    identity = cache.problem_identity
    changed = singleton_mode_from_theta(
        grid,
        np.array([0.5, -0.05, 0.3, 0.02, -0.1, -0.05, 0.0]),
        mode,
    )
    cache.set_mode(changed)
    second = cache.prepare(
        state,
        np.ones(1),
        np.zeros(2),
        entropy_normalized=0.0,
        ood_suspect=False,
    )
    assert first is second
    assert cache.problem_identity == identity
    assert cache.graph_build_count == 1
    assert first.problem.is_dcp(dpp=True)
    np.testing.assert_allclose(first.A_parameter.value, changed.prediction_model.A)


def test_singleton_epigraph_is_anchored_and_tight_at_optimum() -> None:
    grid = _grid()
    mode = singleton_mode_from_arx(grid, _model())
    cache = MutableSingletonProblemCache(mode, single_model_mpc_config(_mpc()))
    state = np.zeros(10)
    state[0] = -0.001
    state[9] = 1.0
    bundle = cache.prepare(
        state,
        np.ones(1),
        np.zeros(2),
        entropy_normalized=0.0,
        ood_suspect=False,
    )
    bundle.problem.solve(solver="MOSEK")
    assert bundle.problem.status == cp.OPTIMAL
    assert bundle.worst_case_epigraph.value == pytest.approx(
        float(bundle.base_cost.value), rel=1.0e-6, abs=1.0e-7
    )
    assert bundle.problem.is_dcp(dpp=True)


def test_final_arx_controller_implements_uniform_api_and_strict_failure_fallback() -> None:
    def fail(*args: object, **kwargs: object) -> SolverResult:
        return SolverResult(
            status="solver_error",
            outcome=SolverOutcome.ERROR,
            solver="CLARABEL",
            solver_version=None,
            total_wall_time_s=0.01,
            objective=None,
            values={},
            attempts=(),
            error_type="SyntheticFailure",
            error_message="injected",
        )

    controller = FinalARXMPCController(
        _grid(),
        singleton_mode_from_arx(_grid(), _model()),
        mpc_config=_mpc(),
        controller_config=_policy(),
        solve_function=fail,
    )
    assert isinstance(controller, FrequencyController)
    assert tuple(inspect.signature(controller.act).parameters) == ("measurement",)
    initial = Measurement(0.0, -0.001, 0.0, 0.0, 0.0, 0.02)
    controller.reset(initial)
    action = controller.act(initial)
    assert action.controller_state == "FIXED_REFERENCE_ARX_MPC_FALLBACK"
    assert action.solver_status == "solver_error"
    assert action.u_ibr_pu == pytest.approx(0.0)  # exact Eq.71 rate withdrawal
    assert controller.fallback_events[0].reasons == ("solver_error",)
    assert controller.act(initial) == action
    assert len(controller.step_records) == 1


def test_single_model_config_removes_uncertainty_only_worst_term() -> None:
    config = single_model_mpc_config(_mpc())
    assert config.weights.lambda_worst_base == 0.0
    assert config.weights.lambda_worst_entropy == 0.0
    assert config.credible_mass == 1.0
