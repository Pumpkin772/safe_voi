"""Engineer, audit and gate the unique DCSV-CR-MPC formulation."""

from __future__ import annotations

from dataclasses import replace
import inspect
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from direction5freq.controllers.contract_violation_supervisor import (
    ContractViolationSupervisor,
)
from direction5freq.controllers.dcsv_cr_mpc import DCSVContractRecourseMPC
from direction5freq.controllers.dcsv_mpc_final import DCSVInput
from direction5freq.controllers.domain_supervisor import DomainSupervisor
from direction5freq.controllers.recourse_tree import RecourseTree
from direction5freq.estimation.deliverability_set_membership import DeliverabilitySetMembership
from direction5freq.estimation.grid_load_mhe import ConstrainedGridLoadMHE
from direction5freq.estimation.grid_load_observer import LoadObserverInput
from direction5freq.models.capability_contract import CapabilityRealization
from direction5freq.models.plant_a_full import PlantAFull


RESULTS = REPO / "results_final/R3"
METHOD = REPO / "research_outputs_final/04_METHOD"
PROGRESS = REPO / "progress_final"


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def observer() -> ConstrainedGridLoadMHE:
    return ConstrainedGridLoadMHE(
        nominal_frequency_hz=50.0,
        inertia_s=(5.0, 4.5),
        damping_pu_per_pu_frequency=(1.0, 1.0),
        derivative_filter=0.40,
        warmup_samples=8,
    )


def public_load_update(load_observer: ConstrainedGridLoadMHE, observation):
    return load_observer.update(LoadObserverInput(
        time_s=float(observation.time_s),
        frequency_deviation_hz=observation.frequency_deviation_hz,
        tie_line_pu=float(observation.tie_line_pu),
        sg_mechanical_power_pu=observation.sg_mechanical_power_pu,
        bess_actual_poi_power_pu=observation.bess_actual_power_pu,
        slow_reserve_power_pu=observation.slow_reserve_power_pu,
    ))


def formulation_audit() -> pd.DataFrame:
    plant = PlantAFull()
    observation = plant.public_observation(0.0, plant.equilibrium(), np.zeros(4))
    base = DeliverabilitySetMembership(
        plant.parameters.bess.contract, 2.0
    ).update(0.0, np.zeros(2), np.zeros(2))
    promoted = replace(
        base,
        performance_power_pu=np.array((0.080, 0.080)),
        performance_ramp_pu_per_s=np.array((0.060, 0.060)),
    )
    rows: list[dict[str, Any]] = []
    for period_s in (2.0, 4.0):
        for envelope_name, envelope in (("contract", base), ("online", promoted)):
            for load_level in (0.04, 0.08, 0.10):
                load = np.array((load_level, 0.90 * load_level))
                domain = DomainSupervisor(plant.parameters).classify(
                    load, observation.measured_soc
                )
                result = DCSVContractRecourseMPC(period_s, 5).propose(
                    DCSVInput(observation, load, envelope, domain)
                )
                rows.append({
                    "period_s": period_s,
                    "envelope": envelope_name,
                    "load_level_pu": load_level,
                    "solver_status": result.diagnostics.status,
                    "attempted_optimization_calls": result.diagnostics.attempted_optimization_calls,
                    "solve_time_s": result.diagnostics.solve_time_s,
                    "maximum_constraint_residual": result.diagnostics.maximum_constraint_residual,
                    "hard_margin_pu": result.diagnostics.hard_margin_pu,
                    "energy_margin_mwh": result.diagnostics.energy_margin_mwh,
                    "restoration_used": result.diagnostics.restoration_used,
                    "fallback_used": result.diagnostics.fallback_used,
                    "branch_count": result.diagnostics.branch_count,
                    "delay_vertex_count": result.diagnostics.delay_vertex_count,
                    "shared_current_action_verified": result.shared_current_action_verified,
                    "surplus_loss_branch_verified": result.surplus_loss_branch_verified,
                    "current_surplus_norm_pu": float(np.linalg.norm(result.surplus_bess_command_pu)),
                    "horizon_surplus_max_pu": float(np.max(np.abs(result.predicted_surplus_bess_sequence_pu))),
                    "predicted_state_steps": result.predicted_state_sequence.shape[-1],
                    "predicted_input_steps": result.predicted_input_sequence.shape[-1],
                    "predicted_energy_steps": result.predicted_energy_sequence_mwh.shape[-1],
                })
    return pd.DataFrame(rows)


