"""Final-study single-ARX MPC baseline built on the Phase-5 QCQP.

This module is deliberately controller-side and truth-free.  A fixed ARX
component is selected by a separately frozen validation artifact; the runtime
controller then sees only that component, ordinary measurements, and the
shared grid-state estimator.  Solver rejection, timeout handling, command
withdrawal, and LQI recovery are inherited from :mod:`d5freq.controllers.sd_bmpc`
instead of being reimplemented with a weaker baseline-specific policy.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import json
import math
from numbers import Integral, Real
from pathlib import Path
from time import perf_counter
from types import MappingProxyType
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray
import cvxpy as cp

from d5freq.controllers.base import GridStateEstimator
from d5freq.controllers.lqi_fallback import LQIFallbackConfig
from d5freq.controllers.sd_bmpc import (
    FallbackEvent,
    OnlineDiagnosticRuntime,
    SDBMPCController,
    SDBMPCControllerConfig,
    SDBMPCStepRecord,
)
from d5freq.estimation.online_diagnostic import DiagnosticOutput
from d5freq.identification.arx import arx_to_state_space
from d5freq.identification.model_library import ARXModeModel, ModeLibrary
from d5freq.interfaces import ControlAction, Measurement
from d5freq.models.grid_frequency import GridFrequencyModel
from d5freq.optimization.joint_prediction import assemble_joint_arx_prediction
from d5freq.optimization.mpc_problem import (
    ARX_CONSTANT_INDEX,
    ARX_POWER_INDEX,
    GRID_FREQUENCY_INDEX,
    GRID_INTEGRAL_INDEX,
    SDBMPCConfig,
    SDBMPCMode,
)
from d5freq.optimization.solver_utils import SolverResult
from d5freq.utils.hashing import sha256_file, sha256_json


FloatArray = NDArray[np.float64]
REFERENCE_SELECTION_SCHEMA_VERSION = "d5freq.fixed_reference_selection.v1"
_SELECTION_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "mode_library_file_sha256",
        "mode_library_logical_sha256",
        "component_count",
        "selected_component_id",
        "selection_split",
        "criterion",
        "direction",
        "selection_dataset_sha256",
        "protocol_sha256",
        "label_access",
        "candidate_scores",
    }
)
_SELECTION_SCORE_KEYS = frozenset(
    {
        "component_id",
        "score",
        "registered_episode_count",
        "retained_episode_count",
        "failed_episode_count",
    }
)


def _finite_real(value: object, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real scalar")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


def _nonnegative_integer(value: object, name: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise TypeError(f"{name} must be an integer")
    normalized = int(value)
    if normalized < 0:
        raise ValueError(f"{name} must be non-negative")
    return normalized


def _sha256(value: object, name: str) -> str:
    normalized = str(value).strip().lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return normalized


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise TypeError(f"{name} must be a string-keyed mapping")
    return value


def _exact_keys(value: Mapping[str, Any], expected: frozenset[str], name: str) -> None:
    actual = frozenset(value)
    if actual != expected:
        raise ValueError(
            f"{name} keys mismatch; missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


@dataclass(frozen=True, slots=True)
class ReferenceCandidateScore:
    """One pre-registered validation score with all episodes retained."""

    component_id: int
    score: float
    registered_episode_count: int
    retained_episode_count: int
    failed_episode_count: int

    def __post_init__(self) -> None:
        component = _nonnegative_integer(self.component_id, "component_id")
        registered = _nonnegative_integer(
            self.registered_episode_count, "registered_episode_count"
        )
        retained = _nonnegative_integer(
            self.retained_episode_count, "retained_episode_count"
        )
        failed = _nonnegative_integer(self.failed_episode_count, "failed_episode_count")
        if registered == 0:
            raise ValueError("registered_episode_count must be positive")
        if retained != registered:
            raise ValueError("reference selection must retain every registered episode")
        if failed > retained:
            raise ValueError("failed_episode_count cannot exceed retained_episode_count")
        object.__setattr__(self, "component_id", component)
        object.__setattr__(self, "score", _finite_real(self.score, "score"))
        object.__setattr__(self, "registered_episode_count", registered)
        object.__setattr__(self, "retained_episode_count", retained)
        object.__setattr__(self, "failed_episode_count", failed)

    def to_dict(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value: object) -> "ReferenceCandidateScore":
        mapping = _mapping(value, "candidate score")
        _exact_keys(mapping, _SELECTION_SCORE_KEYS, "candidate score")
        return cls(**mapping)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class FixedReferenceSelectionArtifact:
    """Strict B1 component choice frozen before closed-loop test.

    The selected component is the deterministic optimum of a criterion on the
    declared validation split.  ``label_access`` must be ``"none"`` and the
    artifact contains no semantic mode name, test result, or simulator field.
    """

    mode_library_file_sha256: str
    mode_library_logical_sha256: str
    component_count: int
    selected_component_id: int
    selection_split: str
    criterion: str
    direction: str
    selection_dataset_sha256: str
    protocol_sha256: str
    label_access: str
    candidate_scores: tuple[ReferenceCandidateScore, ...]
    schema_version: str = REFERENCE_SELECTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != REFERENCE_SELECTION_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must equal {REFERENCE_SELECTION_SCHEMA_VERSION!r}"
            )
        count = _nonnegative_integer(self.component_count, "component_count")
        selected = _nonnegative_integer(
            self.selected_component_id, "selected_component_id"
        )
        if count < 1 or selected >= count:
            raise ValueError("component_count/selected_component_id are inconsistent")
        split = str(self.selection_split).strip()
        if split not in {"identification_validation", "closed_loop_validation"}:
            raise ValueError("B1 selection must use a registered validation split")
        criterion = str(self.criterion).strip()
        if not criterion:
            raise ValueError("criterion must not be empty")
        direction = str(self.direction).strip().lower()
        if direction not in {"minimize", "maximize"}:
            raise ValueError("direction must be 'minimize' or 'maximize'")
        if str(self.label_access).strip().lower() != "none":
            raise ValueError("B1 reference selection cannot access labels")
        scores = tuple(self.candidate_scores)
        if not all(isinstance(item, ReferenceCandidateScore) for item in scores):
            raise TypeError("candidate_scores must contain ReferenceCandidateScore values")
        if tuple(item.component_id for item in scores) != tuple(range(count)):
            raise ValueError("candidate scores must cover ordered native component IDs")
        key = (
            (lambda item: (item.score, item.component_id))
            if direction == "minimize"
            else (lambda item: (-item.score, item.component_id))
        )
        if min(scores, key=key).component_id != selected:
            raise ValueError("selected_component_id is not the deterministic score optimum")
        object.__setattr__(
            self,
            "mode_library_file_sha256",
            _sha256(self.mode_library_file_sha256, "mode_library_file_sha256"),
        )
        object.__setattr__(
            self,
            "mode_library_logical_sha256",
            _sha256(self.mode_library_logical_sha256, "mode_library_logical_sha256"),
        )
        object.__setattr__(
            self,
            "selection_dataset_sha256",
            _sha256(self.selection_dataset_sha256, "selection_dataset_sha256"),
        )
        object.__setattr__(
            self, "protocol_sha256", _sha256(self.protocol_sha256, "protocol_sha256")
        )
        object.__setattr__(self, "component_count", count)
        object.__setattr__(self, "selected_component_id", selected)
        object.__setattr__(self, "selection_split", split)
        object.__setattr__(self, "criterion", criterion)
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "label_access", "none")
        object.__setattr__(self, "candidate_scores", scores)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "mode_library_file_sha256": self.mode_library_file_sha256,
            "mode_library_logical_sha256": self.mode_library_logical_sha256,
            "component_count": self.component_count,
            "selected_component_id": self.selected_component_id,
            "selection_split": self.selection_split,
            "criterion": self.criterion,
            "direction": self.direction,
            "selection_dataset_sha256": self.selection_dataset_sha256,
            "protocol_sha256": self.protocol_sha256,
            "label_access": self.label_access,
            "candidate_scores": [item.to_dict() for item in self.candidate_scores],
        }

    @classmethod
    def from_dict(cls, value: object) -> "FixedReferenceSelectionArtifact":
        mapping = _mapping(value, "fixed-reference selection artifact")
        _exact_keys(mapping, _SELECTION_TOP_LEVEL_KEYS, "fixed-reference selection artifact")
        raw_scores = mapping["candidate_scores"]
        if not isinstance(raw_scores, list):
            raise TypeError("candidate_scores must be a JSON array")
        return cls(
            schema_version=mapping["schema_version"],
            mode_library_file_sha256=mapping["mode_library_file_sha256"],
            mode_library_logical_sha256=mapping["mode_library_logical_sha256"],
            component_count=mapping["component_count"],
            selected_component_id=mapping["selected_component_id"],
            selection_split=mapping["selection_split"],
            criterion=mapping["criterion"],
            direction=mapping["direction"],
            selection_dataset_sha256=mapping["selection_dataset_sha256"],
            protocol_sha256=mapping["protocol_sha256"],
            label_access=mapping["label_access"],
            candidate_scores=tuple(
                ReferenceCandidateScore.from_dict(item) for item in raw_scores
            ),
        )

    @classmethod
    def load_json(cls, path: str | Path) -> "FixedReferenceSelectionArtifact":
        def reject_nonfinite(token: str) -> None:
            raise ValueError(f"non-standard JSON number {token!r} is forbidden")

        payload = json.loads(
            Path(path).read_text(encoding="utf-8"), parse_constant=reject_nonfinite
        )
        return cls.from_dict(payload)

    def validate_library(self, library: ModeLibrary, library_path: str | Path) -> None:
        if not isinstance(library, ModeLibrary):
            raise TypeError("library must be a ModeLibrary")
        if sha256_file(library_path) != self.mode_library_file_sha256:
            raise ValueError("B1 selection model-library file SHA-256 mismatch")
        if sha256_json(library.to_dict()) != self.mode_library_logical_sha256:
            raise ValueError("B1 selection model-library logical SHA-256 mismatch")
        if len(library.models) != self.component_count:
            raise ValueError("B1 selection component count differs from the library")


class SingletonDiagnostic:
    """Deterministic one-component diagnostic with strict timestamp handling."""

    __slots__ = ("_sample_index", "_last_time_s")

    def __init__(self) -> None:
        self._sample_index = 0
        self._last_time_s: float | None = None

    def reset(self) -> None:
        self._sample_index = 0
        self._last_time_s = None

    def step(self, measurement: Measurement) -> DiagnosticOutput:
        if not isinstance(measurement, Measurement):
            raise TypeError("measurement must be a Measurement")
        if self._last_time_s is not None and measurement.time_s <= self._last_time_s:
            raise ValueError("measurement times must be strictly increasing")
        output = DiagnosticOutput(
            time_s=measurement.time_s,
            sample_index=self._sample_index,
            valid_update=self._sample_index >= 2,
            mode_belief=np.ones(1, dtype=np.float64),
            map_mode=0,
            belief_entropy=0.0,
            raw_belief_entropy=0.0,
            mode_predictions_pu=np.array([measurement.p_ibr_pu], dtype=np.float64),
            residuals_pu=np.zeros(1, dtype=np.float64),
            innovation_variances_pu2=np.ones(1, dtype=np.float64),
            nis=np.zeros(1, dtype=np.float64),
            log_normalization_constant=0.0,
            ood_score=0.0,
            ood_pvalue=1.0,
            ood_active=False,
            diagnostic_state="KNOWN",
        )
        self._sample_index += 1
        self._last_time_s = measurement.time_s
        return output


def singleton_mode_from_arx(
    grid_model: GridFrequencyModel,
    model: ARXModeModel,
) -> SDBMPCMode:
    """Convert one persisted equation-(17) model to a local K=1 component."""

    if not isinstance(grid_model, GridFrequencyModel):
        raise TypeError("grid_model must be a GridFrequencyModel")
    if not isinstance(model, ARXModeModel):
        raise TypeError("model must be an ARXModeModel")
    A_b, B_b, F_b, _ = arx_to_state_space(model.theta)
    return SDBMPCMode(
        component_id=0,
        prediction_model=assemble_joint_arx_prediction(grid_model, A_b, B_b, F_b),
        frequency_q95_hz=model.multi_step_frequency_error_quantiles_hz,
        rocof_q95_hz_per_s=model.multi_step_rocof_error_quantiles_hz_per_s,
        power_q95_pu=model.multi_step_power_error_quantiles_pu,
        p_output_min_pu=model.p_output_min_pu,
        p_output_max_pu=model.p_output_max_pu,
        ramp_down_pu_per_s=model.ramp_down_pu_per_s,
        ramp_up_pu_per_s=model.ramp_up_pu_per_s,
    )


def singleton_mode_from_theta(
    grid_model: GridFrequencyModel,
    theta: ArrayLike,
    template: SDBMPCMode,
) -> SDBMPCMode:
    """Replace only a single-mode predictor's ARX coefficients."""

    if not isinstance(grid_model, GridFrequencyModel):
        raise TypeError("grid_model must be a GridFrequencyModel")
    if not isinstance(template, SDBMPCMode):
        raise TypeError("template must be an SDBMPCMode")
    A_b, B_b, F_b, _ = arx_to_state_space(theta)
    return SDBMPCMode(
        component_id=0,
        prediction_model=assemble_joint_arx_prediction(grid_model, A_b, B_b, F_b),
        frequency_q95_hz=template.frequency_q95_hz,
        rocof_q95_hz_per_s=template.rocof_q95_hz_per_s,
        power_q95_pu=template.power_q95_pu,
        p_output_min_pu=template.p_output_min_pu,
        p_output_max_pu=template.p_output_max_pu,
        ramp_down_pu_per_s=template.ramp_down_pu_per_s,
        ramp_up_pu_per_s=template.ramp_up_pu_per_s,
    )


