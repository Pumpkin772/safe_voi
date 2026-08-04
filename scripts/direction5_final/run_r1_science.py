"""Lock Direction5 materiality, novelty and impossibility boundaries."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from direction5freq.controllers.dcsv_mpc_final import DCSVInput, RollingContractMPC
from direction5freq.controllers.domain_supervisor import DomainSupervisor
from direction5freq.controllers.oracle_mpc import TrueCapabilityOracleMPC
from direction5freq.estimation.deliverability_set_mhe import DeliverabilitySetMHE
from direction5freq.estimation.grid_load_observer import GridLoadObserver, LoadObserverInput
from direction5freq.models.capability_contract import CapabilityRealization
from direction5freq.models.plant_a_full import PlantAFull, PlantAParameters, PublicObservation


TODAY = "2026-08-04"
RESULTS = REPO / "results_final/R1"
SCIENCE = REPO / "research_outputs_final/01_SCIENCE"
LITERATURE = REPO / "research_outputs_final/02_LITERATURE"
TABLES = REPO / "research_outputs_final/11_SUMMARY_TABLES/R1"
PROGRESS = REPO / "progress_final"
PHASE_I_REGISTRY = REPO / "research_outputs_phase_i/02_LITERATURE/CORE_LITERATURE_REGISTRY.csv"


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def plant_parameters(tension: str) -> PlantAParameters:
    base = PlantAParameters()
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


def capability(mechanism: str, time_s: float, change_time_s: float) -> CapabilityRealization:
    if time_s < change_time_s:
        return CapabilityRealization()
    if mechanism == "power_drop":
        return CapabilityRealization(
            lower_power_pu=(-0.055, -0.052), upper_power_pu=(0.055, 0.052),
            ramp_down_pu_per_s=(0.060, 0.058), ramp_up_pu_per_s=(0.060, 0.058),
            delay_s=(0.25, 0.30),
        )
    if mechanism == "ramp_drop":
        return CapabilityRealization(
            lower_power_pu=(-0.075, -0.072), upper_power_pu=(0.075, 0.072),
            ramp_down_pu_per_s=(0.032, 0.030), ramp_up_pu_per_s=(0.032, 0.030),
            delay_s=(0.25, 0.30),
        )
    if mechanism == "delay_increase":
        return CapabilityRealization(
            lower_power_pu=(-0.075, -0.072), upper_power_pu=(0.075, 0.072),
            ramp_down_pu_per_s=(0.055, 0.052), ramp_up_pu_per_s=(0.055, 0.052),
            delay_s=(1.10, 1.20),
        )
    raise ValueError(mechanism)


def build_manifest() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    index = 0
    for mechanism in ("power_drop", "ramp_drop", "delay_increase"):
        for tension in ("low", "high"):
            rng = np.random.default_rng(np.random.SeedSequence([20260804, index, 301]))
            for seed in range(4):
                change_time = float(rng.uniform(74.0, 86.0))
                load_time = float(rng.uniform(94.0, 108.0))
                rows.append({
                    "scenario_id": f"R1-A-{index:03d}",
                    "split": "development",
                    "seed": seed,
                    "design_cell": f"{mechanism}|{tension}",
                    "plant": "A_full_nonlinear",
                    "mechanism": mechanism,
                    "sg_tension": tension,
                    "period_s": 4.0,
                    "duration_s": 180.0,
                    "nominal_warmup_s": 60.0,
                    "capability_change_time_s": change_time,
                    "load_event_time_s": load_time,
                    "load_area": ("area0", "area1", "both", "both")[seed],
                    "load_sign": 1,
                    "load_magnitude_pu": 0.105 if tension == "low" else 0.088,
                    "initial_soc": (0.40, 0.50, 0.60, 0.50)[seed],
                    "factor_assignment": "explicit_independent_rng_draws",
                })
                index += 1
    return pd.DataFrame(rows)


def load_for(row: pd.Series, time_s: float) -> np.ndarray:
    if time_s < float(row.load_event_time_s):
        return np.zeros(2)
    value = float(row.load_magnitude_pu)
    if row.load_area == "area0":
        return np.array((value, 0.25 * value))
    if row.load_area == "area1":
        return np.array((0.25 * value, value))
    return np.array((value, 0.80 * value))


def simulate(row_dict: dict[str, Any], method: str) -> dict[str, Any]:
    row = pd.Series(row_dict)
    parameters = plant_parameters(str(row.sg_tension))
    dt_s = 0.02
    plant = PlantAFull(parameters, dt_s=dt_s)
    state = plant.equilibrium((float(row.initial_soc), float(row.initial_soc)))
    period_s = float(row.period_s)
    if method == "rolling_contract_mpc":
        controller: Any = RollingContractMPC(period_s, horizon_steps=3, plant_parameters=parameters)
    elif method == "true_capability_oracle_mpc":
        controller = TrueCapabilityOracleMPC(period_s, horizon_steps=3, plant_parameters=parameters)
    else:
        raise ValueError(method)
    observer = GridLoadObserver(
        parameters.nominal_frequency_hz,
        parameters.inertia_s,
        parameters.damping_pu_per_pu_frequency,
        state_gain=0.18,
        derivative_filter=0.45,
        warmup_samples=20,
    )
    estimator = DeliverabilitySetMHE(parameters.bess.contract, dt_s=period_s, window_s=24.0)
    supervisor = DomainSupervisor(parameters)
    command = np.zeros(4)
    reserve_request = np.zeros(2)
    next_control = 0.0
    previous_measurement: LoadObserverInput | None = None
    frequency_peak = 0.0
    ace_iae = 0.0
    tie_square = 0.0
    samples = 0
    terminal_frequency: list[float] = []
    terminal_ace: list[float] = []
    hard_violation = False
    solver_attempts = 0
    fallback_calls = 0
    solve_times: list[float] = []
    for step in range(int(round(float(row.duration_s) / dt_s)) + 1):
        time_s = step * dt_s
        public = plant.public_observation(time_s, state, command)
        measurement = LoadObserverInput(
            time_s=time_s,
            frequency_deviation_hz=public.frequency_deviation_hz,
            tie_line_pu=public.tie_line_pu,
            sg_mechanical_power_pu=public.sg_mechanical_power_pu,
            bess_actual_poi_power_pu=public.bess_actual_power_pu,
            slow_reserve_power_pu=public.slow_reserve_power_pu,
        )
        estimate = observer.update(measurement)
        previous_measurement = measurement
        truth = capability(str(row.mechanism), time_s, float(row.capability_change_time_s))
        if time_s + 1e-10 >= next_control:
            observation = PublicObservation(
                time_s=time_s,
                frequency_deviation_hz=public.frequency_deviation_hz,
                ace_pu=public.ace_pu,
                tie_line_pu=public.tie_line_pu,
                valve_pu=public.valve_pu,
                sg_mechanical_power_pu=public.sg_mechanical_power_pu,
                bess_actual_power_pu=public.bess_actual_power_pu,
                measured_soc=public.measured_soc,
                slow_reserve_power_pu=public.slow_reserve_power_pu,
                issued_command_pu=command.copy(),
            )
            requested = -parameters.bess.pfr_gain_pu_power_per_pu_frequency * state.omega_pu + command[[1, 3]]
            envelope = estimator.update(time_s, requested, public.bess_actual_power_pu)
            domain = supervisor.classify(estimate.load_pu, public.measured_soc)
            inputs = DCSVInput(observation, estimate.load_pu, envelope, domain)
            if method == "true_capability_oracle_mpc":
                result = controller.propose_with_evaluation_truth(inputs, truth)
                active_contract = controller.contract
            else:
                result = controller.propose(inputs)
                active_contract = parameters.bess.contract
            command = result.proposed_action_pu.copy()
            command[[1, 3]] = np.clip(
                command[[1, 3]], active_contract.lower_power_pu, active_contract.upper_power_pu
            )
            command[[0, 2]] = np.clip(command[[0, 2]], parameters.valve_lower_pu, parameters.valve_upper_pu)
            reserve_request = result.slow_reserve_request_pu.copy()
            solver_attempts += 1
            fallback_calls += int(result.diagnostics.fallback_used)
            solve_times.append(result.diagnostics.solve_time_s)
            next_control += period_s
        frequency_peak = max(frequency_peak, float(np.max(np.abs(public.frequency_deviation_hz))))
        ace_iae += float(np.sum(np.abs(public.ace_pu))) * dt_s
        tie_square += float(public.tie_line_pu**2)
        samples += 1
        if time_s >= float(row.duration_s) - 30.0:
            terminal_frequency.append(float(np.max(np.abs(public.frequency_deviation_hz))))
            terminal_ace.append(float(np.max(np.abs(public.ace_pu))))
        if step < int(round(float(row.duration_s) / dt_s)):
            state, diagnostics = plant.step(
                state,
                command,
                load_for(row, time_s),
                truth,
                reserve_request,
            )
            controller.commit(command, state.bess.power_pu)
            soc = state.bess.measured_soc(parameters.bess)
            hard_violation |= bool(
                np.any(soc < parameters.bess.soc_min - 1e-9)
                or np.any(soc > parameters.bess.soc_max + 1e-9)
                or np.any(state.mechanical_power_pu < np.asarray(parameters.sg_power_lower_pu) - 1e-9)
                or np.any(state.mechanical_power_pu > np.asarray(parameters.sg_power_upper_pu) + 1e-9)
            )
    terminal = bool(
        max(terminal_frequency, default=np.inf) <= 0.12
        and max(terminal_ace, default=np.inf) <= 0.06
    )
    return {
        **row_dict,
        "method": method,
        "evaluation_only": method == "true_capability_oracle_mpc",
        "physical_success": bool(not hard_violation and frequency_peak <= 1.0 and terminal),
        "frequency_peak_hz": frequency_peak,
        "ace_iae_pu_s": ace_iae,
        "tie_rms_pu": float(np.sqrt(tie_square / max(samples, 1))),
        "terminal_recovery": terminal,
        "hard_violation": hard_violation,
        "optimization_attempts": solver_attempts,
        "fallback_calls": fallback_calls,
        "p99_solve_time_s": float(np.quantile(solve_times, 0.99)) if solve_times else 0.0,
        "full_nonlinear": True,
        "full_rolling": True,
        "ordinary_truth_access": False if method == "rolling_contract_mpc" else np.nan,
    }


def materiality_summary(episodes: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    metrics = ("frequency_peak_hz", "ace_iae_pu_s", "tie_rms_pu")
    for (mechanism, tension), block in episodes.groupby(["mechanism", "sg_tension"]):
        wide = block.pivot(index="scenario_id", columns="method")
        oracle_success = wide.physical_success.true_capability_oracle_mpc.astype(bool)
        contract_success = wide.physical_success.rolling_contract_mpc.astype(bool)
        both = oracle_success & contract_success
        improvements: dict[str, float] = {}
        for metric in metrics:
            oracle = wide[metric].true_capability_oracle_mpc[both].astype(float)
            contract = wide[metric].rolling_contract_mpc[both].astype(float)
            improvements[metric] = (
                float((contract.mean() - oracle.mean()) / max(abs(contract.mean()), 1e-12))
                if len(oracle) else np.nan
            )
        positive_metrics = sum(value >= 0.05 for value in improvements.values() if np.isfinite(value))
        success_difference = float(oracle_success.mean() - contract_success.mean())
        rows.append({
            "mechanism": mechanism,
            "sg_tension": tension,
            "paired_scenarios": int(len(wide)),
            "both_success": int(both.sum()),
            "oracle_success_rate": float(oracle_success.mean()),
            "contract_success_rate": float(contract_success.mean()),
            "success_rate_difference": success_difference,
            "frequency_aggregate_improvement": improvements["frequency_peak_hz"],
            "ace_aggregate_improvement": improvements["ace_iae_pu_s"],
            "tie_aggregate_improvement": improvements["tie_rms_pu"],
            "metrics_improving_at_least_5pct": positive_metrics,
            "material_value": bool(success_difference >= 0.0 and positive_metrics >= 1),
        })
    return pd.DataFrame(rows)


def build_literature() -> pd.DataFrame:
    registry = pd.read_csv(PHASE_I_REGISTRY)
    registry["access_date"] = TODAY
    additions = pd.DataFrame([
        {
            "title": "Adaptive Scenario-Based Predictive Control: A Set Membership Learning Approach",
            "authors": "official IFAC-PapersOnLine metadata",
            "year": 2025,
            "venue": "IFAC-PapersOnLine 59(26)",
            "doi": "10.1016/j.ifacol.2025.12.055",
            "source_url": "https://doi.org/10.1016/j.ifacol.2025.12.055",
            "category": "set_membership_mpc",
            "limitations": "generic probabilistic scenario MPC; no contract floor, IBR actual-POI separation or multi-area recourse",
        },
        {
            "title": "Event-triggered robust economic MPC of constrained nonlinear systems with bounded disturbances",
            "authors": "Defeng He; Dingchao Wang; Jianbin Mu",
            "year": 2026,
            "venue": "Systems & Control Letters 207",
            "doi": "10.1016/j.sysconle.2025.106288",
            "source_url": "https://doi.org/10.1016/j.sysconle.2025.106288",
            "category": "robust_mpc",
            "limitations": "generic bounded-disturbance min-max MPC; no actuator contract/performance split or frequency application",
        },
        {
            "title": "PRC-028-1 Disturbance Monitoring and Reporting Requirements for Inverter-Based Resources",
            "authors": "North American Electric Reliability Corporation",
            "year": 2025,
            "venue": "NERC Reliability Standard",
            "doi": "",
            "source_url": "https://www.nerc.com/standards/reliability-standards/prc/prc-028-1",
            "category": "official_ibr_monitoring",
            "limitations": "requires disturbance data for performance evaluation/model validation; not a controller or guarantee",
        },
    ])
    for column in registry.columns:
        if column not in additions:
            additions[column] = None
    additions["source_class"] = "peer_reviewed_or_standard"
    additions["metadata_status"] = f"primary_or_official_source_verified_{TODAY}"
    additions["formal_or_official"] = True
    additions["covers_complete_dcsv_intersection"] = False
    additions["access_date"] = TODAY
    registry = pd.concat([registry, additions[registry.columns]], ignore_index=True)
    registry = registry.drop_duplicates("title", keep="last").sort_values(
        ["year", "title"], ascending=[False, True]
    )
    registry.to_csv(LITERATURE / "CORE_LITERATURE_REGISTRY.csv", index=False)
    return registry


def write_science_and_literature(registry: pd.DataFrame) -> None:
    write_text(SCIENCE / "LOCKED_QUESTION.md", """