def rolling_episode(period_s: float, seed: int) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    rng = np.random.default_rng(np.random.SeedSequence([20260804, seed, 503]))
    plant = PlantAFull(dt_s=0.02)
    state = plant.equilibrium(soc=(0.48, 0.52))
    controller = DCSVContractRecourseMPC(period_s, 4, plant.parameters)
    estimator = DeliverabilitySetMembership(plant.parameters.bess.contract, period_s)
    load_observer = observer()
    domain_supervisor = DomainSupervisor(plant.parameters)
    violation_supervisor = ContractViolationSupervisor(
        plant.parameters.bess.contract, period_s
    )
    realization = CapabilityRealization(
        upper_power_pu=(0.070, 0.074),
        lower_power_pu=(-0.070, -0.074),
        ramp_up_pu_per_s=(0.045, 0.050),
        ramp_down_pu_per_s=(0.045, 0.050),
        delay_s=(0.55, 0.85),
    )
    duration_s = 60.0
    event_time = 20.0 + 2.0 * (seed % 3)
    load_step = rng.uniform((0.035, 0.025), (0.055, 0.045))
    command = np.zeros(4)
    guaranteed = np.zeros(2)
    reserve_request = np.zeros(2)
    next_control = 0.0
    calls: list[dict[str, Any]] = []
    transactions: list[dict[str, Any]] = []
    peak_frequency = 0.0
    peak_ace = 0.0
    peak_tie = 0.0
    hard_violations = 0
    fallback_calls = 0
    restoration_calls = 0
    for step in range(int(duration_s / plant.dt_s) + 1):
        time_s = step * plant.dt_s
        observation = plant.public_observation(time_s, state, command)
        peak_frequency = max(
            peak_frequency, float(np.max(np.abs(observation.frequency_deviation_hz)))
        )
        peak_ace = max(peak_ace, float(np.max(np.abs(observation.ace_pu))))
        peak_tie = max(peak_tie, abs(float(observation.tie_line_pu)))
        if time_s + 1e-10 >= next_control:
            load_estimate = public_load_update(load_observer, observation)
            envelope = estimator.update(
                time_s, command[[1, 3]], observation.bess_actual_power_pu
            )
            domain = domain_supervisor.classify(
                load_estimate.load_pu, observation.measured_soc
            )
            violation = violation_supervisor.update(guaranteed, observation)
            result = controller.propose(DCSVInput(
                observation,
                load_estimate.load_pu,
                envelope,
                domain,
                contract_violation_status=violation.status,
            ))
            proposed = result.proposed_action_pu.copy()
            applied = proposed.copy()
            applied[[0, 2]] = np.clip(
                applied[[0, 2]] + violation.sg_emergency_increment_pu,
                plant.parameters.valve_lower_pu,
                plant.parameters.valve_upper_pu,
            )
            reserve_request = np.maximum(
                result.slow_reserve_request_pu, violation.slow_reserve_request_pu
            )
            controller.commit(
                applied,
                observation.bess_actual_power_pu,
                result.guaranteed_bess_command_pu,
            )
            transaction_match = np.allclose(controller.last_committed_action, applied)
            transactions.append({
                "episode_id": f"R3-E-{period_s:g}-{seed}",
                "time_s": time_s,
                "proposed_action": json.dumps(proposed.tolist()),
                "applied_action": json.dumps(applied.tolist()),
                "committed_action": json.dumps(controller.last_committed_action.tolist()),
                "applied_equals_committed": transaction_match,
                "supervisor_changed_action": not np.allclose(proposed, applied),
            })
            calls.append({
                "episode_id": f"R3-E-{period_s:g}-{seed}",
                "period_s": period_s,
                "time_s": time_s,
                "status": result.diagnostics.status,
                "primary_status": result.diagnostics.primary_status,
                "restoration_status": result.diagnostics.restoration_status,
                "attempted_optimization_calls": result.diagnostics.attempted_optimization_calls,
                "solve_time_s": result.diagnostics.solve_time_s,
                "maximum_constraint_residual": result.diagnostics.maximum_constraint_residual,
                "restoration_used": result.diagnostics.restoration_used,
                "fallback_used": result.diagnostics.fallback_used,
                "mathematical_infeasibility": result.diagnostics.mathematical_infeasibility,
                "numerical_failure": result.diagnostics.numerical_failure,
                "shared_current_action_verified": result.shared_current_action_verified,
                "surplus_loss_branch_verified": result.surplus_loss_branch_verified,
                "contract_violation_detected": violation.detected,
            })
            fallback_calls += int(result.diagnostics.fallback_used)
            restoration_calls += int(result.diagnostics.restoration_used)
            guaranteed = result.guaranteed_bess_command_pu.copy()
            command = applied
            next_control += period_s
        load = np.zeros(2) if time_s < event_time else load_step
        if step < int(duration_s / plant.dt_s):
            state, _ = plant.step(
                state, command, load, realization, reserve_request
            )
        soc = state.bess.measured_soc(plant.parameters.bess)
        hard_violations += int(
            np.any(soc < plant.parameters.bess.soc_min - 1e-9)
            or np.any(soc > plant.parameters.bess.soc_max + 1e-9)
            or np.any(np.abs(command[[0, 2]]) > np.asarray(plant.parameters.valve_upper_pu) + 1e-9)
            or np.any(np.abs(command[[1, 3]]) > plant.parameters.bess.rating_pu + 1e-9)
        )
    return ({
        "episode_id": f"R3-E-{period_s:g}-{seed}",
        "period_s": period_s,
        "seed": seed,
        "duration_s": duration_s,
        "event_time_s": event_time,
        "frequency_peak_hz": peak_frequency,
        "ace_peak_pu": peak_ace,
        "tie_peak_pu": peak_tie,
        "hard_violations": hard_violations,
        "control_calls": len(calls),
        "fallback_calls": fallback_calls,
        "restoration_calls": restoration_calls,
        "final_soc_min": float(np.min(state.bess.measured_soc(plant.parameters.bess))),
    }, calls, transactions)


