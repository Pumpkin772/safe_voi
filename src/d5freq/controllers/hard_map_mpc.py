"""Hard-MAP controller and diagnostic projections for Phase-6 ablations."""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

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
from d5freq.interfaces import ControlAction, Measurement
from d5freq.models.grid_frequency import GridFrequencyModel
from d5freq.optimization.mpc_problem import SDBMPCConfig, SDBMPCMode


@dataclass(frozen=True, slots=True)
class DiagnosticProjectionRecord:
    """Raw-to-executable diagnostic mapping at one distinct timestamp."""

    time_s: float
    raw_mode_belief: np.ndarray
    projected_mode_belief: np.ndarray
    raw_diagnostic_state: str
    projected_diagnostic_state: str

    def __post_init__(self) -> None:
        raw = np.asarray(self.raw_mode_belief, dtype=np.float64)
        projected = np.asarray(self.projected_mode_belief, dtype=np.float64)
        if raw.ndim != 1 or raw.shape != projected.shape or raw.size == 0:
            raise ValueError("diagnostic beliefs must be equal non-empty vectors")
        if not np.all(np.isfinite(raw)) or not np.all(np.isfinite(projected)):
            raise ValueError("diagnostic beliefs must be finite")
        for value, name in ((raw, "raw"), (projected, "projected")):
            if np.any(value < 0.0) or not np.isclose(np.sum(value), 1.0, atol=1.0e-12):
                raise ValueError(f"{name} diagnostic belief is not a probability vector")
        raw = raw.copy()
        projected = projected.copy()
        raw.setflags(write=False)
        projected.setflags(write=False)
        object.__setattr__(self, "raw_mode_belief", raw)
        object.__setattr__(self, "projected_mode_belief", projected)


class DiagnosticRuntimeProjection:
    """Call an online diagnostic exactly once, then project only its output."""

    __slots__ = ("_diagnostic", "_hard_map", "_ignore_ood", "_records")

    def __init__(
        self,
        diagnostic: OnlineDiagnosticRuntime,
        *,
        hard_map: bool,
        ignore_ood: bool,
    ) -> None:
        if not isinstance(diagnostic, OnlineDiagnosticRuntime):
            raise TypeError("diagnostic must satisfy OnlineDiagnosticRuntime")
        if not isinstance(hard_map, (bool, np.bool_)) or not isinstance(
            ignore_ood, (bool, np.bool_)
        ):
            raise TypeError("projection flags must be boolean")
        self._diagnostic = diagnostic
        self._hard_map = bool(hard_map)
        self._ignore_ood = bool(ignore_ood)
        self._records: list[DiagnosticProjectionRecord] = []

    @property
    def source_diagnostic(self) -> OnlineDiagnosticRuntime:
        return self._diagnostic

    @property
    def records(self) -> tuple[DiagnosticProjectionRecord, ...]:
        return tuple(self._records)

    def reset(self) -> None:
        self._diagnostic.reset()
        self._records.clear()

    def step(self, measurement: Measurement) -> DiagnosticOutput:
        # This is the one and only source-diagnostic call for this timestamp.
        output = self._diagnostic.step(measurement)
        if not isinstance(output, DiagnosticOutput):
            raise TypeError("source diagnostic must return DiagnosticOutput")
        raw_belief = np.asarray(output.mode_belief, dtype=np.float64)
        projected_belief = raw_belief.copy()
        entropy = output.belief_entropy
        raw_entropy = output.raw_belief_entropy
        map_mode = output.map_mode
        if self._hard_map:
            map_mode = int(np.argmax(raw_belief))
            projected_belief = np.zeros_like(raw_belief)
            projected_belief[map_mode] = 1.0
            entropy = 0.0
            raw_entropy = 0.0
        state = "KNOWN" if self._ignore_ood else output.diagnostic_state
        pvalue = 1.0 if self._ignore_ood else output.ood_pvalue
        active = False if self._ignore_ood else output.ood_active
        projected = replace(
            output,
            mode_belief=projected_belief,
            map_mode=map_mode,
            belief_entropy=entropy,
            raw_belief_entropy=raw_entropy,
            ood_pvalue=pvalue,
            ood_active=active,
            diagnostic_state=state,
        )
        self._records.append(
            DiagnosticProjectionRecord(
                time_s=measurement.time_s,
                raw_mode_belief=raw_belief,
                projected_mode_belief=projected_belief,
                raw_diagnostic_state=output.diagnostic_state,
                projected_diagnostic_state=state,
            )
        )
        return projected


class HardMAPMPCController:
    """B3: diagnostic argmax selects one of the same frozen K models."""

    __slots__ = ("_inner", "_projection")

    def __init__(
        self,
        grid_model: GridFrequencyModel,
        modes: tuple[SDBMPCMode, ...],
        diagnostic: OnlineDiagnosticRuntime,
        *,
        mpc_config: SDBMPCConfig,
        controller_config: SDBMPCControllerConfig,
        estimator: GridStateEstimator | None = None,
        fallback_config: LQIFallbackConfig | None = None,
        enable_ood_fallback: bool = True,
    ) -> None:
        projection = DiagnosticRuntimeProjection(
            diagnostic, hard_map=True, ignore_ood=not enable_ood_fallback
        )
        # B3 isolates probability softening.  It optimizes only J_MAP rather
        # than silently retaining an uncertainty-only worst-mode objective.
        weights = replace(
            mpc_config.weights,
            lambda_worst_base=0.0,
            lambda_worst_entropy=0.0,
        )
        hard_config = replace(mpc_config, weights=weights)
        policy = replace(
            controller_config, enable_ood_fallback=bool(enable_ood_fallback)
        )
        self._inner = SDBMPCController(
            grid_model,
            modes,
            projection,
            mpc_config=hard_config,
            controller_config=policy,
            estimator=estimator,
            fallback_config=fallback_config,
        )
        self._projection = projection

    @property
    def inner_controller(self) -> SDBMPCController:
        return self._inner

    @property
    def projection_records(self) -> tuple[DiagnosticProjectionRecord, ...]:
        return self._projection.records

    @property
    def step_records(self) -> tuple[SDBMPCStepRecord, ...]:
        return self._inner.step_records

    @property
    def fallback_events(self) -> tuple[FallbackEvent, ...]:
        return self._inner.fallback_events

    def reset(self, initial_measurement: Measurement) -> None:
        self._inner.reset(initial_measurement)

    def act(self, measurement: Measurement) -> ControlAction:
        action = self._inner.act(measurement)
        return ControlAction(
            u_sg_pu=action.u_sg_pu,
            u_ibr_pu=action.u_ibr_pu,
            controller_state=(
                "HARD_MAP_MPC_FALLBACK"
                if action.controller_state == "FALLBACK"
                else "HARD_MAP_MPC"
            ),
            solver_status=action.solver_status,
            solve_time_s=action.solve_time_s,
            max_freq_slack_hz=action.max_freq_slack_hz,
        )


__all__ = [
    "DiagnosticProjectionRecord",
    "DiagnosticRuntimeProjection",
    "HardMAPMPCController",
]
