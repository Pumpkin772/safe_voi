"""Controller-visible fixed nominal linear MPC baseline."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from d5freq.controllers.base import GridStateEstimator
from d5freq.interfaces import ControlAction, Measurement
from d5freq.optimization.linear_mpc import (
    IBR_FILTER_INDEX,
    IBR_POWER_INDEX,
    JOINT_STATE_SIZE,
    LinearMPC,
)


FloatArray = NDArray[np.float64]


def _initial_state_from_measurement(measurement: Measurement) -> FloatArray:
    state = np.zeros(JOINT_STATE_SIZE, dtype=float)
    state[0] = measurement.omega_pu
    state[1] = measurement.p_mech_pu
    state[2] = measurement.p_mech_pu
    state[IBR_FILTER_INDEX] = measurement.p_ibr_pu
    state[IBR_POWER_INDEX] = measurement.p_ibr_pu
    return state


def _correct_state_from_measurement(
    predicted_state: FloatArray, measurement: Measurement
) -> FloatArray:
    corrected = np.asarray(predicted_state, dtype=float).copy()
    if corrected.shape != (JOINT_STATE_SIZE,):
        raise ValueError("predicted_state must be a seven-state vector")
    corrected[0] = measurement.omega_pu
    corrected[1] = measurement.p_mech_pu
    corrected[IBR_POWER_INDEX] = measurement.p_ibr_pu
    return corrected


def _safe_failure_input(mpc: LinearMPC, previous: FloatArray) -> FloatArray:
    """Withdraw commands toward zero while respecting one-step bounds/rates."""

    maximum_change = mpc.bounds.ramp * mpc.model.sample_time_s
    withdrawn = previous - np.clip(previous, -maximum_change, maximum_change)
    return np.clip(withdrawn, mpc.bounds.lower, mpc.bounds.upper)


class FixedNominalMPCController:
    """Run one immutable nominal prediction model for every measurement."""

    def __init__(
        self,
        mpc: LinearMPC,
        grid_state_estimator: GridStateEstimator | None = None,
    ) -> None:
        if not isinstance(mpc, LinearMPC):
            raise TypeError("mpc must be a LinearMPC")
        if grid_state_estimator is not None and not isinstance(
            grid_state_estimator, GridStateEstimator
        ):
            raise TypeError("grid_state_estimator must satisfy GridStateEstimator")
        self._mpc = mpc
        self._grid_state_estimator = grid_state_estimator
        self._state_estimate: FloatArray | None = None
        self._last_measurement_time_s: float | None = None

    @property
    def mpc(self) -> LinearMPC:
        return self._mpc

    def reset(self, initial_measurement: Measurement) -> None:
        if not isinstance(initial_measurement, Measurement):
            raise TypeError("initial_measurement must be a Measurement")
        self._state_estimate = _initial_state_from_measurement(initial_measurement)
        if self._grid_state_estimator is not None:
            self._state_estimate[:5] = self._grid_state_estimator.reset_from_measurement(
                initial_measurement
            )
        self._last_measurement_time_s = initial_measurement.time_s
        self._mpc.reset_warm_start()

    def act(self, measurement: Measurement) -> ControlAction:
        if not isinstance(measurement, Measurement):
            raise TypeError("measurement must be a Measurement")
        if self._state_estimate is None:
            raise RuntimeError("controller must be reset before act")
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
        result = self._mpc.solve(corrected, previous)
        if result.success:
            assert result.state_sequence is not None
            action_values = result.first_action
            self._state_estimate = result.state_sequence[:, 1].copy()
            controller_state = "FIXED_NOMINAL_MPC"
        else:
            action_values = _safe_failure_input(self._mpc, previous)
            self._state_estimate = corrected
            controller_state = "FIXED_MPC_SOLVER_FAILURE"
        return ControlAction(
            u_sg_pu=float(action_values[0]),
            u_ibr_pu=float(action_values[1]),
            controller_state=controller_state,
            solver_status=result.status,
            solve_time_s=result.solve_time_s,
            max_freq_slack_hz=0.0,
        )


__all__ = ["FixedNominalMPCController"]
