"""Lock the Phase D terminal negative-result protocol after the fatal H2 Gate.

The manifest is intentionally a *planned but not executed* final design.  It
keeps every factor explicit and crosses every scenario cell with the same 20
independent final seeds.  No final seed is consumed by a simulator or used to
tune the estimator/controller.
"""
from __future__ import annotations

import csv
import hashlib
import itertools
import json
import subprocess
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts_phase_d" / "D7"
RESULTS = ROOT / "results_phase_d" / "D7"
REPORTS = ROOT / "research_outputs_phase_d" / "experiment_design"
PROGRESS = ROOT / "progress_phase_d" / "D7.json"
FATAL_REASON = "not_evaluated_due_to_H2_PASSIVE_CAPABILITY_SET_NOT_SUPPORTED"
FINAL_SEEDS = [
    15485863, 32452843, 49979687, 67867967, 86028121,
    104395303, 122949823, 141650939, 160481183, 179424673,
    198491317, 217645199, 236887699, 256203221, 275604541,
    295075147, 314606891, 334214467, 353868013, 373587883,
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def git_text(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def design_cells() -> list[dict[str, object]]:
    """Build 120 preregistered cells without encoding factors in episode seeds."""
    plants = ["A", "B"]
    mechanisms = [
        "nominal", "headroom_only", "ramp_only", "delay_only",
        "energy_only", "availability_only",
    ]
    severities = ["mild", "medium", "severe"]
    sg_levels = ["adequate", "scarce", "critical"]
    sfr_periods = [2, 4]
    relations = ["before", "simultaneous", "after", "no_incident"]
    load_shapes = ["step", "ramp", "pulse", "stochastic_net_load"]
    noise_levels = ["low", "medium", "high"]
    communications = ["normal", "jitter", "random_dropout"]
    soc_bands = ["low_0p25_0p40", "mid_0p45_0p60", "high_0p65_0p80"]

    cells: list[dict[str, object]] = []
    core = itertools.product(plants, mechanisms, severities, sg_levels)
    for index, (plant, mechanism, severity, sg_level) in enumerate(core):
        # These rotations are part of the locked design table, not functions of
        # episode seeds.  The complete core crosses Plant/mechanism/severity/SG.
        cells.append(
            {
                "design_cell": f"core_{index:03d}",
                "plant": plant,
                "sfr_period_s": sfr_periods[(index // 3) % len(sfr_periods)],
                "sg_reserve": sg_level,
                "mechanism": mechanism,
                "severity": severity,
                "capability_change_time_policy": "uniform_20_120_s",
                "load_event_relation": relations[(index * 3 + 1) % len(relations)],
                "load_shape": load_shapes[(index * 5 + 2) % len(load_shapes)],
                "measurement_noise": noise_levels[(index * 7 + 1) % len(noise_levels)],
                "communication": communications[(index * 11 + 2) % len(communications)],
                "initial_soc_band": soc_bands[(index * 13) % len(soc_bands)],
                "knowledge_split": "final_known" if mechanism != "nominal" else "final_known_negative_control",
            }
        )

    ood_mechanisms = [
        "asymmetric_power_ramp", "dynamic_q_current_limit",
        "third_order_nonminimum_phase", "time_varying_random_delay",
        "slow_drift", "multiple_switches", "load_capability_simultaneous",
        "unknown_initial_energy", "service_restoration",
    ]
    for offset, mechanism in enumerate(ood_mechanisms + ["indistinguishable_candidates"] * 3):
        index = len(cells)
        cells.append(
            {
                "design_cell": f"ood_{offset:03d}",
                "plant": plants[offset % 2],
                "sfr_period_s": sfr_periods[(offset // 2) % 2],
                "sg_reserve": sg_levels[offset % 3],
                "mechanism": mechanism,
                "severity": severities[(offset // 3) % 3],
                "capability_change_time_policy": "uniform_20_120_s",
                "load_event_relation": relations[offset % 4],
                "load_shape": load_shapes[(offset + 1) % 4],
                "measurement_noise": noise_levels[(offset + 2) % 3],
                "communication": communications[(offset + 1) % 3],
                "initial_soc_band": soc_bands[(offset + 2) % 3],
                "knowledge_split": "final_ood",
            }
        )
    assert len(cells) == 120
    return cells


def build_scenario_manifest() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for cell in design_cells():
        for replicate, seed in enumerate(FINAL_SEEDS):
            row = dict(cell)
            row.update(
                {
                    "scenario_id": f"{cell['design_cell']}_seed_{replicate:02d}",
                    "episode_seed": seed,
                    "factor_source": "explicit_locked_manifest",
                    "execution_status": "not_evaluated",
                    "status_reason": FATAL_REASON,
                }
            )
            rows.append(row)
    frame = pd.DataFrame(rows)
    assert len(frame) == 2400
    return frame


def controller_manifest() -> pd.DataFrame:
    controllers = [
        ("sg_only_ace_pi", "deployable", "baseline"),
        ("fixed_allocation_pi", "deployable", "baseline"),
        ("nominal_linear_mpc", "deployable", "baseline"),
        ("true_rls_adaptive_mpc", "deployable", "baseline"),
        ("worst_case_tube_mpc", "deployable", "baseline"),
        ("crcs_tmpc", "deployable", "proposed"),
        ("current_capability_rolling_nmpc_oracle", "evaluation_only", "oracle"),
    ]
    return pd.DataFrame(
        [
            {
                "controller": name,
                "information_boundary": boundary,
                "role": role,
                "implementation_status": "not_implemented_after_fatal_H2_gate",
                "execution_status": "not_evaluated",
                "status_reason": FATAL_REASON,
                "rolling_horizon_audit": "not_applicable_not_implemented",
            }
            for name, boundary, role in controllers
        ]
    )


def main() -> int:
    for path in (OUT, RESULTS, REPORTS, PROGRESS.parent):
        path.mkdir(parents=True, exist_ok=True)

    scenarios = build_scenario_manifest()
    controllers = controller_manifest()
    scenario_path = RESULTS / "SCENARIO_MANIFEST.csv"
    controller_path = RESULTS / "CONTROLLER_MANIFEST.csv"
    scenarios.to_csv(scenario_path, index=False, quoting=csv.QUOTE_MINIMAL)
    controllers.to_csv(controller_path, index=False)

    seed_firewall = {
        "schema": "direction1.phase_d.d7.seed_firewall.v1",
        "final_seeds": FINAL_SEEDS,
        "final_seeds_used_for_tuning": False,
        "final_episodes_executed": 0,
        "all_cells_share_identical_seed_set": True,
        "seed_encodes_factors": False,
        "seed_percent_factor_encoding": False,
        "reason_not_executed": FATAL_REASON,
    }
    write_json(RESULTS / "SEED_FIREWALL.json", seed_firewall)

    lock_candidates = sorted(
        p for base in (ROOT / "src" / "direction1freq", ROOT / "configs" / "phase_d", ROOT / "scripts" / "phase_d")
        for p in base.rglob("*") if p.is_file() and "__pycache__" not in p.parts
    )
    locked_hashes = {str(p.relative_to(ROOT)).replace("\\", "/"): sha256(p) for p in lock_candidates}
    locked_hashes.update(
        {
            str(scenario_path.relative_to(ROOT)).replace("\\", "/"): sha256(scenario_path),
            str(controller_path.relative_to(ROOT)).replace("\\", "/"): sha256(controller_path),
        }
    )
    write_json(OUT / "LOCKED_HASHES.json", locked_hashes)

    protocol = {
        "schema": "direction1.phase_d.d7.final_protocol_lock.v1",
        "lock_scope": "terminal_negative_result_after_H2_fatal_gate",
        "research_status": "PASSIVE_CAPABILITY_SET_NOT_SUPPORTED",
        "fatal_gate": "H2",
        "d4_d5_d6_d8_controller_experiments": "not_evaluated",
        "not_evaluated_is_method_failure": False,
        "planned_scenario_count": int(len(scenarios)),
        "planned_controller_count": int(len(controllers)),
        "executed_final_episode_count": 0,
        "factor_encoding": "explicit columns; identical final seed set crossed with every design cell",
        "final_seeds_used_for_tuning": False,
        "post_final_parameter_changes_allowed": False,
        "git_branch": git_text("branch", "--show-current"),
        "git_commit_at_lock": git_text("rev-parse", "HEAD"),
        "scenario_manifest_sha256": sha256(scenario_path),
        "controller_manifest_sha256": sha256(controller_path),
        "locked_hashes_sha256": sha256(OUT / "LOCKED_HASHES.json"),
    }
    write_json(OUT / "FINAL_PROTOCOL_LOCK.json", protocol)

    (REPORTS / "STATISTICAL_ANALYSIS_PLAN.md").write_text(
        "# Locked statistical analysis plan\n\n"
        "The fatal H2 Gate precedes controller/Oracle evaluation. Therefore no H1, H3, H4, "
        "known/OOD, ablation, Pareto, or controller success-first comparison is computed. "
        "Those cells remain `not_evaluated`, never method failures.\n\n"
        "For the completed D3 experiment, report joint and marginal truth coverage, false and "
        "pre-change alarm rates, per-mechanism update-before-loss probability, and the exact "
        "numbers of timing-evaluated versus not-applicable episodes. No mean episode-wise "
        "relative percentages are used. All development rounds and validation failures remain.\n",
        encoding="utf-8",
    )
    (REPORTS / "METRIC_DICTIONARY.csv").write_text(
        "metric,unit,aggregation,interpretation\n"
        "joint_coverage,fraction,time-weighted_then_episode-balanced,truth inside all capability intervals\n"
        "power_coverage,fraction,time-weighted_then_episode-balanced,truth inside power interval\n"
        "ramp_coverage,fraction,time-weighted_then_episode-balanced,truth inside ramp interval\n"
        "delay_coverage,fraction,time-weighted_then_episode-balanced,truth inside delay interval\n"
        "energy_coverage,fraction,time-weighted_then_episode-balanced,truth inside energy interval\n"
        "false_alarm_rate,fraction,scenario-balanced,no-change episode with an alarm\n"
        "prechange_alarm_rate,fraction,scenario-balanced,alarm before physical change\n"
        "update_before_control_loss,fraction,mechanism-balanced,causal update precedes registered loss time\n",
        encoding="utf-8",
    )
    (REPORTS / "COMPUTE_BUDGET.md").write_text(
        "# Compute budget and terminal stop\n\n"
        "D0-D2 verification and D3 development/validation were completed locally on Windows "
        "with four worker processes for D3. The planned final matrix contains 2,400 scenarios "
        "per controller, but zero final controller episodes were run because H2 is a fatal "
        "scientific Gate. Running them would violate the automatic-stop contract.\n",
        encoding="utf-8",
    )

    outputs = [scenario_path, controller_path, RESULTS / "SEED_FIREWALL.json", OUT / "LOCKED_HASHES.json", OUT / "FINAL_PROTOCOL_LOCK.json"]
    progress = {
        "stage": "D7",
        "status": "COMPLETED_NEGATIVE_PATH",
        "goal": "Lock independent final factors and seed firewall without crossing the fatal H2 stop",
        "inputs_sha256": {"h2_gate": sha256(ROOT / "results_phase_d" / "D3" / "h2_gate.json")},
        "commands": ["python scripts/phase_d/d7_lock_negative_protocol.py"],
        "tests": {"planned_rows": 2400, "final_rows_executed": 0, "all_cells_share_seed_set": True},
        "gate": "D7_PROTOCOL_INTEGRITY",
        "gate_passed": True,
        "failures": [],
        "repairs": [],
        "outputs_sha256": {str(p.relative_to(ROOT)).replace("\\", "/"): sha256(p) for p in outputs},
        "next_stage": "D8_NEGATIVE_RESULT_SYNTHESIS",
    }
    write_json(PROGRESS, progress)
    print(json.dumps({"rows": len(scenarios), "controllers": len(controllers), "gate": "PASS", "final_executed": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
