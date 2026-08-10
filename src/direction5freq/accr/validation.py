"""Shared locked A6 simulation policies and full nonlinear Plant-A episodes."""

from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd

from direction5freq.accr.accr_mpc import ActiveCapabilityCertificationRecourseMPC
from direction5freq.controllers.anti_windup_pi import (
    FixedAllocationAntiWindupPI,
    SGOnlyAntiWindupPI,
)
from direction5freq.controllers.dcsv_cr_mpc import DCSVContractRecourseMPC
from direction5freq.controllers.dcsv_mpc_final import DCSVInput
from direction5freq.controllers.domain_supervisor import DomainSupervisor
from direction5freq.controllers.voi_accr_mpc import (
    VOIActiveCapabilityCertificationRecourseMPC,
    weighted_contract_mpc_class,
)
from direction5freq.estimation.deliverability_set_membership import DeliverabilitySetMembership
from direction5freq.estimation.grid_load_mhe import ConstrainedGridLoadMHE
from direction5freq.estimation.grid_load_observer import LoadObserverInput
from direction5freq.models.capability_contract import (
    CapabilityContract,
    CapabilityRealization,
)
from direction5freq.models.plant_a_full import PlantAFull, PlantAParameters, PublicObservation


MPC_METHODS = (
    "contract_only_recourse_mpc",
    "passive_set_adaptive_mpc",
    "safe_persistent_excitation_mpc",
    "fixed_periodic_probe_mpc",
    "unsafe_no_gate_probe_mpc",
    "accr_mpc",
    "voi_accr_mpc",
    "perfect_capability_recourse_oracle",
)

# A6 must reuse the capability realizations that actually passed the A1
# perfect-information materiality Gate. Keeping these values beside the shared
# simulation policy avoids silently relabeling a non-material realization as
# an A1-positive design cell.
A1_MATERIALITY_CAPABILITY = {
    "power_drop": {"power_pu": 0.065, "ramp_pu_per_s": 0.025, "delay_s": 1.50},
    "ramp_drop": {"power_pu": 0.045, "ramp_pu_per_s": 0.055, "delay_s": 1.50},
    "delay_drop": {"power_pu": 0.065, "ramp_pu_per_s": 0.055, "delay_s": 1.50},
}


class VOIContractOnlyRollingAdapter:
    """The exact M1 rolling core used for the fair contract and Oracle arms."""

    def __init__(
        self,
        period_s: float,
        horizon_steps: int,
        parameters: PlantAParameters,
        controller_lock: dict[str, Any],
    ) -> None:
        weighted = weighted_contract_mpc_class(
            ace_weight=float(controller_lock["ace_weight"]),
            tie_weight=float(controller_lock["tie_weight"]),
            frequency_weight=float(controller_lock["frequency_weight"]),
            bess_effort_weight=float(controller_lock["bess_effort_weight"]),
            sg_effort_weight=float(controller_lock["sg_effort_weight"]),
        )
        self.core = weighted(period_s, horizon_steps, parameters)
        self.registered_contract = parameters.bess.contract

    def propose(self, inputs: DCSVInput):
        power = np.maximum(
            np.asarray(inputs.deliverability_set.performance_power_pu, dtype=float),
            np.asarray(self.registered_contract.upper_power_pu, dtype=float),
        )
        ramp = np.maximum(
            np.asarray(inputs.deliverability_set.performance_ramp_pu_per_s, dtype=float),
            np.asarray(self.registered_contract.ramp_up_pu_per_s, dtype=float),
        )
        is_contract = bool(
            np.allclose(power, self.registered_contract.upper_power_pu)
            and np.allclose(ramp, self.registered_contract.ramp_up_pu_per_s)
        )
        delay = (
            np.asarray(self.registered_contract.maximum_delay_s, dtype=float)
            if is_contract
            else np.asarray(inputs.deliverability_set.delay_interval_s[:, 1], dtype=float)
        )
        self.core.contract = CapabilityContract(
            lower_power_pu=tuple(-float(value) for value in power),
            upper_power_pu=tuple(float(value) for value in power),
            ramp_down_pu_per_s=tuple(float(value) for value in ramp),
            ramp_up_pu_per_s=tuple(float(value) for value in ramp),
            maximum_delay_s=tuple(float(value) for value in delay),
        )
        raw = self.core.propose(inputs)
        diagnostic_values = asdict(raw.diagnostics)
        diagnostic_values["attempted_optimization_calls"] = 2 if (
            raw.diagnostics.restoration_used or raw.diagnostics.fallback_used
        ) else 1
        raw = replace(raw, diagnostics=SimpleNamespace(**diagnostic_values))
        guaranteed = np.clip(
            raw.proposed_action_pu[[1, 3]],
            np.asarray(self.registered_contract.lower_power_pu),
            np.asarray(self.registered_contract.upper_power_pu),
        )
        fields = {name: getattr(raw, name) for name in raw.__dataclass_fields__}
        return SimpleNamespace(
            **fields,
            guaranteed_bess_command_pu=guaranteed,
            surplus_bess_command_pu=raw.proposed_action_pu[[1, 3]] - guaranteed,
            shared_current_action_verified=True,
            surplus_loss_branch_verified=False,
        )

    def commit(
        self,
        action: np.ndarray,
        actual: np.ndarray,
        guaranteed: np.ndarray | None = None,
    ) -> None:
        self.core.commit(action, actual)