def contract_violation_audit() -> pd.DataFrame:
    plant = PlantAFull()
    observation = plant.public_observation(0.0, plant.equilibrium(), np.zeros(4))
    supervisor = ContractViolationSupervisor(plant.parameters.bess.contract, 2.0)
    rows = []
    for index in range(7):
        actual = np.array((0.041, 0.042)) if index < 3 else np.array((0.010, 0.012))
        decision = supervisor.update(
            np.array((0.045, 0.045)),
            replace(observation, time_s=2.0 * index, bess_actual_power_pu=actual),
        )
        rows.append({
            "time_s": 2.0 * index,
            "detected": decision.detected,
            "status": decision.status,
            "emergency_sg_norm_pu": float(np.linalg.norm(decision.sg_emergency_increment_pu)),
            "slow_reserve_request_norm_pu": float(np.linalg.norm(decision.slow_reserve_request_pu)),
            "uses_truth": False,
            "same_instant_guarantee_claimed": False,
        })
    return pd.DataFrame(rows)


def write_method_documents() -> None:
    write_text(METHOD / "DCSV_CR_MPC_FORMULATION.md", r"""
# DCSV-CR-MPC formulation

The BESS command is `u_b = u_b^g + u_b^s`. The guaranteed component obeys
contract power/ramp/delay constraints; the surplus component is bounded by the
current revocable performance witness. Both delivered and zero-surplus-loss
branches share the complete stage-0 command. From stage 1 onward SG and slow
reserve are branch-specific. Every delay vertex propagates grid state, actual
BESS power, measured-SoC energy and slow-reserve state.

The objective uses a worst-branch epigraph plus a subordinate delivered-branch
performance term and control effort. Restoration can relax only terminal
frequency/ACE/tie targets. It cannot relax contract power/ramp, physical energy,
delay causality, SG or reserve bounds. A detected contract breach revokes all
surplus and routes causal emergency support; no same-instant guarantee is made.
""")
    write_text(METHOD / "PSEUDOCODE.md", """
# DCSV-CR-MPC pseudocode

1. Read public grid measurements, actual BESS POI power and measured SoC.
2. Update slow-load MHE and the causal deliverability feasible set.
3. Classify sustainable, bridge or physically infeasible domain.
4. Detect matured contract underdelivery; revoke surplus if detected.
5. Build delivered and zero-surplus loss branches with a shared current action.
6. Solve the hard rolling epigraph QP; if needed relax terminal performance only.
7. Apply supervisory SG/reserve recourse and commit the action actually applied.
8. Record every attempted optimization call, restoration and fallback.
""")
    equation_map = pd.DataFrame([
        {"requirement": "command split", "code": "dcsv_cr_mpc.py: guaranteed + surplus"},
        {"requirement": "shared stage 0", "code": "dcsv_cr_mpc.py: sg/reserve_request equality"},
        {"requirement": "surplus-loss branch", "code": "recourse_tree.py: delivery fraction 0"},
        {"requirement": "delay pipeline", "code": "dcsv_cr_mpc.py: _pipeline_expression"},
        {"requirement": "actual SoC energy", "code": "dcsv_cr_mpc.py: energy0 from measured_soc"},
        {"requirement": "worst epigraph", "code": "dcsv_cr_mpc.py: branch_cost <= worst_cost"},
        {"requirement": "contract breach routing", "code": "contract_violation_supervisor.py"},
        {"requirement": "actual action commit", "code": "dcsv_cr_mpc.py: commit"},
    ])
    equation_map.to_csv(METHOD / "EQUATION_CODE_MAP.csv", index=False)


