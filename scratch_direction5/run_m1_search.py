"""Run the guarded, sequential M1 VOI-ACCR development search."""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path
import sys
import traceback
from types import SimpleNamespace

import numpy as np
import pandas as pd
import yaml


REPO = Path(__file__).resolve().parents[1]
for path in (REPO / "src", REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import direction5freq.accr.validation as validation
from direction5freq.controllers.voi_accr_mpc import (
    VOIActiveCapabilityCertificationRecourseMPC,
    weighted_contract_mpc_class,
)
from direction5freq.models.capability_contract import CapabilityContract


def make_manifest() -> pd.DataFrame:
    source = pd.read_csv(REPO / "results_accr/A1/A1_MATERIALITY_MANIFEST.csv")
    # M1 requires at least eight cases spanning power/ramp and low/high SG.
    rows = []
    for mechanism in ("power_drop", "ramp_drop"):
        for tension in ("low", "high"):
            chosen = source[
                (source.mechanism == mechanism)
                & (source.sg_tension == tension)
                & (source.period_s == 2.0)
            ].head(2)
            rows.append(chosen)
    manifest = pd.concat(rows, ignore_index=True).copy()
    manifest["source_scenario_id"] = manifest["scenario_id"]
    manifest["scenario_id"] = [f"VOI-M1-{index:02d}" for index in range(len(manifest))]
    manifest["split"] = "development"
    manifest["condition"] = "known"
    manifest["known_ood"] = "known"
    manifest["control_period_s"] = manifest["period_s"]
    manifest["capability_mechanism"] = manifest["mechanism"]
    manifest["initial_soc"] = 0.5
    manifest["duration_s"] = 300.0
    manifest["plant"] = "A_full_nonlinear"
    high_load = manifest["sg_tension"].map({"low": 0.0744, "high": 0.0558})
    high_value = np.arange(len(manifest)) % 2 == 0
    manifest["load_magnitude_pu"] = np.where(high_value, high_load, 0.020)
    manifest["value_region_design"] = np.where(
        high_value, "HIGH_VALUE_CANDIDATE", "LOW_VALUE_CONTROL"
    )
    # Remove the inherited A1 confounding between timing and load area.  Both
    # value regions use the same 14 s load-before-capability separation, while
    # load area is balanced across mechanism/tension cells.
    manifest["load_event_time_s"] = manifest["capability_change_time_s"] - 14.0
    manifest["timing_relation"] = "before"
    manifest["load_area"] = [
        "area0", "area1", "area1", "area0",
        "area0", "area1", "area1", "area0",
    ]
    manifest["load_sign"] = 1.0
    manifest["probe_eligible"] = True
    manifest["contract_violation"] = False
    manifest["contract_status"] = "WITHIN_CONTRACT"
    manifest["materiality_positive"] = high_value
    manifest["factor_assignment"] = "VOI_M1_VALUE_REGION_CROSSED_NOT_SEED_MODULO"
    return manifest


def run_candidate(manifest: pd.DataFrame, candidate: dict, output: Path) -> dict:
    original = validation.ActiveCapabilityCertificationRecourseMPC
    original_rolling = validation.DCSVContractRecourseMPC
    original_policy = validation.ValidationPolicy

    class BoundVOI(VOIActiveCapabilityCertificationRecourseMPC):
        def __init__(self, period_s, horizon_steps, parameters, **kwargs):
            super().__init__(
                period_s,
                int(candidate["horizon_steps"]),
                parameters,
                probe_id=candidate["probe_id"],
                probe_amplitude_pu=candidate["amplitude_pu"],
                probe_sequence=tuple(candidate["sequence"]),
                certificate_validity_s=candidate["validity_s"],
                cooldown_s=candidate["cooldown_s"],
                voi_margin=candidate["voi_margin"],
                action_relevance_norm=candidate["relevance"],
                minimum_oracle_gap=candidate["minimum_oracle_gap"],
                minimum_ace_for_probe=candidate["minimum_ace_for_probe"],
                estimator_window_s=candidate["estimator_window_s"],
                active_filter_residual_bound_pu=candidate["residual_bound_pu"],
                passive_renewal=candidate["passive_renewal"],
                physical_dt_s=kwargs.get("physical_dt_s", 0.05),
                delivered_branch_weight=candidate["delivered_branch_weight"],
                ace_weight=candidate["ace_weight"],
                tie_weight=candidate["tie_weight"],
                frequency_weight=candidate["frequency_weight"],
                bess_effort_weight=candidate["bess_effort_weight"],
                sg_effort_weight=candidate["sg_effort_weight"],
                certificate_confirmation_s=candidate["confirmation_s"],
                latch_abstention=candidate["latch_abstention"],
            )

    weighted_class = weighted_contract_mpc_class(
        ace_weight=candidate["ace_weight"],
        tie_weight=candidate["tie_weight"],
        frequency_weight=candidate["frequency_weight"],
        bess_effort_weight=candidate["bess_effort_weight"],
        sg_effort_weight=candidate["sg_effort_weight"],
    )

    class BoundRolling(weighted_class):
        def __init__(self, period_s, horizon_steps, parameters, **kwargs):
            super().__init__(period_s, int(candidate["horizon_steps"]), parameters)
            self.registered_contract = parameters.bess.contract

        def propose(self, inputs):
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
                if is_contract else
                np.asarray(inputs.deliverability_set.delay_interval_s[:, 1], dtype=float)
            )
            self.contract = CapabilityContract(
                lower_power_pu=tuple(-float(value) for value in power),
                upper_power_pu=tuple(float(value) for value in power),
                ramp_down_pu_per_s=tuple(float(value) for value in ramp),
                ramp_up_pu_per_s=tuple(float(value) for value in ramp),
                maximum_delay_s=tuple(float(value) for value in delay),
            )
            raw = super().propose(inputs)
            values = asdict(raw.diagnostics)
            values["attempted_optimization_calls"] = 2 if (
                raw.diagnostics.restoration_used or raw.diagnostics.fallback_used
            ) else 1
            raw = replace(raw, diagnostics=SimpleNamespace(**values))
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

        def commit(self, action, actual, guaranteed=None):
            super().commit(action, actual)

    class BoundPolicy(original_policy):
        def cycle_diagnostics(self):
            values = super().cycle_diagnostics()
            if self.method == "accr_mpc":
                decision = self.controller.last_decision
                certificate = self.controller.certificate
                values.update({
                    "voi_worthwhile": bool(decision.worthwhile),
                    "voi_reason": decision.reason,
                    "decision_relevance_pu": float(decision.decision_relevance_pu),
                    "oracle_gap_proxy": float(decision.oracle_gap_proxy),
                    "estimated_net_voi": float(decision.net_value),
                    "predicted_diameter_reduction": float(decision.predicted_diameter_reduction),
                    "certificate_issued_time_s": float(
                        certificate.issued_time_s if certificate is not None else np.nan
                    ),
                })
            return values

        def diagnostics(self):
            values = super().diagnostics()
            if self.method == "accr_mpc":
                reductions = self.controller.candidate_diameter_reductions
                values.update({
                    "voi_worthwhile_calls": int(self.controller.worthwhile_calls),
                    "ever_probe_worthwhile": bool(self.controller.worthwhile_calls > 0),
                    "candidate_diameter_reduction": float(np.mean(reductions)) if reductions else 0.0,
                    "minimum_candidate_diameter_reduction": float(min(reductions)) if reductions else 0.0,
                    "unmetered_responsibility_jump_pu": float(
                        self.controller.maximum_unmetered_responsibility_jump_pu
                    ),
                    "passive_renewals": int(self.controller.passive_renewals),
                    "probe_aborts_on_change": int(self.controller.probe_aborts_on_change),
                    "passive_candidate_reductions": int(
                        len(self.controller.passive_candidate_reductions)
                    ),
                })
            return values

    validation.ActiveCapabilityCertificationRecourseMPC = BoundVOI
    validation.DCSVContractRecourseMPC = BoundRolling
    validation.ValidationPolicy = BoundPolicy
    lock = yaml.safe_load((REPO / "configs/direction5_accr/a6_validation_lock.yaml").read_text("utf-8"))
    lock["horizon_steps"] = int(candidate["horizon_steps"])
    lock["probe"] = {
        "amplitude_pu": candidate["amplitude_pu"],
        "normalized_sequence": candidate["sequence"],
        "certificate_validity_s": candidate["validity_s"],
        "residual_bound_pu": candidate["residual_bound_pu"],
        # Compatibility-only fields consumed by ValidationPolicy; BoundVOI
        # rejects the old fixed base and ignores these values.
        "base_bess_pu": 0.0,
        "preload_s": 0.0,
        "trigger_minimum_total_sfr_pu": 0.0,
    }
    checkpoint_path = output / f"{candidate['candidate_id']}_EPISODE_CHECKPOINT.csv"
    checkpoint = (
        pd.read_csv(checkpoint_path) if checkpoint_path.exists() else pd.DataFrame()
    )
    rows = checkpoint.to_dict("records")
    completed = {
        (str(row["scenario_id"]), str(row["method"])) for row in rows
    }
    try:
        for scenario in manifest.to_dict("records"):
            for method in (
                "contract_only_recourse_mpc",
                "accr_mpc",
                "perfect_capability_recourse_oracle",
            ):
                key = (str(scenario["scenario_id"]), method)
                if key in completed:
                    continue
                result = validation.simulate_plant_a_episode(
                    scenario,
                    method,
                    lock,
                    float(candidate["delivered_branch_weight"]),
                    cycle_output_path=(
                        output / "cycle_parts"
                        / f"{scenario['scenario_id']}__{candidate['candidate_id']}__{method}.parquet"
                        if method in {"accr_mpc", "contract_only_recourse_mpc"} else None
                    ),
                )
                result["candidate_id"] = candidate["candidate_id"]
                rows.append(result)
                completed.add(key)
                pd.DataFrame(rows).to_csv(checkpoint_path, index=False)
    finally:
        validation.ActiveCapabilityCertificationRecourseMPC = original
        validation.DCSVContractRecourseMPC = original_rolling
        validation.ValidationPolicy = original_policy
    episodes = pd.DataFrame(rows)
    output.mkdir(parents=True, exist_ok=True)
    episodes.to_csv(output / f"{candidate['candidate_id']}_EPISODES.csv", index=False)
    pivot = episodes.pivot(index="scenario_id", columns="method")
    contract = "contract_only_recourse_mpc"
    active = "accr_mpc"
    oracle = "perfect_capability_recourse_oracle"
    paired = manifest[["scenario_id", "mechanism", "sg_tension", "materiality_positive"]].copy()
    for metric in ("ace_iae_pu_s", "tie_iae_pu_s", "frequency_peak_hz", "sg_mechanical_mileage_pu"):
        paired[f"contract_{metric}"] = paired.scenario_id.map(pivot[metric][contract])
        paired[f"voi_{metric}"] = paired.scenario_id.map(pivot[metric][active])
        paired[f"oracle_{metric}"] = paired.scenario_id.map(pivot[metric][oracle])
    paired["ace_improvement"] = (paired.contract_ace_iae_pu_s - paired.voi_ace_iae_pu_s) / paired.contract_ace_iae_pu_s
    paired["tie_improvement"] = (paired.contract_tie_iae_pu_s - paired.voi_tie_iae_pu_s) / paired.contract_tie_iae_pu_s
    paired["oracle_ace_gap"] = (paired.contract_ace_iae_pu_s - paired.oracle_ace_iae_pu_s) / paired.contract_ace_iae_pu_s
    paired["oracle_tie_gap"] = (paired.contract_tie_iae_pu_s - paired.oracle_tie_iae_pu_s) / paired.contract_tie_iae_pu_s
    active_rows = episodes[episodes.method == active].set_index("scenario_id")
    paired["probe_active_calls"] = paired.scenario_id.map(active_rows.probe_active_calls)
    paired["certificate_issues"] = paired.scenario_id.map(active_rows.certificate_issues)
    paired["hard_violation"] = paired.scenario_id.map(active_rows.hard_violation)
    paired["fallback_calls"] = paired.scenario_id.map(active_rows.fallback_calls)
    paired["probe_worthwhile"] = paired.scenario_id.map(active_rows.ever_probe_worthwhile).astype(bool)
    paired["value_region_design"] = paired.scenario_id.map(
        active_rows.value_region_design
    )
    paired["candidate_diameter_reduction"] = paired.scenario_id.map(
        active_rows.candidate_diameter_reduction
    )
    paired["unmetered_responsibility_jump_pu"] = paired.scenario_id.map(
        active_rows.unmetered_responsibility_jump_pu
    )
    paired["probe_command_l1_pu_s"] = paired.scenario_id.map(
        active_rows.probe_command_l1_pu_s
    )
    action_differences = {}
    false_optimism_counts = {}
    certificate_issue_counts = {}
    for scenario in manifest.to_dict("records"):
        scenario_id = scenario["scenario_id"]
        active_cycle = pd.read_parquet(
            output / "cycle_parts" / f"{scenario_id}__{candidate['candidate_id']}__accr_mpc.parquet"
        )
        contract_cycle = pd.read_parquet(
            output / "cycle_parts"
            / f"{scenario_id}__{candidate['candidate_id']}__contract_only_recourse_mpc.parquet"
        )
        action_columns = [
            "command_sg0_pu", "command_bess0_pu",
            "command_sg1_pu", "command_bess1_pu",
        ]
        aligned = active_cycle[["time_s", *action_columns]].merge(
            contract_cycle[["time_s", *action_columns]],
            on="time_s", suffixes=("_voi", "_contract"), validate="one_to_one",
        )
        action_differences[scenario_id] = float(max(
            np.max(np.abs(
                aligned[f"{column}_voi"] - aligned[f"{column}_contract"]
            )) for column in action_columns
        ))
        issue_delta = active_cycle.certificate_issues_to_date.diff().fillna(
            active_cycle.certificate_issues_to_date
        )
        issue_rows = active_cycle[issue_delta > 0]
        false_count = 0
        for issue in issue_rows.itertuples(index=False):
            truth = validation.capability_for(
                pd.Series(scenario), float(issue.certificate_issued_time_s)
            )
            true_power = np.asarray(truth.upper_power_pu, dtype=float)
            true_ramp = np.asarray(truth.ramp_up_pu_per_s, dtype=float)
            true_delay = np.asarray(truth.delay_s, dtype=float)
            certified_power = np.asarray(
                [issue.certificate_power0_pu, issue.certificate_power1_pu], dtype=float
            )
            certified_ramp = np.asarray(
                [issue.certificate_ramp0_pu_per_s, issue.certificate_ramp1_pu_per_s], dtype=float
            )
            certified_delay = np.asarray(
                [issue.certificate_delay0_s, issue.certificate_delay1_s], dtype=float
            )
            false_count += int(
                np.any(certified_power > true_power + 1e-9)
                or np.any(certified_ramp > true_ramp + 1e-9)
                or np.any(certified_delay < true_delay - 1e-9)
            )
        false_optimism_counts[scenario_id] = false_count
        certificate_issue_counts[scenario_id] = int(len(issue_rows))
    paired["max_contract_action_difference_pu"] = paired.scenario_id.map(action_differences)
    paired["false_optimism_count"] = paired.scenario_id.map(false_optimism_counts)
    paired["audited_certificate_issues"] = paired.scenario_id.map(certificate_issue_counts)
    worthwhile = paired[paired.probe_worthwhile]
    not_worthwhile = paired.drop(worthwhile.index)
    best_metric = max(
        float(worthwhile.ace_improvement.mean()) if len(worthwhile) else -1.0,
        float(worthwhile.tie_improvement.mean()) if len(worthwhile) else -1.0,
    )
    worthwhile_diameter = float(worthwhile.candidate_diameter_reduction.mean()) if len(worthwhile) else 0.0
    total_issues = int(worthwhile.audited_certificate_issues.sum()) if len(worthwhile) else 0
    false_optimism_rate = (
        float(worthwhile.false_optimism_count.sum() / total_issues)
        if total_issues else 0.0
    )
    not_worthwhile_metric_change = float(max(
        ((not_worthwhile.contract_ace_iae_pu_s - not_worthwhile.voi_ace_iae_pu_s).abs()
         / not_worthwhile.contract_ace_iae_pu_s.clip(lower=1e-12)).max()
        if len(not_worthwhile) else 0.0,
        ((not_worthwhile.contract_tie_iae_pu_s - not_worthwhile.voi_tie_iae_pu_s).abs()
         / not_worthwhile.contract_tie_iae_pu_s.clip(lower=1e-12)).max()
        if len(not_worthwhile) else 0.0,
    ))
    not_worthwhile_action_difference = float(
        not_worthwhile.max_contract_action_difference_pu.max()
        if len(not_worthwhile) else 0.0
    )
    unmetered_jump = float(paired.unmetered_responsibility_jump_pu.max())
    summary = {
        **candidate,
        "scenario_count": int(len(paired)),
        "worthwhile_scenarios": int(len(worthwhile)),
        "probed_scenarios": int((paired.probe_active_calls > 0).sum()),
        "hard_violations": int(paired.hard_violation.sum()),
        "fallback_calls": int(paired.fallback_calls.sum()),
        "worthwhile_mean_ace_improvement": float(worthwhile.ace_improvement.mean()) if len(worthwhile) else None,
        "worthwhile_mean_tie_improvement": float(worthwhile.tie_improvement.mean()) if len(worthwhile) else None,
        "worthwhile_best_metric_improvement": best_metric,
        "worthwhile_mean_candidate_diameter_reduction": worthwhile_diameter,
        "worthwhile_false_optimism_rate": false_optimism_rate,
        "worthwhile_audited_certificate_issues": total_issues,
        "total_probe_command_l1_pu_s": float(paired.probe_command_l1_pu_s.sum()),
        "worthwhile_mean_probe_command_l1_pu_s": (
            float(worthwhile.probe_command_l1_pu_s.mean()) if len(worthwhile) else 0.0
        ),
        "not_worthwhile_probe_rate": float((not_worthwhile.probe_active_calls > 0).mean()) if len(not_worthwhile) else 0.0,
        "not_worthwhile_max_relative_metric_change": not_worthwhile_metric_change,
        "not_worthwhile_max_action_difference_pu": not_worthwhile_action_difference,
        "maximum_unmetered_responsibility_jump_pu": unmetered_jump,
        "not_worthwhile_max_abs_metric_change": float(max(
            (not_worthwhile.contract_ace_iae_pu_s - not_worthwhile.voi_ace_iae_pu_s).abs().max() if len(not_worthwhile) else 0.0,
            (not_worthwhile.contract_tie_iae_pu_s - not_worthwhile.voi_tie_iae_pu_s).abs().max() if len(not_worthwhile) else 0.0,
        )),
        "frequency_peak_delta_max_hz": float((paired.voi_frequency_peak_hz - paired.contract_frequency_peak_hz).max()),
        "m1_pass": bool(
            int(paired.hard_violation.sum()) == 0
            and float((paired.voi_frequency_peak_hz - paired.contract_frequency_peak_hz).max()) <= 0.02
            and len(worthwhile) >= 4
            and best_metric >= 0.03
            and worthwhile_diameter >= 0.50
            and false_optimism_rate <= 0.01
            and total_issues >= len(worthwhile)
            and int((worthwhile.audited_certificate_issues > 0).sum()) == len(worthwhile)
            and int((paired.probe_active_calls > 0).sum()) >= 4
            and (len(not_worthwhile) == 0 or float((not_worthwhile.probe_active_calls > 0).mean()) == 0.0)
            and not_worthwhile_metric_change <= 0.01
            and not_worthwhile_action_difference <= 1e-6
            and unmetered_jump <= 1e-12
        ),
    }
    paired.to_csv(output / f"{candidate['candidate_id']}_PAIRED.csv", index=False)
    return summary


