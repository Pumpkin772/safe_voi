"""Convex single-model MPC shared by fixed and evaluation-only baselines."""

from __future__ import annotations

from dataclasses import dataclass
import math
from time import perf_counter

import cvxpy as cp
import numpy as np
from numpy.typing import ArrayLike, NDArray

from d5freq.models.discretization import exact_zoh
from d5freq.models.grid_frequency import GridParams, continuous_grid_matrices
from d5freq.models.hidden_mode_ibr import IBRModeParams


FloatArray = NDArray[np.float64]
JOINT_STATE_SIZE = 7
INPUT_SIZE = 2
OMEGA_INDEX = 0
INTEGRAL_INDEX = 3
IBR_FILTER_INDEX = 5
IBR_POWER_INDEX = 6


def _finite(value: float, name: str) -> float:
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


def _vector(value: ArrayLike, size: int, name: str) -> FloatArray:
    vector = np.asarray(value, dtype=float)
    if vector.shape != (size,):
        raise ValueError(f"{name} must have shape ({size},)")
    if not np.all(np.isfinite(vector)):
        raise ValueError(f"{name} must contain only finite values")
    return vector.copy()


def _matrix(value: ArrayLike, shape: tuple[int, int], name: str) -> FloatArray:
    matrix = np.asarray(value, dtype=float)
    if matrix.shape != shape:
        raise ValueError(f"{name} must have shape {shape}")
    if not np.all(np.isfinite(matrix)):
        raise ValueError(f"{name} must contain only finite values")
    owned = matrix.copy()
    owned.setflags(write=False)
    return owned


@dataclass(frozen=True, slots=True)
class LinearPredictionModel:
    """Discrete seven-state grid/IBR model used by a single-model MPC."""

    A: FloatArray
    B: FloatArray
    sample_time_s: float
    f0_hz: float
    name: str = "linear_model"
    p_ibr_min_pu: float | None = None
    p_ibr_max_pu: float | None = None
    p_ibr_ramp_up_pu_per_s: float | None = None
    p_ibr_ramp_down_pu_per_s: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "A", _matrix(self.A, (JOINT_STATE_SIZE, JOINT_STATE_SIZE), "A"))
        object.__setattr__(self, "B", _matrix(self.B, (JOINT_STATE_SIZE, INPUT_SIZE), "B"))
        sample_time = _finite(self.sample_time_s, "sample_time_s")
        nominal_frequency = _finite(self.f0_hz, "f0_hz")
        if sample_time <= 0.0 or nominal_frequency <= 0.0:
            raise ValueError("sample_time_s and f0_hz must be positive")
        name = str(self.name).strip()
        if not name:
            raise ValueError("name must not be empty")
        object.__setattr__(self, "sample_time_s", sample_time)
        object.__setattr__(self, "f0_hz", nominal_frequency)
        object.__setattr__(self, "name", name)
        lower = self.p_ibr_min_pu
        upper = self.p_ibr_max_pu
        if (lower is None) != (upper is None):
            raise ValueError("IBR power lower and upper limits must be provided together")
        if lower is not None and upper is not None:
            normalized_lower = _finite(lower, "p_ibr_min_pu")
            normalized_upper = _finite(upper, "p_ibr_max_pu")
            if normalized_lower > normalized_upper:
                raise ValueError("p_ibr_min_pu must not exceed p_ibr_max_pu")
            object.__setattr__(self, "p_ibr_min_pu", normalized_lower)
            object.__setattr__(self, "p_ibr_max_pu", normalized_upper)
        for field_name in (
            "p_ibr_ramp_up_pu_per_s",
            "p_ibr_ramp_down_pu_per_s",
        ):
            value = getattr(self, field_name)
            if value is not None:
                normalized = _finite(value, field_name)
                if normalized < 0.0:
                    raise ValueError(f"{field_name} must be non-negative")
                object.__setattr__(self, field_name, normalized)


