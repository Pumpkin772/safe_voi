"""Known aggregate synchronous-generator frequency model.

The five-state ordering is fixed as
``[omega_pu, p_mech_pu, p_valve_pu, xi_pu_s, load_disturbance_pu]``.
Power quantities are per-unit on the system base.  ``omega_pu`` is the
per-unit frequency deviation and ``xi_pu_s`` is its time integral.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import math
from numbers import Real

import numpy as np
from numpy.typing import ArrayLike, NDArray

from d5freq.models.discretization import exact_zoh

FloatArray = NDArray[np.float64]

GRID_STATE_NAMES: tuple[str, ...] = (
    "omega_pu",
    "p_mech_pu",
    "p_valve_pu",
    "xi_pu_s",
    "load_disturbance_pu",
)
GRID_STATE_SIZE = len(GRID_STATE_NAMES)


class GridStateIndex(IntEnum):
    """Indices of the state vector defined immediately before equation (6)."""

    OMEGA_PU = 0
    P_MECH_PU = 1
    P_VALVE_PU = 2
    XI_PU_S = 3
    LOAD_DISTURBANCE_PU = 4


def _finite_real(value: float, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


@dataclass(frozen=True, slots=True)
class GridParams:
    """Physical and numerical grid parameters with explicit units.

    ``M_s``, ``T_t_s``, ``T_g_s``, ``control_period_s`` and
    ``integration_step_s`` are in seconds.  ``f0_hz`` is nominal frequency in
    hertz. ``D_pu`` and ``R_pu`` use the per-unit system base.

    A fixed-step RK4 control interval is required to contain an integer number
    of integration steps, which prevents silent command-hold boundary drift.
    """

    f0_hz: float
    M_s: float
    D_pu: float
    T_t_s: float
    T_g_s: float
    R_pu: float
    control_period_s: float
    integration_step_s: float

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            object.__setattr__(self, name, _finite_real(getattr(self, name), name))

        strictly_positive = (
            "f0_hz",
            "M_s",
            "T_t_s",
            "T_g_s",
            "R_pu",
            "control_period_s",
            "integration_step_s",
        )
        for name in strictly_positive:
            if getattr(self, name) <= 0.0:
                raise ValueError(f"{name} must be strictly positive")
        if self.D_pu < 0.0:
            raise ValueError("D_pu must be non-negative")
        if self.integration_step_s > self.control_period_s:
            raise ValueError(
                "integration_step_s must not exceed control_period_s"
            )

        steps = self.control_period_s / self.integration_step_s
        nearest_integer = round(steps)
        if nearest_integer < 1 or not math.isclose(
            steps, nearest_integer, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise ValueError(
                "control_period_s must be an integer multiple of "
                "integration_step_s"
            )

    @property
    def integration_steps_per_control_period(self) -> int:
        """Number of fixed RK4 steps in one control ZOH interval."""

        return int(round(self.control_period_s / self.integration_step_s))


def continuous_grid_matrices(
    params: GridParams,
) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray]:
    """Return ``(A_c, B_c, E_c, G_c)`` from equations (6)-(8).

    The state order is ``GRID_STATE_NAMES``. ``B_c`` multiplies synchronous
    generator command ``u_sg_pu``; ``E_c`` multiplies IBR power ``p_ibr_pu``;
    and ``G_c`` multiplies load-disturbance derivative in pu/s.
    """

    if not isinstance(params, GridParams):
        raise TypeError("params must be a GridParams instance")

    A_c = np.array(
        [
            [
                -params.D_pu / params.M_s,
                1.0 / params.M_s,
                0.0,
                0.0,
                -1.0 / params.M_s,
            ],
            [0.0, -1.0 / params.T_t_s, 1.0 / params.T_t_s, 0.0, 0.0],
            [
                -1.0 / (params.R_pu * params.T_g_s),
                0.0,
                -1.0 / params.T_g_s,
                0.0,
                0.0,
            ],
            [1.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0],
        ],
        dtype=np.float64,
    )
    B_c = np.array(
        [[0.0], [0.0], [1.0 / params.T_g_s], [0.0], [0.0]],
        dtype=np.float64,
    )
    E_c = np.array(
        [[1.0 / params.M_s], [0.0], [0.0], [0.0], [0.0]],
        dtype=np.float64,
    )
    G_c = np.array([[0.0], [0.0], [0.0], [0.0], [1.0]], dtype=np.float64)
    return A_c, B_c, E_c, G_c


def initial_grid_state(
    *,
    omega_pu: float = 0.0,
    p_mech_pu: float = 0.0,
    p_valve_pu: float = 0.0,
    xi_pu_s: float = 0.0,
    load_disturbance_pu: float = 0.0,
) -> FloatArray:
    """Build a validated state vector in the fixed equation-(6) order."""

    values = (
        omega_pu,
        p_mech_pu,
        p_valve_pu,
        xi_pu_s,
        load_disturbance_pu,
    )
    return np.array(
        [_finite_real(value, name) for value, name in zip(values, GRID_STATE_NAMES)],
        dtype=np.float64,
    )


class GridFrequencyModel:
    """Stateless evaluator for equations (1)-(8) and exact discretization."""

    __slots__ = ("params", "_A_c", "_B_c", "_E_c", "_G_c")

    state_names = GRID_STATE_NAMES
    state_size = GRID_STATE_SIZE

    def __init__(self, params: GridParams) -> None:
        if not isinstance(params, GridParams):
            raise TypeError("params must be a GridParams instance")
        self.params = params
        self._A_c, self._B_c, self._E_c, self._G_c = continuous_grid_matrices(
            params
        )

    @property
    def A_c(self) -> FloatArray:
        """Continuous state matrix; returned as a defensive copy."""

        return self._A_c.copy()

    @property
    def B_c(self) -> FloatArray:
        """Continuous SG-command matrix; returned as a defensive copy."""

        return self._B_c.copy()

    @property
    def E_c(self) -> FloatArray:
        """Continuous IBR-power matrix; returned as a defensive copy."""

        return self._E_c.copy()

    @property
    def G_c(self) -> FloatArray:
        """Continuous load-random-walk matrix; returned as a defensive copy."""

        return self._G_c.copy()

    def continuous_matrices(
        self,
    ) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray]:
        """Return defensive copies of ``(A_c, B_c, E_c, G_c)``."""

        return self.A_c, self.B_c, self.E_c, self.G_c

    def discrete_matrices(
        self, sample_time_s: float | None = None
    ) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray]:
        """Return exact-ZOH ``(A_d, B_d, E_d, G_d)``.

        ``sample_time_s`` defaults to ``params.control_period_s``. ``G_d``
        maps a load derivative held constant in pu/s over that interval.
        """

        duration_s = (
            self.params.control_period_s
            if sample_time_s is None
            else sample_time_s
        )
        A_d, B_d, E_d, G_d = exact_zoh(
            self._A_c,
            self._B_c,
            self._E_c,
            self._G_c,
            sample_time_s=duration_s,
        )
        return A_d, B_d, E_d, G_d

    def initial_state(
        self,
        *,
        omega_pu: float = 0.0,
        p_mech_pu: float = 0.0,
        p_valve_pu: float = 0.0,
        xi_pu_s: float = 0.0,
        load_disturbance_pu: float = 0.0,
    ) -> FloatArray:
        """Return a validated initial state; the model itself stores no state."""

        return initial_grid_state(
            omega_pu=omega_pu,
            p_mech_pu=p_mech_pu,
            p_valve_pu=p_valve_pu,
            xi_pu_s=xi_pu_s,
            load_disturbance_pu=load_disturbance_pu,
        )

    def zero_state(self, load_disturbance_pu: float = 0.0) -> FloatArray:
        """Return a zero dynamic state with an optional load state in pu."""

        return initial_grid_state(load_disturbance_pu=load_disturbance_pu)

    def derivative(
        self,
        state: ArrayLike,
        u_sg_pu: float,
        p_ibr_pu: float,
        load_derivative_pu_per_s: float = 0.0,
    ) -> FloatArray:
        """Evaluate equations (1)-(5) for one continuous-time instant.

        Parameters use per-unit power/frequency, except
        ``load_derivative_pu_per_s`` which is per-unit power per second.  The
        returned derivative has component units ``[pu/s, pu/s, pu/s, pu,
        pu/s]``.
        """

        raw_state = np.asarray(state)
        if np.iscomplexobj(raw_state):
            raise ValueError("state must be real-valued")
        try:
            state_vector = np.asarray(state, dtype=np.float64)
        except (TypeError, ValueError) as exc:
            raise TypeError("state must be a real-valued vector") from exc
        if state_vector.shape != (GRID_STATE_SIZE,):
            raise ValueError(
                f"state must have shape ({GRID_STATE_SIZE},) in order "
                f"{GRID_STATE_NAMES}, got {state_vector.shape}"
            )
        if not np.all(np.isfinite(state_vector)):
            raise ValueError("state must contain only finite values")

        command_pu = _finite_real(u_sg_pu, "u_sg_pu")
        ibr_power_pu = _finite_real(p_ibr_pu, "p_ibr_pu")
        load_rate_pu_per_s = _finite_real(
            load_derivative_pu_per_s, "load_derivative_pu_per_s"
        )
        return (
            self._A_c @ state_vector
            + self._B_c[:, 0] * command_pu
            + self._E_c[:, 0] * ibr_power_pu
            + self._G_c[:, 0] * load_rate_pu_per_s
        )

    def frequency_deviation_hz(self, omega_pu: float) -> float:
        """Convert per-unit frequency deviation to hertz."""

        return self.params.f0_hz * _finite_real(omega_pu, "omega_pu")

    def rocof_hz_per_s(self, omega_derivative_pu_per_s: float) -> float:
        """Convert per-unit frequency derivative to hertz per second."""

        return self.params.f0_hz * _finite_real(
            omega_derivative_pu_per_s, "omega_derivative_pu_per_s"
        )


__all__ = [
    "FloatArray",
    "GRID_STATE_NAMES",
    "GRID_STATE_SIZE",
    "GridFrequencyModel",
    "GridParams",
    "GridStateIndex",
    "continuous_grid_matrices",
    "initial_grid_state",
]
