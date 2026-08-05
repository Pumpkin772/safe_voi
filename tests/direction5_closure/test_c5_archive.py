from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research_outputs_closure/05_ARCHIVE"


def test_c5_archive_inputs_are_complete_and_credential_free() -> None:
    progress = json.loads((ROOT / "progress_closure/C5.json").read_text(encoding="utf-8"))
    plan = json.loads((OUT / "SOURCE_DATA_ARCHIVE_PLAN.json").read_text(encoding="utf-8"))
    assert progress["status"] == "PASS"
    assert plan["input_files"] > 2000
    assert plan["credentials_included"] is False
    assert plan["caches_included"] is False
    with (OUT / "ARCHIVE_INPUT_SHA256.csv").open(encoding="utf-8", newline="") as handle:
        paths = [row["repository_path"] for row in csv.DictReader(handle)]
    assert any(path.startswith("src/direction5freq/") for path in paths)
    assert any(path.startswith("results_final/R5/") for path in paths)
    assert any(path.startswith("results_closure/C2/") for path in paths)
    assert not any(path.endswith(".lic") or "__pycache__" in path for path in paths)


def test_c5_reproducibility_documents_exist() -> None:
    for name in ("DATA_DICTIONARY.md", "LICENSE_NOTICE.md", "REPRODUCIBILITY_MAP.md", "ARCHIVE_INVENTORY.csv"):
        assert (OUT / name).stat().st_size > 100
