from __future__ import annotations

import numpy as np
import pytest

from d5freq.controllers.rls_adaptive_mpc import (
    RLSAdaptiveMPCController,
    RLSConfig,
    project_covariance,
    project_stable_arx_theta,
)
from d5freq.controllers.sd_bmpc import SDBMPCControllerConfig
from d5freq.identification.model_library import ARXModeModel
from d5freq.interfaces import Measurement
from d5freq.models.grid_frequency import GridFrequencyModel, GridParams
from d5freq.optimization.mpc_problem import SDBMPCConfig


def _grid() -> GridFrequencyModel:
    return GridFrequencyModel(GridParams(50.0, 8.0, 1.0, 0.5, 0.2, 0.08, 0.5, 0.02))


def _model() -> ARXModeModel:
    q = {lead: 0.0 for lead in range(1, 4)}
    return ARXModeModel(
        component_id=2,
        theta=np.array([0.4, -0.05, 0.2, 0.05, -0.3, -0.1, 0.0]),
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


def _controller() -> RLSAdaptiveMPCController:
    return RLSAdaptiveMPCController(
        _grid(),
        _model(),
        mpc_config=SDBMPCConfig(horizon_steps=3),
        controller_config=SDBMPCControllerConfig(
            solver_priority=("CLARABEL",),
            solve_timeout_s=2.0,
            precompile_on_reset=False,
            recovery_hold_steps=0,
            return_blend_steps=1,
        ),
    )


def test_rls_defaults_are_prescribed_and_projection_is_stable() -> None:
    config = RLSConfig()
    assert config.forgetting_factor == 0.995
    assert config.covariance_initial_scale == 1000.0
    theta, pole_projected, _ = project_stable_arx_theta(
        np.array([2.2, -0.2, 0.2, 0.0, 0.0, 0.0, 0.0]), config
    )
    poles = np.roots([1.0, -theta[0], -theta[1]])
    assert pole_projected
    assert np.max(np.abs(poles)) <= config.maximum_arx_pole_radius + 1.0e-10
    covariance, projected = project_covariance(np.diag([-1.0, 1, 2, 3, 4, 5, 6]), config)
    assert projected
    assert np.linalg.eigvalsh(covariance)[0] > 0.0


def test_rls_equations_update_once_and_keep_same_precompiled_graph() -> None:
    controller = _controller()
    samples = (
        Measurement(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        Measurement(0.5, -0.001, 0.0, 0.001, 0.0, 0.01),
        Measurement(1.0, -0.002, 0.001, 0.004, 0.0, 0.02),
    )
    controller.reset(samples[0])
    controller.act(samples[0])
    identity = controller.problem_cache.problem_identity
    controller.act(samples[1])
    theta_before = controller.theta.copy()
    covariance_before = controller.covariance.copy()
    controller.act(samples[2])
    record = controller.update_records[-1]

    phi = np.array([0.001, 0.0, 0.02, 0.01, -0.001, 0.0, 1.0])
    denominator = 0.995 + phi @ covariance_before @ phi
    gain = covariance_before @ phi / denominator
    expected_unprojected = theta_before + gain * (0.004 - phi @ theta_before)
    expected, _, _ = project_stable_arx_theta(expected_unprojected, controller.config)
    np.testing.assert_allclose(record.theta_after, expected, rtol=1.0e-12, atol=1.0e-12)
    assert record.denominator == pytest.approx(denominator)
    assert record.update_success
    assert controller.problem_cache.problem_identity == identity
    assert controller.problem_cache.graph_build_count == 1
    assert len(controller.runtime_log_records()) == 3

    repeated = controller.act(samples[2])
    assert repeated == controller.act(samples[2])
    assert len(controller.update_records) == 3
    assert controller.problem_cache.graph_build_count == 1


def test_rls_rejects_changed_signals_at_reused_timestamp() -> None:
    controller = _controller()
    initial = Measurement(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    controller.reset(initial)
    controller.act(initial)
    with pytest.raises(ValueError, match="reused"):
        controller.act(Measurement(0.0, 0.0, 0.0, 0.001, 0.0, 0.0))