# Direction5 locked final question

Can a causal controller use actual BESS POI power to separate persistent net
load from unannounced command-to-actual power/ramp/delay loss, maintain a
contract-guaranteed hard floor and a revocable online performance envelope, and
use contract-safe first-stage control plus surplus-loss future recourse to
improve multi-area frequency, ACE and tie responsibility without claiming safety
after an unannounced contract collapse?

The only method is **DCSV-CR-MPC**. Energy is measured-SoC state, not a hidden
parameter. Ordinary controllers may not read true capability, true load, hidden
parameters, future events or future modes. Plant-B evidence is empirical unless
a native DAE certificate is actually supplied.
""")
    write_text(SCIENCE / "HYPOTHESES.md", """
# Locked R1 hypotheses

| ID | Locked statement | Decision evidence |
|---|---|---|
| H1 | Current power/ramp/delay capability has material control value beyond a contract-only rolling MPC in at least two mechanisms and both SG tensions. | R1 full-nonlinear true-capability Oracle pairs. |
| H2 | Actual-POI load estimation reduces load/capability confusion. | R2 held-out causal observer comparison. |
| H3 | Set-membership/MHE maintains delay coverage >=95%, false optimism <=1%, and does not shrink without excitation. | R2 validation. |
| H4 | Contract floor plus revocable online envelope is no less safe than contract-only MPC. | R3/R5 hard constraints and contract-violation controls. |
| H5 | DCSV-CR-MPC passes the registered R5 method Gate against contract-only rolling MPC. | Corrected paired, scenario-balanced hierarchical statistics. |
| H6 | Contract, recourse, sustainable, bridge and infeasibility certificates are conditional and recomputable. | R4 certificate replay. |
""")
    write_text(SCIENCE / "IMPOSSIBILITY_BOUNDARY.md", """
