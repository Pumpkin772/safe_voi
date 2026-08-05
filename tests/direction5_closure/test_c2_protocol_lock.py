from __future__ import annotations

from collections import Counter
from pathlib import Path
import subprocess
import sys

import yaml

from scripts.direction5_closure.run_c2_confirmatory import (
    MARKER,
    combined_manifest,
    contract_violation_manifest,
    load_config,
    normal_manifest,
    plant_a_manifest,
    plant_b_manifest,
)


REPO = Path(__file__).resolve().parents[2]


def test_confirmatory_protocol_reuses_frozen_gate_and_all_final_seeds() -> None:
    config = load_config()
    r5 = yaml.safe_load((REPO / "configs/direction5_final/r5_validation_lock.yaml").read_text("utf-8"))
    assert config["gates"] == r5["gates"]
    assert config["final_seeds"] == r5["final_seeds"]
    assert config["no_post_result_tuning"] is True


def test_plant_a_confirmatory_matrix_is_balanced_and_uses_each_seed_twice() -> None:
    frame = plant_a_manifest()
    assert len(frame) == 120
    assert frame.groupby(["mechanism", "sg_tension", "period_s"]).size().eq(10).all()
    assert set(frame.seed) == set(range(100, 160))
    assert frame.seed.value_counts().eq(2).all()
    for _, block in frame.groupby(["mechanism", "sg_tension", "period_s"]):
        assert Counter(block.magnitude_class) == Counter({"sustainable": 5, "bridge": 3, "infeasible": 2})
        assert Counter(block.condition) == Counter({"known": 5, "OOD": 5})


def test_other_confirmatory_manifests_have_registered_scale() -> None:
    assert len(plant_b_manifest()) == 24
    assert plant_b_manifest().groupby("mechanism").size().eq(8).all()
    assert len(normal_manifest()) == 6
    assert set(normal_manifest().seed) == set(range(40, 46))
    assert normal_manifest().profile_provenance.eq(
        "SYNTHETIC_AR2_MULTI_SINE_REGISTERED_NOT_PUBLIC_MEASURED"
    ).all()
    assert len(contract_violation_manifest()) == 6
    assert contract_violation_manifest().contract_violation.all()
    assert len(combined_manifest()) == 180


def test_final_seed_marker_lifecycle_is_irreversible() -> None:
    if not MARKER.exists():
        return
    import json
    marker = json.loads(MARKER.read_text("utf-8"))
    assert marker["status"] == "COMPLETE"
    assert marker["final_seeds_consumed"] is True
    assert marker["single_execution"] is True
    assert marker["post_result_tuning_forbidden"] is True


def test_confirmatory_entrypoint_imports_from_direct_execution() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/direction5_closure/run_c2_confirmatory.py", "--help"],
        cwd=REPO, text=True, capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr
