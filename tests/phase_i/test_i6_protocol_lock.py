from __future__ import annotations

from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[2]


def test_i6_lock_uses_validation_not_final_seeds() -> None:
    lock = yaml.safe_load((REPO / "configs/phase_i/i6_validation_lock.yaml").read_text("utf-8"))
    assert lock["locked_before_validation"]
    assert lock["split"] == "validation"
    assert min(lock["seeds"]) >= 30 and max(lock["seeds"]) <= 59
    assert not lock["final_seeds_consumed"]


def test_i6_lock_names_only_true_method_and_deployable_baseline() -> None:
    lock = yaml.safe_load((REPO / "configs/phase_i/i6_validation_lock.yaml").read_text("utf-8"))
    assert lock["methods"] == ["dcsv_mpc", "fixed_allocation_pi"]
    assert lock["best_deployable_baseline"] == "fixed_allocation_pi"
    assert lock["dcsv"]["hard_safety_source"] == "contract_floor"
    assert lock["dcsv"]["online_envelope_use"] == "performance_only"
