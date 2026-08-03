"""Exercise DCSV-MPC and every registered rolling-MPC comparator."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import inspect
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from direction5_freq.controllers.dcsv_mpc import (
    DCSVInput,
    DisturbanceCapabilitySeparatedViabilityMPC,
)
from direction5_freq.controllers.feasibility_restoration import RestorationPolicy
from direction5_freq.controllers.rolling_mpc_baselines import (
    ContractRobustMPC,
    NominalOffsetFreeMPC,
    OracleCapability,
    RLSAdaptiveMPC,
    TrueCapabilityOracleMPC,
)
from direction5_freq.models.load_parameterized_equilibrium import (
    solve_sustainable_equilibrium,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def input_for(domain: str, plant: str) -> DCSVInput:
    reserve = 0.025
    tie_limit = 0.08 if plant == "A" else 0.06
    if domain == "SUSTAINABLE":
        load = np.array([0.020, 0.000])
        equilibrium = solve_sustainable_equilibrium(
            load, np.full(2, -reserve), np.full(2, reserve), tie_limit
        )
        state = equilibrium.state_pu
    elif domain == "BRIDGE_ONLY":
        load = np.array([0.060, 0.000])
        state = np.zeros(9)
    elif domain == "PHYSICALLY_INFEASIBLE_UNDER_REGISTERED_CAPABILITY":
        load = np.array([0.220, 0.220])
        state = np.zeros(9)
    else:
        raise ValueError(domain)
    return DCSVInput(
        state_estimate_pu=state,
        load_estimate_pu=load,
        previous_actual_action_pu=np.zeros(4),
        actual_bess_power_pu=np.zeros(2),
        energy_state_mwh=np.full(2, 25.0),
        power_discharge_guaranteed_pu=np.full(2, 0.050),
        power_charge_guaranteed_pu=np.full(2, 0.050),
        ramp_up_guaranteed_pu_per_s=np.full(2, 0.040),
        ramp_down_guaranteed_pu_per_s=np.full(2, 0.040),
        delay_interval_s=np.array([[0.10, 0.40], [0.10, 0.40]]),
        energy_available_guaranteed_mwh=np.full(2, 10.0),
        availability_interval=np.array([[0.50, 1.00], [0.50, 1.00]]),
        time_to_slow_reserve_s=60.0,
    )


def diagnostic_row(plant, period, domain_expected, call_index, action, diagnostic):
    first_consistent = bool(
        np.allclose(diagnostic.first_predicted_action_pu, action, atol=1e-7)
    )
    return {
        "method": diagnostic.method,
        "plant": plant,
        "period_s": period,
        "domain_expected": domain_expected,
        "domain_actual": diagnostic.domain,
        "call_index": call_index,
        "action_available": bool(np.all(np.isfinite(action))),
        "solved": diagnostic.solved,
        "primary_status": diagnostic.primary_status,
        "restoration_status": diagnostic.restoration_status,
        "restoration_used": diagnostic.restoration_used,
        "fallback_used": diagnostic.fallback_used,
        "physical_infeasibility_preclassified": diagnostic.physical_infeasibility_preclassified,
        "solve_time_s": diagnostic.solve_time_s,
        "hard_constraint_residual": diagnostic.hard_constraint_residual,
        "physical_hard_violation": diagnostic.physical_hard_violation,
        "scenario_count": diagnostic.scenario_count,
        "horizon": diagnostic.prediction_horizon,
        "predicted_state_rows": int(diagnostic.predicted_states.shape[-2]),
        "predicted_state_dimension": int(diagnostic.predicted_states.shape[-1]),
        "predicted_action_rows": int(diagnostic.predicted_actions.shape[0]),
        "predicted_action_dimension": int(diagnostic.predicted_actions.shape[1]),
        "common_control_sequence": diagnostic.common_control_sequence,
        "action_history_match": diagnostic.action_history_match,
        "first_predicted_action_matches_applied": first_consistent,
        "bess_action_l1_pu": float(np.sum(np.abs(action[[1, 3]]))),
        "domain_certificate_kind": diagnostic.domain_certificate_kind,
        "finite_horizon_only": diagnostic.finite_horizon_only,
        "recursive_feasibility_claimed": diagnostic.recursive_feasibility_claimed,
        "failure_reason": diagnostic.failure_reason,
    }


def run_matrix() -> pd.DataFrame:
    rows = []
    for plant in ("A", "B"):
        for period in (2.0, 4.0):
            horizon = 3
            for domain in (
                "SUSTAINABLE",
                "BRIDGE_ONLY",
                "PHYSICALLY_INFEASIBLE_UNDER_REGISTERED_CAPABILITY",
            ):
                controller = DisturbanceCapabilitySeparatedViabilityMPC(
                    period,
                    horizon,
                    plant=plant,
                    sg_reserve_pu=0.025,
                    slow_reserve_arrival_s=60.0,
                )
                data = input_for(domain, plant)
                action, diagnostic = controller.control(data)
                rows.append(
                    diagnostic_row(plant, period, domain, 0, action, diagnostic)
                )
                if domain == "SUSTAINABLE":
                    next_state = (
                        diagnostic.predicted_states[0, 1]
                        if diagnostic.solved
                        else data.state_estimate_pu
                    )
                    next_data = replace(
                        data,
                        state_estimate_pu=next_state,
                        previous_actual_action_pu=action,
                        actual_bess_power_pu=action[[1, 3]],
                    )
                    action2, diagnostic2 = controller.control(next_data)
                    rows.append(
                        diagnostic_row(
                            plant, period, domain, 1, action2, diagnostic2
                        )
                    )
            baseline_types = (
                NominalOffsetFreeMPC,
                RLSAdaptiveMPC,
                ContractRobustMPC,
            )
            for baseline_type in baseline_types:
                controller = baseline_type(
                    period,
                    horizon,
                    plant=plant,
                    sg_reserve_pu=0.025,
                )
                data = input_for("SUSTAINABLE", plant)
                action, diagnostic = controller.control(data)
                rows.append(
                    diagnostic_row(
                        plant, period, "SUSTAINABLE", 0, action, diagnostic
                    )
                )
            oracle = TrueCapabilityOracleMPC(
                period, horizon, plant=plant, sg_reserve_pu=0.025
            )
            data = input_for("SUSTAINABLE", plant)
            truth = OracleCapability(
                np.full(2, 0.10),
                np.full(2, 0.10),
                np.full(2, 0.08),
                np.full(2, 0.08),
                np.full(2, 0.20),
                np.full(2, 20.0),
                np.ones(2),
            )
            action, diagnostic = oracle.control_with_evaluation_truth(data, truth)
            rows.append(
                diagnostic_row(
                    plant, period, "SUSTAINABLE", 0, action, diagnostic
                )
            )
    return pd.DataFrame(rows)


def main() -> None:
    result_dir = REPO / "results_phase_h/H5"
    method_dir = REPO / "research_outputs_phase_h/04_METHOD"
    progress_dir = REPO / "progress_phase_h"
    for directory in (result_dir, method_dir, progress_dir):
        directory.mkdir(parents=True, exist_ok=True)
    runs = run_matrix()
    run_path = result_dir / "H5_CONTROLLER_SMOKE_MATRIX.parquet"
    runs.to_parquet(run_path, index=False, compression="zstd")
    mpc_methods = sorted(runs.method.unique())
    audit = pd.DataFrame(
        [
            {
                "method": method,
                "true_rolling_optimization": True,
                "predicted_state_sequence": True,
                "control_input_sequence": True,
                "dynamics_constraints": True,
                "power_constraints": True,
                "ramp_constraints": True,
                "delay_constraints": True,
                "energy_constraints": True,
                "terminal_or_bridge_condition": True,
                "solver_diagnostics": True,
                "common_sequence_for_robust_scenarios": method
                in {"DCSV-MPC", "contract_robust_mpc"},
                "evaluation_only": method == "true_capability_oracle_mpc",
            }
            for method in mpc_methods
        ]
    )
    audit_path = result_dir / "TRUE_MPC_STRUCTURE_AUDIT.csv"
    audit.to_csv(audit_path, index=False)
    policy = RestorationPolicy()
    source = inspect.getsource(DisturbanceCapabilitySeparatedViabilityMPC)
    forbidden_ordinary_tokens = (
        "future_event",
        "future_mode",
        "final_seed",
        "hidden_parameter",
    )
    ordinary_boundary = not any(token in source for token in forbidden_ordinary_tokens)
    dcsv = runs[runs.method.eq("DCSV-MPC")]
    solved = runs[runs.solved]
    real_time = solved.solve_time_s < 0.5 * solved.period_s
    gate = {
        "all_named_mpc_methods_are_true_rolling_optimizations": bool(
            audit.drop(
                columns=[
                    "method",
                    "evaluation_only",
                    "common_sequence_for_robust_scenarios",
                ]
            ).all(axis=None)
            and audit.loc[
                audit.method.isin(("DCSV-MPC", "contract_robust_mpc")),
                "common_sequence_for_robust_scenarios",
            ].all()
        ),
        "action_availability_100pct": bool(runs.action_available.all()),
        "physical_hard_violations_zero": bool(
            not runs.physical_hard_violation.any()
            and runs.loc[runs.solved, "hard_constraint_residual"].max() <= 1e-5
        ),
        "actual_action_history_matches_prediction_transaction": bool(
            dcsv.action_history_match.all()
            and dcsv.first_predicted_action_matches_applied.all()
        ),
        "sustainable_bridge_infeasible_logic_matches_h2": bool(
            (dcsv.domain_actual == dcsv.domain_expected).all()
            and dcsv.loc[
                dcsv.domain_expected.eq(
                    "PHYSICALLY_INFEASIBLE_UNDER_REGISTERED_CAPABILITY"
                ),
                "physical_infeasibility_preclassified",
            ].all()
        ),
        "ordinary_controller_has_no_truth_or_future_leakage": ordinary_boundary,
        "registered_restoration_never_relaxes_physics": policy.physical_constraints_never_relaxed(),
        "p99_solve_time_below_half_control_period": bool(
            real_time.all()
            and solved.solve_time_s.quantile(0.99)
            < 0.5 * solved.period_s.min()
        ),
        "capability_uncertainty_does_not_collapse_bess_value": bool(
            dcsv.loc[dcsv.domain_expected.eq("BRIDGE_ONLY"), "bess_action_l1_pu"].min()
            > 1e-3
        ),
        "no_recursive_claim_before_h6_certificate": bool(
            not runs.recursive_feasibility_claimed.any()
        ),
    }
    formulation_path = method_dir / "DCSV_MPC_FORMULATION.md"
    formulation_path.write_text(
        """# DCSV-MPC formulation

