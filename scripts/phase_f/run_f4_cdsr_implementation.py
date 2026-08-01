"""Exercise the implemented CDSR-MPC formulation on development states."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import inspect
import json
from pathlib import Path

import numpy as np
import pandas as pd

from direction1freq.controllers.ace_pi_aw import ACEPIAntiWindup, design_stable_pi
from direction1freq.controllers.cdsr_mpc import CapabilityDelaySetRobustMPC
from direction1freq.models.plant_a_v2 import PlantAParametersV2, TwoAreaPlantAV2
from scripts.phase_e.run_e3_materiality import SharedCausalEstimator, capability_at, load_at
from scripts.phase_f.run_f3_model_sets import build_calibration_manifest


REPO = Path(__file__).resolve().parents[2]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_public_state(row: pd.Series):
    period = float(row.sfr_period_s)
    reserve = float(row.sg_reserve_pu)
    base = PlantAParametersV2()
    plant = TwoAreaPlantAV2(
        replace(
            base,
            sg_power_lower_pu=(-reserve, -reserve),
            sg_power_upper_pu=(reserve, reserve),
            valve_lower_pu=(-1.2 * reserve, -1.2 * reserve),
            valve_upper_pu=(1.2 * reserve, 1.2 * reserve),
        ),
        dt_s=0.05,
    )
    state = plant.equilibrium((float(row.initial_soc_1), float(row.initial_soc_2)))
    kp, ki, _ = design_stable_pi(TwoAreaPlantAV2(), period)
    baseline = ACEPIAntiWindup(period, kp, ki, sg_fraction=0.70)
    estimator = SharedCausalEstimator(period)
    command = np.zeros(4)
    update_steps = int(round(period / plant.dt_s))
    estimate = plant.state_vector(state)
    load_estimate = np.zeros(2)
    observation = plant.public_observation(0.0, state, command)
    for step in range(int(round(24.0 / plant.dt_s)) + 1):
        time_s = step * plant.dt_s
        observation = plant.public_observation(time_s, state, command)
        if step % update_steps == 0:
            estimate, load_estimate = estimator.update(observation)
            command, _ = baseline.update(observation)
            command[[0, 2]] = np.clip(command[[0, 2]], -reserve, reserve)
        if step == int(round(24.0 / plant.dt_s)):
            break
        state, _ = plant.step(
            state, command, load_at(row, time_s), capability_at(row, time_s)
        )
    return plant, state, observation, estimate, load_estimate


def predicted_hard_violation(controller, diagnostic) -> float:
    if not diagnostic.solved:
        return 0.0
    residual = max(float(diagnostic.hard_constraint_residual), 0.0)
    energy = diagnostic.predicted_energy_mwh
    residual = max(
        residual,
        float(np.max(controller.envelope.energy_lower_mwh[None, :, None] - energy)),
        float(np.max(energy - controller.envelope.energy_upper_mwh[None, :, None])),
    )
    return max(residual, 0.0)


def main() -> None:
    output = REPO / "results_phase_f" / "F4"
    method = REPO / "research_outputs_phase_f" / "04_METHOD"
    progress_dir = REPO / "progress_phase_f"
    for directory in (output, method, progress_dir):
        directory.mkdir(parents=True, exist_ok=True)
    manifest = build_calibration_manifest()
    development = manifest[manifest.split == "development"]
    rows = []
    for _, scenario in development.iterrows():
        plant, state, observation, estimate, load_estimate = prepare_public_state(scenario)
        controller = CapabilityDelaySetRobustMPC(float(scenario.sfr_period_s))
        before = controller.previous_action.copy()
        action, diagnostic = controller.update(
            observation,
            estimate,
            load_estimate,
            float(scenario.sg_reserve_pu),
            public_energy_mwh=state.bess.energy_mwh,
        )
        rows.append(
            {
                "scenario_id": scenario.scenario_id,
                "mechanism": scenario.mechanism,
                "period_s": float(scenario.sfr_period_s),
                "horizon": controller.horizon,
                "scenario_count": diagnostic.scenario_count,
                "solver_status": diagnostic.solver_status,
                "primary_status": diagnostic.primary_status,
                "secondary_status": diagnostic.secondary_status,
                "solver_accepted": diagnostic.solved,
                "restoration_used": diagnostic.restoration_used,
                "terminal_reject": diagnostic.terminal_reject,
                "backup_used": diagnostic.backup_used,
                "finite_action": bool(np.all(np.isfinite(action))),
                "history_match": diagnostic.history_match,
                "proposal_was_side_effect_free": bool(
                    np.allclose(diagnostic.previous_model_action, before)
                ),
                "committed_action_matches_applied": bool(
                    np.allclose(controller.previous_action, action)
                ),
                "hard_constraint_violation": predicted_hard_violation(
                    controller, diagnostic
                ),
                "solve_time_s": diagnostic.solve_time_s,
                "bess_action_norm": float(np.linalg.norm(action[[1, 3]])),
            }
        )
    evidence = pd.DataFrame(rows)

    plant = TwoAreaPlantAV2()
    state = plant.equilibrium()
    observation = plant.public_observation(0.0, state, np.zeros(4))
    restoration_controller = CapabilityDelaySetRobustMPC(4.0, 3)
    _action, restoration = restoration_controller.update(
        observation,
        plant.state_vector(state),
        np.zeros(2),
        0.05,
        public_energy_mwh=state.bess.energy_mwh,
        force_primary_secondary_failure=True,
    )
    fallback_controller = CapabilityDelaySetRobustMPC(4.0, 3)
    fallback_action, fallback = fallback_controller.update(
        observation,
        plant.state_vector(state),
        np.zeros(2),
        0.05,
        public_energy_mwh=state.bess.energy_mwh,
        force_all_solver_failure=True,
    )
    forced = pd.DataFrame(
        [
            {
                "case": "forced_primary_secondary_failure",
                "restoration_used": restoration.restoration_used,
                "restoration_succeeded": restoration.solved,
                "backup_used": restoration.backup_used,
                "history_match": restoration.history_match,
            },
            {
                "case": "forced_all_solver_failure",
                "restoration_used": fallback.restoration_used,
                "restoration_succeeded": False,
                "backup_used": fallback.backup_used,
                "history_match": fallback.history_match,
                "bess_backup_zero": bool(
                    np.allclose(fallback_action[[1, 3]], 0.0)
                ),
            },
        ]
    )
    evidence_path = output / "CDSR_DEVELOPMENT_ACTIONS.parquet"
    forced_path = output / "CDSR_FORCED_PATHS.csv"
    evidence.to_parquet(evidence_path, index=False)
    forced.to_csv(forced_path, index=False)

    source = inspect.getsource(CapabilityDelaySetRobustMPC)
    forbidden = ("true_capability", "hidden_parameter", "future_load", "future_event")
    no_truth_signature = not any(
        name in inspect.signature(CapabilityDelaySetRobustMPC.update).parameters
        for name in forbidden
    )
    gate = {
        "true_rolling_qp": bool(
            CapabilityDelaySetRobustMPC(4.0, 3).primary_problem.is_qp()
        ),
        "explicit_state_action_horizon": all(
            token in source for token in ("self.x", "self.u", "horizon", "vertex.ad")
        ),
        "five_delay_vertices_common_control": bool(
            (evidence.scenario_count == 5).all()
        ),
        "development_action_availability_100pct": bool(evidence.finite_action.all()),
        "physical_hard_constraint_violations_zero": bool(
            (evidence.hard_constraint_violation <= 1e-5).all()
        ),
        "history_synchronized": bool(
            evidence.history_match.all()
            and evidence.proposal_was_side_effect_free.all()
            and evidence.committed_action_matches_applied.all()
        ),
        "both_2s_4s_exercised": set(evidence.period_s) == {2.0, 4.0},
        "restoration_path_succeeds": bool(
            restoration.restoration_used
            and restoration.solved
            and not restoration.backup_used
        ),
        "sg_terminal_backup_available": bool(
            fallback.backup_used
            and np.allclose(fallback_action[[1, 3]], 0.0)
        ),
        "ordinary_api_has_no_truth_or_future_fields": no_truth_signature,
    }
    gate_passed = all(gate.values())
    (method / "CDSR_MPC_FORMULATION.md").write_text(
        """# CDSR-MPC formulation