def linearize_grid_ibr(
    grid_params: GridParams,
    ibr_params: IBRModeParams,
) -> LinearPredictionModel:
    """Build the nominal seven-state linearization with delay/nonlinearities omitted.

    State order is ``[omega, p_m, p_v, xi, d, q, p_ibr]`` and input order is
    ``[u_sg, u_ibr]``. The IBR deadband, delay, saturation, and ramp clipping
    remain truth-model mismatch by design.
    """

    if not isinstance(grid_params, GridParams):
        raise TypeError("grid_params must be a GridParams instance")
    if not isinstance(ibr_params, IBRModeParams):
        raise TypeError("ibr_params must be an IBRModeParams instance")

    grid_A, grid_B, grid_E, _ = continuous_grid_matrices(grid_params)
    A_c = np.zeros((JOINT_STATE_SIZE, JOINT_STATE_SIZE), dtype=float)
    B_c = np.zeros((JOINT_STATE_SIZE, INPUT_SIZE), dtype=float)
    A_c[:5, :5] = grid_A
    A_c[:5, IBR_POWER_INDEX] = grid_E[:, 0]
    B_c[:5, 0] = grid_B[:, 0]

    A_c[IBR_FILTER_INDEX, OMEGA_INDEX] = (
        -ibr_params.frequency_gain / ibr_params.command_filter_time_s
    )
    A_c[IBR_FILTER_INDEX, IBR_FILTER_INDEX] = (
        -1.0 / ibr_params.command_filter_time_s
    )
    B_c[IBR_FILTER_INDEX, 1] = (
        ibr_params.command_gain / ibr_params.command_filter_time_s
    )
    A_c[IBR_POWER_INDEX, IBR_FILTER_INDEX] = (
        1.0 / ibr_params.power_response_time_s
    )
    A_c[IBR_POWER_INDEX, IBR_POWER_INDEX] = (
        -1.0 / ibr_params.power_response_time_s
    )

    A_d, B_d = exact_zoh(A_c, B_c, sample_time_s=grid_params.control_period_s)
    return LinearPredictionModel(
        A=A_d,
        B=B_d,
        sample_time_s=grid_params.control_period_s,
        f0_hz=grid_params.f0_hz,
        name=ibr_params.name,
        p_ibr_min_pu=-ibr_params.p_max_neg_pu,
        p_ibr_max_pu=ibr_params.p_max_pos_pu,
        p_ibr_ramp_up_pu_per_s=ibr_params.ramp_up_pu_per_s,
        p_ibr_ramp_down_pu_per_s=ibr_params.ramp_down_pu_per_s,
    )


@dataclass(frozen=True, slots=True)
class MPCWeights:
    q_freq: float = 3000.0
    q_integral: float = 50.0
    q_rocof: float = 50.0
    r_sg: float = 1.0
    r_ibr: float = 0.5
    s_delta_sg: float = 20.0
    s_delta_ibr: float = 10.0
    q_terminal_freq: float = 6000.0
    q_terminal_integral: float = 100.0
    rho_power_slack: float = 1.0e6

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = _finite(getattr(self, name), name)
            if value < 0.0:
                raise ValueError(f"{name} must be non-negative")
            object.__setattr__(self, name, value)

    @property
    def input_weights(self) -> FloatArray:
        return np.array([self.r_sg, self.r_ibr], dtype=float)

    @property
    def delta_weights(self) -> FloatArray:
        return np.array([self.s_delta_sg, self.s_delta_ibr], dtype=float)


