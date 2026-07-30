from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[2]
ZIP_PATH = ROOT / "DIRECTION1_PHASE_D_CRCS_TUBE_MPC_SINGLE_REVIEW_PACKAGE.zip"
DIRS = [
    "00_README", "01_SCIENCE", "02_LITERATURE", "03_MODEL_AND_THEORY", "04_SOURCE",
    "05_CONFIG_AND_ENV", "06_TESTS_AND_VERIFICATION", "07_EXPERIMENT_DESIGN", "08_RAW_RESULTS",
    "09_SUMMARY_TABLES", "10_FIGURES", "11_FAILURES", "12_REPRODUCIBILITY",
    "13_GIT_AND_MANIFEST", "14_FINAL_STATUS",
]


def test_active_source_causality_seed_and_method_audit() -> None:
    sources = list((ROOT / "src" / "direction1freq").rglob("*.py")) + [
        path for path in (ROOT / "scripts" / "phase_d").glob("*.py") if path.name != "d9_build_review_package.py"
    ]
    forbidden_seed = ("seed%2", "seed % 2", "seed%3", "seed % 3", "seed%4", "seed % 4", "seed%5", "seed % 5")
    for source in sources:
        text = source.read_text(encoding="utf-8").lower()
        assert "mode='same'" not in text and 'mode="same"' not in text
        assert not any(token in text for token in forbidden_seed)
    controller_dir = ROOT / "src" / "direction1freq" / "controllers"
    assert not controller_dir.exists(), "H2 fatal stop forbids Direction1 MPC implementation"


def test_final_seed_firewall_is_data_backed() -> None:
    firewall = json.loads((ROOT / "results_phase_d" / "D7" / "SEED_FIREWALL.json").read_text(encoding="utf-8"))
    manifest = pd.read_csv(ROOT / "results_phase_d" / "D7" / "SCENARIO_MANIFEST.csv")
    assert firewall["final_seeds_used_for_tuning"] is False
    assert firewall["final_episodes_executed"] == 0
    assert set(manifest["execution_status"]) == {"not_evaluated"}


def test_review_zip_completeness_hashes_and_no_licenses() -> None:
    if not ZIP_PATH.exists():
        pytest.skip("run d9_build_review_package.py before the final package audit")
    assert ZIP_PATH.stat().st_size < 512 * 1024 * 1024
    with zipfile.ZipFile(ZIP_PATH) as archive:
        assert archive.testzip() is None
        names = archive.namelist()
        assert sorted({name.split("/")[0] for name in names}) == DIRS
        assert not any(name.lower().endswith(".lic") for name in names)
        requirements = archive.read("05_CONFIG_AND_ENV/requirements-lock.txt").decode("utf-8")
        assert "file://" not in requirements
        manifest = pd.read_csv(archive.open("13_GIT_AND_MANIFEST/FILE_MANIFEST.csv"))
        for row in manifest.itertuples(index=False):
            content = archive.read(row.path)
            assert len(content) == row.bytes
            assert hashlib.sha256(content).hexdigest() == row.sha256
        status = json.loads(archive.read("14_FINAL_STATUS/FINAL_STATUS.json"))
        assert status["final_research_status"] == "PASSIVE_CAPABILITY_SET_NOT_SUPPORTED"
