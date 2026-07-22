"""Convex SD-BMPC problem construction for equations (52)--(66).

This module deliberately contains no solver policy and no simulator truth.  It
turns the frozen, label-free ARX component library into one convex QCQP with a
single SG/IBR command sequence shared by every candidate component.  Solver
selection, time limits, and fallback decisions belong to the controller layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from numbers import Integral, Real
from time import perf_counter
from types import MappingProxyType
from typing import Mapping, Sequence

import cvxpy as cp
import numpy as np
from numpy.typing import ArrayLike, NDArray

from d5freq.identification.model_library import ModeLibrary
from d5freq.models.grid_frequency import GridFrequencyModel
from d5freq.optimization.joint_prediction import (
    JOINT_ARX_STATE_SIZE,
    JOINT_INPUT_SIZE,
    JointARXPredictionModel,
    assemble_joint_arx_prediction,
)


FloatArray = NDArray[np.float64]
REQUIRED_NATIVE_COMPONENT_COUNT = 6
GRID_FREQUENCY_INDEX = 0
GRID_INTEGRAL_INDEX = 3
ARX_POWER_INDEX = 5
ARX_CONSTANT_INDEX = 9


def _finite_real(value: object, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


def _nonnegative_real(value: object, name: str) -> float:
    normalized = _finite_real(value, name)
    if normalized < 0.0:
        raise ValueError(f"{name} must be non-negative")
    return normalized


def _positive_real(value: object, name: str) -> float:
    normalized = _finite_real(value, name)
    if normalized <= 0.0:
        raise ValueError(f"{name} must be strictly positive")
    return normalized


def _positive_integer(value: object, name: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise TypeError(f"{name} must be an integer")
    normalized = int(value)
    if normalized < 1:
        raise ValueError(f"{name} must be positive")
    return normalized


def _finite_vector(value: ArrayLike, size: int, name: str) -> FloatArray:
    raw = np.asarray(value)
    if np.iscomplexobj(raw):
        raise TypeError(f"{name} must be real-valued")
    try:
        vector = np.asarray(raw, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be a real-valued vector") from exc
    if vector.shape != (size,):
        raise ValueError(f"{name} must have shape ({size},), got {vector.shape}")
    if not np.all(np.isfinite(vector)):
        raise ValueError(f"{name} must contain only finite values")
    return vector.copy()


def _quantiles(value: Mapping[int, float], name: str) -> Mapping[int, float]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a horizon-to-q95 mapping")
    normalized: dict[int, float] = {}
    for raw_horizon, raw_quantile in value.items():
        horizon = _positive_integer(raw_horizon, f"{name} horizon")
        if horizon in normalized:
            raise ValueError(f"{name} horizons must be unique")
        normalized[horizon] = _nonnegative_real(raw_quantile, name)
    return MappingProxyType(dict(sorted(normalized.items())))


@dataclass(frozen=True, slots=True)
class SDBMPCMode:
    """One native discovered component and its validation/calibration bounds."""

    component_id: int
    prediction_model: JointARXPredictionModel
    frequency_q95_hz: Mapping[int, float]
    rocof_q95_hz_per_s: Mapping[int, float]
    power_q95_pu: Mapping[int, float]
    p_output_min_pu: float
    p_output_max_pu: float
    ramp_down_pu_per_s: float
    ramp_up_pu_per_s: float

    def __post_init__(self) -> None:
        if (
            isinstance(self.component_id, (bool, np.bool_))
            or not isinstance(self.component_id, Integral)
        ):
            raise TypeError("component_id must be an integer")
        component_id = int(self.component_id)
        if component_id < 0:
            raise ValueError("component_id must be non-negative")
        if not isinstance(self.prediction_model, JointARXPredictionModel):
            raise TypeError("prediction_model must be a JointARXPredictionModel")

        frequency = _quantiles(self.frequency_q95_hz, "frequency_q95_hz")
        rocof = _quantiles(self.rocof_q95_hz_per_s, "rocof_q95_hz_per_s")
        power = _quantiles(self.power_q95_pu, "power_q95_pu")
        if not (tuple(frequency) == tuple(rocof) == tuple(power)):
            raise ValueError("all q95 mappings must contain identical lead horizons")

        lower = _finite_real(self.p_output_min_pu, "p_output_min_pu")
        upper = _finite_real(self.p_output_max_pu, "p_output_max_pu")
        if lower > upper:
            raise ValueError("p_output_min_pu must not exceed p_output_max_pu")
        ramp_down = _nonnegative_real(
            self.ramp_down_pu_per_s, "ramp_down_pu_per_s"
        )
        ramp_up = _nonnegative_real(self.ramp_up_pu_per_s, "ramp_up_pu_per_s")

        # Equation (21) contains a literal affine constant.  Reject a malformed
        # predictor here rather than silently allowing that state to drift.
        expected_constant_row = np.zeros(JOINT_ARX_STATE_SIZE, dtype=np.float64)
        expected_constant_row[ARX_CONSTANT_INDEX] = 1.0
        if not np.allclose(
            self.prediction_model.A[ARX_CONSTANT_INDEX],
            expected_constant_row,
            rtol=0.0,
            atol=1.0e-13,
        ):
            raise ValueError("prediction model must preserve the ARX constant state")
        if not np.allclose(
            self.prediction_model.B[ARX_CONSTANT_INDEX],
            0.0,
            rtol=0.0,
            atol=1.0e-13,
        ):
            raise ValueError("control inputs must not alter the ARX constant state")

        object.__setattr__(self, "component_id", component_id)
        object.__setattr__(self, "frequency_q95_hz", frequency)
        object.__setattr__(self, "rocof_q95_hz_per_s", rocof)
        object.__setattr__(self, "power_q95_pu", power)
        object.__setattr__(self, "p_output_min_pu", lower)
        object.__setattr__(self, "p_output_max_pu", upper)
        object.__setattr__(self, "ramp_down_pu_per_s", ramp_down)
        object.__setattr__(self, "ramp_up_pu_per_s", ramp_up)


@dataclass(frozen=True, slots=True)
class SDBMPCWeights:
    """Non-negative scalar weights in equations (57), (60), and (61)."""

    q_freq: float = 3000.0
    q_integral: float = 50.0
    q_rocof: float = 50.0
    r_sg: float = 1.0
    r_ibr: float = 0.5
    s_delta_sg: float = 20.0
    s_delta_ibr: float = 10.0
    q_terminal_freq: float = 6000.0
    q_terminal_integral: float = 100.0
    lambda_worst_base: float = 0.05
    lambda_worst_entropy: float = 0.50
    rho_freq_slack: float = 1.0e7
    rho_rocof_slack: float = 1.0e6
    rho_power_slack: float = 1.0e6

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            object.__setattr__(
                self, name, _nonnegative_real(getattr(self, name), name)
            )

    @property
    def input_weights(self) -> FloatArray:
        return np.array([self.r_sg, self.r_ibr], dtype=np.float64)

    @property
    def delta_weights(self) -> FloatArray:
        return np.array([self.s_delta_sg, self.s_delta_ibr], dtype=np.float64)


@dataclass(frozen=True, slots=True)
class SDBMPCBounds:
    """Physical command, command-rate, frequency, and RoCoF limits."""

    u_min_pu: tuple[float, float] = (-0.12, -0.08)
    u_max_pu: tuple[float, float] = (0.12, 0.08)
    ramp_pu_per_s: tuple[float, float] = (0.02, 0.04)
    freq_limit_hz: float = 0.5
    rocof_limit_hz_per_s: float = 0.5

    def __post_init__(self) -> None:
        if not (
            len(self.u_min_pu) == len(self.u_max_pu) == len(self.ramp_pu_per_s) == 2
        ):
            raise ValueError("command bounds and ramps must each contain SG and IBR values")
        lower = tuple(_finite_real(value, "u_min_pu") for value in self.u_min_pu)
        upper = tuple(_finite_real(value, "u_max_pu") for value in self.u_max_pu)
        ramp = tuple(
            _nonnegative_real(value, "ramp_pu_per_s")
            for value in self.ramp_pu_per_s
        )
        if any(lo >= hi for lo, hi in zip(lower, upper, strict=True)):
            raise ValueError("each command lower bound must be below its upper bound")
        object.__setattr__(self, "u_min_pu", lower)
        object.__setattr__(self, "u_max_pu", upper)
        object.__setattr__(self, "ramp_pu_per_s", ramp)
        object.__setattr__(
            self, "freq_limit_hz", _positive_real(self.freq_limit_hz, "freq_limit_hz")
        )
        object.__setattr__(
            self,
            "rocof_limit_hz_per_s",
            _positive_real(self.rocof_limit_hz_per_s, "rocof_limit_hz_per_s"),
        )

    @property
    def lower(self) -> FloatArray:
        return np.asarray(self.u_min_pu, dtype=np.float64)

    @property
    def upper(self) -> FloatArray:
        return np.asarray(self.u_max_pu, dtype=np.float64)

    @property
    def ramp(self) -> FloatArray:
        return np.asarray(self.ramp_pu_per_s, dtype=np.float64)


@dataclass(frozen=True, slots=True)
class SDBMPCConfig:
    """Fixed horizon and risk settings for one family of online QCQPs."""

    horizon_steps: int = 20
    sample_time_s: float = 0.5
    f0_hz: float = 50.0
    credible_mass: float = 0.99
    entropy_use_all_modes: float = 0.70
    use_constraint_tightening: bool = True
    weights: SDBMPCWeights = field(default_factory=SDBMPCWeights)
    bounds: SDBMPCBounds = field(default_factory=SDBMPCBounds)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "horizon_steps", _positive_integer(self.horizon_steps, "horizon_steps")
        )
        object.__setattr__(
            self, "sample_time_s", _positive_real(self.sample_time_s, "sample_time_s")
        )
        object.__setattr__(self, "f0_hz", _positive_real(self.f0_hz, "f0_hz"))
        credible = _finite_real(self.credible_mass, "credible_mass")
        if not 0.0 < credible <= 1.0:
            raise ValueError("credible_mass must lie in (0, 1]")
        entropy_threshold = _finite_real(
            self.entropy_use_all_modes, "entropy_use_all_modes"
        )
        if not 0.0 <= entropy_threshold <= 1.0:
            raise ValueError("entropy_use_all_modes must lie in [0, 1]")
        if not isinstance(self.use_constraint_tightening, (bool, np.bool_)):
            raise TypeError("use_constraint_tightening must be boolean")
        if not isinstance(self.weights, SDBMPCWeights):
            raise TypeError("weights must be SDBMPCWeights")
        if not isinstance(self.bounds, SDBMPCBounds):
            raise TypeError("bounds must be SDBMPCBounds")
        object.__setattr__(self, "credible_mass", credible)
        object.__setattr__(self, "entropy_use_all_modes", entropy_threshold)
        object.__setattr__(
            self, "use_constraint_tightening", bool(self.use_constraint_tightening)
        )


@dataclass(frozen=True, slots=True)
class SDBMPCProblem:
    """Auditable CVXPY representation of one SD-BMPC control instant."""

    problem: cp.Problem
    shared_input: cp.Variable
    mode_states: tuple[cp.Variable, ...]
    freq_slack_hz: cp.Variable
    rocof_slack_hz_per_s: cp.Variable
    power_slack_pu: cp.Variable
    worst_case_epigraph: cp.Variable
    initial_state_parameter: cp.Parameter
    previous_input_parameter: cp.Parameter
    belief_parameter: cp.Parameter
    lambda_worst_parameter: cp.Parameter
    risk_mask_parameter: cp.Parameter
    mode_costs: tuple[cp.Expression, ...]
    component_ids: tuple[int, ...]
    config: SDBMPCConfig
    frequency_tightening_hz: tuple[FloatArray, ...]
    rocof_tightening_hz_per_s: tuple[FloatArray, ...]

    @property
    def horizon_steps(self) -> int:
        return int(self.shared_input.shape[1])

    @property
    def belief(self) -> FloatArray:
        """Owned snapshot of the currently bound label-free belief."""

        values = np.asarray(self.belief_parameter.value, dtype=np.float64).copy()
        values.setflags(write=False)
        return values

    @property
    def lambda_worst(self) -> float:
        """Current entropy-adaptive worst-mode multiplier (equation 60)."""

        return float(np.asarray(self.lambda_worst_parameter.value).item())

    @property
    def risk_mask(self) -> FloatArray:
        """Owned 0/1 snapshot of modes carrying robust constraints."""

        values = np.asarray(self.risk_mask_parameter.value, dtype=np.float64).copy()
        if values.shape != (len(self.component_ids),):
            raise RuntimeError("risk mask parameter has an invalid shape")
        if not np.all((values == 0.0) | (values == 1.0)):
            raise RuntimeError("risk mask parameter must contain exact binary values")
        if not np.any(values == 1.0):
            raise RuntimeError("risk mask parameter must activate at least one mode")
        values.setflags(write=False)
        return values

    @property
    def risk_mode_indices(self) -> tuple[int, ...]:
        return tuple(int(index) for index in np.flatnonzero(self.risk_mask == 1.0))

    @property
    def risk_component_ids(self) -> tuple[int, ...]:
        return tuple(self.component_ids[index] for index in self.risk_mode_indices)

    def solution_variables(self) -> dict[str, cp.Expression]:
        """Return finite-valued expressions expected by the solver adapter."""

        variables: dict[str, cp.Expression] = {
            "shared_input": self.shared_input,
            "freq_slack_hz": self.freq_slack_hz,
            "rocof_slack_hz_per_s": self.rocof_slack_hz_per_s,
            "power_slack_pu": self.power_slack_pu,
            "worst_case_epigraph": self.worst_case_epigraph,
        }
        variables.update(
            {
                f"mode_state_{mode_index}": state
                for mode_index, state in enumerate(self.mode_states)
            }
        )
        return variables

    def precompile(self, solver: str) -> float:
        """Canonicalize this DPP template before the timed control loop.

        ``prepare`` constructs a CVXPY graph but does not canonicalize it for a
        particular solver.  The controller should call this method during
        ``reset`` once for the single masked template, then call the strict
        solver adapter during control steps.  The returned wall
        time in seconds is audit metadata; no optimization is performed and no
        executable action is created.
        """

        solver_name = str(solver).strip().upper()
        if not solver_name:
            raise ValueError("solver must not be empty")
        start = perf_counter()
        self.problem.get_problem_data(solver=solver_name)
        return perf_counter() - start

    def set_warm_start(self, shared_input_pu: ArrayLike | None) -> None:
        """Set or clear only the executable shared sequence's warm start."""

        if shared_input_pu is None:
            self.shared_input.value = None
            return
        values = np.asarray(shared_input_pu, dtype=np.float64)
        expected = (JOINT_INPUT_SIZE, self.horizon_steps)
        if values.shape != expected:
            raise ValueError(f"shared_input_pu must have shape {expected}")
        if not np.all(np.isfinite(values)):
            raise ValueError("shared_input_pu must contain only finite values")
        self.shared_input.value = values.copy()

    def update_parameters(
        self,
        initial_state: ArrayLike,
        belief: ArrayLike,
        previous_input: ArrayLike,
        *,
        entropy_normalized: float,
        ood_suspect: bool,
        diagnostic_numerical_issue: bool = False,
    ) -> None:
        """Atomically rebind runtime data and the exact 0/1 risk mask."""

        state0, probabilities, previous, entropy = _validate_runtime_data(
            initial_state,
            belief,
            previous_input,
            entropy_normalized=entropy_normalized,
            ood_suspect=ood_suspect,
            diagnostic_numerical_issue=diagnostic_numerical_issue,
            mode_count=len(self.component_ids),
        )
        risk_indices = _select_risk_mode_indices(
            probabilities,
            self.component_ids,
            entropy,
            bool(ood_suspect),
            bool(diagnostic_numerical_issue),
            self.config,
        )
        if not risk_indices:
            raise RuntimeError("SD-BMPC risk set must never be empty")
        risk_mask = np.zeros(len(self.component_ids), dtype=np.float64)
        risk_mask[list(risk_indices)] = 1.0
        lambda_worst = (
            self.config.weights.lambda_worst_base
            + self.config.weights.lambda_worst_entropy * entropy
        )
        # All validation and structural checks precede mutation, so an invalid
        # update cannot partially mix samples from two control instants.
        self.initial_state_parameter.value = state0
        self.previous_input_parameter.value = previous
        self.belief_parameter.value = probabilities
        self.lambda_worst_parameter.value = lambda_worst
        self.risk_mask_parameter.value = risk_mask