@dataclass(frozen=True, slots=True)
class MPCBounds:
    u_min_pu: tuple[float, float] = (-0.12, -0.08)
    u_max_pu: tuple[float, float] = (0.12, 0.08)
    ramp_pu_per_s: tuple[float, float] = (0.02, 0.04)
    freq_limit_hz: float | None = None
    rocof_limit_hz_per_s: float | None = None
    p_ibr_min_pu: float | None = None
    p_ibr_max_pu: float | None = None
    p_ibr_ramp_up_pu_per_s: float | None = None
    p_ibr_ramp_down_pu_per_s: float | None = None

    def __post_init__(self) -> None:
        lower = tuple(_finite(value, "u_min_pu") for value in self.u_min_pu)
        upper = tuple(_finite(value, "u_max_pu") for value in self.u_max_pu)
        ramp = tuple(_finite(value, "ramp_pu_per_s") for value in self.ramp_pu_per_s)
        if len(lower) != INPUT_SIZE or len(upper) != INPUT_SIZE or len(ramp) != INPUT_SIZE:
            raise ValueError("input bounds and ramps must each contain two values")
        if any(lo >= hi for lo, hi in zip(lower, upper, strict=True)):
            raise ValueError("each input lower bound must be below its upper bound")
        if any(value < 0.0 for value in ramp):
            raise ValueError("input ramp limits must be non-negative")
        object.__setattr__(self, "u_min_pu", lower)
        object.__setattr__(self, "u_max_pu", upper)
        object.__setattr__(self, "ramp_pu_per_s", ramp)
        for name in ("freq_limit_hz", "rocof_limit_hz_per_s"):
            value = getattr(self, name)
            if value is not None:
                normalized = _finite(value, name)
                if normalized <= 0.0:
                    raise ValueError(f"{name} must be positive when provided")
                object.__setattr__(self, name, normalized)
        power_lower = self.p_ibr_min_pu
        power_upper = self.p_ibr_max_pu
        if (power_lower is None) != (power_upper is None):
            raise ValueError("IBR power lower and upper overrides must be provided together")
        if power_lower is not None and power_upper is not None:
            normalized_lower = _finite(power_lower, "p_ibr_min_pu")
            normalized_upper = _finite(power_upper, "p_ibr_max_pu")
            if normalized_lower > normalized_upper:
                raise ValueError("p_ibr_min_pu must not exceed p_ibr_max_pu")
            object.__setattr__(self, "p_ibr_min_pu", normalized_lower)
            object.__setattr__(self, "p_ibr_max_pu", normalized_upper)
        for name in (
            "p_ibr_ramp_up_pu_per_s",
            "p_ibr_ramp_down_pu_per_s",
        ):
            value = getattr(self, name)
            if value is not None:
                normalized = _finite(value, name)
                if normalized < 0.0:
                    raise ValueError(f"{name} must be non-negative")
                object.__setattr__(self, name, normalized)

    @property
    def lower(self) -> FloatArray:
        return np.asarray(self.u_min_pu, dtype=float)

    @property
    def upper(self) -> FloatArray:
        return np.asarray(self.u_max_pu, dtype=float)

    @property
    def ramp(self) -> FloatArray:
        return np.asarray(self.ramp_pu_per_s, dtype=float)


@dataclass(frozen=True, slots=True)
class LinearMPCResult:
    status: str
    solver: str | None
    solve_time_s: float
    objective: float | None
    control_sequence: FloatArray | None
    state_sequence: FloatArray | None
    max_power_slack_pu: float | None = None
    iterations: int | None = None
    error: str | None = None

    @property
    def success(self) -> bool:
        return (
            self.status in {cp.OPTIMAL, cp.OPTIMAL_INACCURATE}
            and self.control_sequence is not None
            and self.state_sequence is not None
        )

    @property
    def first_action(self) -> FloatArray:
        if not self.success or self.control_sequence is None:
            raise RuntimeError("MPC result has no executable action")
        return self.control_sequence[:, 0].copy()