def main() -> None:
    for directory in (RESULTS, METHOD, PROGRESS):
        directory.mkdir(parents=True, exist_ok=True)
    structural = formulation_audit()
    structural.to_csv(RESULTS / "FORMULATION_AUDIT.csv", index=False)
    episode_rows = []
    call_rows = []
    transaction_rows = []
    for period_s in (2.0, 4.0):
        for seed in range(4):
            episode, calls, transactions = rolling_episode(period_s, seed)
            episode_rows.append(episode)
            call_rows.extend(calls)
            transaction_rows.extend(transactions)
    episodes = pd.DataFrame(episode_rows)
    calls = pd.DataFrame(call_rows)
    transactions = pd.DataFrame(transaction_rows)
    episodes.to_parquet(RESULTS / "ROLLING_ENGINEERING.parquet", index=False)
    calls.to_parquet(RESULTS / "SOLVER_CALLS.parquet", index=False)
    transactions.to_csv(RESULTS / "ACTION_TRANSACTIONS.csv", index=False)
    violation = contract_violation_audit()
    violation.to_csv(RESULTS / "CONTRACT_VIOLATION_AUDIT.csv", index=False)
    write_method_documents()

    controller_source = inspect.getsource(DCSVContractRecourseMPC)
    hard_violations = int(episodes.hard_violations.sum())
    attempted_decisions = len(calls)
    attempted_solver_calls = int(calls.attempted_optimization_calls.sum())
    gates = {
        "true_rolling_prediction_and_controls": bool(
            structural.predicted_state_steps.gt(1).all()
            and structural.predicted_input_steps.gt(0).all()
            and structural.predicted_energy_steps.gt(1).all()
        ),
        "online_envelope_changes_surplus_not_only_cost": bool(
            structural.loc[structural.envelope.eq("online"), "horizon_surplus_max_pu"].gt(1e-5).all()
            and structural.loc[structural.envelope.eq("contract"), "horizon_surplus_max_pu"].lt(1e-7).all()
        ),
        "shared_current_action_all_branches": bool(structural.shared_current_action_verified.all()),
        "zero_surplus_loss_branch": bool(structural.surplus_loss_branch_verified.all()),
        "hard_violations_zero": hard_violations == 0,
        "action_commit_100pct": bool(transactions.applied_equals_committed.all()),
        "constraint_residual_within_tolerance": bool(
            calls.maximum_constraint_residual.fillna(np.inf).le(1e-5).all()
        ),
        "realtime_2s_4s": bool((calls.solve_time_s < calls.period_s).all()),
        "all_attempted_calls_in_denominator": bool(
            attempted_solver_calls >= attempted_decisions and attempted_decisions > 0
        ),
        "contract_breach_detected_and_routed": bool(
            violation.detected.any()
            and violation.loc[violation.detected, "emergency_sg_norm_pu"].gt(0).all()
        ),
        "ordinary_controller_truth_future_free": bool(
            "true_capability" not in controller_source
            and "future_event" not in controller_source
            and "CapabilityRealization" not in controller_source
        ),
    }
    status = "PASS" if all(gates.values()) else "FAIL"
    progress = {
        "schema": "direction5.final_repair.progress.v1",
        "stage": "R3",
        "status": status,
        "gate": "DCSV_CR_ENGINEERING" if status == "PASS" else "R3_REPAIR_REQUIRED",
        "repair_rounds_used": 0,
        "method": "DCSV-CR-MPC",
        "engineering_episodes": len(episodes),
        "attempted_optimization_decisions": attempted_decisions,
        "attempted_solver_calls": attempted_solver_calls,
        "all_attempted_calls_in_denominator": gates["all_attempted_calls_in_denominator"],
        "solver_status_counts": calls.status.value_counts().to_dict(),
        "restoration_calls": int(calls.restoration_used.sum()),
        "fallback_calls": int(calls.fallback_used.sum()),
        "hard_violations": hard_violations,
        "action_application_rate": float(transactions.applied_equals_committed.mean()),
        "solve_time_p99_s": float(calls.solve_time_s.quantile(0.99)),
        "contract_violation_detected": bool(violation.detected.any()),
        "final_seeds_consumed": False,
        "gates": gates,
        "failures": [name for name, passed in gates.items() if not passed],
        "next_stage": "R4" if status == "PASS" else "R3_REPAIR_1",
    }
    (PROGRESS / "R3.json").write_text(
        json.dumps(progress, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(progress, indent=2))
    if status != "PASS":
        raise SystemExit("R3 Gate failed: " + ", ".join(progress["failures"]))


if __name__ == "__main__":
    main()