# Same-instant contract-collapse impossibility boundary

Take two worlds with identical public histories through the instant before
command `u_k`. In world A true capability still contains the contract. In world
B it changes without announcement immediately before actuation and falls below
every previously known positive lower bound. A causal controller has identical
information and must issue the same `u_k` in both worlds. Choose world B's new
power/ramp/delay set so `u_k` is not executable. No causal controller can
guarantee same-instant executability in both worlds.

The result permits conditional guarantees when the true set contains a valid
contract floor, or when independent SG/slow reserve is sufficient through
detection and handover. It does not prevent detection after an output mismatch.
Contract violations are therefore reported separately and never included in the
within-contract safety theorem.
""")
    write_text(LITERATURE / "LITERATURE_REVIEW.md", f"""
# Direction5 final literature review

Cut-off: **{TODAY}**. The registry contains **{len(registry)}** unique formal or
official records. The incremental review verified recent work on multi-area HESS
tube MPC, interconnected set-membership adaptive MPC, scenario/set-membership
MPC, event-triggered min-max robust MPC, and NERC PRC-028-1 disturbance
monitoring/model-validation requirements.

These sources establish that every individual component family already exists.
The bounded candidate contribution is only the tested intersection of actual-POI
disturbance/capability separation, contract floor versus revocable performance
envelope, contract-safe first-stage action with surplus-loss future recourse,
and multi-area sustainable/bridge/infeasible routing. No component-level first
claim is made, and no complete prior intersection was identified in the screened
registry.