class LinearMPC:
    """Finite-horizon convex QP with one shared SG/IBR input sequence."""

    def __init__(
        self,
        model: LinearPredictionModel,
        *,
        horizon_steps: int = 20,
        weights: MPCWeights | None = None,
        bounds: MPCBounds | None = None,
        solver_priority: tuple[str, ...] = ("MOSEK", "GUROBI", "CLARABEL", "SCS"),
        warm_start: bool = True,
    ) -> None:
        if not isinstance(model, LinearPredictionModel):
            raise TypeError("model must be a LinearPredictionModel")
        if isinstance(horizon_steps, bool) or int(horizon_steps) != horizon_steps:
            raise TypeError("horizon_steps must be an integer")
        if int(horizon_steps) < 1:
            raise ValueError("horizon_steps must be positive")
        if weights is not None and not isinstance(weights, MPCWeights):
            raise TypeError("weights must be an MPCWeights instance")
        if bounds is not None and not isinstance(bounds, MPCBounds):
            raise TypeError("bounds must be an MPCBounds instance")
        priority = tuple(str(solver).strip().upper() for solver in solver_priority)
        if not priority or any(not solver for solver in priority):
            raise ValueError("solver_priority must contain non-empty solver names")
        self.model = model
        self.horizon_steps = int(horizon_steps)
        self.weights = MPCWeights() if weights is None else weights
        self.bounds = MPCBounds() if bounds is None else bounds
        self.solver_priority = priority
        self.warm_start = bool(warm_start)
        self._warm_sequence: FloatArray | None = None

    def _ibr_limits(
        self,
    ) -> tuple[float | None, float | None, float | None, float | None]:
        """Return explicit bounds overrides or model-library capabilities."""

        return (
            self.bounds.p_ibr_min_pu
            if self.bounds.p_ibr_min_pu is not None
            else self.model.p_ibr_min_pu,
            self.bounds.p_ibr_max_pu
            if self.bounds.p_ibr_max_pu is not None
            else self.model.p_ibr_max_pu,
            self.bounds.p_ibr_ramp_up_pu_per_s
            if self.bounds.p_ibr_ramp_up_pu_per_s is not None
            else self.model.p_ibr_ramp_up_pu_per_s,
            self.bounds.p_ibr_ramp_down_pu_per_s
            if self.bounds.p_ibr_ramp_down_pu_per_s is not None
            else self.model.p_ibr_ramp_down_pu_per_s,
        )

    def reset_warm_start(self) -> None:
        self._warm_sequence = None

    def solve(self, initial_state: ArrayLike, previous_input: ArrayLike) -> LinearMPCResult:
        state0 = _vector(initial_state, JOINT_STATE_SIZE, "initial_state")
        previous = _vector(previous_input, INPUT_SIZE, "previous_input")
        horizon = self.horizon_steps
        state = cp.Variable((JOINT_STATE_SIZE, horizon + 1), name="state")
        shared_input = cp.Variable((INPUT_SIZE, horizon), name="shared_input")
        constraints: list[cp.Constraint] = [state[:, 0] == state0]
        objective: cp.Expression = cp.Constant(0.0)
        previous_expression: cp.Expression = cp.Constant(previous)
        p_ibr_min, p_ibr_max, p_ibr_ramp_up, p_ibr_ramp_down = self._ibr_limits()
        initial_ibr_power = float(state0[IBR_POWER_INDEX])
        power_outside_capability = bool(
            p_ibr_min is not None
            and p_ibr_max is not None
            and (initial_ibr_power < p_ibr_min or initial_ibr_power > p_ibr_max)
        )
        # A switched mode can inherit physical power outside its new limits.
        # Its saturated/rate-clipped truth dynamics are not representable by
        # this deliberately linear baseline, so use a high-penalty slack only
        # during that transient while contracting the desired envelope at the
        # declared physical ramp. Ordinary in-capability operation remains hard.
        transient_power_slack = (
            cp.Variable(horizon, nonneg=True, name="transient_power_slack")
            if power_outside_capability
            else None
        )
        if transient_power_slack is not None:
            objective += self.weights.rho_power_slack * cp.sum_squares(
                transient_power_slack
            )

        for index in range(horizon):
            constraints.append(
                state[:, index + 1]
                == self.model.A @ state[:, index] + self.model.B @ shared_input[:, index]
            )
            constraints.extend(
                [
                    shared_input[:, index] >= self.bounds.lower,
                    shared_input[:, index] <= self.bounds.upper,
                ]
            )
            delta = shared_input[:, index] - previous_expression
            constraints.extend(
                [
                    delta <= self.bounds.ramp * self.model.sample_time_s,
                    delta >= -self.bounds.ramp * self.model.sample_time_s,
                ]
            )
            frequency_hz = self.model.f0_hz * state[OMEGA_INDEX, index]
            next_frequency_hz = self.model.f0_hz * state[OMEGA_INDEX, index + 1]
            rocof_hz_per_s = (
                next_frequency_hz - frequency_hz
            ) / self.model.sample_time_s
            objective += (
                self.weights.q_freq * cp.square(frequency_hz)
                + self.weights.q_integral * cp.square(state[INTEGRAL_INDEX, index])
                + self.weights.q_rocof * cp.square(rocof_hz_per_s)
                + cp.sum(cp.multiply(self.weights.input_weights, cp.square(shared_input[:, index])))
                + cp.sum(cp.multiply(self.weights.delta_weights, cp.square(delta)))
            )
            if self.bounds.freq_limit_hz is not None:
                constraints.append(cp.abs(next_frequency_hz) <= self.bounds.freq_limit_hz)
            if self.bounds.rocof_limit_hz_per_s is not None:
                constraints.append(
                    cp.abs(rocof_hz_per_s) <= self.bounds.rocof_limit_hz_per_s
                )
            next_ibr_power = state[IBR_POWER_INDEX, index + 1]
            current_ibr_power = state[IBR_POWER_INDEX, index]
            if p_ibr_min is not None and p_ibr_max is not None:
                if transient_power_slack is None:
                    constraints.extend(
                        [next_ibr_power >= p_ibr_min, next_ibr_power <= p_ibr_max]
                    )
                else:
                    lower_envelope = p_ibr_min
                    upper_envelope = p_ibr_max
                    if initial_ibr_power > p_ibr_max:
                        decay = 0.0 if p_ibr_ramp_down is None else (
                            (index + 1)
                            * p_ibr_ramp_down
                            * self.model.sample_time_s
                        )
                        upper_envelope = max(
                            p_ibr_max, initial_ibr_power - decay
                        )
                    if initial_ibr_power < p_ibr_min:
                        recovery = 0.0 if p_ibr_ramp_up is None else (
                            (index + 1)
                            * p_ibr_ramp_up
                            * self.model.sample_time_s
                        )
                        lower_envelope = min(
                            p_ibr_min, initial_ibr_power + recovery
                        )
                    constraints.extend(
                        [
                            next_ibr_power
                            >= lower_envelope - transient_power_slack[index],
                            next_ibr_power
                            <= upper_envelope + transient_power_slack[index],
                        ]
                    )
            if p_ibr_ramp_up is not None:
                constraints.append(
                    next_ibr_power - current_ibr_power
                    <= p_ibr_ramp_up * self.model.sample_time_s
                    + (
                        transient_power_slack[index]
                        if transient_power_slack is not None
                        else 0.0
                    )
                )
            if p_ibr_ramp_down is not None:
                constraints.append(
                    next_ibr_power - current_ibr_power
                    >= -p_ibr_ramp_down * self.model.sample_time_s
                    - (
                        transient_power_slack[index]
                        if transient_power_slack is not None
                        else 0.0
                    )
                )
            previous_expression = shared_input[:, index]

        terminal_frequency_hz = self.model.f0_hz * state[OMEGA_INDEX, horizon]
        objective += self.weights.q_terminal_freq * cp.square(terminal_frequency_hz)
        objective += self.weights.q_terminal_integral * cp.square(
            state[INTEGRAL_INDEX, horizon]
        )
        problem = cp.Problem(cp.Minimize(objective), constraints)
        if not problem.is_dcp():
            raise RuntimeError("linear MPC problem is unexpectedly non-DCP")

        if self.warm_start and self._warm_sequence is not None:
            shared_input.value = self._warm_sequence.copy()
        installed = set(cp.installed_solvers())
        attempts: list[str] = []
        final_status = "solver_failed"
        final_solver: str | None = None
        total_start = perf_counter()
        for solver in self.solver_priority:
            if solver not in installed:
                attempts.append(f"{solver}:not_installed")
                continue
            try:
                problem.solve(solver=solver, warm_start=self.warm_start, verbose=False)
            except Exception as exc:  # Solver failures are returned as auditable data.
                final_status = "solver_error"
                final_solver = solver
                attempts.append(f"{solver}:{type(exc).__name__}")
                continue
            if problem.status not in {cp.OPTIMAL, cp.OPTIMAL_INACCURATE}:
                final_status = str(problem.status)
                final_solver = solver
                attempts.append(f"{solver}:{problem.status}")
                continue
            controls = np.asarray(shared_input.value, dtype=float)
            states = np.asarray(state.value, dtype=float)
            if controls.shape != (INPUT_SIZE, horizon) or states.shape != (
                JOINT_STATE_SIZE,
                horizon + 1,
            ):
                attempts.append(f"{solver}:invalid_shape")
                continue
            if not np.all(np.isfinite(controls)) or not np.all(np.isfinite(states)):
                attempts.append(f"{solver}:non_finite")
                continue
            self._warm_sequence = np.concatenate(
                (controls[:, 1:], controls[:, -1:]), axis=1
            )
            stats = problem.solver_stats
            iterations = getattr(stats, "num_iters", None)
            return LinearMPCResult(
                status=str(problem.status),
                solver=solver,
                solve_time_s=perf_counter() - total_start,
                objective=float(problem.value),
                control_sequence=controls.copy(),
                state_sequence=states.copy(),
                max_power_slack_pu=(
                    float(np.max(np.asarray(transient_power_slack.value, dtype=float)))
                    if transient_power_slack is not None
                    and transient_power_slack.value is not None
                    else 0.0
                ),
                iterations=int(iterations) if iterations is not None else None,
            )
        return LinearMPCResult(
            status=final_status,
            solver=final_solver,
            solve_time_s=perf_counter() - total_start,
            objective=None,
            control_sequence=None,
            state_sequence=None,
            error=";".join(attempts) or "no_solver_attempted",
        )


__all__ = [
    "IBR_FILTER_INDEX",
    "IBR_POWER_INDEX",
    "INPUT_SIZE",
    "INTEGRAL_INDEX",
    "JOINT_STATE_SIZE",
    "LinearMPC",
    "LinearMPCResult",
    "LinearPredictionModel",
    "MPCBounds",
    "MPCWeights",
    "OMEGA_INDEX",
    "linearize_grid_ibr",
]
