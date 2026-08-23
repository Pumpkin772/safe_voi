"""Compute branchwise value and break-even prior from paired nonlinear results."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from direction5freq.voi_positive_region import BinaryPriorValueBoundary


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "research_outputs_direction5_safe_voi_positive_region_rebuild" / "R1_NONLINEAR_PILOT"
METRICS = (
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
        (branch(row), row.get("objective_preference", "resource_economy")): row
        for row in results if row["method"] == "contract"
    }
    rows = []
    for dual in (row for row in results if row["method"] == "dual"):
        objective = dual.get("objective_preference", "resource_economy")
        amplitude = dual.get("probe_amplitude_pu")
        evidence = dual.get("evidence_model")
        matching = [
            row for row in results
            if row["method"] == "dual"
            and row.get("objective_preference", "resource_economy") == objective
            and row.get("probe_amplitude_pu") == amplitude
            and row.get("evidence_model") == evidence
        ]
        by_branch = {branch(row): row for row in matching}
        if set(by_branch) != {"low", "high"}:
            continue
        for metric in METRICS:
            value = {
                capability: contracts[(capability, objective)][metric] - result[metric]
                for capability, result in by_branch.items()
            }
            boundary = BinaryPriorValueBoundary(value["low"], value["high"])
            rows.append({
                "objective": objective,
                "probe_amplitude_pu": amplitude,
                "evidence_model": evidence,
                "metric": metric,
                "low_capability_value": value["low"],
                "high_capability_value": value["high"],
                "break_even_high_capability_probability": boundary.break_even_probability(),
                "value_at_prior_0_5": boundary.net_value(0.5),
            })
        break
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
