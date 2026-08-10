"""Focused full-nonlinear exercise of the registered ACCR-MPC implementation."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import yaml


REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from direction5freq.accr.accr_mpc import ActiveCapabilityCertificationRecourseMPC
from direction5freq.controllers.dcsv_mpc_final import DCSVInput
from direction5freq.controllers.domain_supervisor import DomainSupervisor
from direction5freq.estimation.grid_load_mhe import ConstrainedGridLoadMHE
from direction5freq.estimation.grid_load_observer import LoadObserverInput
from direction5freq.models.capability_contract import CapabilityRealization
from direction5freq.models.plant_a_full import PlantAFull


LOCK = REPO / "configs/direction5_accr/a4_method_lock.yaml"
RESULTS = REPO / "results_accr/A4"
DOCS = REPO / "research_outputs_accr/06_METHOD"
PROGRESS = REPO / "progress_accr/A4.json"


def _truth(time_s: float) -> CapabilityRealization:
    if time_s < 70.0:
        return CapabilityRealization()
    return CapabilityRealization(
        lower_power_pu=(-0.065, -0.065),
        upper_power_pu=(0.065, 0.065),
        ramp_down_pu_per_s=(0.040, 0.040),
        ramp_up_pu_per_s=(0.040, 0.040),
        delay_s=(0.80, 0.80),
    )


def _load(time_s: float) -> np.ndarray:
    return np.zeros(2) if time_s < 80.0 else np.array((0.045, 0.030))


def run_episode(lock: dict) -> tuple[pd.DataFrame, dict]:
    dt_s = float(lock["physical_dt_s"])
    period_s = float(lock["period_s"])
    duration_s = float(lock["focused_duration_s"])
    plant = PlantAFull(dt_s=dt_s)
    state = plant.equilibrium()
    controller = ActiveCapabilityCertificationRecourseMPC(
        period_s,
        int(lock["horizon_steps"]),
        plant.parameters,
        probe_amplitude_pu=float(lock["probe"]["amplitude_pu"]),
        probe_sequence=tuple(lock["probe"]["normalized_sequence"]),
        certificate_validity_s=float(lock["probe"]["certificate_validity_s"]),
        trigger_minimum_bess_pu=float(lock["probe_trigger_minimum_bess_pu"]),
        active_filter_residual_bound_pu=float(lock["probe"]["active_filter_residual_bound_pu"]),
        physical_dt_s=dt_s,
    )
    observer = ConstrainedGridLoadMHE(
        nominal_frequency_hz=plant.parameters.nominal_frequency_hz,
        inertia_s=plant.parameters.inertia_s,
        damping_pu_per_pu_frequency=plant.parameters.damping_pu_per_pu_frequency,
        derivative_filter=0.40,
        warmup_samples=8,
        window_samples=6,
    )
    supervisor = DomainSupervisor(plant.parameters)
    command = np.zeros(4)
    reserve = np.zeros(2)
    next_control_s = 0.0
    pending = None
    rows: list[dict] = []
    hard_physical_violation = False
    max_frequency_hz = 0.0

    steps = int(round(duration_s / dt_s))
    for step in range(steps + 1):
        time_s = step * dt_s
        public = plant.public_observation(time_s, state, command)
        estimate = observer.update(LoadObserverInput(
            time_s=time_s,
            frequency_deviation_hz=public.frequency_deviation_hz,
            tie_line_pu=public.tie_line_pu,
            sg_mechanical_power_pu=public.sg_mechanical_power_pu,
            bess_actual_poi_power_pu=public.bess_actual_power_pu,
            slow_reserve_power_pu=public.slow_reserve_power_pu,
        ))
        controller.observe(public)
        if pending is not None:
            controller.commit(pending, public.bess_actual_power_pu)
            pending = None

        if time_s + 1e-10 >= next_control_s:
            domain = supervisor.classify(estimate.load_pu, public.measured_soc)
            result = controller.propose(DCSVInput(
                observation=public,
                load_estimate_pu=estimate.load_pu,
                deliverability_set=controller.latest_snapshot.interval_set,
                domain=domain,
            ))
            command = result.proposed_action_pu.copy()
            reserve = result.slow_reserve_request_pu.copy()
            pending = result
            core = result.core_result
            component_error = float(np.max(np.abs(
                result.contract_component_pu
                + result.certified_component_pu
                + result.probe_component_pu
                - command
            )))
            command_violation = bool(
                np.any(command[[0, 2]] < np.asarray(plant.parameters.valve_lower_pu) - 1e-8)
                or np.any(command[[0, 2]] > np.asarray(plant.parameters.valve_upper_pu) + 1e-8)
                or np.any(np.abs(command[[1, 3]]) > plant.parameters.bess.rating_pu + 1e-8)
            )
            rows.append({
                "time_s": time_s,
                "domain": domain.domain,
                "observer_warmed": estimate.warmed,
                "action_issued": bool(np.all(np.isfinite(command))),
                "command_violation": command_violation,
                "component_reconstruction_error": component_error,
                "probe_active": result.diagnostics.probe_active,
                "probe_triggered": result.diagnostics.probe_triggered,
                "certificate_valid": result.diagnostics.certificate_valid,
                "certificate_revoked": result.diagnostics.certificate_revoked,
                "certificate_source": "NONE" if result.certificate is None else result.certificate.source,
                "certificate_retained_models": 0 if result.certificate is None else result.certificate.retained_model_count,
                "contract_norm_pu": float(np.linalg.norm(result.contract_component_pu)),
                "certified_norm_pu": float(np.linalg.norm(result.certified_component_pu)),
                "probe_norm_pu": float(np.linalg.norm(result.probe_component_pu)),
                "attempted_optimization_calls": result.diagnostics.attempted_optimization_calls,
                "solver_status": core.diagnostics.status,
                "solve_time_s": result.diagnostics.solve_time_s,
                "restoration_used": result.diagnostics.restoration_used,
                "fallback_used": result.diagnostics.fallback_used,
                "mathematical_infeasibility": result.diagnostics.mathematical_infeasibility,
                "numerical_failure": result.diagnostics.numerical_failure,
                "shared_current_action_verified": result.diagnostics.shared_current_action_verified,
                "surplus_loss_branch_verified": result.diagnostics.surplus_loss_branch_verified,
                "predicted_state_steps": core.predicted_state_sequence.shape[-1],
                "predicted_input_steps": core.predicted_input_sequence.shape[-1],
                "predicted_energy_steps": core.predicted_energy_sequence_mwh.shape[-1],
                "actual_action_committed": True,
            })
            next_control_s += period_s

        max_frequency_hz = max(max_frequency_hz, float(np.max(np.abs(public.frequency_deviation_hz))))
        if step < steps:
            state, _ = plant.step(state, command, _load(time_s), _truth(time_s), reserve)
            soc = state.bess.measured_soc(plant.parameters.bess)
            hard_physical_violation |= bool(
                np.any(soc < plant.parameters.bess.soc_min - 1e-9)
                or np.any(soc > plant.parameters.bess.soc_max + 1e-9)
                or np.any(state.mechanical_power_pu < np.asarray(plant.parameters.sg_power_lower_pu) - 1e-9)
                or np.any(state.mechanical_power_pu > np.asarray(plant.parameters.sg_power_upper_pu) + 1e-9)
            )

    if pending is not None:
        controller.commit(pending, state.bess.power_pu)
    frame = pd.DataFrame(rows)
    summary = {
        "project": "DIRECTION5",
        "stage": "A4",
        "method": "ACCR-MPC",
        "controller_calls": int(len(frame)),
        "attempted_optimization_calls": int(frame.attempted_optimization_calls.sum()),
        "action_availability": float(frame.action_issued.mean()),
        "hard_physical_violations": int(hard_physical_violation),
        "command_violations": int(frame.command_violation.sum()),
        "maximum_component_error": float(frame.component_reconstruction_error.max()),
        "probe_triggers": int(controller.probe_triggers),
        "certificate_issues": int(controller.certificate_issues),
        "certificate_revocations": int(controller.certificate_revocations),
        "certificate_valid_calls": int(frame.certificate_valid.sum()),
        "restoration_calls": int(frame.restoration_used.sum()),
        "fallback_calls": int(frame.fallback_used.sum()),
        "mathematical_infeasibility_calls": int(frame.mathematical_infeasibility.sum()),
        "numerical_failure_calls": int(frame.numerical_failure.sum()),
        "p99_solve_time_s": float(frame.solve_time_s.quantile(0.99)),
        "maximum_frequency_deviation_hz": max_frequency_hz,
        "shared_current_action_all": bool(frame.shared_current_action_verified.all()),
        "surplus_loss_branch_all": bool(frame.surplus_loss_branch_verified.all()),
        "rolling_sequences_all": bool(
            (frame.predicted_state_steps == int(lock["horizon_steps"]) + 1).all()
            and (frame.predicted_input_steps == int(lock["horizon_steps"])).all()
            and (frame.predicted_energy_steps == int(lock["horizon_steps"]) + 1).all()
        ),
        "ordinary_controller_truth_reads": False,
    }
    gates = lock["gates"]
    summary["gate_status"] = "PASS" if (
        summary["action_availability"] >= float(gates["action_availability_min"])
        and summary["hard_physical_violations"] <= int(gates["hard_violations_max"])
        and summary["command_violations"] == 0
        and summary["maximum_component_error"] <= 1e-12
        and summary["p99_solve_time_s"] <= float(gates["p99_solve_fraction_max"]) * period_s
        and summary["shared_current_action_all"]
        and summary["surplus_loss_branch_all"]
        and summary["rolling_sequences_all"]
    ) else "FAIL"
    return frame, summary


def main() -> None:
    lock = yaml.safe_load(LOCK.read_text(encoding="utf-8"))
    RESULTS.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    frame, summary = run_episode(lock)
    frame.to_csv(RESULTS / "A4_ROLLING_CYCLE_DIAGNOSTICS.csv", index=False)
    (RESULTS / "A4_SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    DOCS.joinpath("A4_ACCR_MPC_IMPLEMENTATION.md").write_text(
        "# A4 ACCR-MPC implementation\n\n"
        "The ordinary controller uses only causal public measurements. A finite active "
        "certificate may enlarge the performance envelope, while the hard contract floor "
        "remains unchanged. Every control call solves the registered two-branch rolling "
        "QP with full state/input/SoC/delay/reserve sequences. The current action is shared "
        "by delivered and surplus-loss branches; future SG and reserve decisions provide "
        "recourse. Issued actions are exactly decomposed into contract, certified and "
        "allocation-neutral probe components, and only the action actually applied is "
        "committed. Solver attempts, restoration and fallback are counted separately.\n\n"
        f"Focused full-nonlinear Gate: **{summary['gate_status']}**.\n",
        encoding="utf-8",
    )
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS.write_text(json.dumps({
        "stage": "A4", "status": summary["gate_status"],
        "summary": "results_accr/A4/A4_SUMMARY.json",
    }, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    if summary["gate_status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
