"""Paired physical value components on the registered development distribution."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = (
    ROOT
    / "research_outputs_direction5_safe_voi_positive_region_rebuild"
    / "R2_TARGET_DISTRIBUTION"
)


def branch(row: dict[str, object]) -> str:
    return "high" if float(row["true_power_pu"]) > 0.045 + 1e-8 else "low"


def configuration(row: dict[str, object]) -> tuple[object, ...]:
    return (
        row.get("objective_preference"),
        row.get("probe_amplitude_pu"),
        row.get("second_window_amplitude_pu"),
        row.get("probe_window_duration_s"),
        row.get("probe_cooldown_duration_s"),
        row.get("maximum_probe_windows"),
        row.get("certificate_validity_s"),
    )


def paired_scenario(row: dict[str, object]) -> tuple[object, ...]:
    return (
        int(row["seed"]),
        branch(row),
        row.get("duration_s"),
        row.get("poi_observation_period_s"),
        row.get("period_s"),
        row.get("rolling_horizon_s"),
        row.get("candidate_delay_spread_s", 0.0),
        row.get("comparison_group", ""),
    )


def main() -> None:
    results = []
    for path in OUTPUT.glob("*.json"):
        if path.name.endswith("_resource.json"):
            continue
        row = json.loads(path.read_text(encoding="utf-8"))
        if "grid_service_cost_s" in row:
            results.append(row)

    contracts = {
        paired_scenario(row): row
        for row in results
        if row["method"] == "contract"
    }
    exploits = {
        (*paired_scenario(row), configuration(row)): row
        for row in results
        if row["method"] == "exploit_only"
    }
    rows = []
    for dual in results:
        if dual["method"] != "dual":
            continue
        seed = int(dual["seed"])
        capability = branch(dual)
        scenario_key = paired_scenario(dual)
        contract = contracts.get(scenario_key)
        if contract is None:
            continue
        key = configuration(dual)
        # Evidence and validity are absent from exploit-only by construction;
        # the physical acquisition action is matched on all remaining fields.
        exploit_key = (*key[:-1], 0.0)
        exploit = exploits.get((*scenario_key, exploit_key))
        item = {
            "seed": seed,
            "branch": capability,
            "period_s": dual["period_s"],
            "rolling_horizon_s": dual["rolling_horizon_s"],
            "load_event_time_s": dual["load_event_time_s"],
            "load_magnitude_pu": dual["load_magnitude_pu"],
            "load_sign": dual["load_sign"],
            "load_area": dual["load_area"],
            "initial_soc": dual["initial_soc"],
            "poi_noise_std_pu": dual["poi_noise_std_pu"],
            "probe_amplitude_pu": dual["probe_amplitude_pu"],
            "second_window_amplitude_pu": dual["second_window_amplitude_pu"],
            "probe_window_duration_s": dual.get("probe_window_duration_s"),
            "probe_cooldown_duration_s": dual.get("probe_cooldown_duration_s"),
            "maximum_probe_windows": dual["maximum_probe_windows"],
            "certificate_validity_s": dual["certificate_validity_s"],
            "power_certified": dual.get("power_certified", False),
            "power_certificate_time_s": dual.get("power_certificate_time_s"),
            "probe_windows_started": dual.get("probe_windows_started", 0),
            "futility_stopped": dual.get("futility_stopped", False),
            "physical_success": dual["physical_success"],
            "hard_violation": dual["hard_violation"],
            "solver_failure_calls": dual["solver_failure_calls"],
            "fallback_calls": dual["fallback_calls"],
            "total_grid_service_value_s": (
                contract["grid_service_cost_s"] - dual["grid_service_cost_s"]
            ),
            "total_sg_mileage_value_pu": (
                contract["sg_mechanical_mileage_pu"]
                - dual["sg_mechanical_mileage_pu"]
            ),
            "total_bess_throughput_value_pu_s": (
                contract["bess_energy_throughput_pu_s"]
                - dual["bess_energy_throughput_pu_s"]
            ),
            "total_frequency_peak_value_hz": (
                contract["frequency_peak_hz"] - dual["frequency_peak_hz"]
            ),
            "total_ace_iae_value_pu_s": (
                contract["ace_iae_pu_s"] - dual["ace_iae_pu_s"]
            ),
            "total_tie_iae_value_pu_s": (
                contract["tie_iae_pu_s"] - dual["tie_iae_pu_s"]
            ),
            "exploit_comparator_available": exploit is not None,
        }
        for metric, output_name in (
            ("grid_service_cost_s", "information_grid_service_value_s"),
            ("sg_mechanical_mileage_pu", "information_sg_mileage_value_pu"),
            ("bess_energy_throughput_pu_s", "information_bess_throughput_value_pu_s"),
            ("ace_iae_pu_s", "information_ace_iae_value_pu_s"),
            ("tie_iae_pu_s", "information_tie_iae_value_pu_s"),
        ):
            item[output_name] = (
                None if exploit is None else exploit[metric] - dual[metric]
            )
        rows.append(item)

    if not rows:
        print("no paired target-distribution results")
        return
    destination = OUTPUT / "COMPONENT_VALUES.csv"
    with destination.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(destination)


if __name__ == "__main__":
    main()
