from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

from direction5freq.accr.materiality import METHODS, build_manifest, capability_for, paired_analysis


REPO = Path(__file__).resolve().parents[2]


def lock() -> dict:
    return yaml.safe_load((REPO / "configs/direction5_accr/a1_materiality_lock.yaml").read_text("utf-8"))


def test_manifest_is_factor_explicit_and_uses_only_new_development_seeds() -> None:
    manifest = build_manifest(lock())
    assert len(manifest) == 24
    assert manifest.seed.is_unique
    assert manifest.seed.min() == 206 and manifest.seed.max() == 229
    assert (manifest.nominal_warmup_s >= 60.0).all()
    assert set(manifest.mechanism) == {"power_drop", "ramp_drop"}
    assert set(manifest.sg_tension) == {"low", "high"}


def test_mechanism_profiles_change_only_registered_dimension() -> None:
    manifest = build_manifest(lock())
    for mechanism in ("power_drop", "ramp_drop"):
        row = manifest[manifest.mechanism == mechanism].iloc[0]
        truth = capability_for(row, row.capability_change_time_s + 1.0, lock())
        if mechanism == "power_drop":
            assert truth.upper_power_pu == (0.065, 0.065)
            assert truth.ramp_up_pu_per_s == (0.025, 0.025)
        else:
            assert truth.upper_power_pu == (0.045, 0.045)
            assert truth.ramp_up_pu_per_s == (0.055, 0.055)
        assert truth.delay_s == (1.5, 1.5)


def test_paired_analysis_uses_absolute_contract_minus_perfect_difference() -> None:
    rows = []
    for seed in range(3):
        for method in METHODS:
            rows.append({
                "scenario_id": f"s{seed}", "mechanism": "power_drop", "sg_tension": "low",
                "period_s": 2.0, "seed": seed, "method": method,
                "ace_iae_pu_s": 2.0 if method.startswith("contract") else 1.0,
                "tie_iae_pu_s": 3.0 if method.startswith("contract") else 1.0,
                "sg_mechanical_mileage_pu": 4.0 if method.startswith("contract") else 1.0,
            })
    paired, cells = paired_analysis(pd.DataFrame(rows), 100)
    assert (paired["delta_ace_iae_pu_s"] == 1.0).all()
    assert bool(cells.iloc[0].materiality_positive)