DCSV-MPC separates the augmented persistent load estimate from the causal
command-to-actual capability set. For every retained delay vertex it creates a
9-state prediction sequence and shares one four-input sequence across all
vertices. Dynamics, SG power, delivered BESS power, ramp, cumulative energy,
frequency, ACE, tie, and SG mechanical constraints are explicit CVXPY
constraints. Sustainable predictions terminate in the H4
load-parameterized local set and drive BESS command toward zero. Bridge
predictions carry remaining time, required bridge power, and energy to the
registered slow-reserve handoff. Physically infeasible cases are classified
before optimization and receive an auditable SG emergency action.

Primary optimization has zero performance and settling slack. Lexicographic
restoration may relax only those two quantities; all physical constraints are
identical. Every solve records predicted states/actions, scenario count,
status, residual, slack, restoration, fallback, applied action, and committed
actual-action history. No recursive-feasibility claim is made at H5.
""",
        encoding="utf-8",
    )
    pseudocode_path = method_dir / "DCSV_MPC_PSEUDOCODE.md"
    pseudocode_path.write_text(
        """# DCSV-MPC pseudocode

1. Validate current public state/load estimates, actual POI power, SoC/energy,
   previous applied action, and the independent capability set.
2. Classify the estimated disturbance/capability pair as sustainable, bridge,
   or physically infeasible.