def candidate_designs() -> list[dict]:
    sequences = {
        "biphasic_2": [1.0, -1.0],
        "biphasic_4": [1.0, 1.0, -1.0, -1.0],
        "staircase_5": [0.5, 1.0, 0.0, -1.0, -0.5],
        "alternating_4": [1.0, -1.0, 1.0, -1.0],
    }
    # Stratified first screen: short, moderate-amplitude designs first; later
    # rows expand duration/amplitude only if those fail.
    # The first two rows retain the exact controller objective that established
    # positive perfect-information materiality in A1. Later rows explore the
    # preregistered wider weight range; every VOI candidate is compared against
    # a contract-only MPC with the identical objective and horizon.
    raw = [
        ("biphasic_2", 0.0025, 40.0, 60.0, 0.0, 0.001, 0.01, 3, 24.0, 0.0020, 0.20, 30.0, 0.0, 12.0, 0.085, 0.050),
        ("biphasic_2", 0.0050, 60.0, 90.0, 0.0, 0.001, 0.01, 3, 24.0, 0.0020, 0.20, 30.0, 0.0, 12.0, 0.085, 0.050),
        ("alternating_4", 0.0050, 60.0, 90.0, 0.0, 0.001, 0.01, 3, 24.0, 0.0015, 0.20, 30.0, 0.0, 12.0, 0.085, 0.050),
        ("alternating_4", 0.0100, 60.0, 90.0, 0.0, 0.001, 0.01, 3, 24.0, 0.0015, 0.20, 30.0, 0.0, 12.0, 0.085, 0.050),
        ("biphasic_4", 0.0075, 60.0, 90.0, 0.0, 0.001, 0.01, 4, 32.0, 0.0015, 0.20, 30.0, 0.0, 12.0, 0.085, 0.050),
        ("staircase_5", 0.0100, 90.0, 120.0, 0.0, 0.001, 0.01, 4, 32.0, 0.0015, 0.20, 30.0, 0.0, 12.0, 0.085, 0.050),
        ("biphasic_2", 0.0025, 40.0, 60.0, 0.0, 0.001, 0.01, 3, 24.0, 0.0020, 0.20, 35.0, 10.0, 15.0, 0.001, 0.10),
        ("biphasic_2", 0.0050, 60.0, 90.0, 0.0, 0.001, 0.01, 3, 24.0, 0.0020, 0.20, 35.0, 10.0, 15.0, 0.001, 0.10),
        ("alternating_4", 0.0025, 60.0, 90.0, 0.0025, 0.0025, 0.02, 4, 32.0, 0.0020, 0.20, 50.0, 20.0, 25.0, 0.001, 0.10),
        ("biphasic_4", 0.00375, 60.0, 90.0, 0.0025, 0.0025, 0.01, 4, 32.0, 0.0015, 0.50, 50.0, 20.0, 25.0, 0.001, 0.10),
        ("staircase_5", 0.00375, 90.0, 120.0, 0.005, 0.0025, 0.01, 6, 48.0, 0.0015, 0.50, 50.0, 20.0, 25.0, 0.01, 0.10),
        ("alternating_4", 0.0050, 90.0, 120.0, 0.005, 0.005, 0.02, 6, 48.0, 0.0015, 0.50, 50.0, 20.0, 25.0, 0.001, 0.10),
        ("biphasic_2", 0.0100, 40.0, 90.0, 0.0, 0.001, 0.01, 3, 24.0, 0.0015, 0.20, 30.0, 0.0, 12.0, 0.085, 0.050),
        ("biphasic_2", 0.0025, 4.0, 60.0, 0.0, 0.001, 0.01, 3, 24.0, 0.0020, 0.20, 30.0, 0.0, 12.0, 0.085, 0.050),
        ("biphasic_2", 0.0025, 4.0, 60.0, 0.0025, 0.001, 0.01, 3, 24.0, 0.0020, 0.20, 30.0, 0.0, 12.0, 0.085, 0.050),
        ("biphasic_2", 0.0025, 4.0, 60.0, 0.0025, 0.001, 0.01, 3, 24.0, 0.0020, 0.20, 30.0, 0.0, 12.0, 0.085, 0.050),
    ]
    candidates = []
    for index, values in enumerate(raw):
        (
            probe_id, amplitude, validity, cooldown, margin, relevance, gap,
            horizon, window, residual, branch, ace, tie, frequency, bess, sg,
        ) = values
        candidates.append({
            "candidate_id": f"M1-C{index:02d}",
            "probe_id": probe_id,
            "sequence": sequences[probe_id],
            "amplitude_pu": amplitude,
            "validity_s": validity,
            "cooldown_s": cooldown,
            "voi_margin": margin,
            "relevance": relevance,
            "minimum_oracle_gap": gap,
            "minimum_ace_for_probe": 0.03 if index == len(raw) - 1 else 0.0,
            "horizon_steps": horizon,
            "estimator_window_s": window,
            "residual_bound_pu": residual,
            "delivered_branch_weight": branch,
            "ace_weight": ace,
            "tie_weight": tie,
            "frequency_weight": frequency,
            "bess_effort_weight": bess,
            "sg_effort_weight": sg,
            "passive_renewal": bool(index % 2),
            "confirmation_s": (
                0.0 if probe_id == "biphasic_2" and validity <= 4.0 else None
            ),
            "latch_abstention": bool(index == len(raw) - 1),
        })
    return candidates


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-candidates", type=int, default=6)
    parser.add_argument("--start-candidate", type=int, default=0)
    parser.add_argument("--scenario-limit", type=int, default=0)
    parser.add_argument("--run-label", default="VOI_V2")
    args = parser.parse_args()
    if not args.run_label.replace("-", "").replace("_", "").isalnum():
        raise ValueError("run-label must contain only letters, digits, hyphens, or underscores")
    output = REPO / "research_outputs_working/M1/runs" / args.run_label
    output.mkdir(parents=True, exist_ok=True)
    manifest = make_manifest()
    if args.scenario_limit > 0:
        manifest = manifest.head(args.scenario_limit).copy()
    manifest.to_csv(output / "M1_DEVELOPMENT_MANIFEST.csv", index=False)
    summaries = []
    selected = candidate_designs()[
        args.start_candidate : args.start_candidate + args.max_candidates
    ]
    for candidate in selected:
        print(f"RUN {candidate['candidate_id']}", flush=True)
        summary = run_candidate(manifest, candidate, output)
        summaries.append(summary)
        pd.DataFrame(summaries).to_csv(output / "M1_SEARCH_SUMMARY.csv", index=False)
        (REPO / "progress_working.json").write_text(json.dumps({
            "project": "DIRECTION5",
            "method": "VOI-ACCR-MPC",
            "milestone": "M1",
            "run_label": args.run_label,
            "candidates_completed": len(summaries),
            "latest": summary,
            "m1_reached": bool(summary["m1_pass"]),
            "git_writes_permitted": bool(summary["m1_pass"]),
        }, indent=2) + "\n", "utf-8")
        print(json.dumps(summary, indent=2), flush=True)
        if summary["m1_pass"]:
            break


if __name__ == "__main__":
    try:
        main()
    except Exception:
        error_path = REPO / "research_outputs_working/M1/M1_SEARCH_ERROR.log"
        error_path.parent.mkdir(parents=True, exist_ok=True)
        error_path.write_text(traceback.format_exc(), encoding="utf-8")
        raise
