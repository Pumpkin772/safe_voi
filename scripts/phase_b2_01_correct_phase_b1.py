"""Reanalyse existing Phase-B1 CSV evidence without rerunning any episode."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from d5freq.evaluation.phase_b2_baseline import verify_phase_b1_baseline_manifest
from d5freq.evaluation.phase_b2_protocol import PhaseB2Paths
from d5freq.evaluation.phase_b2_statistics import (
    CONTROL_COMPARISONS,
    add_total_cost_columns,
    build_corrected_comparison_table,
    build_corrected_materiality_table,
    build_corrected_phase_b1_decision,
    build_paired_failure_outcomes,
    strict_bottleneck_decision,
)
from d5freq.utils.hashing import sha256_file


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--repo-root", type=Path, default=Path("."))
    return result


def _write_csv(frame: pd.DataFrame, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(destination, index=False, lineterminator="\n")


def _bug_regression_text() -> str:
    labels = {
        "MODEL_MISMATCH_DOMINANT": False,
        "IDENTIFIABILITY_DOMINANT": False,
        "CONTROL_DESIGN_DOMINANT": False,
    }
    scores = {name: value for name, value in zip(labels, (0.81, 0.73, 0.86))}
    checks = [
        (
            "all_false",
            strict_bottleneck_decision(
                problem_material=True,
                triggers=labels,
                normalized_scores=scores,
            ),
            "INCONCLUSIVE_REQUIRES_MORE_EVIDENCE",
        ),
        (
            "model_only",
            strict_bottleneck_decision(
                problem_material=True,
                triggers={**labels, "MODEL_MISMATCH_DOMINANT": True},
                normalized_scores=scores,
            ),
            "MODEL_MISMATCH_DOMINANT",
        ),
        (
            "two_active",
            strict_bottleneck_decision(
                problem_material=True,
                triggers={
                    **labels,
                    "MODEL_MISMATCH_DOMINANT": True,
                    "IDENTIFIABILITY_DOMINANT": True,
                },
                normalized_scores=scores,
            ),
            "COMBINED:MODEL_MISMATCH_DOMINANT+IDENTIFIABILITY_DOMINANT",
        ),
    ]
    lines = ["Phase-B1 bottleneck decision bug regression"]
    for name, actual, expected in checks:
        if actual != expected:
            raise AssertionError(f"{name}: expected {expected}, got {actual}")
        lines.append(f"PASS {name}: {actual}")
    lines.append("PASS inactive triggers are never ranked or placed in COMBINED")
    return "\n".join(lines) + "\n"


def main() -> int:
    arguments = parser().parse_args()
    paths = PhaseB2Paths.from_repo(arguments.repo_root)
    verify_phase_b1_baseline_manifest(paths)
    config = paths.load_config()
    corrected = config["corrected_phase_b1"]
    assert isinstance(corrected, dict)
    statistics = corrected
    cost_config = corrected["cost"]
    assert isinstance(cost_config, dict)
    materiality_thresholds = corrected["materiality"]
    bottleneck_thresholds = corrected["bottleneck"]
    assert isinstance(materiality_thresholds, dict)
    assert isinstance(bottleneck_thresholds, dict)

    source_paths = {
        "episodes": paths.phase_b1_tables / "per_episode_metrics.csv",
        "identifiability": paths.phase_b1_tables / "identifiability_delay.csv",
        "decision": paths.phase_b1_tables / "bottleneck_decision.json",
    }
    episodes = pd.read_csv(source_paths["episodes"], low_memory=False)
    identifiability = pd.read_csv(source_paths["identifiability"], low_memory=False)
    original_decision = json.loads(source_paths["decision"].read_text(encoding="utf-8"))
    ratios = tuple(float(value) for value in cost_config["ibr_energy_to_sg_ratio"])
    episodes_with_cost, cost_columns = add_total_cost_columns(
        episodes,
        ratios=ratios,
        sg_energy_weight=float(cost_config["sg_energy_weight"]),
        sg_mileage_weight=float(cost_config["sg_mileage_weight"]),
    )
    resamples = int(statistics["bootstrap_resamples"])
    seed = int(statistics["bootstrap_seed"])
    penalty = float(statistics["failure_penalty_multiplier"])

    materiality_comparison = build_corrected_comparison_table(
        episodes_with_cost,
        comparisons=(("B5", "B0", "phase_b1_materiality"),),
        metrics=("freq_iae", "max_abs_freq_hz", *cost_columns.values()),
        bootstrap_resamples=resamples,
        bootstrap_seed=seed,
        failure_penalty_multiplier=penalty,
    )
    oracle_gap = build_corrected_comparison_table(
        episodes_with_cost,
        comparisons=(("B4", "B5", "identified_arx_vs_exact_plant_shooting"),),
        metrics=("freq_iae", "max_abs_freq_hz", "sg_mileage", "ibr_mileage"),
        bootstrap_resamples=resamples,
        bootstrap_seed=seed + 100000,
        failure_penalty_multiplier=penalty,
    )
    control = build_corrected_comparison_table(
        episodes_with_cost,
        comparisons=CONTROL_COMPARISONS,
        metrics=("freq_iae", "max_abs_freq_hz", "sg_mileage", "ibr_mileage"),
        bootstrap_resamples=resamples,
        bootstrap_seed=seed + 200000,
        failure_penalty_multiplier=penalty,
    )
    all_comparisons = (
        ("B5", "B0", "phase_b1_materiality"),
        ("B4", "B5", "identified_arx_vs_exact_plant_shooting"),
        *CONTROL_COMPARISONS,
    )
    failures = build_paired_failure_outcomes(episodes_with_cost, all_comparisons)
    b5_classification = str(corrected["b5_benchmark_classification"])
    materiality = build_corrected_materiality_table(
        materiality_comparison,
        cost_columns=cost_columns,
        thresholds=materiality_thresholds,
        b5_classification=b5_classification,
    )
    decision = build_corrected_phase_b1_decision(
        materiality=materiality,
        oracle_gap=oracle_gap,
        control=control,
        identifiability=identifiability,
        original_decision=original_decision,
        thresholds=bottleneck_thresholds,
        b5_classification=b5_classification,
    )

    destination = paths.results_root / "corrected_phase_b1"
    destination.mkdir(parents=True, exist_ok=True)
    outputs = {
        "corrected_phase_b1_materiality.csv": materiality,
        "corrected_phase_b1_oracle_gap.csv": oracle_gap,
        "corrected_phase_b1_control_decomposition.csv": control,
        "corrected_phase_b1_failure_pairs.csv": failures,
        "corrected_phase_b1_cost_sensitivity.csv": materiality[
            [
                "sg_level",
                "cost_ratio_ibr_to_sg",
                "total_cost_improvement_fraction",
                "frequency_iae_improvement_fraction",
                "failure_rate_difference",
                "frequency_value_candidate",
                "cost_value_candidate",
                "materiality_gate_passed",
            ]
        ],
    }
    for filename, frame in outputs.items():
        _write_csv(frame, destination / filename)
    decision_path = destination / "corrected_phase_b1_decision.json"
    decision_path.write_text(
        json.dumps(decision, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    regression_path = destination / "phase_b1_decision_bug_regression_test.txt"
    regression_path.write_text(
        _bug_regression_text(), encoding="utf-8", newline="\n"
    )
    source_manifest = {
        name: {"path": str(path.relative_to(paths.repo_root)), "sha256": sha256_file(path)}
        for name, path in source_paths.items()
    }
    (destination / "source_csv_hashes.json").write_text(
        json.dumps(source_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "decision": decision["corrected_phase_b1_decision"],
                "active_triggers": decision["active_triggers"],
                "episode_rows_read": len(episodes),
                "episode_rerun_count": 0,
                "failure_pair_rows": len(failures),
                "output": str(destination),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
