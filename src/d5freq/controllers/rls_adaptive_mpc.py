"""Single-model RLS-MPC baseline for equations (85)--(87).

The RLS estimator consumes only measured IBR power, previously executable IBR
commands, and frequency.  Its seven parameters update one precompiled DPP MPC
template; the CVXPY graph is never rebuilt at a control instant.  Projection
and every skipped/failed update are retained as first-class runtime records.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
from numbers import Real

import numpy as np
from numpy.typing import ArrayLike, NDArray

from d5freq.controllers.base import GridStateEstimator
from d5freq.controllers.final_arx_mpc import (
    FinalARXMPCController,
    MutableSingletonProblemCache,
    single_model_mpc_config,
    singleton_mode_from_arx,
    singleton_mode_from_theta,
)
from d5freq.controllers.lqi_fallback import LQIFallbackConfig
from d5freq.controllers.sd_bmpc import (
    FallbackEvent,
    SDBMPCControllerConfig,
    SDBMPCStepRecord,
)
from d5freq.identification.model_library import ARXModeModel
from d5freq.interfaces import ControlAction, Measurement
from d5freq.models.grid_frequency import GridFrequencyModel
from d5freq.optimization.mpc_problem import SDBMPCConfig, SDBMPCMode


FloatArray = NDArray[np.float64]
RLS_PARAMETER_COUNT = 7


def _finite(value: object, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real scalar")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _readonly_vector(value: ArrayLike, size: int, name: str) -> FloatArray:
    array = np.asarray(value, dtype=np.float64)
    if array.shape != (size,) or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must be finite with shape ({size},)")
    result = array.copy()
    result.setflags(write=False)
    return result


@dataclass(frozen=True, slots=True)
class RLSConfig:
    """Frozen numerical policy for equations (85)--(87)."""

    forgetting_factor: float = 0.995
    covariance_initial_scale: float = 1000.0
    covariance_eigenvalue_min: float = 1.0e-8
    covariance_eigenvalue_max: float = 1.0e8
    denominator_floor: float = 1.0e-12
    maximum_arx_pole_radius: float = 0.995
    parameter_lower: tuple[float, ...] = (-2.0, -1.0, -5.0, -5.0, -20.0, -20.0, -0.1)
    parameter_upper: tuple[float, ...] = (2.0, 1.0, 5.0, 5.0, 20.0, 20.0, 0.1)

    def __post_init__(self) -> None:
        forgetting = _finite(self.forgetting_factor, "forgetting_factor")
        if not 0.0 < forgetting <= 1.0:
            raise ValueError("forgetting_factor must lie in (0, 1]")
        p0 = _finite(self.covariance_initial_scale, "covariance_initial_scale")
        eig_min = _finite(
            self.covariance_eigenvalue_min, "covariance_eigenvalue_min"
        )
        eig_max = _finite(
            self.covariance_eigenvalue_max, "covariance_eigenvalue_max"
        )
        denominator = _finite(self.denominator_floor, "denominator_floor")
        radius = _finite(self.maximum_arx_pole_radius, "maximum_arx_pole_radius")
        if p0 <= 0.0 or eig_min <= 0.0 or eig_max < eig_min or denominator <= 0.0:
            raise ValueError("RLS covariance and denominator limits are inconsistent")
        if not 0.0 < radius < 1.0:
            raise ValueError("maximum_arx_pole_radius must lie in (0, 1)")
        lower = tuple(_finite(item, "parameter_lower") for item in self.parameter_lower)
        upper = tuple(_finite(item, "parameter_upper") for item in self.parameter_upper)
        if len(lower) != RLS_PARAMETER_COUNT or len(upper) != RLS_PARAMETER_COUNT:
            raise ValueError("parameter bounds must contain seven entries")
        if any(lo >= hi for lo, hi in zip(lower, upper, strict=True)):
            raise ValueError("every RLS parameter lower bound must be below its upper bound")
        object.__setattr__(self, "forgetting_factor", forgetting)
        object.__setattr__(self, "covariance_initial_scale", p0)
        object.__setattr__(self, "covariance_eigenvalue_min", eig_min)
        object.__setattr__(self, "covariance_eigenvalue_max", eig_max)
        object.__setattr__(self, "denominator_floor", denominator)
        object.__setattr__(self, "maximum_arx_pole_radius", radius)
        object.__setattr__(self, "parameter_lower", lower)
        object.__setattr__(self, "parameter_upper", upper)


@dataclass(frozen=True, slots=True)
class RLSUpdateRecord:
    """Auditable result of one warm-up, successful, or failed update."""

    time_s: float
    sample_index: int
    valid_update: bool
    update_success: bool
    theta_before: FloatArray
    theta_after: FloatArray
    innovation_pu: float | None
    denominator: float | None
    gain_norm: float | None
    covariance_trace_before: float
    covariance_trace_after: float
    covariance_condition_after: float
    pole_projection_applied: bool
    parameter_projection_applied: bool
    covariance_projection_applied: bool
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        time = _finite(self.time_s, "time_s")
        if time < 0.0 or self.sample_index < 0:
            raise ValueError("time_s/sample_index must be non-negative")
        before = _readonly_vector(self.theta_before, RLS_PARAMETER_COUNT, "theta_before")
        after = _readonly_vector(self.theta_after, RLS_PARAMETER_COUNT, "theta_after")
        for name in (
            "innovation_pu",
            "denominator",
            "gain_norm",
            "covariance_trace_before",
            "covariance_trace_after",
            "covariance_condition_after",
        ):
            value = getattr(self, name)
            if value is not None:
                normalized = _finite(value, name)
                if name != "innovation_pu" and normalized < 0.0:
                    raise ValueError(f"{name} must be non-negative")
                object.__setattr__(self, name, normalized)
        if self.update_success and not self.valid_update:
            raise ValueError("a successful update must be valid")
        if self.update_success and self.failure_reason is not None:
            raise ValueError("successful updates cannot have a failure_reason")
        if not self.update_success and self.valid_update and not self.failure_reason:
            raise ValueError("failed valid updates require a failure_reason")
        object.__setattr__(self, "time_s", time)
        object.__setattr__(self, "theta_before", before)
        object.__setattr__(self, "theta_after", after)

    def to_log_record(self) -> dict[str, object]:
        return {
            "time_s": self.time_s,
            "sample_index": self.sample_index,
            "rls_valid_update": self.valid_update,
            "rls_update_success": self.update_success,
            "rls_theta_before": self.theta_before.tolist(),
            "rls_theta_after": self.theta_after.tolist(),
            "rls_innovation_pu": self.innovation_pu,
            "rls_denominator": self.denominator,
            "rls_gain_norm": self.gain_norm,
            "rls_covariance_trace_before": self.covariance_trace_before,
            "rls_covariance_trace_after": self.covariance_trace_after,
            "rls_covariance_condition_after": self.covariance_condition_after,
            "rls_pole_projection_applied": self.pole_projection_applied,
            "rls_parameter_projection_applied": self.parameter_projection_applied,
            "rls_covariance_projection_applied": self.covariance_projection_applied,
            "rls_failure_reason": self.failure_reason,
        }


def project_stable_arx_theta(
    theta: ArrayLike,
    config: RLSConfig,
) -> tuple[FloatArray, bool, bool]:
    """Project parameters to finite bounds and a Schur AR(2) polynomial."""

    if not isinstance(config, RLSConfig):
        raise TypeError("config must be an RLSConfig")
    raw = _readonly_vector(theta, RLS_PARAMETER_COUNT, "theta").copy()
    clipped = np.clip(raw, np.asarray(config.parameter_lower), np.asarray(config.parameter_upper))
    parameter_projection = not np.array_equal(clipped, raw)
    roots = np.roots(np.array([1.0, -clipped[0], -clipped[1]], dtype=np.float64))
    if not np.all(np.isfinite(roots)):
        raise FloatingPointError("ARX pole calculation became non-finite")
    projected_roots = roots.astype(np.complex128, copy=True)
    pole_projection = False
    for index, root in enumerate(projected_roots):
        magnitude = abs(root)
        if magnitude > config.maximum_arx_pole_radius:
            projected_roots[index] = root * (config.maximum_arx_pole_radius / magnitude)
            pole_projection = True
    if pole_projection:
        polynomial = np.poly(projected_roots)
        if np.max(np.abs(np.imag(polynomial))) > 1.0e-10:
            raise FloatingPointError("ARX pole projection lost real conjugate symmetry")
        coefficients = np.real(polynomial)
        clipped[0] = -coefficients[1]
        clipped[1] = -coefficients[2]
    clipped = np.clip(
        clipped, np.asarray(config.parameter_lower), np.asarray(config.parameter_upper)
    )
    final_roots = np.roots([1.0, -clipped[0], -clipped[1]])
    if float(np.max(np.abs(final_roots))) > config.maximum_arx_pole_radius + 1.0e-10:
        raise FloatingPointError("projected ARX model is not Schur stable")
    result = clipped.copy()
    result.setflags(write=False)
    return result, pole_projection, parameter_projection


def project_covariance(
    covariance: ArrayLike,
    config: RLSConfig,
) -> tuple[FloatArray, bool]:
    """Symmetrize and eigen-project the RLS covariance to a finite SPD cone."""

    raw = np.asarray(covariance, dtype=np.float64)
    if raw.shape != (RLS_PARAMETER_COUNT, RLS_PARAMETER_COUNT) or not np.all(
        np.isfinite(raw)
    ):
        raise FloatingPointError("RLS covariance must remain a finite 7x7 matrix")
    symmetric = 0.5 * (raw + raw.T)
    eigenvalues, eigenvectors = np.linalg.eigh(symmetric)
    clipped = np.clip(
        eigenvalues,
        config.covariance_eigenvalue_min,
        config.covariance_eigenvalue_max,
    )
    projected = not np.allclose(clipped, eigenvalues, rtol=0.0, atol=0.0) or not np.allclose(
        raw, symmetric, rtol=0.0, atol=1.0e-14
    )
    result = (eigenvectors * clipped) @ eigenvectors.T
    result = 0.5 * (result + result.T)
    if not np.all(np.isfinite(result)) or float(np.linalg.eigvalsh(result)[0]) <= 0.0:
        raise FloatingPointError("projected RLS covariance is not finite SPD")
    return result, projected


class RLSAdaptiveMPCController:
    """B2: one continuously adapted ARX model plus strict MPC/LQI safety."""

    __slots__ = (
        "_grid_model",
        "_initial_mode",
        "_template_mode",
        "_config",
        "_theta",
        "_covariance",
        "_inner",
        "_history",
        "_records",
        "_reset_measurement",
        "_last_action_measurement",
        "_last_action",
    )

    def __init__(
        self,
        grid_model: GridFrequencyModel,
        initial_model: ARXModeModel,
        *,
        mpc_config: SDBMPCConfig,
        controller_config: SDBMPCControllerConfig,
        rls_config: RLSConfig | None = None,
        estimator: GridStateEstimator | None = None,
        fallback_config: LQIFallbackConfig | None = None,
    ) -> None:
        if not isinstance(grid_model, GridFrequencyModel):
            raise TypeError("grid_model must be a GridFrequencyModel")
        if not isinstance(initial_model, ARXModeModel):
            raise TypeError("initial_model must be an ARXModeModel")
        settings = RLSConfig() if rls_config is None else rls_config
        if not isinstance(settings, RLSConfig):
            raise TypeError("rls_config must be an RLSConfig")
        template = singleton_mode_from_arx(grid_model, initial_model)
        single_config = single_model_mpc_config(mpc_config)
        cache = MutableSingletonProblemCache(template, single_config)
        self._inner = FinalARXMPCController(
            grid_model,
            template,
            mpc_config=single_config,
            controller_config=controller_config,
            estimator=estimator,
            fallback_config=fallback_config,
            method_state="RLS_ADAPTIVE_ARX_MPC",
            source_component_id=initial_model.component_id,
            mutable_cache=cache,
        )
        initial_theta, _, _ = project_stable_arx_theta(initial_model.theta, settings)
        self._grid_model = grid_model
        self._initial_mode = initial_model
        self._template_mode = template
        self._config = settings
        self._theta = initial_theta.copy()
        self._covariance = np.eye(RLS_PARAMETER_COUNT) * settings.covariance_initial_scale
        self._history: deque[Measurement] = deque(maxlen=2)
        self._records: list[RLSUpdateRecord] = []
        self._reset_measurement: Measurement | None = None
        self._last_action_measurement: Measurement | None = None
        self._last_action: ControlAction | None = None

    @property
    def config(self) -> RLSConfig:
        return self._config

    @property
    def theta(self) -> FloatArray:
        result = self._theta.copy()
        result.setflags(write=False)
        return result

    @property
    def covariance(self) -> FloatArray:
        result = self._covariance.copy()
        result.setflags(write=False)
        return result

    @property
    def update_records(self) -> tuple[RLSUpdateRecord, ...]:
        return tuple(self._records)

    @property
    def step_records(self) -> tuple[SDBMPCStepRecord, ...]:
        return self._inner.step_records

    @property
    def fallback_events(self) -> tuple[FallbackEvent, ...]:
        return self._inner.fallback_events

    @property
    def problem_cache(self) -> MutableSingletonProblemCache:
        return self._inner.problem_cache

    def reset(self, initial_measurement: Measurement) -> None:
        if not isinstance(initial_measurement, Measurement):
            raise TypeError("initial_measurement must be a Measurement")
        self._theta = project_stable_arx_theta(
            self._initial_mode.theta, self._config
        )[0].copy()
        self._covariance = (
            np.eye(RLS_PARAMETER_COUNT, dtype=np.float64)
            * self._config.covariance_initial_scale
        )
        self._history.clear()
        self._history.append(initial_measurement)
        self._records.clear()
        self._reset_measurement = initial_measurement
        self._last_action_measurement = None
        self._last_action = None
        self._inner.replace_runtime_mode(
            singleton_mode_from_theta(
                self._grid_model, self._theta, self._template_mode
            )
        )
        self._inner.reset(initial_measurement)

    def _warmup_record(self, measurement: Measurement) -> RLSUpdateRecord:
        trace = float(np.trace(self._covariance))
        return RLSUpdateRecord(
            time_s=measurement.time_s,
            sample_index=len(self._records),
            valid_update=False,
            update_success=False,
            theta_before=self._theta,
            theta_after=self._theta,
            innovation_pu=None,
            denominator=None,
            gain_norm=None,
            covariance_trace_before=trace,
            covariance_trace_after=trace,
            covariance_condition_after=float(np.linalg.cond(self._covariance)),
            pole_projection_applied=False,
            parameter_projection_applied=False,
            covariance_projection_applied=False,
        )

    def _rls_update(self, measurement: Measurement) -> RLSUpdateRecord:
        if len(self._history) < 2:
            return self._warmup_record(measurement)
        previous = self._history[-1]
        two_back = self._history[-2]
        phi = np.array(
            [
                previous.p_ibr_pu,
                two_back.p_ibr_pu,
                measurement.u_ibr_prev_pu,
                previous.u_ibr_prev_pu,
                previous.omega_pu,
                two_back.omega_pu,
                1.0,
            ],
            dtype=np.float64,
        )
        theta_before = self._theta.copy()
        covariance_before = self._covariance.copy()
        trace_before = float(np.trace(covariance_before))
        innovation: float | None = None
        denominator: float | None = None
        gain_norm: float | None = None
        try:
            denominator = float(
                self._config.forgetting_factor + phi @ covariance_before @ phi
            )
            if not math.isfinite(denominator) or denominator <= self._config.denominator_floor:
                raise FloatingPointError("RLS denominator is non-finite or too small")
            gain = covariance_before @ phi / denominator
            gain_norm = float(np.linalg.norm(gain))
            innovation = float(measurement.p_ibr_pu - phi @ theta_before)
            raw_theta = theta_before + gain * innovation
            theta_after, pole_projected, parameter_projected = project_stable_arx_theta(
                raw_theta, self._config
            )
            raw_covariance = (
                np.eye(RLS_PARAMETER_COUNT, dtype=np.float64)
                - np.outer(gain, phi)
            ) @ covariance_before / self._config.forgetting_factor
            covariance_after, covariance_projected = project_covariance(
                raw_covariance, self._config
            )
            condition = float(np.linalg.cond(covariance_after))
            if not math.isfinite(condition):
                raise FloatingPointError("RLS covariance condition is non-finite")
            self._theta = theta_after.copy()
            self._covariance = covariance_after
            return RLSUpdateRecord(
                time_s=measurement.time_s,
                sample_index=len(self._records),
                valid_update=True,
                update_success=True,
                theta_before=theta_before,
                theta_after=theta_after,
                innovation_pu=innovation,
                denominator=denominator,
                gain_norm=gain_norm,
                covariance_trace_before=trace_before,
                covariance_trace_after=float(np.trace(covariance_after)),
                covariance_condition_after=condition,
                pole_projection_applied=pole_projected,
                parameter_projection_applied=parameter_projected,
                covariance_projection_applied=covariance_projected,
            )
        except Exception as exc:
            return RLSUpdateRecord(
                time_s=measurement.time_s,
                sample_index=len(self._records),
                valid_update=True,
                update_success=False,
                theta_before=theta_before,
                theta_after=theta_before,
                innovation_pu=innovation,
                denominator=denominator,
                gain_norm=gain_norm,
                covariance_trace_before=trace_before,
                covariance_trace_after=trace_before,
                covariance_condition_after=float(np.linalg.cond(covariance_before)),
                pole_projection_applied=False,
                parameter_projection_applied=False,
                covariance_projection_applied=False,
                failure_reason=f"{type(exc).__name__}: {exc}",
            )

    def act(self, measurement: Measurement) -> ControlAction:
        if not isinstance(measurement, Measurement):
            raise TypeError("measurement must be a Measurement")
        if self._reset_measurement is None:
            raise RuntimeError("reset must be called before act")
        if self._last_action_measurement is not None:
            if measurement.time_s < self._last_action_measurement.time_s:
                raise ValueError("measurement times must be nondecreasing")
            if measurement.time_s == self._last_action_measurement.time_s:
                if measurement != self._last_action_measurement:
                    raise ValueError("a timestamp cannot be reused with changed signals")
                assert self._last_action is not None
                return self._last_action
        elif measurement.time_s < self._reset_measurement.time_s:
            raise ValueError("measurement precedes reset")
        elif measurement.time_s == self._reset_measurement.time_s:
            if measurement != self._reset_measurement:
                raise ValueError("the reset timestamp cannot be reused with changed signals")
            record = self._warmup_record(measurement)
            self._records.append(record)
            action = self._inner.act(measurement)
            self._last_action_measurement = measurement
            self._last_action = action
            return action

        record = self._rls_update(measurement)
        self._records.append(record)
        if record.update_success:
            self._inner.replace_runtime_mode(
                singleton_mode_from_theta(
                    self._grid_model, self._theta, self._template_mode
                )
            )
        action = self._inner.act(measurement)
        self._history.append(measurement)
        self._last_action_measurement = measurement
        self._last_action = action
        return action

    def runtime_log_records(self) -> tuple[dict[str, object], ...]:
        """Merge RLS and strict solver/fallback logs by controller sample."""

        if len(self._records) != len(self.step_records):
            raise RuntimeError("RLS and MPC records are not time-aligned")
        merged: list[dict[str, object]] = []
        for rls, mpc in zip(self._records, self.step_records, strict=True):
            record = mpc.to_log_record()
            record.update(rls.to_log_record())
            merged.append(record)
        return tuple(merged)


__all__ = [
    "RLSAdaptiveMPCController",
    "RLSConfig",
    "RLSUpdateRecord",
    "project_covariance",
    "project_stable_arx_theta",
]