def plant_parameters(tension: str, nominal_frequency_hz: float = 50.0) -> PlantAParameters:
    base = PlantAParameters(nominal_frequency_hz=nominal_frequency_hz)
    if tension == "low":
        return base
    if tension == "high":
        return replace(
            base,
            valve_upper_pu=(0.105, 0.105),
            sg_power_upper_pu=(0.090, 0.090),
            grc_up_pu_per_s=(0.009, 0.009),
        )
    raise ValueError(tension)


def capability_for(row: pd.Series, time_s: float) -> CapabilityRealization:
    if time_s < float(row.capability_change_time_s):
        return CapabilityRealization()
    if bool(row.get("contract_violation", False)):
        power = float(row.get("true_power_override_pu", 0.020))
        ramp = float(row.get("true_ramp_override_pu_per_s", 0.010))
        delay = float(row.get("true_delay_override_s", 2.0))
        return CapabilityRealization(
            lower_power_pu=(-power, -power), upper_power_pu=(power, power),
            ramp_down_pu_per_s=(ramp, ramp), ramp_up_pu_per_s=(ramp, ramp),
            delay_s=(delay, delay),
        )
    known = str(row.condition) == "known"
    if row.mechanism == "power_drop":
        registered = A1_MATERIALITY_CAPABILITY["power_drop"]
        power = float(registered["power_pu"]) if known else 0.055
        ramp = float(registered["ramp_pu_per_s"])
        delay = float(registered["delay_s"])
        return CapabilityRealization(
            lower_power_pu=(-power, -power), upper_power_pu=(power, power),
            ramp_down_pu_per_s=(ramp, ramp), ramp_up_pu_per_s=(ramp, ramp),
            delay_s=(delay, delay),
        )
    if row.mechanism == "ramp_drop":
        registered = A1_MATERIALITY_CAPABILITY["ramp_drop"]
        power = float(registered["power_pu"])
        ramp = float(registered["ramp_pu_per_s"]) if known else 0.032
        delay = float(registered["delay_s"])
        return CapabilityRealization(
            lower_power_pu=(-power, -power), upper_power_pu=(power, power),
            ramp_down_pu_per_s=(ramp, ramp), ramp_up_pu_per_s=(ramp, ramp),
            delay_s=(delay, delay),
        )
    if row.mechanism == "delay_drop":
        registered = A1_MATERIALITY_CAPABILITY["delay_drop"]
        power = float(registered["power_pu"])
        ramp = float(registered["ramp_pu_per_s"])
        delay = float(registered["delay_s"]) if known else 1.10
        return CapabilityRealization(
            lower_power_pu=(-power, -power), upper_power_pu=(power, power),
            ramp_down_pu_per_s=(ramp, ramp), ramp_up_pu_per_s=(ramp, ramp),
            delay_s=(delay, delay),
        )
    raise ValueError(row.mechanism)