@dataclass(slots=True)
class ParameterizedSingletonProblem:
    """One DPP QCQP whose ARX/capability values are online parameters."""

    problem: cp.Problem
    shared_input: cp.Variable
    state: cp.Variable
    freq_slack_hz: cp.Variable
    rocof_slack_hz_per_s: cp.Variable
    power_slack_pu: cp.Variable
    worst_case_epigraph: cp.Variable
    initial_state_parameter: cp.Parameter
    previous_input_parameter: cp.Parameter
    A_parameter: cp.Parameter
    B_parameter: cp.Parameter
    frequency_q95_parameter: cp.Parameter
    rocof_q95_parameter: cp.Parameter
    p_output_min_parameter: cp.Parameter
    p_output_max_parameter: cp.Parameter
    ramp_down_parameter: cp.Parameter
    ramp_up_parameter: cp.Parameter
    base_cost: cp.Expression
    config: SDBMPCConfig

    @property
    def risk_component_ids(self) -> tuple[int, ...]:
        return (0,)

    def solution_variables(self) -> dict[str, cp.Expression]:
        return {
            "shared_input": self.shared_input,
            "freq_slack_hz": self.freq_slack_hz,
            "rocof_slack_hz_per_s": self.rocof_slack_hz_per_s,
            "power_slack_pu": self.power_slack_pu,
            "worst_case_epigraph": self.worst_case_epigraph,
            "base_cost": self.base_cost,
            "mode_state_0": self.state,
        }

    def precompile(self, solver: str) -> float:
        solver_name = str(solver).strip().upper()
        if not solver_name:
            raise ValueError("solver must not be empty")
        start = perf_counter()
        self.problem.get_problem_data(solver=solver_name)
        return perf_counter() - start

    def set_warm_start(self, shared_input_pu: ArrayLike | None) -> None:
        if shared_input_pu is None:
            self.shared_input.value = None
            return
        values = np.asarray(shared_input_pu, dtype=np.float64)
        expected = (2, self.config.horizon_steps)
        if values.shape != expected or not np.all(np.isfinite(values)):
            raise ValueError(f"shared_input_pu must be finite with shape {expected}")
        self.shared_input.value = values.copy()

    def update_runtime(
        self,
        initial_state: ArrayLike,
        belief: ArrayLike,
        previous_input: ArrayLike,
        *,
        entropy_normalized: float,
        ood_suspect: bool,
        diagnostic_numerical_issue: bool,
    ) -> None:
        state0 = np.asarray(initial_state, dtype=np.float64)
        probabilities = np.asarray(belief, dtype=np.float64)
        previous = np.asarray(previous_input, dtype=np.float64)
        entropy = _finite_real(entropy_normalized, "entropy_normalized")
        if state0.shape != (10,) or not np.all(np.isfinite(state0)):
            raise ValueError("initial_state must be a finite ten-vector")
        if probabilities.shape != (1,) or probabilities[0] != 1.0:
            raise ValueError("singleton belief must equal [1]")
        if previous.shape != (2,) or not np.all(np.isfinite(previous)):
            raise ValueError("previous_input must be a finite two-vector")
        if not 0.0 <= entropy <= 1.0:
            raise ValueError("entropy_normalized must lie in [0, 1]")
        if not isinstance(ood_suspect, (bool, np.bool_)) or not isinstance(
            diagnostic_numerical_issue, (bool, np.bool_)
        ):
            raise TypeError("diagnostic flags must be boolean")
        self.initial_state_parameter.value = state0.copy()
        self.previous_input_parameter.value = previous.copy()

    def update_mode(self, mode: SDBMPCMode) -> None:
        if not isinstance(mode, SDBMPCMode) or mode.component_id != 0:
            raise ValueError("mode must be a singleton component with ID zero")
        horizon = self.config.horizon_steps

        def quantiles(values: Mapping[int, float], name: str) -> FloatArray:
            expected = tuple(range(1, horizon + 1))
            if any(index not in values for index in expected):
                raise ValueError(f"{name} must contain every lead 1..{horizon}")
            result = np.asarray([values[index] for index in expected], dtype=np.float64)
            if not np.all(np.isfinite(result)) or np.any(result < 0.0):
                raise ValueError(f"{name} must contain finite non-negative values")
            if not self.config.use_constraint_tightening:
                result = np.zeros(horizon, dtype=np.float64)
            return result

        self.A_parameter.value = mode.prediction_model.A.copy()
        self.B_parameter.value = mode.prediction_model.B.copy()
        self.frequency_q95_parameter.value = quantiles(
            mode.frequency_q95_hz, "frequency_q95_hz"
        )
        self.rocof_q95_parameter.value = quantiles(
            mode.rocof_q95_hz_per_s, "rocof_q95_hz_per_s"
        )
        self.p_output_min_parameter.value = mode.p_output_min_pu
        self.p_output_max_parameter.value = mode.p_output_max_pu
        self.ramp_down_parameter.value = mode.ramp_down_pu_per_s
        self.ramp_up_parameter.value = mode.ramp_up_pu_per_s


