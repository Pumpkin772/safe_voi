from __future__ import annotations

import inspect
import json
from pathlib import Path

from direction5freq.controllers.dcsv_cr_mpc import DCSVContractRecourseMPC
from direction5freq.evaluation.final_protocol import (
    build_normal_manifest,
    build_plant_a_manifest,
    build_plant_b_manifest,
)


REPO = Path(__file__).resolve().parents[2]


def test_r5_manifest_scale_warmup_and_factor_assignment() -> None:
    plant_a = build_plant_a_manifest("validation")
    plant_b = build_plant_b_manifest()
    normal = build_normal_manifest()
    assert len(plant_a) == 120
    assert plant_a.groupby(["mechanism", "sg_tension", "period_s"]).size().min() >= 10
    assert plant_b.groupby("mechanism").size().min() >= 8
    assert plant_b.operating_point.nunique() == 2
    assert (plant_a.nominal_warmup_s >= 60.0).all()
    assert (plant_a.duration_s.between(300.0, 600.0)).all()
    assert plant_a.factor_assignment.str.contains("INDEPENDENT_REGISTERED").all()
    assert normal.profile_provenance.str.contains("SYNTHETIC").all()


def test_r5_lock_does_not_consume_final_seeds_and_uses_contract_primary() -> None:
    import yaml

    lock = yaml.safe_load(
        (REPO / "configs/direction5_final/r5_validation_lock.yaml").read_text("utf-8")
    )
    assert not lock["final_seeds_consumed"]
    assert lock["primary_baseline"] == "contract_only_rolling_mpc"
    assert set(lock["validation_seeds"]).isdisjoint(lock["final_seeds"])
    assert lock["gates"]["relative_improvement_min"] == 0.08


def test_ordinary_dcsv_cr_source_has_no_evaluation_truth_or_future_event() -> None:
    source = inspect.getsource(DCSVContractRecourseMPC)
    assert "CapabilityRealization" not in source
    assert "true_capability" not in source
    assert "future_event" not in source
    assert "true_load" not in source


def test_r5_outputs_are_decisive_and_final_seeds_unconsumed() -> None:
    progress = json.loads((REPO / "progress_final/R5.json").read_text("utf-8"))
    assert progress["status"] in {"PASS", "FAIL"}
    assert not progress["final_seeds_consumed"]
    assert progress["attempted_solver_calls"] >= progress["optimization_decisions"]
    if progress["status"] == "FAIL":
        assert progress["validation_repair_rounds_used"] == 2
        assert progress["next_stage"] == "R8_NEGATIVE_PACKAGE"
