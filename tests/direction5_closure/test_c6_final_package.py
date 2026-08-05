from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_only_registered_negative_state_is_selected() -> None:
    final = json.loads((ROOT / "results_closure/final/FINAL_STATUS.json").read_text(encoding="utf-8"))
    assert final["final_status"] == "DIRECTION5_NEGATIVE_RESULT_CONFIRMED_AND_ARCHIVED"
    assert final["validation_positive_gate"] is False
    assert final["confirmatory_positive_gate"] is False
    assert final["joint_validation_confirmatory_positive"] is False
    assert final["confirmatory"]["final_seeds_consumed_once"] is True
    assert final["confirmatory"]["post_result_tuning_permitted"] is False
    assert final["no_new_phase_or_method"] is True


def test_c0_to_c5_pass_and_c6_is_sealable() -> None:
    with (ROOT / "results_closure/final/ALL_STAGE_GATES.csv").open(encoding="utf-8", newline="") as handle:
        rows = {row["stage"]: row["status"] for row in csv.DictReader(handle)}
    assert all(rows[f"C{i}"] == "PASS" for i in range(6))
    assert rows["C6"] in {"PENDING_PACKAGE_VERIFICATION", "PASS"}
    if rows["C6"] == "PASS":
        progress = json.loads((ROOT / "progress_closure/C6.json").read_text(encoding="utf-8"))
        assert progress["package_verification"]["passed"] is True


def test_package_scripts_are_standard_library_only_at_runtime() -> None:
    verifier = (ROOT / "scripts/direction5_closure/package_verify_manifest.py").read_text(encoding="utf-8")
    replay = (ROOT / "scripts/direction5_closure/package_reproduce_minimal.py").read_text(encoding="utf-8")
    forbidden = ("pandas", "numpy", "pyarrow", "direction5freq")
    assert not any(word in verifier for word in forbidden)
    assert not any(word in replay for word in forbidden)


def test_builder_uses_short_temporary_staging_for_windows_paths() -> None:
    builder = (ROOT / "scripts/direction5_closure/build_c6_review_package.py").read_text(encoding="utf-8")
    assert 'STAGING_NAME = "d5c6_stage"' in builder
    assert "Path(tempfile.gettempdir())" in builder
    assert 'root = target / "p"' in builder


def test_manuscript_has_no_prediction_placeholders() -> None:
    for path in (ROOT / "research_outputs_closure/03_PAPER").glob("*.md"):
        assert "[" + "PREDICTED" + "]" not in path.read_text(encoding="utf-8")
