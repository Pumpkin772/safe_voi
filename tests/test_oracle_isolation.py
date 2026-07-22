from __future__ import annotations

from dataclasses import replace
import inspect
from pathlib import Path

import numpy as np
import pytest

from d5freq.evaluation.baselines.oracle import (
    OracleARXArtifact,
    OracleARXMPCBaseline,
    OracleARXRecord,
    OracleMPCBaseline,
)
from d5freq.identification.model_library import ARXModeModel
from d5freq.interfaces import FrequencyController, Measurement
from d5freq.models.grid_frequency import GridFrequencyModel, GridParams
from d5freq.optimization.mpc_problem import SDBMPCConfig
from d5freq.controllers.sd_bmpc import SDBMPCControllerConfig


def _grid() -> GridFrequencyModel:
    return GridFrequencyModel(GridParams(50.0, 8.0, 1.0, 0.5, 0.2, 0.08, 0.5, 0.02))


def _model(b0: float) -> ARXModeModel:
    q = {1: 0.0, 2: 0.0}
    return ARXModeModel(
        component_id=0,
        theta=np.array([0.5, -0.1, b0, 0.0, -0.1, 0.0, 0.0]),
        residual_variance=1.0e-6,
        multi_step_power_error_quantiles_pu=q,
        multi_step_frequency_error_quantiles_hz=q,
        multi_step_rocof_error_quantiles_hz_per_s=q,
        p_output_min_pu=-0.08,
        p_output_max_pu=0.08,
        ramp_down_pu_per_s=0.04,
        ramp_up_pu_per_s=0.04,
        training_episode_count=8,
        training_sample_count=1000,
    )


def _artifact() -> OracleARXArtifact:
    return OracleARXArtifact(
        training_dataset_sha256="1" * 64,
        config_sha256="2" * 64,
        models=(
            OracleARXRecord("known_a", _model(0.2)),
            OracleARXRecord("known_b", _model(0.4)),
        ),
    )


class _CountingEstimator:
    def __init__(self) -> None:
        self.reset_calls = 0
        self.update_calls = 0

    def reset_from_measurement(self, measurement: Measurement) -> np.ndarray:
        self.reset_calls += 1
        return np.array([measurement.omega_pu, measurement.p_mech_pu, 0, 0, 0])

    def update_from_measurement(self, measurement: Measurement) -> np.ndarray:
        self.update_calls += 1
        return np.array([measurement.omega_pu, measurement.p_mech_pu, 0, 0, 0])


def _oracle(estimator: _CountingEstimator | None = None) -> OracleARXMPCBaseline:
    return OracleARXMPCBaseline(
        _grid(),
        _artifact(),
        mpc_config=SDBMPCConfig(horizon_steps=2),
        controller_config=SDBMPCControllerConfig(
            solver_priority=("CLARABEL",),
            solve_timeout_s=2.0,
            precompile_on_reset=False,
        ),
        estimator=estimator,
    )


def test_oracle_is_evaluation_only_supervised_arx_not_normal_api() -> None:
    oracle = _oracle()
    assert OracleMPCBaseline is OracleARXMPCBaseline
    assert not isinstance(oracle, FrequencyController)
    signature = inspect.signature(oracle.act_evaluation_only)
    assert "true_mode_eval_only" in signature.parameters
    assert oracle.select_arx("known_a").theta[2] == pytest.approx(0.2)
    with pytest.raises(KeyError, match="no supervised Oracle ARX"):
        oracle.select_arx("unknown")
    payload = _artifact().to_dict()
    assert OracleARXArtifact.from_dict(payload).to_dict() == payload
    with pytest.raises(ValueError, match=r"equation-\(17\)"):
        replace(_artifact(), model_family="private_physical_linearization")


def test_oracle_switches_parameterized_arx_and_unseen_mode_immediately_falls_back() -> None:
    estimator = _CountingEstimator()
    oracle = _oracle(estimator)
    initial = Measurement(0.0, -0.001, 0.0, 0.0, 0.0, 0.02)
    oracle.reset(initial)
    first = oracle.act_evaluation_only(initial, true_mode_eval_only="known_a")
    problem_identity = oracle.inner_controller.problem_cache.problem_identity
    later = Measurement(0.5, -0.001, 0.0, 0.0, first.u_sg_pu, first.u_ibr_pu)
    oracle.act_evaluation_only(later, true_mode_eval_only="known_b")
    assert oracle.inner_controller.problem_cache.problem_identity == problem_identity
    unseen = Measurement(1.0, -0.002, 0.0, 0.01, 0.0, 0.02)
    action = oracle.act_evaluation_only(unseen, true_mode_eval_only="ood_unseen")
    assert action.controller_state == "ORACLE_ARX_TRUTH_INFORMED_OOD_FALLBACK"
    assert action.solver_status == "not_run_fallback_trigger"
    assert oracle.routing_records[-1].truth_informed_fallback
    assert estimator.reset_calls == 1
    assert estimator.update_calls == 2


def test_controller_packages_do_not_import_evaluation_or_accept_evaluator_key() -> None:
    controller_root = Path(__file__).resolve().parents[1] / "src" / "d5freq" / "controllers"
    for source_path in controller_root.glob("*.py"):
        source = source_path.read_text(encoding="utf-8")
        assert "d5freq.evaluation" not in source
        assert "true_mode_eval_only" not in source
