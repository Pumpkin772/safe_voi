"""Small preregistered-range E3 diagnostic; never used as the materiality Gate."""

from __future__ import annotations

import json

import pandas as pd

from scripts.phase_e.run_e3_materiality import (
    ControllerBank,
    RESULT,
    build_manifest,
    materiality_summary,
    simulate_plant_a_episode,
)


def main() -> None:
    output = RESULT / "targeted_diagnostic"
    output.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(False)
    manifest = manifest[
        (manifest["sfr_period_s"] == 4.0)
        & manifest["mechanism"].isin(["delay", "energy", "availability"])
        & manifest["sg_tension"].isin(["scarce", "critical"])
        & (manifest["load_timing"] != "no_load")
    ]
    manifest = (
        manifest.groupby(["mechanism", "sg_tension"], sort=True, group_keys=False)
        .head(5)
        .reset_index(drop=True)
    )
    manifest.to_csv(output / "DIAGNOSTIC_MANIFEST.csv", index=False)
    bank = ControllerBank(4.0, horizon=4)
    episodes = []
    for _, row in manifest.iterrows():
        for method in ("nominal_mpc", "oracle_o2_nmpc"):
            episode, _ = simulate_plant_a_episode(row, method, bank)
            episodes.append(episode)
    frame = pd.DataFrame(episodes)
    frame.to_parquet(output / "DIAGNOSTIC_EPISODES.parquet", index=False)
    summary = materiality_summary(frame, "nominal_mpc")
    summary.to_csv(output / "DIAGNOSTIC_SUMMARY.csv", index=False)
    report = {
        "purpose": "pre-full diagnostic only; not a Gate and not used to tune thresholds",
        "scenarios": len(manifest),
        "episodes": len(frame),
        "mechanisms_passing": int(summary.loc[summary.cell_materiality_pass, "mechanism"].nunique()),
        "sg_tensions_passing": int(summary.loc[summary.cell_materiality_pass, "sg_tension"].nunique()),
        "cells": summary.to_dict(orient="records"),
    }
    (output / "DIAGNOSTIC_REPORT.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
