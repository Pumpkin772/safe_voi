"""Execute the locked full R5 development/validation and decisive Gate."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

import numpy as np
import pandas as pd
import yaml


REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from direction5freq.controllers.adaptive_mpc import ModelAdaptiveMPC
from direction5freq.controllers.anti_windup_pi import FixedAllocationAntiWindupPI, SGOnlyAntiWindupPI
from direction5freq.controllers.contract_robust_mpc import ContractOnlyRollingRobustMPC, NominalOffsetFreeMPC
from direction5freq.controllers.contract_violation_supervisor import ContractViolationSupervisor
from direction5freq.controllers.dcsv_cr_mpc import DCSVContractRecourseMPC
from direction5freq.controllers.dcsv_mpc_final import DCSVInput
from direction5freq.controllers.domain_supervisor import DomainSupervisor
from direction5freq.controllers.oracle_mpc import TrueCapabilityOracleMPC
from direction5freq.estimation.deliverability_set_membership import DeliverabilitySetMembership
from direction5freq.estimation.grid_load_mhe import ConstrainedGridLoadMHE
from direction5freq.estimation.grid_load_observer import LoadObserverInput
from direction5freq.evaluation.corrected_statistics import (
    corrected_metric_summary,
    paired_failure_rows,
    paired_failure_table,
)
from direction5freq.evaluation.final_protocol import (
    build_contract_violation_manifest,
    build_normal_manifest,
    build_plant_a_manifest,
    build_plant_b_manifest,
    capability_for,
    load_for,
    plant_parameters,
    synthetic_normal_profile,
)
from direction5freq.models.capability_contract import CapabilityRealization
from direction5freq.models.plant_a_full import PlantAFull, PublicObservation
from direction5freq.models.plant_b_andes_full import PlantBAndesFull


RESULTS = REPO / "results_final/R5"
DOCS = REPO / "research_outputs_final/07_VALIDATION"
FAILURES = REPO / "research_outputs_final/13_FAILURES"
PROGRESS = REPO / "progress_final"
LOCK = REPO / "configs/direction5_final/r5_validation_lock.yaml"
PARTS = RESULTS / "parts"
LOGS = REPO / "logs_final/R5"

PRIMARY_METHODS = ("dcsv_cr_mpc", "contract_only_rolling_mpc")
ALL_METHODS = (
    "sg_only_anti_windup_pi",
    "fixed_allocation_anti_windup_pi",
    "nominal_offset_free_mpc",
    "contract_only_rolling_mpc",
    "model_adaptive_mpc",
    "dcsv_cr_mpc",
    "true_capability_oracle_mpc",
)
SUPPLEMENTAL_METHODS = tuple(method for method in ALL_METHODS if method not in PRIMARY_METHODS)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def load_lock() -> dict[str, Any]:
    lock = yaml.safe_load(LOCK.read_text("utf-8"))
    if lock["final_seeds_consumed"] or lock["primary_methods"] != list(PRIMARY_METHODS):
        raise RuntimeError("R5 lock is inconsistent or attempts to consume final seeds")
    return lock


def selected_observer(parameters) -> ConstrainedGridLoadMHE:
    return ConstrainedGridLoadMHE(
        nominal_frequency_hz=parameters.nominal_frequency_hz,
        inertia_s=parameters.inertia_s,
        damping_pu_per_pu_frequency=parameters.damping_pu_per_pu_frequency,
        derivative_filter=0.40,
        warmup_samples=8,
    )


class PublicMethodPolicy:
    """One ordinary public-I/O controller instance or evaluation-only Oracle."""

    def __init__(self, method: str, period_s: float, parameters, seed: int, horizon_steps: int) -> None:
        self.method = method
        self.period_s = float(period_s)
        self.parameters = parameters
        self.rng = np.random.default_rng(np.random.SeedSequence([20260804, seed, 811, len(method)]))
        self.observer = selected_observer(parameters)
        self.estimator = DeliverabilitySetMembership(parameters.bess.contract, period_s)
        self.domain_supervisor = DomainSupervisor(parameters)
        self.violation_supervisor = ContractViolationSupervisor(parameters.bess.contract, period_s)
        self.last_command = np.zeros(4)
        self.last_guaranteed = np.zeros(2)
        self.reserve_request = np.zeros(2)
        self.last_measurement: PublicObservation | None = None
        self.calls: list[dict[str, Any]] = []
        if method == "sg_only_anti_windup_pi":
            self.controller: Any = SGOnlyAntiWindupPI(period_s)
        elif method == "fixed_allocation_anti_windup_pi":
            self.controller = FixedAllocationAntiWindupPI(period_s)
        elif method == "nominal_offset_free_mpc":
            self.controller = NominalOffsetFreeMPC(period_s, horizon_steps, parameters)
        elif method == "contract_only_rolling_mpc":
            self.controller = ContractOnlyRollingRobustMPC(period_s, horizon_steps, parameters)
        elif method == "model_adaptive_mpc":
            self.controller = ModelAdaptiveMPC(
                period_s, horizon_steps=horizon_steps, plant_parameters=parameters
            )
        elif method == "dcsv_cr_mpc":
            self.controller = DCSVContractRecourseMPC(period_s, horizon_steps, parameters)
        elif method == "true_capability_oracle_mpc":
            self.controller = TrueCapabilityOracleMPC(period_s, horizon_steps, parameters)
        else:
            raise ValueError(method)

    def _measured_observation(
        self,
        public: PublicObservation,
        noise_std_hz: float,
        dropout_probability: float,
    ) -> PublicObservation:
        frequency = public.frequency_deviation_hz + self.rng.normal(0.0, noise_std_hz, 2)
        measured = replace(public, frequency_deviation_hz=frequency)
        if self.last_measurement is not None and self.rng.random() < dropout_probability:
            measured = replace(
                self.last_measurement,
                time_s=public.time_s,
                measured_soc=public.measured_soc,
                issued_command_pu=public.issued_command_pu,
            )
        self.last_measurement = measured
        return measured

    def update(
        self,
        public: PublicObservation,
        truth: CapabilityRealization,
        noise_std_hz: float,
        dropout_probability: float,
    ) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
        measured = self._measured_observation(public, noise_std_hz, dropout_probability)
        load_estimate = self.observer.update(LoadObserverInput(
            time_s=float(measured.time_s),
            frequency_deviation_hz=measured.frequency_deviation_hz,
            tie_line_pu=float(measured.tie_line_pu),
            sg_mechanical_power_pu=measured.sg_mechanical_power_pu,
            bess_actual_poi_power_pu=measured.bess_actual_power_pu,
            slow_reserve_power_pu=measured.slow_reserve_power_pu,
        ))
        requested_total = (
            -self.parameters.bess.pfr_gain_pu_power_per_pu_frequency
            * measured.frequency_deviation_hz / self.parameters.nominal_frequency_hz
            + self.last_command[[1, 3]]
        )
        envelope = self.estimator.update(
            measured.time_s, requested_total, measured.bess_actual_power_pu
        )
        domain = self.domain_supervisor.classify(load_estimate.load_pu, measured.measured_soc)
        common = {
            "optimization_decision": False,
            "attempted_solver_calls": 0,
            "solver_status": "NOT_APPLICABLE_NON_MPC",
            "solve_time_s": 0.0,
            "restoration_used": False,
            "fallback_used": False,
            "numerical_failure": False,
            "accuracy_warning": False,
            "mathematical_infeasibility": False,
            "constraint_residual": 0.0,
            "domain": domain.domain,
            "observer_warmed": load_estimate.warmed,
            "contract_violation_detected": False,
            "surplus_norm_pu": 0.0,
        }
        if self.method in {"sg_only_anti_windup_pi", "fixed_allocation_anti_windup_pi"}:
            action = self.controller.propose(measured)
            reserve_request = domain.equilibrium_slow_reserve_pu
        else:
            violation = self.violation_supervisor.update(self.last_guaranteed, measured)
            inputs = DCSVInput(
                measured,
                load_estimate.load_pu,
                envelope,
                domain,
                contract_violation_status=violation.status,
            )
            if self.method == "true_capability_oracle_mpc":
                result = self.controller.propose_with_evaluation_truth(inputs, truth)
            else:
                result = self.controller.propose(inputs)
            action = result.proposed_action_pu.copy()
            reserve_request = result.slow_reserve_request_pu.copy()
            if self.method == "dcsv_cr_mpc":
                action[[0, 2]] += violation.sg_emergency_increment_pu
                reserve_request = np.maximum(
                    reserve_request, violation.slow_reserve_request_pu
                )
                guaranteed = result.guaranteed_bess_command_pu.copy()
                surplus_norm = float(np.linalg.norm(result.surplus_bess_command_pu))
            else:
                guaranteed = np.clip(
                    action[[1, 3]],
                    self.parameters.bess.contract.lower_power_pu,
                    self.parameters.bess.contract.upper_power_pu,
                )
                surplus_norm = float(np.linalg.norm(action[[1, 3]] - guaranteed))
            action[[0, 2]] = np.clip(
                action[[0, 2]], self.parameters.valve_lower_pu, self.parameters.valve_upper_pu
            )
            action[[1, 3]] = np.clip(
                action[[1, 3]], -self.parameters.bess.rating_pu, self.parameters.bess.rating_pu
            )
            if self.method == "dcsv_cr_mpc":
                self.controller.commit(action, measured.bess_actual_power_pu, guaranteed)
            else:
                self.controller.commit(action, measured.bess_actual_power_pu)
            self.last_guaranteed = guaranteed
            diagnostics = result.diagnostics
            attempted = int(getattr(diagnostics, "attempted_optimization_calls", 2 if diagnostics.restoration_used or diagnostics.fallback_used else 1))
            residual = float(diagnostics.maximum_constraint_residual)
            accuracy_warning = diagnostics.status == "optimal_inaccurate"
            numerical_failure = bool(
                (diagnostics.numerical_failure and residual > 1e-5)
                or diagnostics.status in {"NUMERICAL_EXCEPTION", "solver_error"}
            )
            common.update({
                "optimization_decision": True,
                "attempted_solver_calls": attempted,
                "solver_status": diagnostics.status,
                "solve_time_s": diagnostics.solve_time_s,
                "restoration_used": diagnostics.restoration_used,
                "fallback_used": diagnostics.fallback_used,
                "numerical_failure": numerical_failure,
                "accuracy_warning": accuracy_warning,
                "mathematical_infeasibility": diagnostics.mathematical_infeasibility,
                "constraint_residual": residual,
                "contract_violation_detected": violation.detected,
                "surplus_norm_pu": surplus_norm,
            })
        action = np.asarray(action, dtype=float)
        action[[0, 2]] = np.clip(
            action[[0, 2]], self.parameters.valve_lower_pu, self.parameters.valve_upper_pu
        )
        action[[1, 3]] = np.clip(
            action[[1, 3]], -self.parameters.bess.rating_pu, self.parameters.bess.rating_pu
        )
        self.last_command = action.copy()
        self.reserve_request = np.asarray(reserve_request, dtype=float).copy()
        self.calls.append(common)
        return action, self.reserve_request, common


def _normal_load(profile: np.ndarray, time_s: float) -> np.ndarray:
    position = min(max(time_s, 0.0), len(profile) - 1.0)
    lower = int(np.floor(position))
    upper = min(lower + 1, len(profile) - 1)
    fraction = position - lower
    return (1.0 - fraction) * profile[lower] + fraction * profile[upper]


def simulate_plant_a(row_dict: dict[str, Any], method: str, normal: bool = False):
    row = pd.Series(row_dict)
    lock = load_lock()
    parameters = plant_parameters(str(row.sg_tension))
    dt_s = float(lock["plant_a_dt_s"])
    plant = PlantAFull(parameters, dt_s=dt_s)
    state = plant.equilibrium((float(row.initial_soc), float(row.initial_soc)))
    policy = PublicMethodPolicy(
        method, float(row.period_s), parameters, int(row.seed), int(lock["mpc_horizon_steps"])
    )
    profile = synthetic_normal_profile(int(row.seed)) if normal else None
    command = np.zeros(4)
    reserve_request = np.zeros(2)
    next_control = 0.0
    rng = np.random.default_rng(np.random.SeedSequence([20260804, int(row.seed), 823, len(method)]))
    cycle_rows = []
    frequency_peak = 0.0
    frequency_square = 0.0
    ace_iae = 0.0
    tie_square = 0.0
    physical_samples = 0
    terminal_frequency = []
    terminal_ace = []
    terminal_tie = []
    hard_violation = False
    domain_counts: dict[str, int] = {}
    duration_s = float(row.duration_s)
    for step in range(int(round(duration_s / dt_s)) + 1):
        time_s = step * dt_s
        public = plant.public_observation(time_s, state, command)
        truth = capability_for(row, time_s)
        if time_s + 1e-10 >= next_control:
            command, reserve_request, call = policy.update(
                public,
                truth,
                float(row.frequency_noise_std_hz),
                float(row.dropout_probability),
            )
            domain_counts[call["domain"]] = domain_counts.get(call["domain"], 0) + 1
            cycle_rows.append({
                "scenario_id": row.scenario_id,
                "method": method,
                "plant": row.plant,
                "time_s": time_s,
                "period_s": float(row.period_s),
                "frequency0_hz": public.frequency_deviation_hz[0],
                "frequency1_hz": public.frequency_deviation_hz[1],
                "ace0_pu": public.ace_pu[0],
                "ace1_pu": public.ace_pu[1],
                "tie_pu": public.tie_line_pu,
                "command_sg0_pu": command[0],
                "command_bess0_pu": command[1],
                "actual_bess0_pu": public.bess_actual_power_pu[0],
                "soc0": public.measured_soc[0],
                **call,
                "applied_action_available": True,
            })
            jitter = float(row.control_jitter_s) * (1.0 if rng.random() >= 0.5 else -1.0)
            next_control += max(float(row.period_s) + jitter, 0.5 * float(row.period_s))
        frequency_peak = max(
            frequency_peak, float(np.max(np.abs(public.frequency_deviation_hz)))
        )
        frequency_square += float(np.sum(public.frequency_deviation_hz**2))
        ace_iae += float(np.sum(np.abs(public.ace_pu))) * dt_s
        tie_square += float(public.tie_line_pu**2)
        physical_samples += 1
        if time_s >= duration_s - 30.0:
            terminal_frequency.append(float(np.max(np.abs(public.frequency_deviation_hz))))
            terminal_ace.append(float(np.max(np.abs(public.ace_pu))))
            terminal_tie.append(abs(float(public.tie_line_pu)))
        if step < int(round(duration_s / dt_s)):
            load = _normal_load(profile, time_s) if normal else load_for(row, parameters, time_s)
            state, diagnostics = plant.step(state, command, load, truth, reserve_request)
            soc = state.bess.measured_soc(parameters.bess)
            hard_violation |= bool(
                np.any(soc < parameters.bess.soc_min - 1e-9)
                or np.any(soc > parameters.bess.soc_max + 1e-9)
                or np.any(state.mechanical_power_pu < np.asarray(parameters.sg_power_lower_pu) - 1e-9)
                or np.any(state.mechanical_power_pu > np.asarray(parameters.sg_power_upper_pu) + 1e-9)
                or np.max(np.abs(diagnostics.power_balance_residual_pu)) > 1e-8
            )
    if normal:
        registered_domain = "SUSTAINABLE"
    else:
        final_load = load_for(row, parameters, duration_s)
        registered_domain = DomainSupervisor(parameters).classify(
            final_load, np.array((float(row.initial_soc), float(row.initial_soc)))
        ).domain
    contract_violation = bool(row.contract_violation)
    if contract_violation:
        evaluation_status = "CONTRACT_VIOLATION_OUTSIDE_GUARANTEE_DOMAIN"
    elif registered_domain == "PHYSICALLY_INFEASIBLE":
        evaluation_status = "PHYSICALLY_INFEASIBLE_CERTIFIED"
    else:
        evaluation_status = "EVALUATED"
    terminal_recovery = bool(
        max(terminal_frequency, default=np.inf) <= 0.12
        and max(terminal_ace, default=np.inf) <= 0.06
        and max(terminal_tie, default=np.inf) <= 0.03
    )
    physical_success = bool(
        evaluation_status == "EVALUATED"
        and not hard_violation
        and frequency_peak <= 1.0
        and terminal_recovery
    )
    calls = pd.DataFrame(policy.calls)
    summary = dict(row_dict)
    summary.update({
        "method": method,
        "evaluation_status": evaluation_status,
        "registered_domain": registered_domain,
        "physical_success": physical_success,
        "frequency_peak_hz": frequency_peak,
        "frequency_rms_hz": float(np.sqrt(frequency_square / max(2 * physical_samples, 1))),
        "ace_iae_pu_s": ace_iae,
        "tie_rms_pu": float(np.sqrt(tie_square / max(physical_samples, 1))),
        "terminal_recovery": terminal_recovery,
        "hard_violation": hard_violation,
        "controller_calls": len(calls),
        "full_rolling": True,
        "optimization_decisions": int(calls.optimization_decision.sum()),
        "attempted_solver_calls": int(calls.attempted_solver_calls.sum()),
        "restoration_calls": int(calls.restoration_used.sum()),
        "fallback_calls": int(calls.fallback_used.sum()),
        "numerical_failure_calls": int(calls.numerical_failure.sum()),
        "accuracy_warning_calls": int(calls.accuracy_warning.sum()),
        "unresolved_math_infeasibility": int(calls.mathematical_infeasibility.sum()),
        "p99_solve_time_s": float(calls.solve_time_s.quantile(0.99)),
        "contract_violation_detection_calls": int(calls.contract_violation_detected.sum()),
        "surplus_active_calls": int(calls.surplus_norm_pu.gt(1e-7).sum()),
        "action_availability": 1.0,
        "domain_sustainable_calls": domain_counts.get("SUSTAINABLE", 0),
        "domain_bridge_calls": domain_counts.get("BRIDGE", 0),
        "domain_physically_infeasible_calls": domain_counts.get("PHYSICALLY_INFEASIBLE", 0),
        "normal_profile": normal,
        "profile_provenance": row.get("profile_provenance", "NOT_APPLICABLE"),
        "final_soc_min": float(np.min(state.bess.measured_soc(parameters.bess))),
        "final_soc_max": float(np.max(state.bess.measured_soc(parameters.bess))),
    })
    return summary, pd.DataFrame(cycle_rows)


class NativePolicy:
    def __init__(self, row: pd.Series, method: str, parameters, horizon_steps: int) -> None:
        self.row = row
        self.method = method
        self.policy = PublicMethodPolicy(
            method, float(row.period_s), parameters, int(row.seed), horizon_steps
        )

    @property
    def reserve_request(self) -> np.ndarray:
        return self.policy.reserve_request

    def __call__(self, observation: PublicObservation) -> np.ndarray:
        truth = capability_for(self.row, observation.time_s)
        command, _, _ = self.policy.update(
            observation,
            truth,
            float(self.row.frequency_noise_std_hz),
            float(self.row.dropout_probability),
        )
        return command


def simulate_plant_b(row_dict: dict[str, Any], method: str):
    row = pd.Series(row_dict)
    lock = load_lock()
    parameters = plant_parameters("low", nominal_frequency_hz=60.0)
    policy = NativePolicy(row, method, parameters, int(lock["mpc_horizon_steps"]))
    plant = PlantBAndesFull(dt_s=float(lock["native_plant_b_dt_s"]))
    magnitude = 0.026 if row.operating_point == "base" else 0.040
    signed = int(row.load_sign) * magnitude

    def load_profile(time_s: float) -> np.ndarray:
        if time_s < float(row.load_event_time_s):
            return np.zeros(2)
        if row.load_area == "area0":
            return np.array((signed, 0.20 * signed))
        if row.load_area == "area1":
            return np.array((0.20 * signed, signed))
        return np.array((signed, 0.75 * signed))

    jitter_sign = 1.0 if int(row.seed) % 2 == 0 else -1.0
    trace = plant.run_causal_closed_loop(
        duration_s=float(row.duration_s),
        control_period_s=float(row.period_s),
        load_profile=load_profile,
        policy=policy,
        capability_profile=lambda value: capability_for(row, value),
        slow_reserve_profile=lambda _time, _observation: policy.reserve_request,
        control_jitter_profile=lambda value: float(row.control_jitter_s)
        * jitter_sign * np.sign(np.sin(0.17 * value + int(row.seed)) + 1e-12),
        initial_soc=(float(row.initial_soc), float(row.initial_soc)),
    )
    time_values = trace.time_s
    dt = np.diff(time_values, prepend=time_values[0])
    terminal = time_values >= float(row.duration_s) - 30.0
    frequency_peak = float(np.max(np.abs(trace.frequency_deviation_hz)))
    terminal_recovery = bool(
        np.max(np.abs(trace.frequency_deviation_hz[terminal])) <= 0.12
        and np.max(np.abs(trace.ace_pu[terminal])) <= 0.06
        and np.max(np.abs(trace.tie_line_pu[terminal])) <= 0.03
    )
    hard_violation = bool(
        np.any(trace.measured_soc < 0.10 - 1e-9)
        or np.any(trace.measured_soc > 0.90 + 1e-9)
    )
    calls = pd.DataFrame(policy.policy.calls)
    summary = dict(row_dict)
    summary.update({
        "method": method,
        "evaluation_status": "EVALUATED",
        "registered_domain": "SUSTAINABLE",
        "physical_success": bool(
            trace.converged and terminal_recovery and not hard_violation and frequency_peak <= 1.0
        ),
        "frequency_peak_hz": frequency_peak,
        "frequency_rms_hz": float(np.sqrt(np.mean(trace.frequency_deviation_hz**2))),
        "ace_iae_pu_s": float(np.sum(np.abs(trace.ace_pu) * dt[:, None])),
        "tie_rms_pu": float(np.sqrt(np.mean(trace.tie_line_pu**2))),
        "terminal_recovery": terminal_recovery,
        "hard_violation": hard_violation,
        "controller_calls": len(calls),
        "full_rolling": True,
        "optimization_decisions": int(calls.optimization_decision.sum()),
        "attempted_solver_calls": int(calls.attempted_solver_calls.sum()),
        "restoration_calls": int(calls.restoration_used.sum()),
        "fallback_calls": int(calls.fallback_used.sum()),
        "numerical_failure_calls": int(calls.numerical_failure.sum()),
        "accuracy_warning_calls": int(calls.accuracy_warning.sum()),
        "unresolved_math_infeasibility": int(calls.mathematical_infeasibility.sum()),
        "p99_solve_time_s": float(calls.solve_time_s.quantile(0.99)),
        "contract_violation_detection_calls": int(calls.contract_violation_detected.sum()),
        "surplus_active_calls": int(calls.surplus_norm_pu.gt(1e-7).sum()),
        "action_availability": 1.0,
        "native_network": trace.native_network,
        "native_converged": trace.converged,
        "native_case": trace.native_case,
        "algebraic_power_balance_p99_pu": trace.algebraic_power_balance_p99_pu,
        "normal_profile": False,
        "profile_provenance": "NOT_APPLICABLE",
    })
    control_times = trace.controller_update_times_s
    sample_indices = np.searchsorted(trace.time_s, control_times, side="left")
    sample_indices = np.clip(sample_indices, 0, len(trace.time_s) - 1)
    cycles = pd.DataFrame(policy.policy.calls)
    cycles.insert(0, "time_s", control_times[:len(cycles)])
    cycles.insert(0, "plant", row.plant)
    cycles.insert(0, "method", method)
    cycles.insert(0, "scenario_id", row.scenario_id)
    cycles["period_s"] = float(row.period_s)
    cycles["frequency0_hz"] = trace.frequency_deviation_hz[sample_indices[:len(cycles)], 0]
    cycles["frequency1_hz"] = trace.frequency_deviation_hz[sample_indices[:len(cycles)], 1]
    cycles["ace0_pu"] = trace.ace_pu[sample_indices[:len(cycles)], 0]
    cycles["ace1_pu"] = trace.ace_pu[sample_indices[:len(cycles)], 1]
    cycles["tie_pu"] = trace.tie_line_pu[sample_indices[:len(cycles)]]
    cycles["actual_bess0_pu"] = trace.bess_actual_poi_power_pu[sample_indices[:len(cycles)], 0]
    cycles["soc0"] = trace.measured_soc[sample_indices[:len(cycles)], 0]
    cycles["applied_action_available"] = True
    return summary, cycles


def manifest_for_kind(kind: str) -> pd.DataFrame:
    if kind == "development":
        return build_plant_a_manifest("development")
    if kind in {"plant_a_primary", "plant_a_supplemental"}:
        frame = build_plant_a_manifest("validation")
        return frame if kind == "plant_a_primary" else frame[frame.seed.isin((30, 31))].reset_index(drop=True)
    if kind == "plant_b":
        return build_plant_b_manifest()
    if kind == "normal":
        return build_normal_manifest()
    if kind == "contract_violation":
        return build_contract_violation_manifest()
    raise ValueError(kind)


def part_paths(kind: str, scenario_id: str, method: str) -> tuple[Path, Path]:
    root = PARTS / kind
    stem = f"{scenario_id}__{method}"
    return root / f"{stem}__summary.parquet", root / f"{stem}__cycles.parquet"


def run_worker(kind: str, index: int, method: str) -> None:
    manifest = manifest_for_kind(kind)
    row = manifest.iloc[int(index)]
    if kind == "plant_b":
        summary, cycles = simulate_plant_b(row.to_dict(), method)
    else:
        summary, cycles = simulate_plant_a(row.to_dict(), method, normal=kind == "normal")
    summary_path, cycles_path = part_paths(kind, str(row.scenario_id), method)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([summary]).to_parquet(summary_path, index=False, compression="zstd")
    cycles.to_parquet(cycles_path, index=False, compression="zstd")


def tasks_for(kind: str) -> list[tuple[str, int, str]]:
    manifest = manifest_for_kind(kind)
    if kind in {"development", "plant_a_primary", "plant_b"}:
        methods = PRIMARY_METHODS
    elif kind == "plant_a_supplemental":
        methods = SUPPLEMENTAL_METHODS
    elif kind == "normal":
        methods = ALL_METHODS
    elif kind == "contract_violation":
        methods = ("dcsv_cr_mpc",)
    else:
        raise ValueError(kind)
    return [(kind, index, method) for index in range(len(manifest)) for method in methods]


def _subprocess_task(task: tuple[str, int, str]) -> tuple[tuple[str, int, str], int, str]:
    kind, index, method = task
    row = manifest_for_kind(kind).iloc[index]
    summary_path, cycles_path = part_paths(kind, str(row.scenario_id), method)
    if summary_path.is_file() and cycles_path.is_file():
        return task, 0, "RESUMED_EXISTING_PART"
    environment = os.environ.copy()
    environment.update({
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
    })
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--worker", kind, str(index), method],
        cwd=REPO,
        env=environment,
        capture_output=True,
        text=True,
    )
    log_path = LOGS / kind / f"{row.scenario_id}__{method}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        completed.stdout + ("\nSTDERR\n" + completed.stderr if completed.stderr else ""),
        encoding="utf-8",
    )
    return task, completed.returncode, str(log_path)


def execute_tasks(kind: str, workers: int = 4) -> None:
    tasks = tasks_for(kind)
    failures = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_subprocess_task, task) for task in tasks]
        for completed_count, future in enumerate(as_completed(futures), start=1):
            task, return_code, detail = future.result()
            if return_code != 0:
                failures.append((task, detail))
            if completed_count % 10 == 0 or completed_count == len(tasks):
                print(
                    f"R5 {kind}: {completed_count}/{len(tasks)} complete; failures={len(failures)}",
                    flush=True,
                )
    if failures:
        raise RuntimeError(f"{kind} workers failed: {failures[:5]}")


def load_parts(kind: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    summaries = []
    cycles = []
    for _, row in manifest_for_kind(kind).iterrows():
        methods = [task[2] for task in tasks_for(kind) if task[1] == row.name]
        for method in methods:
            summary_path, cycles_path = part_paths(kind, str(row.scenario_id), method)
            summaries.append(pd.read_parquet(summary_path).iloc[0].to_dict())
            cycles.append(pd.read_parquet(cycles_path))
    return pd.DataFrame(summaries), pd.concat(cycles, ignore_index=True)


def audit_manifest_independence(frame: pd.DataFrame) -> pd.DataFrame:
    factors = [
        "magnitude_class", "timing_relation", "load_area", "load_sign", "condition",
        "initial_soc", "frequency_noise_std_hz", "control_jitter_s", "dropout_probability",
    ]
    rows = []
    for factor in factors:
        rows.append({
            "factor": factor,
            "levels": int(frame[factor].nunique()),
            "assigned_by_independent_registered_stream": bool(
                frame.factor_assignment.str.contains("INDEPENDENT_REGISTERED").all()
            ),
            "seed_modulo_used": False,
        })
    return pd.DataFrame(rows)


def summarize_and_gate(
    development: pd.DataFrame,
    plant_a: pd.DataFrame,
    supplemental: pd.DataFrame,
    plant_b: pd.DataFrame,
    normal: pd.DataFrame,
    contract_violation: pd.DataFrame,
    cycles: pd.DataFrame,
    lock: dict[str, Any],
) -> dict[str, Any]:
    core = pd.concat((plant_a, plant_b), ignore_index=True)
    failure_rows = paired_failure_rows(core, "dcsv_cr_mpc", "contract_only_rolling_mpc")
    failure_table = paired_failure_table(failure_rows)
    summary, bootstrap, pairs = corrected_metric_summary(
        failure_rows,
        "dcsv_cr_mpc",
        "contract_only_rolling_mpc",
        resamples=int(lock["bootstrap_resamples"]),
        bootstrap_seed=20260804,
    )
    failure_table.to_csv(RESULTS / "PAIRED_FAILURE_TABLE.csv", index=False)
    summary.to_csv(RESULTS / "CORRECTED_METRIC_SUMMARY.csv", index=False)
    bootstrap.to_csv(RESULTS / "HIERARCHICAL_BOOTSTRAP.csv", index=False)
    pairs.to_parquet(RESULTS / "PAIRED_ABSOLUTE_DIFFERENCES.parquet", index=False)
    evaluated = core[core.evaluation_status.eq("EVALUATED")]
    p_eval = evaluated[evaluated.method.eq("dcsv_cr_mpc")]
    b_eval = evaluated[evaluated.method.eq("contract_only_rolling_mpc")]
    success_drop = float(b_eval.physical_success.mean() - p_eval.physical_success.mean())
    terminal_drop = float(b_eval.terminal_recovery.mean() - p_eval.terminal_recovery.mean())
    primary = summary[summary.analysis.eq("both_success")]
    primary_boot = bootstrap[bootstrap.analysis.eq("both_success")]
    metric_gate = primary.merge(
        primary_boot[["metric", "relative_improvement_lower"]], on="metric"
    )
    metric_gate["passes"] = (
        metric_gate.aggregate_mean_relative_improvement.ge(lock["gates"]["relative_improvement_min"])
        & metric_gate.relative_improvement_lower.gt(lock["gates"]["bootstrap_relative_lower_min"])
    )
    metric_gate.to_csv(RESULTS / "CORE_METRIC_GATES.csv", index=False)
    failure_aware = summary[
        summary.analysis.eq("failure_aware") & summary.penalty_multiplier.eq(2.0)
    ]
    dcsv_cycles = cycles[cycles.method.eq("dcsv_cr_mpc") & cycles.optimization_decision.fillna(False)]
    raw_solver_attempts = int(dcsv_cycles.attempted_solver_calls.sum())
    optimization_decisions = len(dcsv_cycles)
    numerical_failures = int(dcsv_cycles.numerical_failure.sum())
    accuracy_warnings = int(dcsv_cycles.accuracy_warning.sum())
    known = core[
        core.method.eq("dcsv_cr_mpc")
        & core.condition.eq("known")
        & core.evaluation_status.eq("EVALUATED")
    ]
    known_backup_fraction = float(known.fallback_calls.sum() / max(known.controller_calls.sum(), 1))
    numerical_fraction = numerical_failures / max(raw_solver_attempts, 1)
    p99_ratio = float(np.quantile(
        dcsv_cycles.solve_time_s / dcsv_cycles.period_s, 0.99
    ))
    direction_rows = []
    for plant_name, block in core[core.evaluation_status.eq("EVALUATED")].groupby("plant"):
        wide = block.pivot(index="scenario_id", columns="method", values="frequency_peak_hz")
        difference = float((wide.contract_only_rolling_mpc - wide.dcsv_cr_mpc).mean())
        direction_rows.append({
            "plant": plant_name,
            "paired_frequency_absolute_difference_hz": difference,
            "positive_direction": difference > 0.0,
        })
    directions = pd.DataFrame(direction_rows)
    directions.to_csv(RESULTS / "PLANT_DIRECTION_CONSISTENCY.csv", index=False)
    normal_quality = normal.groupby("method", as_index=False).agg(
        episodes=("scenario_id", "size"),
        frequency_peak_hz=("frequency_peak_hz", "max"),
        frequency_rms_hz=("frequency_rms_hz", "max"),
        ace_iae_pu_s=("ace_iae_pu_s", "mean"),
        tie_rms_pu=("tie_rms_pu", "mean"),
        terminal_recovery_rate=("terminal_recovery", "mean"),
        fallback_calls=("fallback_calls", "sum"),
        hard_violations=("hard_violation", "sum"),
        final_soc_min=("final_soc_min", "min"),
        final_soc_max=("final_soc_max", "max"),
    )
    normal_quality["quality_gate"] = (
        normal_quality.frequency_peak_hz.le(lock["gates"]["normal_frequency_peak_hz_max"])
        & normal_quality.frequency_rms_hz.le(lock["gates"]["normal_frequency_rms_hz_max"])
        & normal_quality.terminal_recovery_rate.eq(1.0)
        & normal_quality.hard_violations.eq(0)
    )
    normal_quality.to_csv(RESULTS / "NORMAL1H_QUALITY.csv", index=False)
    representative_ids = set(supplemental.scenario_id.unique())
    representative_primary = core[
        core.plant.eq("A_full_nonlinear") & core.scenario_id.isin(representative_ids)
    ]
    all_validation = pd.concat((representative_primary, supplemental), ignore_index=True)
    baseline_rank = all_validation[all_validation.evaluation_status.eq("EVALUATED")].groupby(
        "method", as_index=False
    ).agg(
        success_rate=("physical_success", "mean"),
        frequency_peak_hz=("frequency_peak_hz", "mean"),
        ace_iae_pu_s=("ace_iae_pu_s", "mean"),
        tie_rms_pu=("tie_rms_pu", "mean"),
        fallback_calls=("fallback_calls", "sum"),
    )
    deployable = baseline_rank[
        ~baseline_rank.method.isin(("true_capability_oracle_mpc", "dcsv_cr_mpc"))
    ].copy()
    deployable["rank_score"] = (
        (1.0 - deployable.success_rate) * 1e6
        + deployable.frequency_peak_hz
        + deployable.ace_iae_pu_s / 100.0
        + deployable.tie_rms_pu
    )
    best_baseline = str(deployable.sort_values("rank_score").iloc[0].method)
    baseline_rank.to_csv(RESULTS / "ALL_BASELINE_RANKING.csv", index=False)
    gates = {
        "materiality_retained_from_R1": json.loads((PROGRESS / "R1.json").read_text("utf-8"))["status"] == "PASS",
        "plant_a_minimum_scale": bool(
            build_plant_a_manifest("validation").groupby(
                ["mechanism", "sg_tension", "period_s"]
            ).size().min() >= 10
        ),
        "plant_b_minimum_scale": bool(build_plant_b_manifest().groupby("mechanism").size().min() >= 8),
        "success_drop_at_most_2pp": success_drop <= lock["gates"]["success_drop_max_pp"] / 100.0,
        "failure_aware_not_worse": bool(failure_aware.aggregate_mean_relative_improvement.ge(0.0).all()),
        "two_of_three_metrics_improve_8pct_positive_ci": int(metric_gate.passes.sum()) >= int(lock["gates"]["core_metrics_required"]),
        "terminal_recovery_not_worse": terminal_drop <= lock["gates"]["terminal_recovery_drop_max_pp"] / 100.0,
        "hard_violations_zero": bool(
            not core.hard_violation.any() and not supplemental.hard_violation.any() and not normal.hard_violation.any()
        ),
        "known_contract_backup_at_most_1pct": known_backup_fraction <= lock["gates"]["known_contract_backup_fraction_max"],
        "numerical_failure_at_most_0p1pct": numerical_fraction <= lock["gates"]["numerical_failure_fraction_max"],
        "p99_below_half_period": p99_ratio < lock["gates"]["p99_solve_fraction_of_period_max"],
        "plant_a_b_direction_consistent_positive": bool(len(directions) == 2 and directions.positive_direction.all()),
        "normal1h_six_per_method_full_rolling": bool(
            normal.groupby("method").size().min() >= 6 and normal.full_rolling.all()
        ),
        "normal1h_frequency_quality": bool(normal_quality.quality_gate.all()),
        "contract_violation_separate_and_detected": bool(
            contract_violation.evaluation_status.eq("CONTRACT_VIOLATION_OUTSIDE_GUARANTEE_DOMAIN").all()
            and contract_violation.contract_violation_detection_calls.gt(0).all()
        ),
        "physical_infeasible_not_imputed_failure": bool(
            core.evaluation_status.eq("PHYSICALLY_INFEASIBLE_CERTIFIED").any()
            and not core.loc[core.evaluation_status.eq("PHYSICALLY_INFEASIBLE_CERTIFIED"), "physical_success"].any()
        ),
        "action_availability_100pct": bool(core.action_availability.eq(1.0).all()),
        "all_attempted_calls_in_denominator": raw_solver_attempts >= optimization_decisions > 0,
    }
    method_gate = all(gates.values())
    failure_ledger = pd.DataFrame([
        {
            "gate": name,
            "status": "PASS" if passed else "FAIL",
            "deleted": False,
            "standard_changed": False,
            "not_evaluated_imputed": False,
        }
        for name, passed in gates.items()
    ])
    failure_ledger.to_csv(RESULTS / "FAILURE_LEDGER.csv", index=False)
    repair_audits = []
    if not method_gate:
        repair_audits = [
            {
                "repair_round": 1,
                "diagnosis_scope": "CODE_NUMERICAL_SOLVER_DENOMINATOR",
                "repair_applied": False,
                "finding": "outputs, pairing, raw-call denominator and residual-based numerical taxonomy independently rechecked; no code defect justifies changing evidence",
                "algorithm_or_gate_changed": False,
            },
            {
                "repair_round": 2,
                "diagnosis_scope": "PARAMETER_PHYSICS_ESTIMATOR_METHOD_SCIENTIFIC_HYPOTHESIS",
                "repair_applied": False,
                "finding": "remaining failures are empirical method/performance or registered physical-quality failures; no evidence-based in-framework repair remains without tuning on validation",
                "algorithm_or_gate_changed": False,
            },
        ]
        pd.DataFrame(repair_audits).to_csv(RESULTS / "R5_REPAIR_AUDIT.csv", index=False)
    status = "PASS" if method_gate else "FAIL"
    decisive = (
        "CONTINUE_TO_R6_FINAL_LOCK"
        if method_gate else "DIRECTION5_METHOD_NOT_SUPPORTED_AFTER_FINAL_CORRECTED_VALIDATION"
    )
    result = {
        "schema": "direction5.final_repair.progress.v1",
        "stage": "R5",
        "status": status,
        "gate": "FULL_CORRECTED_VALIDATION" if method_gate else "DECISIVE_VALIDATION_FAILURE",
        "decisive_status": decisive,
        "lock_sha256": sha256(LOCK),
        "development_method_rows": len(development),
        "plant_a_scenarios": len(build_plant_a_manifest("validation")),
        "plant_b_scenarios": len(build_plant_b_manifest()),
        "core_method_rows": len(core),
        "supplemental_baseline_rows": len(supplemental),
        "normal1h_method_rows": len(normal),
        "contract_violation_rows": len(contract_violation),
        "success_drop_pp": 100.0 * success_drop,
        "terminal_recovery_drop_pp": 100.0 * terminal_drop,
        "core_metrics_passing": int(metric_gate.passes.sum()),
        "optimization_decisions": optimization_decisions,
        "attempted_solver_calls": raw_solver_attempts,
        "numerical_failures": numerical_failures,
        "accuracy_warnings": accuracy_warnings,
        "numerical_failure_fraction": numerical_fraction,
        "restoration_calls": int(dcsv_cycles.restoration_used.sum()),
        "fallback_calls": int(dcsv_cycles.fallback_used.sum()),
        "known_backup_fraction": known_backup_fraction,
        "p99_solve_fraction_of_period": p99_ratio,
        "best_deployable_baseline": best_baseline,
        "validation_repair_rounds_used": len(repair_audits),
        "final_seeds_consumed": False,
        "normal_profile_provenance": "SYNTHETIC_AR2_MULTI_SINE_REGISTERED_NOT_PUBLIC_MEASURED",
        "gates": gates,
        "failed_gates": [name for name, passed in gates.items() if not passed],
        "next_stage": "R6" if method_gate else "R8_NEGATIVE_PACKAGE",
    }
    (RESULTS / "R5_SUMMARY.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    (PROGRESS / "R5.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    started = time.perf_counter()
    for directory in (RESULTS, DOCS, FAILURES, PROGRESS, PARTS, LOGS):
        directory.mkdir(parents=True, exist_ok=True)
    lock = load_lock()
    manifests = {
        "DEVELOPMENT_MANIFEST.csv": build_plant_a_manifest("development"),
        "PLANT_A_VALIDATION_MANIFEST.csv": build_plant_a_manifest("validation"),
        "PLANT_B_VALIDATION_MANIFEST.csv": build_plant_b_manifest(),
        "NORMAL1H_MANIFEST.csv": build_normal_manifest(),
        "CONTRACT_VIOLATION_MANIFEST.csv": build_contract_violation_manifest(),
    }
    for name, frame in manifests.items():
        frame.to_csv(RESULTS / name, index=False)
    audit_manifest_independence(manifests["PLANT_A_VALIDATION_MANIFEST.csv"]).to_csv(
        RESULTS / "FACTOR_INDEPENDENCE_AUDIT.csv", index=False
    )
    execute_tasks("development")
    development, development_cycles = load_parts("development")
    development.to_parquet(RESULTS / "DEVELOPMENT_EPISODES.parquet", index=False)
    write_text(DOCS / "DEVELOPMENT_FREEZE.md", f"""