def modes_from_library(
    grid_model: GridFrequencyModel,
    mode_library: ModeLibrary,
    *,
    expected_component_count: int | None = REQUIRED_NATIVE_COMPONENT_COUNT,
) -> tuple[SDBMPCMode, ...]:
    """Create native joint predictors without relabeling discovered components.

    The canonical controller leaves ``expected_component_count`` at six.  A
    caller may pass ``None`` only for compact mathematical unit tests.
    """

    if not isinstance(grid_model, GridFrequencyModel):
        raise TypeError("grid_model must be a GridFrequencyModel")
    if not isinstance(mode_library, ModeLibrary):
        raise TypeError("mode_library must be a ModeLibrary")
    if expected_component_count is not None:
        expected = _positive_integer(
            expected_component_count, "expected_component_count"
        )
        if len(mode_library.models) != expected:
            raise ValueError(
                "canonical SD-BMPC requires the frozen native "
                f"K={expected} library, got K={len(mode_library.models)}"
            )

    modes = tuple(
        SDBMPCMode(
            component_id=model.component_id,
            prediction_model=assemble_joint_arx_prediction(
                grid_model, model.A_b, model.B_b, model.F_b
            ),
            frequency_q95_hz=model.multi_step_frequency_error_quantiles_hz,
            rocof_q95_hz_per_s=(
                model.multi_step_rocof_error_quantiles_hz_per_s
            ),
            power_q95_pu=model.multi_step_power_error_quantiles_pu,
            p_output_min_pu=model.p_output_min_pu,
            p_output_max_pu=model.p_output_max_pu,
            ramp_down_pu_per_s=model.ramp_down_pu_per_s,
            ramp_up_pu_per_s=model.ramp_up_pu_per_s,
        )
        for model in mode_library.models
    )
    component_ids = tuple(mode.component_id for mode in modes)
    if component_ids != tuple(range(len(modes))):
        raise ValueError("native component IDs must remain contiguous and ordered")
    return modes


