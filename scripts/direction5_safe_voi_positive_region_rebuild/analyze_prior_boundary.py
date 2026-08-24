"""Compute branchwise value and break-even prior from paired nonlinear results."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from statistics import mean

from direction5freq.voi_positive_region import BinaryPriorValueBoundary


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "research_outputs_direction5_safe_voi_positive_region_rebuild" / "R1_NONLINEAR_PILOT"
METRICS = (
    "frequency_peak_hz",
    "ace_iae_pu_s",
    "tie_iae_pu_s",
    "sg_mechanical_mileage_pu",
)


def branch(row: dict[str, object]) -> str:
    return "high" if float(row["true_power_pu"]) > 0.045 + 1e-8 else "low"


def main() -> None:
    results = []
    for path in OUTPUT.glob("*.json"):
        if path.name.endswith("_resource.json"):
            continue
        row = json.loads(path.read_text(encoding="utf-8"))
        if "frequency_peak_hz" in row:
            results.append(row)

    contracts = {
        (
            branch(row),
            row.get("objective_preference", "resource_economy"),
            int(row["seed"]),
        ): row
        for row in results if row["method"] == "contract"
    }
    rows = []
    configurations: dict[tuple[object, ...], list[dict[str, object]]] = {}
    for row in results:
        if row["method"] != "dual":
            continue
        key = (
            row.get("objective_preference", "resource_economy"),
            row.get("probe_amplitude_pu"),
            row.get("second_window_amplitude_pu"),
            row.get("evidence_model"),
            row.get("maximum_probe_windows"),
            row.get("certificate_validity_s"),
        )
        configurations.setdefault(key, []).append(row)

    for configuration, matching in configurations.items():
        (
            objective,
            amplitude,
            second_window_amplitude,
            evidence,
            maximum_windows,
            validity,
        ) = configuration
        by_branch_seed = {
            (branch(row), int(row["seed"])): row for row in matching
        }
        low_seeds = {
            seed for capability, seed in by_branch_seed if capability == "low"
        }
        high_seeds = {
            seed for capability, seed in by_branch_seed if capability == "high"
        }
        paired_seeds = sorted(
            seed for seed in low_seeds & high_seeds
            if ("low", objective, seed) in contracts
            and ("high", objective, seed) in contracts
        )
        if not paired_seeds:
            continue
        exploits = {
            (branch(row), int(row["seed"])): row
            for row in results
            if row["method"] == "exploit_only"
            and row.get("objective_preference", "resource_economy") == objective
            and row.get("probe_amplitude_pu") == amplitude
            and row.get("second_window_amplitude_pu") == second_window_amplitude
            and row.get("maximum_probe_windows") == maximum_windows
        }
        for metric in METRICS:
            values = {
                capability: [
                    contracts[(capability, objective, seed)][metric]
                    - by_branch_seed[(capability, seed)][metric]
                    for seed in paired_seeds
                ]
                for capability in ("low", "high")
            }
            average = {
                capability: mean(values[capability]) for capability in ("low", "high")
            }
            boundary = BinaryPriorValueBoundary(average["low"], average["high"])
            information_values = {
                capability: [
                    exploits[(capability, seed)][metric]
                    - by_branch_seed[(capability, seed)][metric]
                    for seed in paired_seeds
                    if (capability, seed) in exploits
                ]
                for capability in ("low", "high")
            }
            low_relative_downside = [
                -value / contracts[("low", objective, seed)][metric]
                for value, seed in zip(values["low"], paired_seeds, strict=True)
            ]
            rows.append({
                "objective": objective,
                "probe_amplitude_pu": amplitude,
                "second_window_amplitude_pu": second_window_amplitude,
                "evidence_model": evidence,
                "maximum_probe_windows": maximum_windows,
                "certificate_validity_s": validity,
                "metric": metric,
                "paired_seeds": len(paired_seeds),
                "low_capability_mean_value": average["low"],
                "high_capability_mean_value": average["high"],
                "low_positive_seed_fraction": sum(
                    value > 0.0 for value in values["low"]
                ) / len(paired_seeds),
                "high_positive_seed_fraction": sum(
                    value > 0.0 for value in values["high"]
                ) / len(paired_seeds),
                "low_maximum_relative_downside": max(low_relative_downside),
                "low_mean_pure_information_value": (
                    mean(information_values["low"])
                    if information_values["low"] else None
                ),
                "high_mean_pure_information_value": (
                    mean(information_values["high"])
                    if information_values["high"] else None
                ),
                "high_information_positive_seed_fraction": (
                    sum(value > 0.0 for value in information_values["high"])
                    / len(information_values["high"])
                    if information_values["high"] else None
                ),
                "high_certification_rate": sum(
                    bool(by_branch_seed[("high", seed)].get("power_certified", False))
                    for seed in paired_seeds
                ) / len(paired_seeds),
                "low_false_certification_rate": sum(
                    bool(by_branch_seed[("low", seed)].get("power_certified", False))
                    for seed in paired_seeds
                ) / len(paired_seeds),
                "break_even_high_capability_probability": boundary.break_even_probability(),
                "value_at_prior_0_5": boundary.net_value(0.5),
            })
    if not rows:
        print("paired low/high dual results are not yet complete")
        return
    destination = OUTPUT / "PRIOR_BOUNDARY.csv"
    with destination.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(destination)


if __name__ == "__main__":
    main()