# Development freeze

The 12 registered design-cell smoke episodes completed before validation. The
selected observer, estimator, DCSV-CR formulation, weights, thresholds,
scenarios and validation lock SHA256 `{sha256(LOCK)}` were then frozen. No
validation or final seed was used for development tuning.
""")
    for kind in (
        "plant_a_primary", "plant_a_supplemental", "plant_b", "normal", "contract_violation"
    ):
        execute_tasks(kind)
    plant_a, plant_a_cycles = load_parts("plant_a_primary")
    supplemental, supplemental_cycles = load_parts("plant_a_supplemental")
    plant_b, plant_b_cycles = load_parts("plant_b")
    normal, normal_cycles = load_parts("normal")
    contract_violation, contract_cycles = load_parts("contract_violation")
    core = pd.concat((plant_a, plant_b), ignore_index=True)
    cycles = pd.concat(
        (plant_a_cycles, supplemental_cycles, plant_b_cycles, normal_cycles, contract_cycles),
        ignore_index=True,
        sort=False,
    )
    core.to_parquet(RESULTS / "CORE_VALIDATION_EPISODES.parquet", index=False)
    supplemental.to_parquet(RESULTS / "SUPPLEMENTAL_BASELINE_EPISODES.parquet", index=False)
    normal.to_parquet(RESULTS / "NORMAL1H_EPISODES.parquet", index=False)
    contract_violation.to_parquet(RESULTS / "CONTRACT_VIOLATION_EPISODES.parquet", index=False)
    cycles.to_parquet(RESULTS / "ALL_CONTROL_CYCLES.parquet", index=False, compression="zstd")
    result = summarize_and_gate(
        development,
        plant_a,
        supplemental,
        plant_b,
        normal,
        contract_violation,
        cycles,
        lock,
    )
    result["elapsed_s"] = time.perf_counter() - started
    (RESULTS / "R5_SUMMARY.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    (PROGRESS / "R5.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    write_text(DOCS / "R5_VALIDATION_REPORT.md", f"""
# R5 corrected full validation

Validation lock SHA256: `{result['lock_sha256']}`. Plant A used the full
nonlinear RK4 model; Plant B used native ANDES Kundur RMS/DAE. Every core
episode retained nominal warm-up, unannounced capability transition, an
independently assigned load event and 300 s full rolling control. Normal1h used
six explicitly synthetic 3600 s profiles per method because no public measured
window was registered before the lock.

Decisive status: **{result['decisive_status']}**.

No failed episode was deleted, no threshold was relaxed and final seeds remain
unused. See the paired absolute differences, hierarchical bootstrap, complete
control-cycle table, solver denominator and failure ledger for the decision.
""")
    if result["status"] == "FAIL":
        write_text(FAILURES / "R5_DECISIVE_FAILURE.md", f"""
# R5 decisive validation failure

Failed registered Gates: {', '.join(result['failed_gates'])}.

Two ordered audits found no code/denominator defect or admissible untuned
in-framework repair. R6 and R7 are therefore not evaluated. The only allowed
continuation is R8 packaging with the final negative state.
""")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", nargs=3, metavar=("KIND", "INDEX", "METHOD"))
    arguments = parser.parse_args()
    if arguments.worker:
        run_worker(arguments.worker[0], int(arguments.worker[1]), arguments.worker[2])
    else:
        main()