def credible_mode_indices(
    belief: ArrayLike,
    credible_mass: float = 0.99,
    *,
    component_ids: Sequence[int] | None = None,
) -> tuple[int, ...]:
    """Return the minimal cumulative-belief set with stable component-ID ties."""

    raw = np.asarray(belief)
    if raw.ndim != 1 or raw.size == 0:
        raise ValueError("belief must be a non-empty one-dimensional vector")
    probabilities = _finite_vector(raw, raw.size, "belief")
    if np.any(probabilities < 0.0):
        raise ValueError("belief entries must be non-negative")
    total = float(np.sum(probabilities))
    if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1.0e-10):
        raise ValueError("belief entries must sum to one")
    probabilities /= total
    mass = _finite_real(credible_mass, "credible_mass")
    if not 0.0 < mass <= 1.0:
        raise ValueError("credible_mass must lie in (0, 1]")

    if component_ids is None:
        ids = np.arange(probabilities.size, dtype=np.int64)
    else:
        if len(component_ids) != probabilities.size:
            raise ValueError("component_ids must have one entry per belief component")
        if any(
            isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral)
            for value in component_ids
        ):
            raise TypeError("component_ids must contain integers")
        ids = np.asarray(component_ids, dtype=np.int64)
        if np.unique(ids).size != ids.size:
            raise ValueError("component_ids must be unique")

    order = np.lexsort((ids, -probabilities))
    cumulative = np.cumsum(probabilities[order])
    count = int(np.searchsorted(cumulative, mass, side="left")) + 1
    return tuple(int(index) for index in order[:count])


def _validate_runtime_data(
    initial_state: ArrayLike,
    belief: ArrayLike,
    previous_input: ArrayLike,
    *,
    entropy_normalized: float,
    ood_suspect: bool,
    diagnostic_numerical_issue: bool,
    mode_count: int,
) -> tuple[FloatArray, FloatArray, FloatArray, float]:
    state0 = _finite_vector(initial_state, JOINT_ARX_STATE_SIZE, "initial_state")
    if not math.isclose(
        float(state0[ARX_CONSTANT_INDEX]), 1.0, rel_tol=0.0, abs_tol=1.0e-12
    ):
        raise ValueError("initial_state[9] must equal the ARX affine constant 1")
    previous = _finite_vector(previous_input, JOINT_INPUT_SIZE, "previous_input")
    probabilities = _finite_vector(belief, mode_count, "belief")
    if np.any(probabilities < 0.0):
        raise ValueError("belief entries must be non-negative")
    total_probability = float(np.sum(probabilities))
    if not math.isclose(
        total_probability, 1.0, rel_tol=0.0, abs_tol=1.0e-10
    ):
        raise ValueError("belief entries must sum to one")
    probabilities /= total_probability
    entropy = _finite_real(entropy_normalized, "entropy_normalized")
    if not 0.0 <= entropy <= 1.0:
        raise ValueError("entropy_normalized must lie in [0, 1]")
    if not isinstance(ood_suspect, (bool, np.bool_)):
        raise TypeError("ood_suspect must be boolean")
    if not isinstance(diagnostic_numerical_issue, (bool, np.bool_)):
        raise TypeError("diagnostic_numerical_issue must be boolean")
    return state0, probabilities, previous, entropy