def _build_parameterized_singleton_problem(
    mode: SDBMPCMode,
    config: SDBMPCConfig,
    initial_state: ArrayLike,
    previous_input: ArrayLike,
) -> ParameterizedSingletonProblem:
    """Build the K=1 specialization of equations (52)--(66) once."""

    horizon = config.horizon_steps
    initial_state_parameter = cp.Parameter(10, name="rls_initial_state")
    previous_input_parameter = cp.Parameter(2, name="rls_previous_input")
    A_parameter = cp.Parameter((10, 10), name="rls_joint_A")
    B_parameter = cp.Parameter((10, 2), name="rls_joint_B")
    frequency_q95_parameter = cp.Parameter(
        horizon, nonneg=True, name="rls_frequency_q95_hz"
    )
    rocof_q95_parameter = cp.Parameter(
        horizon, nonneg=True, name="rls_rocof_q95_hz_per_s"
    )
    p_output_min_parameter = cp.Parameter(name="rls_p_output_min_pu")
    p_output_max_parameter = cp.Parameter(name="rls_p_output_max_pu")
    ramp_down_parameter = cp.Parameter(nonneg=True, name="rls_ramp_down_pu_per_s")
    ramp_up_parameter = cp.Parameter(nonneg=True, name="rls_ramp_up_pu_per_s")

    shared_input = cp.Variable((2, horizon), name="rls_shared_input")
    state = cp.Variable((10, horizon + 1), name="rls_mode_state")
    freq_slack_hz = cp.Variable(horizon, nonneg=True, name="rls_freq_slack_hz")
    rocof_slack_hz_per_s = cp.Variable(
        horizon, nonneg=True, name="rls_rocof_slack_hz_per_s"
    )
    power_slack_pu = cp.Variable(horizon, nonneg=True, name="rls_power_slack_pu")
    worst_case_epigraph = cp.Variable(nonneg=True, name="rls_worst_case_epigraph")
    constraints: list[cp.Constraint] = [
        state[:, 0] == initial_state_parameter,
        state[ARX_CONSTANT_INDEX, :] == 1.0,
        shared_input >= config.bounds.lower[:, None],
        shared_input <= config.bounds.upper[:, None],
    ]
    base_cost: cp.Expression = cp.Constant(0.0)
    state_residuals: list[cp.Expression] = []
    prior: cp.Expression = previous_input_parameter
    for lead in range(horizon):
        delta = shared_input[:, lead] - prior
        constraints.extend(
            [
                delta <= config.bounds.ramp * config.sample_time_s,
                delta >= -config.bounds.ramp * config.sample_time_s,
            ]
        )
        base_cost += cp.sum(
            cp.multiply(config.weights.input_weights, cp.square(shared_input[:, lead]))
        ) + cp.sum(cp.multiply(config.weights.delta_weights, cp.square(delta)))
        current = state[:, lead]
        future = state[:, lead + 1]
        constraints.append(
            future == A_parameter @ current + B_parameter @ shared_input[:, lead]
        )
        current_frequency_hz = config.f0_hz * current[GRID_FREQUENCY_INDEX]
        future_frequency_hz = config.f0_hz * future[GRID_FREQUENCY_INDEX]
        rocof = (future_frequency_hz - current_frequency_hz) / config.sample_time_s
        state_residuals.extend(
            [
                math.sqrt(config.weights.q_freq) * current_frequency_hz,
                math.sqrt(config.weights.q_integral) * current[GRID_INTEGRAL_INDEX],
                math.sqrt(config.weights.q_rocof) * rocof,
            ]
        )
        future_power = future[ARX_POWER_INDEX]
        power_change = future_power - current[ARX_POWER_INDEX]
        constraints.extend(
            [
                cp.abs(future_frequency_hz)
                <= config.bounds.freq_limit_hz
                - frequency_q95_parameter[lead]
                + freq_slack_hz[lead],
                cp.abs(rocof)
                <= config.bounds.rocof_limit_hz_per_s
                - rocof_q95_parameter[lead]
                + rocof_slack_hz_per_s[lead],
                p_output_min_parameter - power_slack_pu[lead] <= future_power,
                future_power <= p_output_max_parameter + power_slack_pu[lead],
                power_change
                <= ramp_up_parameter * config.sample_time_s + power_slack_pu[lead],
                -ramp_down_parameter * config.sample_time_s - power_slack_pu[lead]
                <= power_change,
            ]
        )
        prior = shared_input[:, lead]
    terminal = state[:, horizon]
    state_residuals.extend(
        [
            math.sqrt(config.weights.q_terminal_freq)
            * config.f0_hz
            * terminal[GRID_FREQUENCY_INDEX],
            math.sqrt(config.weights.q_terminal_integral)
            * terminal[GRID_INTEGRAL_INDEX],
        ]
    )
    state_cost = cp.sum_squares(cp.hstack(state_residuals))
    base_cost += state_cost
    constraints.append(base_cost <= worst_case_epigraph)
    # For K=1, min(t) subject to base_cost <= t is exactly min(base_cost).
    # Putting t in the objective anchors the epigraph and removes the otherwise
    # harmless but numerically undesirable free positive ray.
    objective = worst_case_epigraph + (
        config.weights.rho_freq_slack * cp.sum_squares(freq_slack_hz)
        + config.weights.rho_rocof_slack * cp.sum_squares(rocof_slack_hz_per_s)
        + config.weights.rho_power_slack * cp.sum_squares(power_slack_pu)
    )
    problem = cp.Problem(cp.Minimize(objective), constraints)
    if not problem.is_dcp() or not problem.is_dcp(dpp=True):
        raise RuntimeError("parameterized single-ARX MPC must be DCP and DPP")
    bundle = ParameterizedSingletonProblem(
        problem=problem,
        shared_input=shared_input,
        state=state,
        freq_slack_hz=freq_slack_hz,
        rocof_slack_hz_per_s=rocof_slack_hz_per_s,
        power_slack_pu=power_slack_pu,
        worst_case_epigraph=worst_case_epigraph,
        initial_state_parameter=initial_state_parameter,
        previous_input_parameter=previous_input_parameter,
        A_parameter=A_parameter,
        B_parameter=B_parameter,
        frequency_q95_parameter=frequency_q95_parameter,
        rocof_q95_parameter=rocof_q95_parameter,
        p_output_min_parameter=p_output_min_parameter,
        p_output_max_parameter=p_output_max_parameter,
        ramp_down_parameter=ramp_down_parameter,
        ramp_up_parameter=ramp_up_parameter,
        base_cost=base_cost,
        config=config,
    )
    bundle.update_mode(mode)
    bundle.update_runtime(
        initial_state,
        np.ones(1, dtype=np.float64),
        previous_input,
        entropy_normalized=0.0,
        ood_suspect=False,
        diagnostic_numerical_issue=False,
    )
    return bundle