def load_for(row: pd.Series, parameters: PlantAParameters, time_s: float) -> np.ndarray:
    if time_s < float(row.load_event_time_s):
        return np.zeros(2)
    magnitude = float(row.get("load_magnitude_pu", 0.62 * min(parameters.sg_power_upper_pu)))
    magnitude *= float(row.get("load_sign", 1.0))
    if row.load_area == "area0":
        return np.array((magnitude, 0.25 * magnitude))
    if row.load_area == "area1":
        return np.array((0.25 * magnitude, magnitude))
    return np.array((magnitude, 0.78 * magnitude))


class ValidationPolicy:
    """Causal policy adapter; only the explicitly labeled Oracle reads truth."""

    def __init__(
        self,
        method: str,
        period_s: float,
        parameters: PlantAParameters,
        lock: dict[str, Any],
        delivered_branch_weight: float,
        *,
        observation_dt_s: float,
    ) -> None:
        self.method = method
        self.period_s = float(period_s)
        self.parameters = parameters
        self.lock = lock
        self.last_command = np.zeros(4)
        self.reserve_request = np.zeros(2)
        self.last_result = None
        self.control_calls = 0
        self.attempted_calls = 0
        self.solver_failures = 0
        self.fallbacks = 0
        self.restorations = 0
        self.solve_times: list[float] = []
        self.probe_command_l1_pu_s = 0.0
        self.probe_active_calls = 0
        self.certified_surplus_l1_pu_s = 0.0
        self.full_rolling_all = True
        self.latest_deliverability = None
        self.observer = ConstrainedGridLoadMHE(
            nominal_frequency_hz=parameters.nominal_frequency_hz,
            inertia_s=parameters.inertia_s,
            damping_pu_per_pu_frequency=parameters.damping_pu_per_pu_frequency,
            derivative_filter=0.40,
            warmup_samples=8,
            window_samples=6,
        )
        self.supervisor = DomainSupervisor(parameters)
        self.estimator = DeliverabilitySetMembership(parameters.bess.contract, self.period_s)
        if method == "sg_only_anti_windup_pi":
            self.controller: Any = SGOnlyAntiWindupPI(period_s)
        elif method == "fixed_allocation_anti_windup_pi":
            self.controller = FixedAllocationAntiWindupPI(period_s)
        elif method == "accr_mpc":
            probe = lock["probe"]
            self.controller = ActiveCapabilityCertificationRecourseMPC(
                period_s,
                int(lock["horizon_steps"]),
                parameters,
                probe_amplitude_pu=float(probe["amplitude_pu"]),
                probe_sequence=tuple(probe["normalized_sequence"]),
                certificate_validity_s=float(probe["certificate_validity_s"]),
                active_filter_residual_bound_pu=float(probe["residual_bound_pu"]),
                physical_dt_s=float(observation_dt_s),
                probe_base_bess_pu=float(probe["base_bess_pu"]),
                probe_preload_s=float(probe["preload_s"]),
                trigger_minimum_total_sfr_pu=float(probe["trigger_minimum_total_sfr_pu"]),
                delivered_branch_weight=delivered_branch_weight,
            )
        elif method == "voi_accr_mpc":
            controller = lock["voi_controller"]
            probe = lock["voi_probe"]
            estimator = lock["voi_estimator"]
            self.controller = VOIActiveCapabilityCertificationRecourseMPC(
                period_s,
                int(controller["horizon_steps"]),
                parameters,
                probe_id=str(probe["id"]),
                probe_amplitude_pu=float(probe["amplitude_pu"]),
                probe_sequence=tuple(probe["normalized_sequence"]),
                certificate_validity_s=float(probe["certificate_validity_s"]),
                cooldown_s=float(probe["cooldown_s"]),
                voi_margin=float(controller["voi_margin"]),
                action_relevance_norm=float(controller["action_relevance_norm"]),
                minimum_oracle_gap=float(controller["minimum_oracle_gap"]),
                minimum_ace_for_probe=float(controller["minimum_ace_for_probe"]),
                estimator_window_s=float(estimator["window_s"]),
                active_filter_residual_bound_pu=float(estimator["active_residual_bound_pu"]),
                passive_renewal=bool(probe["passive_renewal"]),
                physical_dt_s=float(observation_dt_s),
                delivered_branch_weight=float(controller["delivered_branch_weight"]),
                ace_weight=float(controller["ace_weight"]),
                tie_weight=float(controller["tie_weight"]),
                frequency_weight=float(controller["frequency_weight"]),
                bess_effort_weight=float(controller["bess_effort_weight"]),
                sg_effort_weight=float(controller["sg_effort_weight"]),
                trigger_time_s=float(probe["trigger_time_s"]),
                certificate_confirmation_s=(
                    None
                    if probe.get("certificate_confirmation_s") is None
                    else float(probe["certificate_confirmation_s"])
                ),
                latch_abstention=bool(probe["latch_abstention"]),
                require_detected_change_for_probe=bool(
                    probe.get("require_detected_change_for_probe", False)
                ),
                minimum_partition_reduction=float(
                    probe.get("minimum_partition_reduction", 0.25)
                ),
                certificate_power_guard_pu=float(
                    probe.get("certificate_power_guard_pu", 0.0)
                ),
                certificate_ramp_guard_pu_per_s=float(
                    probe.get("certificate_ramp_guard_pu_per_s", 0.0)
                ),
                certificate_delay_guard_s=float(
                    probe.get("certificate_delay_guard_s", 0.0)
                ),
                probe_prediction_dt_s=float(
                    probe.get("probe_prediction_dt_s", observation_dt_s)
                ),
            )
        elif (
            method in {"contract_only_recourse_mpc", "perfect_capability_recourse_oracle"}
            and "voi_controller" in lock
        ):
            self.controller = VOIContractOnlyRollingAdapter(
                period_s,
                int(lock["voi_controller"]["horizon_steps"]),
                parameters,
                lock["voi_controller"],
            )
        elif method in MPC_METHODS:
            self.controller = DCSVContractRecourseMPC(
                period_s,
                int(lock["horizon_steps"]),
                parameters,
                delivered_branch_weight=delivered_branch_weight,
            )
        else:
            raise ValueError(method)

    @property
    def is_mpc(self) -> bool:
        return self.method in MPC_METHODS

    def observe(self, observation: PublicObservation) -> None:
        if self.method in {"accr_mpc", "voi_accr_mpc"}:
            self.controller.observe(observation)

    def _probe_overlay(self, action: np.ndarray, observation: PublicObservation, domain: str) -> tuple[np.ndarray, float]:
        q = 0.0
        index = self.control_calls
        if self.method == "safe_persistent_excitation_mpc":
            eligible = bool(
                observation.time_s >= 60.0
                and domain == "SUSTAINABLE"
                and np.all((observation.measured_soc >= 0.25) & (observation.measured_soc <= 0.75))
            )
            if eligible:
                q = 0.00125 * (1.0 if index % 2 == 0 else -1.0)
        elif self.method in {"fixed_periodic_probe_mpc", "unsafe_no_gate_probe_mpc"}:
            amplitude = 0.0025 if self.method == "fixed_periodic_probe_mpc" else 0.015
            sequence = np.asarray((0.5, 1.0, 0.0, -1.0, -0.5)) * amplitude
            if observation.time_s >= 60.0:
                cycle = index % 30
                if cycle < len(sequence):
                    q = float(sequence[cycle])
        if q != 0.0:
            action = action.copy()
            action[0] -= q
            action[1] += q
            self.probe_active_calls += 1
            self.probe_command_l1_pu_s += 2.0 * abs(q) * self.period_s
        return action, q

    def propose(
        self,
        observation: PublicObservation,
        evaluation_truth: CapabilityRealization | None = None,
    ) -> np.ndarray:
        estimate = self.observer.update(LoadObserverInput(
            observation.time_s,
            observation.frequency_deviation_hz,
            observation.tie_line_pu,
            observation.sg_mechanical_power_pu,
            observation.bess_actual_power_pu,
            observation.slow_reserve_power_pu,
        ))
        domain = self.supervisor.classify(estimate.load_pu, observation.measured_soc)
        self.control_calls += 1
        if not self.is_mpc:
            action = self.controller.propose(observation)
            self.reserve_request = domain.equilibrium_slow_reserve_pu.copy()
            self.last_command = action.copy()
            return action

        requested = (
            -self.parameters.bess.pfr_gain_pu_power_per_pu_frequency
            * observation.frequency_deviation_hz / self.parameters.nominal_frequency_hz
            + self.last_command[[1, 3]]
        )
        snapshot = self.estimator.update(
            observation.time_s, requested, observation.bess_actual_power_pu
        )
        if self.method == "contract_only_recourse_mpc":
            snapshot = replace(
                snapshot,
                performance_power_pu=np.asarray(self.parameters.bess.contract.upper_power_pu),
                performance_ramp_pu_per_s=np.asarray(self.parameters.bess.contract.ramp_up_pu_per_s),
            )
        elif self.method == "perfect_capability_recourse_oracle":
            if evaluation_truth is None:
                raise RuntimeError("evaluation truth is required only by the labeled Oracle")
            snapshot = replace(
                snapshot,
                performance_power_pu=np.asarray(evaluation_truth.upper_power_pu),
                performance_ramp_pu_per_s=np.asarray(evaluation_truth.ramp_up_pu_per_s),
                delay_interval_s=np.c_[np.zeros(2), np.asarray(evaluation_truth.delay_s)],
            )
        self.latest_deliverability = snapshot
        inputs = DCSVInput(observation, estimate.load_pu, snapshot, domain)
        if self.method in {"accr_mpc", "voi_accr_mpc"}:
            result = self.controller.propose(inputs)
            action = result.proposed_action_pu.copy()
            core = result.core_result
            self.probe_active_calls += int(result.diagnostics.probe_active)
            self.probe_command_l1_pu_s += float(np.sum(np.abs(result.probe_component_pu))) * self.period_s
            self.certified_surplus_l1_pu_s += float(np.sum(np.abs(result.certified_component_pu))) * self.period_s
        else:
            result = self.controller.propose(inputs)
            core = result
            action, _ = self._probe_overlay(result.proposed_action_pu.copy(), observation, domain.domain)
            self.certified_surplus_l1_pu_s += float(np.sum(np.abs(result.surplus_bess_command_pu))) * self.period_s
        self.reserve_request = core.slow_reserve_request_pu.copy()
        diagnostics = core.diagnostics
        self.attempted_calls += int(diagnostics.attempted_optimization_calls)
        self.solver_failures += int(
            diagnostics.mathematical_infeasibility or diagnostics.numerical_failure
        )
        self.fallbacks += int(diagnostics.fallback_used)
        self.restorations += int(diagnostics.restoration_used)
        self.solve_times.append(float(diagnostics.solve_time_s))
        self.full_rolling_all &= bool(
            core.predicted_state_sequence.shape[-1] == int(self.lock["horizon_steps"]) + 1
            and core.predicted_input_sequence.shape[-1] == int(self.lock["horizon_steps"])
            and core.predicted_energy_sequence_mwh.shape[-1] == int(self.lock["horizon_steps"]) + 1
        )
        self.last_result = result
        self.last_command = action.copy()
        return action

    def cycle_diagnostics(self) -> dict[str, Any]:
        """Return only causal state available at the completed control cycle."""
        result = self.last_result
        snapshot = self.latest_deliverability
        certificate = getattr(result, "certificate", None)
        diagnostics = getattr(result, "diagnostics", None)
        contract = getattr(result, "contract_component_pu", np.zeros(4))
        certified = getattr(result, "certified_component_pu", np.zeros(4))
        probe = getattr(result, "probe_component_pu", np.zeros(4))
        decision = getattr(self.controller, "last_decision", None)
        return {
            "probe_active": bool(getattr(diagnostics, "probe_active", False)),
            "probe_triggered": bool(getattr(diagnostics, "probe_triggered", False)),
            "certificate_valid": bool(getattr(diagnostics, "certificate_valid", False)),
            "certificate_revoked": bool(getattr(diagnostics, "certificate_revoked", False)),
            "certificate_retained_model_count": int(getattr(certificate, "retained_model_count", 0)),
            "certificate_expiry_time_s": float(getattr(certificate, "expiry_time_s", np.nan)),
            "certificate_power0_pu": float(certificate.power_lower_pu[0]) if certificate is not None else np.nan,
            "certificate_power1_pu": float(certificate.power_lower_pu[1]) if certificate is not None else np.nan,
            "certificate_ramp0_pu_per_s": float(certificate.ramp_lower_pu_per_s[0]) if certificate is not None else np.nan,
            "certificate_ramp1_pu_per_s": float(certificate.ramp_lower_pu_per_s[1]) if certificate is not None else np.nan,
            "certificate_delay0_s": float(certificate.maximum_delay_s[0]) if certificate is not None else np.nan,
            "certificate_delay1_s": float(certificate.maximum_delay_s[1]) if certificate is not None else np.nan,
            "performance_power0_pu": float(snapshot.performance_power_pu[0]) if snapshot is not None else np.nan,
            "performance_power1_pu": float(snapshot.performance_power_pu[1]) if snapshot is not None else np.nan,
            "performance_ramp0_pu_per_s": float(snapshot.performance_ramp_pu_per_s[0]) if snapshot is not None else np.nan,
            "performance_ramp1_pu_per_s": float(snapshot.performance_ramp_pu_per_s[1]) if snapshot is not None else np.nan,
            "feasible_delay_count0": int(np.sum(snapshot.feasible_delay_mask[0])) if snapshot is not None else 0,
            "feasible_delay_count1": int(np.sum(snapshot.feasible_delay_mask[1])) if snapshot is not None else 0,
            "contract_component_l1_pu": float(np.sum(np.abs(contract))),
            "certified_component_l1_pu": float(np.sum(np.abs(certified))),
            "probe_component_l1_pu": float(np.sum(np.abs(probe))),
            "voi_worthwhile": bool(getattr(decision, "worthwhile", False)),
            "voi_decision_relevance_pu": float(getattr(decision, "decision_relevance_pu", 0.0)),
            "voi_oracle_gap_proxy": float(getattr(decision, "oracle_gap_proxy", 0.0)),
            "voi_gross_value": float(getattr(decision, "gross_value", 0.0)),
            "voi_predicted_probe_cost": float(getattr(decision, "predicted_probe_cost", 0.0)),
            "voi_net_value": float(getattr(decision, "net_value", 0.0)),
            "voi_reason": str(getattr(decision, "reason", "NOT_APPLICABLE")),
        }

    def commit(self, actual_bess_pu: np.ndarray) -> None:
        if self.last_result is None or not self.is_mpc:
            return
        if self.method in {"accr_mpc", "voi_accr_mpc"}:
            self.controller.commit(self.last_result, actual_bess_pu)
        else:
            guaranteed = np.clip(
                self.last_command[[1, 3]],
                np.asarray(self.parameters.bess.contract.lower_power_pu),
                np.asarray(self.parameters.bess.contract.upper_power_pu),
            )
            self.controller.commit(self.last_command, actual_bess_pu, guaranteed)
        self.last_result = None

    def diagnostics(self) -> dict[str, Any]:
        certificate_issues = int(getattr(self.controller, "certificate_issues", 0))
        certificate_revocations = int(getattr(self.controller, "certificate_revocations", 0))
        reductions = list(getattr(self.controller, "candidate_diameter_reductions", []))
        return {
            "controller_calls": self.control_calls,
            "attempted_optimization_calls": self.attempted_calls,
            "solver_failure_calls": self.solver_failures,
            "fallback_calls": self.fallbacks,
            "restoration_calls": self.restorations,
            "p99_solve_time_s": float(np.quantile(self.solve_times, 0.99)) if self.solve_times else 0.0,
            "full_rolling": bool(self.full_rolling_all if self.is_mpc else False),
            "certificate_issues": certificate_issues,
            "certificate_revocations": certificate_revocations,
            "probe_active_calls": self.probe_active_calls,
            "probe_command_l1_pu_s": self.probe_command_l1_pu_s,
            "certified_surplus_l1_pu_s": self.certified_surplus_l1_pu_s,
            "ordinary_controller_truth_read": False,
            "evaluation_only_truth_read": self.method == "perfect_capability_recourse_oracle",
            "voi_decision_calls": int(getattr(self.controller, "decision_calls", 0)),
            "voi_worthwhile_calls": int(getattr(self.controller, "worthwhile_calls", 0)),
            "voi_abstention_calls": int(getattr(self.controller, "abstention_calls", 0)),
            "voi_probe_triggers": int(getattr(self.controller, "probe_triggers", 0)),
            "candidate_diameter_reduction_mean": float(np.mean(reductions)) if reductions else 0.0,
            "candidate_diameter_reduction_max": float(np.max(reductions)) if reductions else 0.0,
            "passive_certificate_renewals": int(getattr(self.controller, "passive_renewals", 0)),
            "maximum_unmetered_responsibility_jump_pu": float(
                getattr(self.controller, "maximum_unmetered_responsibility_jump_pu", 0.0)
            ),
            "probe_aborts_on_change": int(getattr(self.controller, "probe_aborts_on_change", 0)),
        }