def _select_risk_mode_indices(
    probabilities: FloatArray,
    component_ids: Sequence[int],
    entropy_normalized: float,
    ood_suspect: bool,
    diagnostic_numerical_issue: bool,
    config: SDBMPCConfig,
) -> tuple[int, ...]:
    use_all_modes = bool(
        entropy_normalized >= config.entropy_use_all_modes
        or ood_suspect
        or diagnostic_numerical_issue
    )
    if use_all_modes:
        return tuple(range(probabilities.size))
    return credible_mode_indices(
        probabilities,
        config.credible_mass,
        component_ids=component_ids,
    )


def _lead_q95(
    mapping: Mapping[int, float],
    horizon_steps: int,
    name: str,
    *,
    enabled: bool,
) -> FloatArray:
    if not enabled:
        return np.zeros(horizon_steps, dtype=np.float64)
    expected = tuple(range(1, horizon_steps + 1))
    missing = tuple(lead for lead in expected if lead not in mapping)
    if missing:
        raise ValueError(
            f"{name} must explicitly contain future leads 1..{horizon_steps}; "
            f"missing={missing}"
        )
    return np.asarray([mapping[lead] for lead in expected], dtype=np.float64)


def build_sd_bmpc_problem(
    modes: Sequence[SDBMPCMode],
    initial_state: ArrayLike,
    belief: ArrayLike,
    previous_input: ArrayLike,
    *,
    entropy_normalized: float,
    ood_suspect: bool,
    diagnostic_numerical_issue: bool = False,
    config: SDBMPCConfig | None = None,
) -> SDBMPCProblem:
    """Build equations (52)--(66) as a convex, shared-input QCQP.

    Frequency q95 values are consumed directly in hertz and RoCoF q95 values
    directly in hertz/second.  Neither table is multiplied by ``f0_hz``: that
    conversion is applied only to predicted per-unit frequency states.
    """

    mode_tuple = tuple(modes)
    if not mode_tuple or not all(isinstance(mode, SDBMPCMode) for mode in mode_tuple):
        raise TypeError("modes must be a non-empty sequence of SDBMPCMode")
    component_ids = tuple(mode.component_id for mode in mode_tuple)
    if len(set(component_ids)) != len(component_ids):
        raise ValueError("mode component IDs must be unique")
    settings = SDBMPCConfig() if config is None else config
    if not isinstance(settings, SDBMPCConfig):
        raise TypeError("config must be an SDBMPCConfig")

    state0, probabilities, previous, entropy = _validate_runtime_data(
        initial_state,
        belief,
        previous_input,
        entropy_normalized=entropy_normalized,
        ood_suspect=ood_suspect,
        diagnostic_numerical_issue=diagnostic_numerical_issue,
        mode_count=len(mode_tuple),
    )
    risk_indices = _select_risk_mode_indices(
        probabilities,
        component_ids,
        entropy,
        bool(ood_suspect),
        bool(diagnostic_numerical_issue),
        settings,
    )

    horizon = settings.horizon_steps
    frequency_tightening = tuple(
        _lead_q95(
            mode.frequency_q95_hz,
            horizon,
            f"component {mode.component_id} frequency_q95_hz",
            enabled=settings.use_constraint_tightening,
        )
        for mode in mode_tuple
    )
    rocof_tightening = tuple(
        _lead_q95(
            mode.rocof_q95_hz_per_s,
            horizon,
            f"component {mode.component_id} rocof_q95_hz_per_s",
            enabled=settings.use_constraint_tightening,
        )
        for mode in mode_tuple
    )

    initial_state_parameter = cp.Parameter(
        JOINT_ARX_STATE_SIZE, name="initial_state_parameter"
    )
    previous_input_parameter = cp.Parameter(
        JOINT_INPUT_SIZE, name="previous_input_parameter"
    )
    belief_parameter = cp.Parameter(
        len(mode_tuple), nonneg=True, name="belief_parameter"
    )
    lambda_worst_parameter = cp.Parameter(
        nonneg=True, name="lambda_worst_parameter"
    )
    risk_mask_parameter = cp.Parameter(
        len(mode_tuple), nonneg=True, name="risk_mask_parameter"
    )
    initial_state_parameter.value = state0
    previous_input_parameter.value = previous
    belief_parameter.value = probabilities
    lambda_worst_parameter.value = (
        settings.weights.lambda_worst_base
        + settings.weights.lambda_worst_entropy * entropy
    )
    risk_mask = np.zeros(len(mode_tuple), dtype=np.float64)
    risk_mask[list(risk_indices)] = 1.0
    risk_mask_parameter.value = risk_mask

    shared_input = cp.Variable((JOINT_INPUT_SIZE, horizon), name="shared_input")
    mode_states = tuple(
        cp.Variable(
            (JOINT_ARX_STATE_SIZE, horizon + 1),
            name=f"mode_state_component_{mode.component_id}",
        )
        for mode in mode_tuple
    )
    freq_slack_hz = cp.Variable(horizon, nonneg=True, name="freq_slack_hz")
    rocof_slack_hz_per_s = cp.Variable(
        horizon, nonneg=True, name="rocof_slack_hz_per_s"
    )
    power_slack_pu = cp.Variable(horizon, nonneg=True, name="power_slack_pu")
    worst_case_epigraph = cp.Variable(nonneg=True, name="worst_case_epigraph")
    constraints: list[cp.Constraint] = [
        shared_input >= settings.bounds.lower[:, None],
        shared_input <= settings.bounds.upper[:, None],
    ]
    deltas: list[cp.Expression] = []
    for lead_index in range(horizon):
        prior = (
            previous_input_parameter
            if lead_index == 0
            else shared_input[:, lead_index - 1]
        )
        delta = shared_input[:, lead_index] - prior
        deltas.append(delta)
        constraints.extend(
            [
                delta <= settings.bounds.ramp * settings.sample_time_s,
                delta >= -settings.bounds.ramp * settings.sample_time_s,
            ]
        )

    # The input and input-increment terms in equation (57) are common to every
    # mode because all modes share one executable sequence.  Factoring that
    # common term is algebraically exact (belief sums to one, and max_m(C+J_m)
    # = C+max_m J_m) and keeps the previous-input parameter out of products
    # with online belief/risk parameters, which is required for DPP.
    common_control_cost: cp.Expression = cp.Constant(0.0)
    for lead_index, delta in enumerate(deltas):
        common_control_cost += cp.sum(
            cp.multiply(
                settings.weights.input_weights,
                cp.square(shared_input[:, lead_index]),
            )
        ) + cp.sum(
            cp.multiply(settings.weights.delta_weights, cp.square(delta))
        )

    mode_costs: list[cp.Expression] = []
    mode_state_residuals: list[cp.Expression] = []
    for mode_index, (mode, state) in enumerate(zip(mode_tuple, mode_states, strict=True)):
        constraints.extend(
            [
                state[:, 0] == initial_state_parameter,
                state[ARX_CONSTANT_INDEX, :] == 1.0,
            ]
        )
        state_residuals: list[cp.Expression] = []
        for lead_index in range(horizon):
            current_state = state[:, lead_index]
            future_state = state[:, lead_index + 1]
            constraints.append(
                future_state
                == mode.prediction_model.A @ current_state
                + mode.prediction_model.B @ shared_input[:, lead_index]
            )

            current_frequency_hz = settings.f0_hz * current_state[GRID_FREQUENCY_INDEX]
            future_frequency_hz = settings.f0_hz * future_state[GRID_FREQUENCY_INDEX]
            rocof_hz_per_s = (
                future_frequency_hz - current_frequency_hz
            ) / settings.sample_time_s
            state_residuals.extend(
                [
                    math.sqrt(settings.weights.q_freq) * current_frequency_hz,
                    math.sqrt(settings.weights.q_integral)
                    * current_state[GRID_INTEGRAL_INDEX],
                    math.sqrt(settings.weights.q_rocof) * rocof_hz_per_s,
                ]
            )

            # lead_index + 1 is the validation-table prediction lead.  The
            # q95 tables already have Hz and Hz/s units.  A binary nonnegative
            # DPP parameter activates each complete robust-constraint family;
            # at zero every expression reduces exactly to 0 <= 0.
            risk_mask_entry = risk_mask_parameter[mode_index]
            future_power_pu = future_state[ARX_POWER_INDEX]
            current_power_pu = current_state[ARX_POWER_INDEX]
            power_change_pu = future_power_pu - current_power_pu
            constraints.extend(
                [
                    risk_mask_entry * cp.abs(future_frequency_hz)
                    <= risk_mask_entry
                    * (
                        settings.bounds.freq_limit_hz
                        - frequency_tightening[mode_index][lead_index]
                        + freq_slack_hz[lead_index]
                    ),
                    risk_mask_entry * cp.abs(rocof_hz_per_s)
                    <= risk_mask_entry
                    * (
                        settings.bounds.rocof_limit_hz_per_s
                        - rocof_tightening[mode_index][lead_index]
                        + rocof_slack_hz_per_s[lead_index]
                    ),
                    risk_mask_entry
                    * (
                        mode.p_output_min_pu - power_slack_pu[lead_index]
                    )
                    <= risk_mask_entry * future_power_pu,
                    risk_mask_entry * future_power_pu
                    <= risk_mask_entry
                    * (
                        mode.p_output_max_pu + power_slack_pu[lead_index]
                    ),
                    risk_mask_entry * power_change_pu
                    <= risk_mask_entry
                    * (
                        mode.ramp_up_pu_per_s * settings.sample_time_s
                        + power_slack_pu[lead_index]
                    ),
                    risk_mask_entry
                    * (
                        -mode.ramp_down_pu_per_s * settings.sample_time_s
                        - power_slack_pu[lead_index]
                    )
                    <= risk_mask_entry * power_change_pu,
                ]
            )

        terminal_state = state[:, horizon]
        state_residuals.extend(
            [
                math.sqrt(settings.weights.q_terminal_freq)
                * settings.f0_hz
                * terminal_state[GRID_FREQUENCY_INDEX],
                math.sqrt(settings.weights.q_terminal_integral)
                * terminal_state[GRID_INTEGRAL_INDEX],
            ]
        )
        residual_vector = cp.hstack(state_residuals)
        mode_state_residuals.append(residual_vector)
        mode_costs.append(common_control_cost + cp.sum_squares(residual_vector))

    # The online coefficients multiply parameter-free state residual costs,
    # rather than auxiliary expected-cost epigraphs.  CVXPY therefore accepts
    # the graph as DPP while exact-zero beliefs create no weakly anchored/free
    # variables.  The exact binary risk mask similarly selects a whole mode
    # state cost.  Inactive worst-mode constraints reduce to the redundant
    # common_control_cost <= t; the non-empty active set yields
    # t = common_control_cost + max_{m in M} ||v_m||^2 when weighted.
    expected_cost: cp.Expression = common_control_cost + cp.sum(
        cp.hstack(
            [
                belief_parameter[index]
                * cp.sum_squares(mode_state_residuals[index])
                for index in range(len(mode_tuple))
            ]
        )
    )
    constraints.extend(
        common_control_cost
        + risk_mask_parameter[index]
        * cp.sum_squares(mode_state_residuals[index])
        <= worst_case_epigraph
        for index in range(len(mode_tuple))
    )
    objective = (
        expected_cost
        + lambda_worst_parameter * worst_case_epigraph
        + settings.weights.rho_freq_slack * cp.sum_squares(freq_slack_hz)
        + settings.weights.rho_rocof_slack
        * cp.sum_squares(rocof_slack_hz_per_s)
        + settings.weights.rho_power_slack * cp.sum_squares(power_slack_pu)
    )
    problem = cp.Problem(cp.Minimize(objective), constraints)
    if not problem.is_dcp():
        raise RuntimeError("SD-BMPC equations unexpectedly produced a non-DCP problem")
    if not problem.is_dcp(dpp=True):
        raise RuntimeError("SD-BMPC parameterization unexpectedly violates DPP")

    for values in (*frequency_tightening, *rocof_tightening):
        values.setflags(write=False)
    return SDBMPCProblem(
        problem=problem,
        shared_input=shared_input,
        mode_states=mode_states,
        freq_slack_hz=freq_slack_hz,
        rocof_slack_hz_per_s=rocof_slack_hz_per_s,
        power_slack_pu=power_slack_pu,
        worst_case_epigraph=worst_case_epigraph,
        initial_state_parameter=initial_state_parameter,
        previous_input_parameter=previous_input_parameter,
        belief_parameter=belief_parameter,
        lambda_worst_parameter=lambda_worst_parameter,
        risk_mask_parameter=risk_mask_parameter,
        mode_costs=tuple(mode_costs),
        component_ids=component_ids,
        config=settings,
        frequency_tightening_hz=frequency_tightening,
        rocof_tightening_hz_per_s=rocof_tightening,
    )