class MutableSingletonProblemCache:
    """K=1 DPP cache with no per-sample graph rebuild/canonicalization."""

    __slots__ = ("_mode", "_config", "_problem", "_revision", "_build_count")

    def __init__(self, mode: SDBMPCMode, config: SDBMPCConfig) -> None:
        if not isinstance(mode, SDBMPCMode) or mode.component_id != 0:
            raise ValueError("mode must be a singleton component with ID zero")
        if not isinstance(config, SDBMPCConfig):
            raise TypeError("config must be an SDBMPCConfig")
        self._mode = mode
        self._config = config
        self._problem: ParameterizedSingletonProblem | None = None
        self._revision = 0
        self._build_count = 0

    @property
    def mode(self) -> SDBMPCMode:
        return self._mode

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def graph_build_count(self) -> int:
        return self._build_count

    @property
    def problem_identity(self) -> int | None:
        return None if self._problem is None else id(self._problem.problem)

    def set_mode(self, mode: SDBMPCMode) -> None:
        if not isinstance(mode, SDBMPCMode) or mode.component_id != 0:
            raise ValueError("mode must be a singleton component with ID zero")
        self._mode = mode
        if self._problem is not None:
            self._problem.set_warm_start(None)
            self._problem.update_mode(mode)
        self._revision += 1

    def prepare(
        self,
        initial_state: ArrayLike,
        belief: ArrayLike,
        previous_input: ArrayLike,
        *,
        entropy_normalized: float,
        ood_suspect: bool,
        diagnostic_numerical_issue: bool = False,
    ) -> ParameterizedSingletonProblem:
        if self._problem is None:
            self._problem = _build_parameterized_singleton_problem(
                self._mode, self._config, initial_state, previous_input
            )
            self._build_count += 1
        else:
            self._problem.update_runtime(
                initial_state,
                belief,
                previous_input,
                entropy_normalized=entropy_normalized,
                ood_suspect=ood_suspect,
                diagnostic_numerical_issue=diagnostic_numerical_issue,
            )
        return self._problem

    def clear(self) -> None:
        if self._problem is not None:
            self._problem.set_warm_start(None)
        self._problem = None


