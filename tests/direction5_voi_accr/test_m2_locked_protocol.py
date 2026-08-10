from __future__ import annotations

import pandas as pd
import yaml

from scripts.direction5_voi_accr.run_m2_validation import (
    LOCK_PATH,
    contract_violation_manifest,
    normal_manifest,
    plant_a_manifest,
    plant_b_manifest,
)


def test_m2_primary_manifest_is_unconfounded_and_complete() -> None:
    lock = yaml.safe_load(LOCK_PATH.read_text("utf-8"))
    plant_a = plant_a_manifest(lock)
    factors = plant_a.groupby(
        ["mechanism", "sg_tension", "period_s", "condition", "value_region"]
    ).size()
    assert len(plant_a) == 48
    assert factors.eq(1).all()
    assert set(plant_a.timing_relation) == {"before", "simultaneous", "after"}
    assert set(plant_a.duration_s) == {300.0, 600.0}


def test_m2_native_normal_and_contract_violation_are_separate() -> None:
    lock = yaml.safe_load(LOCK_PATH.read_text("utf-8"))
    plant_a = plant_a_manifest(lock)
    plant_b = plant_b_manifest(lock)
    normal = normal_manifest()
    violation = contract_violation_manifest()
    all_seeds = pd.concat((plant_a.seed, plant_b.seed, normal.seed, violation.seed))
    assert all_seeds.is_unique
    assert len(plant_b) == 12
    assert set(plant_b.mechanism) == {"power_drop", "ramp_drop", "delay_drop"}
    assert normal.iloc[0].duration_s == 3600.0
    assert violation.contract_violation.all()
    assert violation.contract_status.eq("BELOW_CONTRACT").all()
