"""Read-only decomposition of the failed Direction5 M2 validation."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[2]
RESULTS = REPO / "results_direction5_voi_accr/M2"
VOI = "voi_accr_mpc"
BASE = "contract_only_recourse_mpc"


def ratio(frame: pd.DataFrame, metric: str) -> float:
    base = frame[f"{metric}__{BASE}"].sum()
    improvement = frame[f"paired_absolute_improvement__{metric}"].sum()
    return float(improvement / base) if abs(base) > 1e-12 else np.nan


def main() -> None:
    paired = pd.read_csv(RESULTS / "M2_PAIRED.csv")
    manifest = pd.read_csv(RESULTS / "M2_VALIDATION_MANIFEST.csv")
    certificate = pd.read_csv(RESULTS / "M2_CERTIFICATE_AUDIT.csv")
    paired["actually_probed"] = paired[f"voi_probe_triggers__{VOI}"] > 0
    group_columns = [
        "plant", "mechanism", "condition", "period_s", "value_region"
    ]
    groups = []
    for key, frame in paired.groupby(group_columns, dropna=False):
        groups.append({
            **dict(zip(group_columns, key)),
            "scenario_count": len(frame),
            "probed_scenarios": int(frame.actually_probed.sum()),
            "ace_aggregate_improvement": ratio(frame, "ace_iae_pu_s"),
            "tie_aggregate_improvement": ratio(frame, "tie_iae_pu_s"),
            "sg_mileage_aggregate_improvement": ratio(
                frame, "sg_mechanical_mileage_pu"
            ),
            "frequency_delta_max_hz": float(
                (
                    frame[f"frequency_peak_hz__{VOI}"]
                    - frame[f"frequency_peak_hz__{BASE}"]
                ).max()
            ),
            "candidate_reduction_mean": float(
                frame[f"candidate_diameter_reduction_max__{VOI}"].mean()
            ),
        })
    group_frame = pd.DataFrame(groups)
    group_frame.to_csv(RESULTS / "M2_FAILURE_BY_FACTOR.csv", index=False)

    actual = paired[paired.actually_probed]
    actual_summary = {
        "scenario_count": int(len(actual)),
        "ace_aggregate_improvement": ratio(actual, "ace_iae_pu_s"),
        "tie_aggregate_improvement": ratio(actual, "tie_iae_pu_s"),
        "sg_mileage_aggregate_improvement": ratio(
            actual, "sg_mechanical_mileage_pu"
        ),
        "candidate_reduction_mean": float(
            actual[f"candidate_diameter_reduction_max__{VOI}"].mean()
        ),
    }

    certificate = certificate.merge(
        manifest[[
            "scenario_id", "mechanism", "condition", "timing_relation",
            "value_region",
        ]],
        on="scenario_id", how="left",
    )
    certificate.to_csv(RESULTS / "M2_CERTIFICATE_FAILURE_DETAIL.csv", index=False)

    reasons = []
    for path in sorted((RESULTS / "cycle_parts").glob(f"*__{VOI}.parquet")):
        cycles = pd.read_parquet(path, columns=[
            "scenario_id", "plant", "voi_reason", "voi_worthwhile",
            "probe_triggered",
        ])
        reasons.append(cycles)
    reason_frame = pd.concat(reasons, ignore_index=True)
    reason_counts = (
        reason_frame.groupby(["plant", "voi_reason"], dropna=False)
        .agg(
            cycle_count=("scenario_id", "size"),
            scenario_count=("scenario_id", "nunique"),
            probe_triggers=("probe_triggered", "sum"),
        )
        .reset_index()
    )
    reason_counts.to_csv(RESULTS / "M2_VOI_REASON_COUNTS.csv", index=False)

    diagnosis = {
        "actual_probe_subset": actual_summary,
        "false_optimism_by_condition": {
            str(key): float(frame.false_optimism.mean())
            for key, frame in certificate.groupby("condition")
        },
        "false_optimism_by_mechanism": {
            str(key): float(frame.false_optimism.mean())
            for key, frame in certificate.groupby("mechanism")
        },
        "native_probe_triggers": int(
            paired.loc[paired.plant.eq("B_native_ANDES_Kundur"), f"voi_probe_triggers__{VOI}"].sum()
        ),
        "plant_a_probe_triggers": int(
            paired.loc[paired.plant.eq("A_full_nonlinear"), f"voi_probe_triggers__{VOI}"].sum()
        ),
        "failed_certificate_rows": int(certificate.false_optimism.sum()),
        "certificate_rows": int(len(certificate)),
    }
    (RESULTS / "M2_FAILURE_DIAGNOSIS.json").write_text(
        json.dumps(diagnosis, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(diagnosis, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
