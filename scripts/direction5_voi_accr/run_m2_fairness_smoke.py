"""Guarded M1-development replay of contract equivalence before M2 V2."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import yaml


REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from direction5freq.accr.validation import simulate_plant_a_episode


def main() -> None:
    if os.environ.get("DIRECTION5_RESOURCE_GUARDED") != "1":
        raise SystemExit("Refusing unguarded fairness smoke")
    lock = yaml.safe_load(
        (REPO / "configs/direction5_voi_accr/m2_validation_lock.yaml").read_text("utf-8")
    )
    manifest = pd.read_csv(
        REPO / "research_outputs_working/M1/runs/VOI_V12_C13_M1_VALUE_REGIONS/M1_DEVELOPMENT_MANIFEST.csv"
    )
    scenario = manifest.loc[manifest.value_region_design.eq("LOW_VALUE_CONTROL")].iloc[0]
    output = REPO / "research_outputs_working/M2_FAIRNESS_SMOKE"
    rows = []
    for method in ("contract_only_recourse_mpc", "voi_accr_mpc"):
        rows.append(simulate_plant_a_episode(
            scenario.to_dict(), method, lock,
            float(lock["voi_controller"]["delivered_branch_weight"]),
            cycle_output_path=output / f"{scenario.scenario_id}__{method}.parquet",
        ))
    frame = pd.DataFrame(rows)
    output.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output / "FAIRNESS_SMOKE_EPISODES.csv", index=False)
    base = frame.loc[frame.method.eq("contract_only_recourse_mpc")].iloc[0]
    voi = frame.loc[frame.method.eq("voi_accr_mpc")].iloc[0]
    metrics = (
        "frequency_peak_hz", "ace_iae_pu_s", "tie_iae_pu_s",
        "sg_mechanical_mileage_pu", "bess_energy_throughput_pu_s",
    )
    differences = {metric: float(abs(float(base[metric]) - float(voi[metric]))) for metric in metrics}
    result = {
        "status": "PASS" if max(differences.values()) <= 1e-10 else "FAIL",
        "source_split": "M1_DEVELOPMENT_LOW_VALUE_CONTROL",
        "probe_triggers": int(voi.voi_probe_triggers),
        "probe_command_l1_pu_s": float(voi.probe_command_l1_pu_s),
        "absolute_metric_differences": differences,
        "maximum_absolute_metric_difference": max(differences.values()),
    }
    (output / "FAIRNESS_SMOKE_DECISION.json").write_text(
        json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["status"] != "PASS" or result["probe_triggers"] != 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