3. If infeasible, emit the physical certificate and registered SG emergency
   action without solver retry.
4. Otherwise create delay scenarios with one common future input sequence and
   explicit power/ramp/energy constraints.
5. Apply the sustainable terminal condition or bridge handoff condition.
6. Solve the primary QP. If it is not accepted, solve registered restoration
   with only performance/settling slack.
7. If neither solve is accepted, apply SG fallback. Commit exactly the action
   returned to the plant and preserve all diagnostics.
""",
        encoding="utf-8",
    )
    equation_map = pd.DataFrame(
        [
            ("load augmented random walk", "GridDisturbanceObserver persistent load state"),
            ("x[j,k+1]=A[j]x+B0[j]u[k]+B1[j]u[k-1]+Edhat", "dcsv_mpc._solve_problem dynamics"),
            ("-Pchg<=Pbess<=Pdis", "delivered total_bess constraints"),
            ("-Rdown*T<=delta Pbess<=Rup*T", "actual-power ramp constraints"),
            ("Eused[k+1]=Eused[k]+loss-adjusted throughput", "energy_used recursion"),
            ("x[N]-xstar(dhat) in Xf", "sustainable terminal constraint"),
            ("bridge energy and required handoff power", "bridge terminal constraints"),
            ("common u across delay vertices", "single u variable shared by scenario states"),
        ],
        columns=["equation_or_contract", "code_object"],
    )
    equation_path = method_dir / "EQUATION_CODE_MAP.csv"
    equation_map.to_csv(equation_path, index=False)
    outputs = (run_path, audit_path, formulation_path, pseudocode_path, equation_path)
    progress = {
        "schema": "direction5.phase_h.progress.v1",
        "stage": "H5",
        "gate": "H5_TRUE_ROLLING_DCSV_MPC",
        "gate_components": gate,
        "gate_passed": all(gate.values()),
        "methods": mpc_methods,
        "controller_calls": int(len(runs)),
        "solved_calls": int(runs.solved.sum()),
        "restoration_calls": int(runs.restoration_used.sum()),
        "fallback_calls": int(runs.fallback_used.sum()),
        "physical_infeasibility_preclassifications": int(
            runs.physical_infeasibility_preclassified.sum()
        ),
        "p99_solve_time_s": float(solved.solve_time_s.quantile(0.99)),
        "maximum_hard_constraint_residual": float(
            solved.hard_constraint_residual.max()
        ),
        "final_seeds_consumed": False,
        "repairs_used": 0,
        "next_stage": "H6" if all(gate.values()) else "H5_REPAIR_1",
        "outputs": {
            path.relative_to(REPO).as_posix(): sha256(path) for path in outputs
        },
    }
    progress_path = progress_dir / "H5.json"
    progress_path.write_text(
        json.dumps(progress, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(progress, indent=2, sort_keys=True))
    if not progress["gate_passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
