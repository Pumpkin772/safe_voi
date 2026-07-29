"""Controlled Phase-B1 counterfactual controllers C0--C5.

The module stays in the evaluation layer because C0--C2 consume evaluator
mode labels.  C3--C5 remain measurement-only runtime counterfactuals.  Every
build reuses the frozen MPC horizon, weights, solver policy, and command bounds;
the factor ledger below declares the sole changed mechanism.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import math
from types import MappingProxyType
from typing import Any

import numpy as np

from d5freq.controllers.base import clip_with_rate_limit
from d5freq.controllers.sd_bmpc import SDBMPCController
from d5freq.estimation.online_diagnostic import DiagnosticOutput, OnlineModeDiagnostic
from d5freq.evaluation.controller_factories import (
    FinalControllerFactory,
    SDBMPCVariantConfig,
)
from d5freq.interfaces import ControlAction, Measurement
from d5freq.optimization.mpc_problem import modes_from_library


COUNTERFACTUAL_SCHEMA_VERSION = "d5freq.phase_b1.counterfactuals.v1"


@dataclass(frozen=True, slots=True)
class CounterfactualFactorConfig:
    method_id: str
    belief_source: str
    worst_mode_cost: bool
    constraint_tightening: bool
    transition_prior: str
    ood_authority_policy: str
    differs_from: str
    sole_changed_factor: str


COUNTERFACTUAL_FACTORS: Mapping[str, CounterfactualFactorConfig] = MappingProxyType(
    {
        "C0_true_arx_expected": CounterfactualFactorConfig(
            "C0_true_arx_expected",
            "perfect_evaluation_only_labeled_k4",
            False,
            False,
            "not_applicable_perfect_belief",
            "not_applicable_perfect_belief",
            "shared_perfect_belief_base",
            "reference_configuration",
        ),
        "C1_true_arx_worst": CounterfactualFactorConfig(
            "C1_true_arx_worst",
            "perfect_evaluation_only_labeled_k4",
            True,
            False,
            "not_applicable_perfect_belief",
            "not_applicable_perfect_belief",
            "C0_true_arx_expected",
            "worst_mode_cost_false_to_true",
        ),
        "C2_perfect_belief_current_mpc": CounterfactualFactorConfig(
            "C2_perfect_belief_current_mpc",
            "perfect_evaluation_only_labeled_k4",
            True,
            True,
            "not_applicable_perfect_belief",
            "not_applicable_perfect_belief",
            "C1_true_arx_worst",
            "constraint_tightening_false_to_true",
        ),
        "C3_current_belief_expected": CounterfactualFactorConfig(
            "C3_current_belief_expected",
            "current_runtime_belief",
            False,
            True,
            "sticky_phase_a",
            "binary_phase_a",
            "P_old",
            "worst_mode_cost_true_to_false",
        ),
        "C4_gradual_authority": CounterfactualFactorConfig(
            "C4_gradual_authority",
            "current_runtime_belief",
            True,
            True,
            "sticky_phase_a",
            "continuous_entropy_scaled_ibr",
            "P_old",
            "binary_ood_fallback_to_continuous_ibr_authority",
        ),
        "C5_no_sticky_prior": CounterfactualFactorConfig(
            "C5_no_sticky_prior",
            "current_runtime_belief",
            True,
            True,
            "uniform_transition_prior",
            "binary_phase_a",
            "P_old",
            "sticky_transition_prior_to_uniform_transition_prior",
        ),
    }
)


@dataclass(frozen=True, slots=True)
class CounterfactualBuild:
    controller: object
    factors: CounterfactualFactorConfig
    evaluation_truth_required: bool


class _PerfectBeliefDiagnostic:
    """Replace only the belief/OOD decision of a real ARX diagnostic."""

    __slots__ = ("_inner", "_mode_to_component", "_true_mode")

    def __init__(
        self,
        inner: OnlineModeDiagnostic,
        mode_to_component_eval_only: Mapping[str, int],
    ) -> None:
        if not isinstance(inner, OnlineModeDiagnostic):
            raise TypeError("inner must be OnlineModeDiagnostic")
        mapping = {str(key): int(value) for key, value in mode_to_component_eval_only.items()}
        expected = set(range(int(inner.mode_belief.size)))
        if set(mapping.values()) != expected or len(mapping) != len(expected):
            raise ValueError("perfect-belief mapping must bijectively cover all components")
        self._inner = inner
        self._mode_to_component = MappingProxyType(mapping)
        self._true_mode: str | None = None

    def reset(self) -> None:
        self._inner.reset()
        self._true_mode = None

    def set_true_mode_eval_only(self, mode: str) -> None:
        key = str(mode).strip()
        if key not in self._mode_to_component:
            raise KeyError(f"no training-label ARX counterfactual for mode {key!r}")
        self._true_mode = key

    def step(self, measurement: Measurement) -> DiagnosticOutput:
        if self._true_mode is None:
            raise RuntimeError("perfect evaluator belief was not routed before diagnostic step")
        output = self._inner.step(measurement)
        component = self._mode_to_component[self._true_mode]
        belief = np.zeros(output.mode_belief.size, dtype=float)
        belief[component] = 1.0
        return replace(
            output,
            mode_belief=belief,
            map_mode=component,
            belief_entropy=0.0,
            raw_belief_entropy=0.0,
            ood_score=0.0,
            ood_pvalue=1.0,
            ood_active=False,
            diagnostic_state="KNOWN",
        )


class PerfectBeliefMPCOracle:
    """Evaluation-only C0/C1/C2 wrapper; intentionally has no ``act``."""

    __slots__ = ("_inner", "_diagnostic", "_last_measurement", "_last_mode", "_last_action")

    def __init__(
        self,
        inner_controller: SDBMPCController,
        diagnostic: _PerfectBeliefDiagnostic,
    ) -> None:
        self._inner = inner_controller
        self._diagnostic = diagnostic
        self._last_measurement: Measurement | None = None
        self._last_mode: str | None = None
        self._last_action: ControlAction | None = None

    @property
    def inner_controller(self) -> SDBMPCController:
        return self._inner

    def reset(self, initial_measurement: Measurement) -> None:
        self._inner.reset(initial_measurement)
        self._last_measurement = None
        self._last_mode = None
        self._last_action = None

    def act_evaluation_only(
        self,
        measurement: Measurement,
        *,
        true_mode_eval_only: str,
    ) -> ControlAction:
        mode = str(true_mode_eval_only).strip()
        if self._last_measurement is not None:
            if measurement.time_s < self._last_measurement.time_s:
                raise ValueError("perfect-belief measurement time regressed")
            if measurement.time_s == self._last_measurement.time_s:
                if measurement != self._last_measurement or mode != self._last_mode:
                    raise ValueError("perfect-belief timestamp reused with changed data")
                assert self._last_action is not None
                return self._last_action
        self._diagnostic.set_true_mode_eval_only(mode)
        action = self._inner.act(measurement)
        self._last_measurement = measurement
        self._last_mode = mode
        self._last_action = action
        return action


@dataclass(frozen=True, slots=True)
class GradualAuthorityConfig:
    suspect_min_ratio: float = 0.50
    ood_active_min_ratio: float = 0.20
    recovery_min_ratio: float = 0.50

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = float(getattr(self, name))
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must lie in [0, 1]")
            object.__setattr__(self, name, value)


class GradualAuthorityController:
    """C4: continue MPC and shrink IBR authority continuously under OOD."""

    __slots__ = ("_inner", "_config", "_bounds", "_sample_time_s", "_records")

    def __init__(
        self,
        inner_controller: SDBMPCController,
        *,
        config: GradualAuthorityConfig = GradualAuthorityConfig(),
    ) -> None:
        if not isinstance(inner_controller, SDBMPCController):
            raise TypeError("inner_controller must be SDBMPCController")
        self._inner = inner_controller
        self._config = config
        self._bounds = inner_controller.mpc_config.bounds
        self._sample_time_s = inner_controller.mpc_config.sample_time_s
        self._records: list[dict[str, Any]] = []

    @property
    def inner_controller(self) -> SDBMPCController:
        return self._inner

    @property
    def step_records(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(MappingProxyType(dict(record)) for record in self._records)

    def reset(self, initial_measurement: Measurement) -> None:
        self._inner.reset(initial_measurement)
        self._records.clear()

    def _authority(self, diagnostic_state: str, entropy: float) -> float:
        continuous = min(1.0, max(0.0, 1.0 - float(entropy)))
        floor = {
            "KNOWN": 1.0,
            "SUSPECT": self._config.suspect_min_ratio,
            "OOD_ACTIVE": self._config.ood_active_min_ratio,
            "RECOVERY": self._config.recovery_min_ratio,
        }.get(str(diagnostic_state), 1.0)
        return max(floor, continuous) if floor < 1.0 else 1.0

    def act(self, measurement: Measurement) -> ControlAction:
        raw_action = self._inner.act(measurement)
        raw_record = self._inner.step_records[-1].to_log_record()
        diagnostic_state = str(raw_record["diagnostic_state"])
        entropy = float(raw_record["belief_entropy"])
        authority = self._authority(diagnostic_state, entropy)
        # Solver/slack failures still use the common safety fallback.  The
        # audited factor is only the Phase-A binary OOD trigger.
        solver_failure_fallback = bool(raw_record.get("trigger_reasons")) and any(
            reason not in {"ood_active", "ood_recovery"}
            for reason in raw_record.get("trigger_reasons", [])
        )
        if solver_failure_fallback:
            action = raw_action
            authority = 0.0 if raw_action.u_ibr_pu == 0.0 else authority
        else:
            requested = authority * raw_action.u_ibr_pu
            u_ibr = clip_with_rate_limit(
                requested,
                measurement.u_ibr_prev_pu,
                self._bounds.u_min_pu[1],
                self._bounds.u_max_pu[1],
                self._bounds.ramp_pu_per_s[1],
                self._sample_time_s,
            )
            action = ControlAction(
                u_sg_pu=raw_action.u_sg_pu,
                u_ibr_pu=u_ibr,
                controller_state=(
                    "GRADUAL_IBR_AUTHORITY"
                    if authority < 1.0
                    else raw_action.controller_state
                ),
                solver_status=raw_action.solver_status,
                solve_time_s=raw_action.solve_time_s,
                max_freq_slack_hz=raw_action.max_freq_slack_hz,
            )
        record = dict(raw_record)
        record.update(
            {
                "controller_state": action.controller_state,
                "u_ibr_pu": action.u_ibr_pu,
                "raw_inner_u_ibr_pu": raw_action.u_ibr_pu,
                "ibr_authority_ratio": authority,
                "binary_ood_fallback_disabled": True,
            }
        )
        self._records.append(record)
        return action


def _perfect_belief_build(
    factory: FinalControllerFactory,
    *,
    method_id: str,
    mode_to_component_eval_only: Mapping[str, int],
) -> CounterfactualBuild:
    factors = COUNTERFACTUAL_FACTORS[method_id]
    # These private members are deliberately consumed only in this evaluation
    # module so the ordinary controller factory never gains label-bearing APIs.
    mpc_config = replace(
        factory._mpc_config,
        use_constraint_tightening=factors.constraint_tightening,
    )
    if not factors.worst_mode_cost:
        mpc_config = replace(
            mpc_config,
            weights=replace(
                mpc_config.weights,
                lambda_worst_base=0.0,
                lambda_worst_entropy=0.0,
            ),
        )
    diagnostic = _PerfectBeliefDiagnostic(
        factory._new_diagnostic(use_transition_prior=False),
        mode_to_component_eval_only,
    )
    controller = SDBMPCController(
        factory.grid_model,
        modes_from_library(factory.grid_model, factory.library, expected_component_count=None),
        diagnostic,
        mpc_config=mpc_config,
        controller_config=replace(factory._controller_config, enable_ood_fallback=True),
        estimator=factory._new_estimator(),
        fallback_config=factory._fallback_config,
    )
    return CounterfactualBuild(
        PerfectBeliefMPCOracle(controller, diagnostic),
        factors,
        True,
    )


def build_phase_b1_counterfactual(
    factory: FinalControllerFactory,
    method_id: str,
    *,
    mode_to_component_eval_only: Mapping[str, int] | None = None,
) -> CounterfactualBuild:
    """Build one C0--C5 controller with an explicit single-factor ledger."""

    if not isinstance(factory, FinalControllerFactory):
        raise TypeError("factory must be FinalControllerFactory")
    if method_id not in COUNTERFACTUAL_FACTORS:
        raise KeyError(f"unknown Phase-B1 counterfactual {method_id!r}")
    if method_id in {
        "C0_true_arx_expected",
        "C1_true_arx_worst",
        "C2_perfect_belief_current_mpc",
    }:
        if mode_to_component_eval_only is None:
            raise ValueError("perfect-belief counterfactual requires evaluator mapping")
        return _perfect_belief_build(
            factory,
            method_id=method_id,
            mode_to_component_eval_only=mode_to_component_eval_only,
        )
    if mode_to_component_eval_only is not None:
        raise ValueError("runtime counterfactuals must not receive evaluator mapping")
    if method_id == "C3_current_belief_expected":
        build = factory.build_proposed_or_ablation(
            SDBMPCVariantConfig.no_worst_mode()
        )
        controller: object = build.controller
    elif method_id == "C5_no_sticky_prior":
        build = factory.build_proposed_or_ablation(
            SDBMPCVariantConfig.no_transition_prior()
        )
        controller = build.controller
    else:
        build = factory.build_proposed_or_ablation(SDBMPCVariantConfig.no_ood())
        controller = GradualAuthorityController(build.controller)
    return CounterfactualBuild(
        controller,
        COUNTERFACTUAL_FACTORS[method_id],
        False,
    )


__all__ = [
    "COUNTERFACTUAL_FACTORS",
    "COUNTERFACTUAL_SCHEMA_VERSION",
    "CounterfactualBuild",
    "CounterfactualFactorConfig",
    "GradualAuthorityConfig",
    "GradualAuthorityController",
    "PerfectBeliefMPCOracle",
    "build_phase_b1_counterfactual",
]