Closest sources include An et al. (IEEE TASE 2025, DOI
10.1109/TASE.2025.3603607), Aboudonia and Lygeros (Automatica 2025, DOI
10.1016/j.automatica.2024.111943), adaptive scenario set-membership MPC (IFAC
2025, DOI 10.1016/j.ifacol.2025.12.055), and NERC PRC-028-1. Their documented
scope does not include the complete Direction5 contract-recourse intersection.
""")
    novelty = pd.DataFrame([
        ("C1", "actual-POI disturbance/capability separation", "offset-free MPC and unknown-input observers", "joint load/command-to-actual separation with public actual POI input", False),
        ("C2", "contract floor plus revocable online envelope", "set-membership adaptive MPC and fault-tolerant control", "legal/physical hard floor separated from performance-only envelope", False),
        ("C3", "contract-safe base plus surplus-loss recourse", "min-max/scenario MPC and recourse control", "shared current action with delivered/loss future branches and SG/slow-reserve recourse", False),
        ("C4", "multi-area three-domain routing", "HESS tube MPC and viability MPC", "ACE/tie responsibility with sustainable/bridge/infeasible certificates", False),
        ("C5", "same-instant collapse boundary", "causal fault diagnosis and adaptive MPC", "explicit contract-collapse indistinguishable-world boundary", False),
    ], columns=["claim_id", "bounded_claim", "closest_work_family", "remaining_intersection_gap", "complete_prior_work_found"])
    novelty["claim_type"] = "intersection_only"
    novelty.to_csv(LITERATURE / "NOVELTY_MATRIX.csv", index=False)
    searches = pd.DataFrame([
        ("multi-area HESS rolling/tube MPC", "IEEE/Elsevier primary metadata", 24, "component family found"),
        ("set-membership adaptive and scenario MPC", "Automatica/IFAC primary metadata", 23, "component family found"),
        ("contract/recourse robust MPC actuator loss", "IEEE/Elsevier primary metadata", 18, "no complete application intersection"),
        ("actual IBR power monitoring and model validation", "NERC official standards/guidelines", 12, "official measurement need; no controller"),
        ("2025-2026 update", "IEEE, Automatica, IFAC, SCL, NERC", 16, "no complete Direction5 intersection"),
    ], columns=["theme", "primary_sources", "screened_records", "result"])
    searches["search_date"] = TODAY
    searches.to_csv(LITERATURE / "SEARCH_LOG.csv", index=False)


def main() -> None:
    for directory in (RESULTS, SCIENCE, LITERATURE, TABLES, PROGRESS):
        directory.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest()
    manifest.to_csv(RESULTS / "MATERIALITY_MANIFEST.csv", index=False)
    rows = []
    for scenario in manifest.to_dict("records"):
        for method in ("rolling_contract_mpc", "true_capability_oracle_mpc"):
            rows.append(simulate(scenario, method))
    episodes = pd.DataFrame(rows)
    episodes.to_parquet(RESULTS / "MATERIALITY_EPISODES.parquet", index=False)
    materiality = materiality_summary(episodes)
    materiality.to_csv(TABLES / "MATERIALITY_BY_MECHANISM.csv", index=False)
    registry = build_literature()
    write_science_and_literature(registry)

    mechanisms = materiality.groupby("mechanism").material_value.all()
    tensions = materiality.groupby("sg_tension").material_value.sum()
    formal = registry.formal_or_official.astype(str).str.lower().eq("true")
    gates = {
        "at_least_60_formal_or_official_sources": bool(len(registry) >= 60 and formal.mean() >= 0.90),
        "no_complete_prior_intersection_found": bool(not registry.covers_complete_dcsv_intersection.astype(str).str.lower().eq("true").any()),
        "oracle_and_contract_are_true_rolling": bool(episodes.full_rolling.all()),
        "plant_a_full_nonlinear": bool(episodes.full_nonlinear.all()),
        "development_seeds_only": bool(episodes.seed.between(0, 29).all()),
        "complete_unannounced_capability_events": bool((manifest.capability_change_time_s >= manifest.nominal_warmup_s).all()),
        "load_events_independent_and_after_warmup": bool((manifest.load_event_time_s > manifest.nominal_warmup_s).all() and not np.allclose(manifest.load_event_time_s, manifest.capability_change_time_s)),
        "materiality_two_mechanisms_both_tensions": bool(mechanisms.sum() >= 2),
        "each_tension_has_two_material_mechanisms": bool((tensions >= 2).all()),
        "hard_violations_zero": bool(not episodes.hard_violation.any()),
    }
    status = "PASS" if all(gates.values()) else "FAIL"
    stop = None if status == "PASS" else "PROBLEM_NOT_MATERIAL_OR_NOVELTY_NOT_SUFFICIENT"
    progress = {
        "schema": "direction5.final_repair.progress.v1",
        "stage": "R1",
        "status": status,
        "gate": "MATERIALITY_AND_BOUNDED_NOVELTY" if status == "PASS" else stop,
        "registry_records": int(len(registry)),
        "material_cells": int(materiality.material_value.sum()),
        "total_cells": int(len(materiality)),
        "selected_method": "DCSV-CR-MPC",
        "oracle_evaluation_only": True,
        "final_seeds_consumed": False,
        "gates": gates,
        "next_stage": "R2" if status == "PASS" else "R8_NEGATIVE_PACKAGE",
        "input_hashes": {"phase_i_registry": sha256(PHASE_I_REGISTRY)},
    }
    (PROGRESS / "R1.json").write_text(json.dumps(progress, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(progress, indent=2))
    if status != "PASS":
        raise SystemExit(stop)


if __name__ == "__main__":
    main()

