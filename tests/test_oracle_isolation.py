from __future__ import annotations

import inspect
from pathlib import Path

import numpy as np
import pytest

from d5freq.controllers.fixed_model_mpc import FixedNominalMPCController
from d5freq.evaluation.baselines.oracle import OracleMPCBaseline
from d5freq.interfaces import FrequencyController, Measurement
from d5freq.models.grid_frequency import GridParams
from d5freq.models.hidden_mode_ibr import IBRModeParams
from d5freq.optimization.linear_mpc import LinearMPC, linearize_grid_ibr


def _optimizer(name: str, command_gain: float) -> LinearMPC:
    grid = GridParams(50.0, 8.0, 1.0, 0.5, 0.2, 0.08, 0.5, 0.02)
    ibr = IBRModeParams(
        name, command_gain, 4.0, 0.1, 0.2, 0.1, 0.08, 0.08, 0.05, 0.05, 0.0005
    )
    return LinearMPC(
        linearize_grid_ibr(grid, ibr),
        horizon_steps=4,
        solver_priority=("CLARABEL",),
    )


def test_oracle_requires_explicit_evaluation_truth_and_selects_matching_model() -> None:
    fast = _optimizer("fast", 1.0)
    weak = _optimizer("weak", 0.05)
    oracle = OracleMPCBaseline({"fast": fast, "weak": weak})
    measurement = Measurement(0.0, -0.001, 0.0, 0.0, 0.0, 0.0)
    oracle.reset(measurement)

    assert oracle.select_optimizer("fast") is fast
    assert oracle.select_optimizer("weak") is weak
    action = oracle.act_evaluation_only(measurement, true_mode_eval_only="fast")
    assert action.controller_state == "ORACLE_MPC_EVALUATION_ONLY"
    with pytest.raises(KeyError, match="no Oracle optimizer"):
        oracle.select_optimizer("unknown")


def test_oracle_is_not_normal_controller_api_and_dependency_is_one_way() -> None:
    oracle_signature = inspect.signature(OracleMPCBaseline.act_evaluation_only)
    fixed_signature = inspect.signature(FixedNominalMPCController.act)
    assert "true_mode_eval_only" in oracle_signature.parameters
    assert "true_mode_eval_only" not in fixed_signature.parameters
    assert not isinstance(OracleMPCBaseline({"only": _optimizer("only", 1.0)}), FrequencyController)

    controller_source = Path(inspect.getfile(FixedNominalMPCController)).read_text(
        encoding="utf-8"
    )
    assert "d5freq.evaluation" not in controller_source
    assert "true_mode" not in controller_source
    assert ".evaluation" in OracleMPCBaseline.__module__


class _CountingGridEstimator:
    def __init__(self) -> None:
        self.reset_calls = 0
        self.update_calls = 0

    def reset_from_measurement(self, measurement: Measurement) -> np.ndarray:
        self.reset_calls += 1
        state = np.zeros(5)
        state[:2] = (measurement.omega_pu, measurement.p_mech_pu)
        return state

    def update_from_measurement(self, measurement: Measurement) -> np.ndarray:
        self.update_calls += 1
        state = np.zeros(5)
        state[:2] = (measurement.omega_pu, measurement.p_mech_pu)
        state[4] = 0.03
        return state


def test_oracle_uses_grid_estimator_once_per_new_measurement_time() -> None:
    estimator = _CountingGridEstimator()
    oracle = OracleMPCBaseline(
        {"fast": _optimizer("fast", 1.0)},
        grid_state_estimator=estimator,
    )
    initial = Measurement(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    oracle.reset(initial)
    oracle.act_evaluation_only(initial, true_mode_eval_only="fast")
    later = Measurement(0.5, -0.001, 0.0, 0.0, 0.0, 0.0)
    action = oracle.act_evaluation_only(later, true_mode_eval_only="fast")

    assert estimator.reset_calls == 1
    assert estimator.update_calls == 1
    assert action.solver_status in {"optimal", "optimal_inaccurate"}