def simulate_plant_a_episode(
    row_dict: dict[str, Any],
    method: str,
    lock: dict[str, Any],
    delivered_branch_weight: float,
    *,
    normal_profile: np.ndarray | None = None,
    cycle_output_path: Path | None = None,
) -> dict[str, Any]:
    row = pd.Series(row_dict)
    dt_s = float(lock["physical_dt_s"])
    parameters = plant_parameters(str(row.sg_tension))
    plant = PlantAFull(parameters, dt_s=dt_s)
    state = plant.equilibrium((float(row.initial_soc), float(row.initial_soc)))
    policy = ValidationPolicy(
        method, float(row.period_s), parameters, lock, delivered_branch_weight,
        observation_dt_s=dt_s,
    )
    command = np.zeros(4)
    next_control_s = 0.0
    pending_commit = False
    frequency_peak = 0.0
    ace_iae = 0.0
    tie_iae = 0.0
    sg_mileage = 0.0
    bess_energy = 0.0
    hard_violation = False
    command_violation = False
    terminal_frequency: list[float] = []
    terminal_ace: list[float] = []
    previous_mechanical = state.mechanical_power_pu.copy()
    cycle_rows: list[dict[str, Any]] = []
    duration_s = float(row.duration_s)
    steps = int(round(duration_s / dt_s))

    def actual_load(time_s: float) -> np.ndarray:
        if normal_profile is None:
            return load_for(row, parameters, time_s)
        position = min(max(time_s, 0.0), duration_s)
        lower = min(int(np.floor(position)), len(normal_profile) - 1)
        upper = min(lower + 1, len(normal_profile) - 1)
        fraction = position - np.floor(position)
        return (1.0 - fraction) * normal_profile[lower] + fraction * normal_profile[upper]

    for step in range(steps + 1):
        time_s = step * dt_s
        public = plant.public_observation(time_s, state, command)
        policy.observe(public)
        if pending_commit:
            policy.commit(public.bess_actual_power_pu)
            pending_commit = False
        if time_s + 1e-10 >= next_control_s:
            truth = capability_for(row, time_s) if method == "perfect_capability_recourse_oracle" else None
            command = policy.propose(public, truth)
            command_violation |= bool(
                np.any(command[[0, 2]] < np.asarray(parameters.valve_lower_pu) - 1e-8)
                or np.any(command[[0, 2]] > np.asarray(parameters.valve_upper_pu) + 1e-8)
                or np.any(np.abs(command[[1, 3]]) > parameters.bess.rating_pu + 1e-8)
            )
            pending_commit = policy.is_mpc
            cycle_rows.append({
                "scenario_id": row.scenario_id, "method": method, "plant": row.plant,
                "time_s": time_s,
                "frequency0_hz": public.frequency_deviation_hz[0],
                "frequency1_hz": public.frequency_deviation_hz[1],
                "ace0_pu": public.ace_pu[0], "ace1_pu": public.ace_pu[1],
                "tie_pu": public.tie_line_pu,
                "command_sg0_pu": command[0], "command_bess0_pu": command[1],
                "command_sg1_pu": command[2], "command_bess1_pu": command[3],
                "actual_bess0_pu": public.bess_actual_power_pu[0],
                "actual_bess1_pu": public.bess_actual_power_pu[1],
                "soc0": public.measured_soc[0], "soc1": public.measured_soc[1],
                "certificate_issues_to_date": int(getattr(policy.controller, "certificate_issues", 0)),
                **policy.cycle_diagnostics(),
            })
            next_control_s += float(row.period_s)
        frequency_peak = max(frequency_peak, float(np.max(np.abs(public.frequency_deviation_hz))))
        ace_iae += float(np.sum(np.abs(public.ace_pu))) * dt_s
        tie_iae += abs(float(public.tie_line_pu)) * dt_s
        if time_s >= duration_s - 30.0:
            terminal_frequency.append(float(np.max(np.abs(public.frequency_deviation_hz))))
            terminal_ace.append(float(np.max(np.abs(public.ace_pu))))
        if step < steps:
            truth = CapabilityRealization() if normal_profile is not None else capability_for(row, time_s)
            state, _ = plant.step(state, command, actual_load(time_s), truth, policy.reserve_request)
            sg_mileage += float(np.sum(np.abs(state.mechanical_power_pu - previous_mechanical)))
            previous_mechanical = state.mechanical_power_pu.copy()
            bess_energy += float(np.sum(np.abs(state.bess.power_pu))) * dt_s
            soc = state.bess.measured_soc(parameters.bess)
            hard_violation |= bool(
                np.any(soc < parameters.bess.soc_min - 1e-9)
                or np.any(soc > parameters.bess.soc_max + 1e-9)
                or np.any(state.mechanical_power_pu < np.asarray(parameters.sg_power_lower_pu) - 1e-9)
                or np.any(state.mechanical_power_pu > np.asarray(parameters.sg_power_upper_pu) + 1e-9)
            )
    if pending_commit:
        policy.commit(state.bess.power_pu)
    terminal_recovery = bool(
        max(terminal_frequency, default=np.inf) <= 0.12
        and max(terminal_ace, default=np.inf) <= 0.06
    )
    summary = dict(row_dict)
    summary.update({
        "method": method,
        "physical_success": bool(not hard_violation and not command_violation and frequency_peak <= 1.0 and terminal_recovery),
        "frequency_peak_hz": frequency_peak,
        "ace_iae_pu_s": ace_iae,
        "tie_iae_pu_s": tie_iae,
        "sg_mechanical_mileage_pu": sg_mileage,
        "bess_energy_throughput_pu_s": bess_energy,
        "terminal_recovery": terminal_recovery,
        "hard_violation": hard_violation,
        "command_violation": command_violation,
        "normal1h": normal_profile is not None,
        **policy.diagnostics(),
    })
    if cycle_output_path is not None:
        cycle_output_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(cycle_rows).to_parquet(cycle_output_path, index=False, compression="zstd")
    return summary


__all__ = [
    "MPC_METHODS", "ValidationPolicy", "capability_for", "load_for",
    "plant_parameters", "simulate_plant_a_episode",
]