class SDBMPCProblemCache:
    """One reusable DPP template with a parameterized robust risk mask.

    CVXPY canonicalization dominates the first solve of the native K6,
    20-step QCQP.  This holder retains one parameterized problem across every
    credible/all-mode set: subsequent calls update only ``x0``, previous
    input, belief, the entropy-adaptive worst-mode weight, and an exact 0/1
    risk mask while preserving the compiled solver map.  ``prepare`` itself
    does not compile: call the
    returned problem's :meth:`SDBMPCProblem.precompile` during controller
    reset, outside the timed control loop.

    Phase-5 acceptance evidence on the native K6/Np=20 problem with MOSEK was
    1.30 s for reset-time precompilation, then 0.087 s for an all-mode solve
    and 0.062 s after changing the same template to a singleton mask.  These
    are diagnostic measurements, not portable timing guarantees; unit tests
    assert DPP/template identity rather than a hardware-fragile deadline.
    """

    def __init__(
        self,
        modes: Sequence[SDBMPCMode],
        *,
        config: SDBMPCConfig | None = None,
    ) -> None:
        mode_tuple = tuple(modes)
        if not mode_tuple or not all(
            isinstance(mode, SDBMPCMode) for mode in mode_tuple
        ):
            raise TypeError("modes must be a non-empty sequence of SDBMPCMode")
        component_ids = tuple(mode.component_id for mode in mode_tuple)
        if len(set(component_ids)) != len(component_ids):
            raise ValueError("mode component IDs must be unique")
        settings = SDBMPCConfig() if config is None else config
        if not isinstance(settings, SDBMPCConfig):
            raise TypeError("config must be an SDBMPCConfig")
        self._modes = mode_tuple
        self._config = settings
        self._problem: SDBMPCProblem | None = None

    @property
    def modes(self) -> tuple[SDBMPCMode, ...]:
        return self._modes

    @property
    def config(self) -> SDBMPCConfig:
        return self._config

    @property
    def cached_risk_sets(self) -> tuple[tuple[int, ...], ...]:
        if self._problem is None:
            return ()
        return (self._problem.risk_mode_indices,)

    def prepare(
        self,
        initial_state: ArrayLike,
        belief: ArrayLike,
        previous_input: ArrayLike,
        *,
        entropy_normalized: float,
        ood_suspect: bool,
        diagnostic_numerical_issue: bool = False,
    ) -> SDBMPCProblem:
        """Return the matching template after atomically rebinding parameters."""

        state0, probabilities, previous, entropy = _validate_runtime_data(
            initial_state,
            belief,
            previous_input,
            entropy_normalized=entropy_normalized,
            ood_suspect=ood_suspect,
            diagnostic_numerical_issue=diagnostic_numerical_issue,
            mode_count=len(self._modes),
        )
        if self._problem is None:
            self._problem = build_sd_bmpc_problem(
                self._modes,
                state0,
                probabilities,
                previous,
                entropy_normalized=entropy,
                ood_suspect=bool(ood_suspect),
                diagnostic_numerical_issue=bool(diagnostic_numerical_issue),
                config=self._config,
            )
        else:
            self._problem.update_parameters(
                state0,
                probabilities,
                previous,
                entropy_normalized=entropy,
                ood_suspect=bool(ood_suspect),
                diagnostic_numerical_issue=bool(diagnostic_numerical_issue),
            )
        return self._problem

    def clear(self) -> None:
        """Drop compiled templates and all associated warm-start values."""

        self._problem = None


__all__ = [
    "ARX_CONSTANT_INDEX",
    "ARX_POWER_INDEX",
    "GRID_FREQUENCY_INDEX",
    "GRID_INTEGRAL_INDEX",
    "REQUIRED_NATIVE_COMPONENT_COUNT",
    "SDBMPCBounds",
    "SDBMPCConfig",
    "SDBMPCMode",
    "SDBMPCProblem",
    "SDBMPCProblemCache",
    "SDBMPCWeights",
    "build_sd_bmpc_problem",
    "credible_mode_indices",
    "modes_from_library",
]
