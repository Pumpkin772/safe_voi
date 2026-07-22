"""Evaluation-only Oracle MPC baseline with explicit truth selection."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

import numpy as np
from numpy.typing import NDArray

from d5freq.controllers.base import GridStateEstimator
from d5freq.controllers.fixed_model_mpc import (
    _correct_state_from_measurement,
    _initial_state_from_measurement,
    _safe_failure_input,
)
from d5freq.interfaces import ControlAction, Measurement
from d5freq.optimization.linear_mpc import LinearMPC


FloatArray = NDArray[np.float64]


class OracleMPCBaseline:
    """Select the matching prediction model using evaluator-provided truth.

    This intentionally does not implement the normal controller protocol:
    the executable method has an evaluation-only name and requires truth.
    """

    def __init__(
        self,
        optimizers_by_truth: Mapping[str, LinearMPC],
        grid_state_estimator: GridStateEstimator | None = None,
    ) -> None:
        copied = dict(optimizers_by_truth)
        if not copied:
            raise ValueError("optimizers_by_truth must not be empty")
        if any(not isinstance(name, str) or not name.strip() for name in copied):
            raise ValueError("truth names must be non-empty strings")
        if any(not isinstance(optimizer, LinearMPC) for optimizer in copied.values()):
            raise TypeError("all oracle optimizers must be LinearMPC instances")
        if grid_state_estimator is not None and not isinstance(
            grid_state_estimator, GridStateEstimator
        ):
            raise TypeError("grid_state_estimator must satisfy GridStateEstimator")
        self._optimizers = MappingProxyType(copied)
        self._grid_state_estimator = grid_state_estimator
        self._state_estimate: FloatArray | None = None
        self._last_measurement_time_s: float | None = None

    def select_optimizer(self, true_mode_eval_only: str) -> LinearMPC:
        """Return the optimizer selected explicitly by the evaluation layer."""

        try:
            return self._optimizers[true_mode_eval_only]
        except KeyError as exc:
            raise KeyError(f"no Oracle optimizer for evaluation truth {true_mode_eval_only!r}") from exc

    def reset(self, initial_measurement: Measurement) -> None:
        if not isinstance(initial_measurement, Measurement):
            raise TypeError("initial_measurement must be a Measurement")
        self._state_estimate = _initial_state_from_measurement(initial_measurement)
        if self._grid_state_estimator is not None:
            self._state_estimate[:5] = self._grid_state_estimator.reset_from_measurement(
                initial_measurement
            )
        self._last_measurement_time_s = initial_measurement.time_s
        for optimizer in self._optimizers.values():
            optimizer.reset_warm_start()

    def act_evaluation_only(
        self,
        measurement: Measurement,
        *,
        true_mode_eval_only: str,
    ) -> ControlAction:
        """Execute one Oracle action from an evaluator-owned truth label."""

        if not isinstance(measurement, Measurement):
            raise TypeError("measurement must be a Measurement")
        if self._state_estimate is None:
            raise RuntimeError("Oracle baseline must be reset before act")
        optimizer = self.select_optimizer(true_mode_eval_only)
        corrected = _correct_state_from_measurement(self._state_estimate, measurement)
        assert self._last_measurement_time_s is not None
        if measurement.time_s < self._last_measurement_time_s:
            raise ValueError("measurement time must be nondecreasing")
        if (
            self._grid_state_estimator is not None
            and measurement.time_s > self._last_measurement_time_s
        ):
            corrected[:5] = self._grid_state_estimator.update_from_measurement(
                measurement
            )
        self._last_measurement_time_s = measurement.time_s
        previous = np.array(
            [measurement.u_sg_prev_pu, measurement.u_ibr_prev_pu], dtype=float
        )
        result = optimizer.solve(corrected, previous)
        if result.success:
            assert result.state_sequence is not None
            action_values = result.first_action
            self._state_estimate = result.state_sequence[:, 1].copy()
            controller_state = "ORACLE_MPC_EVALUATION_ONLY"
        else:
            action_values = _safe_failure_input(optimizer, previous)
            self._state_estimate = corrected
            controller_state = "ORACLE_MPC_SOLVER_FAILURE"
        return ControlAction(
            u_sg_pu=float(action_values[0]),
            u_ibr_pu=float(action_values[1]),
            controller_state=controller_state,
            solver_status=result.status,
            solve_time_s=result.solve_time_s,
            max_freq_slack_hz=0.0,
        )


__all__ = ["OracleMPCBaseline"]
