"""Summarize paired absolute differences in the nonlinear development pilot."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "research_outputs_direction5_safe_voi_positive_region_rebuild" / "R1_NONLINEAR_PILOT"
METRICS = (
    "frequency_peak_hz",
    "ace_iae_pu_s",
    "tie_iae_pu_s",
    "sg_mechanical_mileage_pu",
    "bess_energy_throughput_pu_s",
)


def capability_branch(row: dict[str, object]) -> str:
    return "high" if float(row["true_power_pu"]) > 0.045 + 1e-8 else "low"


def normalized_cell(row: dict[str, object]) -> str:
    base = str(row["design_cell"]).split("|")[0]
    objective = str(row.get("objective_preference", "resource_economy"))
    return f"{base}|{objective}"


def main() -> None:
    rows = []
    for path in sorted(OUTPUT.glob("*.json")):
        if path.name.endswith("_resource.json"):
            continue
        row = json.loads(path.read_text(encoding="utf-8"))
        if "frequency_peak_hz" in row:
            rows.append(row)
    contracts = {
        (normalized_cell(row), capability_branch(row)): row
        for row in rows if row["method"] == "contract"
    }
    summary = []
    for row in rows:
        contract = contracts.get((normalized_cell(row), capability_branch(row)))
        item = {
            "scenario_id": row["scenario_id"],
            "method": row["method"],
            "objective_preference": row.get("objective_preference", "resource_economy"),
            "probe_amplitude_pu": row.get("probe_amplitude_pu"),
            "evidence_model": row.get("evidence_model"),
            "physical_success": row["physical_success"],
            "hard_violation": row["hard_violation"],
            "solver_failure_calls": row["solver_failure_calls"],
            "fallback_calls": row["fallback_calls"],
            "probe_windows": row.get("probe_windows_started", row["probe_triggers"]),
            "power_certified": row.get("power_certified", False),
            "power_certificate_time_s": row.get("power_certificate_time_s"),
        }
        for metric in METRICS:
            item[metric] = row[metric]
            item[f"delta_{metric}"] = (
                None if contract is None else row[metric] - contract[metric]
            )
        summary.append(item)
    destination = OUTPUT / "SUMMARY.csv"
    with destination.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=summary[0].keys())
        writer.writeheader()
        writer.writerows(summary)
    print(destination)
    for row in summary:
        print({
            "scenario_id": row["scenario_id"],
            "delta_ace": row["delta_ace_iae_pu_s"],
            "delta_tie": row["delta_tie_iae_pu_s"],
            "delta_sg_mileage": row["delta_sg_mechanical_mileage_pu"],
            "certified": row["power_certified"],
        })


if __name__ == "__main__":
    main()