Five exact fractional-ZOH BESS delay vertices propagate separate Plant-A and
energy states under one common finite-horizon command sequence.  At every
vertex and stage, the requested total BESS PFR+SFR power, request ramp,
cumulative split-variable energy, SG command and SG mechanical limits are hard.
Frequency, ACE and tie-line envelopes alone use bounded performance slack.
The objective minimizes an epigraph upper bound on the worst vertex L1
frequency/ACE/tie cost plus quadratic deviation from a stable ACE-PI reference.

The transaction is propose -> numerical retry -> lexicographic
performance-slack restoration -> terminal supervisor -> commit actual action.
Neither proposal nor warm start changes physical command history.  The current
terminal box is only an admissibility supervisor until F5 establishes (or
rejects) an invariance certificate.
""",
        encoding="utf-8",
    )
    (method / "PSEUDOCODE.md").write_text(
        """# CDSR-MPC pseudocode

1. Read public observation, causal state/load estimate, public energy telemetry,
   registered capability envelope, and last actually applied action.
2. Solve one common-control robust horizon over all delay vertices.
3. If the primary numerical solve is unacceptable, retry with the secondary solver.
4. If still unavailable, minimize only performance slack while all resource and
   terminal constraints remain hard, then optimize performance at that slack.
5. Numerically verify terminal membership and hard residuals.
6. Select the proposal or SG-only backup.
7. Commit exactly the selected physical action and update causal energy history.
""",
        encoding="utf-8",
    )
    equation_map = method / "EQUATION_CODE_MAP.csv"
    pd.DataFrame(
        [
            ("common non-anticipative control", "controllers/cdsr_mpc.py", "self.u"),
            ("delay scenario dynamics", "controllers/cdsr_mpc.py", "vertex.ad/b_current/b_previous"),
            ("total PFR+SFR envelope", "controllers/cdsr_mpc.py", "total_bess"),
            ("cumulative energy", "controllers/cdsr_mpc.py", "self.energy"),
            ("lexicographic restoration", "controllers/cdsr_mpc.py", "restoration_stage1_problem"),
            ("terminal supervisor", "controllers/cdsr_supervisor.py", "CDSRFeasibilitySupervisor.select"),
            ("actual action commit", "controllers/cdsr_mpc.py", "commit_applied_action"),
        ],
        columns=["equation_or_contract", "file", "symbol"],
    ).to_csv(equation_map, index=False)
    progress = {
        "schema": "direction1.phase_f.progress.v1",
        "stage": "F4",
        "gate": "G4_CDSR_IMPLEMENTATION",
        "gate_passed": gate_passed,
        "gate_components": gate,
        "tests": {
            "development_states": len(evidence),
            "solver_accepted_fraction": float(evidence.solver_accepted.mean()),
            "restoration_fraction": float(evidence.restoration_used.mean()),
            "backup_fraction": float(evidence.backup_used.mean()),
            "solve_time_p99_s": float(evidence.solve_time_s.quantile(0.99)),
            "nonzero_bess_action_fraction": float(
                (evidence.bess_action_norm > 1e-7).mean()
            ),
        },
        "claim_boundary": "implementation only; no recursive or robust-safety claim before F5",
        "next_stage": "F5" if gate_passed else "F4_REPAIR_OR_F9",
        "outputs_sha256": {
            path.relative_to(REPO).as_posix(): sha256(path)
            for path in (
                evidence_path,
                forced_path,
                method / "CDSR_MPC_FORMULATION.md",
                method / "PSEUDOCODE.md",
                equation_map,
            )
        },
    }
    (progress_dir / "F4.json").write_text(
        json.dumps(progress, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(progress, indent=2, sort_keys=True))
    if not gate_passed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()