def single_model_mpc_config(config: SDBMPCConfig) -> SDBMPCConfig:
    """Remove the uncertainty-only worst-mode term from a K=1 baseline."""

    if not isinstance(config, SDBMPCConfig):
        raise TypeError("config must be an SDBMPCConfig")
    weights = replace(
        config.weights,
        lambda_worst_base=0.0,
        lambda_worst_entropy=0.0,
    )
    return replace(config, weights=weights, credible_mass=1.0)


class FinalARXMPCController:
    """Truth-free fixed-reference ARX MPC implementing ``FrequencyController``."""

    __slots__ = ("_inner", "_cache", "_method_state", "_source_component_id")

    def __init__(
        self,
        grid_model: GridFrequencyModel,
        mode: SDBMPCMode,
        *,
        mpc_config: SDBMPCConfig,
        controller_config: SDBMPCControllerConfig,
        estimator: GridStateEstimator | None = None,
        fallback_config: LQIFallbackConfig | None = None,
        solve_function: Any = None,
        method_state: str = "FIXED_REFERENCE_ARX_MPC",
        source_component_id: int | None = None,
        mutable_cache: MutableSingletonProblemCache | None = None,
        diagnostic: OnlineDiagnosticRuntime | None = None,
        enable_ood_fallback: bool = False,
    ) -> None:
        if not isinstance(mode, SDBMPCMode):
            raise TypeError("mode must be an SDBMPCMode")
        local_mode = replace(mode, component_id=0)
        settings = single_model_mpc_config(mpc_config)
        if not isinstance(enable_ood_fallback, (bool, np.bool_)):
            raise TypeError("enable_ood_fallback must be boolean")
        policy = replace(
            controller_config, enable_ood_fallback=bool(enable_ood_fallback)
        )
        cache = (
            MutableSingletonProblemCache(local_mode, settings)
            if mutable_cache is None
            else mutable_cache
        )
        state = str(method_state).strip()
        if not state:
            raise ValueError("method_state must not be empty")
        source_id = (
            mode.component_id
            if source_component_id is None
            else _nonnegative_integer(source_component_id, "source_component_id")
        )
        kwargs: dict[str, object] = {}
        if solve_function is not None:
            kwargs["solve_function"] = solve_function
        self._inner = SDBMPCController(
            grid_model,
            (local_mode,),
            SingletonDiagnostic() if diagnostic is None else diagnostic,
            mpc_config=settings,
            controller_config=policy,
            estimator=estimator,
            fallback_config=fallback_config,
            problem_cache=cache,
            **kwargs,
        )
        self._cache = cache
        self._method_state = state
        self._source_component_id = source_id

    @property
    def source_component_id(self) -> int:
        return self._source_component_id

    @property
    def inner_controller(self) -> SDBMPCController:
        return self._inner

    @property
    def problem_cache(self) -> MutableSingletonProblemCache:
        return self._cache

    @property
    def step_records(self) -> tuple[SDBMPCStepRecord, ...]:
        return self._inner.step_records

    @property
    def fallback_events(self) -> tuple[FallbackEvent, ...]:
        return self._inner.fallback_events

    def replace_runtime_mode(self, mode: SDBMPCMode) -> None:
        """Set a local K=1 model before the next, not-yet-consumed timestamp."""

        self._cache.set_mode(replace(mode, component_id=0))

    def reset(self, initial_measurement: Measurement) -> None:
        self._inner.reset(initial_measurement)

    def act(self, measurement: Measurement) -> ControlAction:
        action = self._inner.act(measurement)
        fallback = action.controller_state == "FALLBACK"
        return ControlAction(
            u_sg_pu=action.u_sg_pu,
            u_ibr_pu=action.u_ibr_pu,
            controller_state=(
                f"{self._method_state}_FALLBACK" if fallback else self._method_state
            ),
            solver_status=action.solver_status,
            solve_time_s=action.solve_time_s,
            max_freq_slack_hz=action.max_freq_slack_hz,
        )


def build_fixed_reference_arx_controller(
    *,
    grid_model: GridFrequencyModel,
    mode_library: ModeLibrary,
    mode_library_path: str | Path,
    selection: FixedReferenceSelectionArtifact,
    mpc_config: SDBMPCConfig,
    controller_config: SDBMPCControllerConfig,
    estimator: GridStateEstimator | None = None,
    fallback_config: LQIFallbackConfig | None = None,
) -> FinalARXMPCController:
    """Build B1 only after validating its frozen label-free selection."""

    if not isinstance(selection, FixedReferenceSelectionArtifact):
        raise TypeError("selection must be a FixedReferenceSelectionArtifact")
    selection.validate_library(mode_library, mode_library_path)
    source_model = mode_library.models[selection.selected_component_id]
    return FinalARXMPCController(
        grid_model,
        singleton_mode_from_arx(grid_model, source_model),
        mpc_config=mpc_config,
        controller_config=controller_config,
        estimator=estimator,
        fallback_config=fallback_config,
        method_state="FIXED_REFERENCE_ARX_MPC",
        source_component_id=source_model.component_id,
    )


__all__ = [
    "FinalARXMPCController",
    "FixedReferenceSelectionArtifact",
    "MutableSingletonProblemCache",
    "ParameterizedSingletonProblem",
    "REFERENCE_SELECTION_SCHEMA_VERSION",
    "ReferenceCandidateScore",
    "SingletonDiagnostic",
    "build_fixed_reference_arx_controller",
    "single_model_mpc_config",
    "singleton_mode_from_arx",
    "singleton_mode_from_theta",
]
