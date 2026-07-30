from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[2]
ZIP = ROOT / "DIRECTION1_PHASE_E_SCIENCE_RECOVERY_AND_CAPABILITY_CONTROL_SINGLE_REVIEW_PACKAGE.zip"


def test_final_status_is_binding_negative_and_final_was_not_run() -> None:
    status = json.loads((ROOT / "research_outputs_phase_e" / "final" / "FINAL_STATUS.json").read_text())
    assert status["final_research_status"] == "METHOD_NOT_SUPPORTED_BY_EVIDENCE"
    assert status["final_seeds_consumed"] is False
    assert status["known_results"].startswith("not_evaluated")
    assert status["ood_results"].startswith("not_evaluated")


def test_zip_crc_structure_size_and_sidecar() -> None:
    assert ZIP.is_file() and ZIP.stat().st_size < 512 * 1024 * 1024
    with zipfile.ZipFile(ZIP) as archive:
        assert archive.testzip() is None
        top = {name.split("/")[0] for name in archive.namelist()}
        assert top == {
            "00_README", "01_SCIENCE", "02_LITERATURE", "03_MODEL",
            "04_METHOD_AND_ORACLES", "05_CONFIG_ENV_SOLVERS", "06_SOURCE",
            "07_TESTS_VERIFICATION", "08_EXPERIMENT_DESIGN", "09_RAW_RESULTS",
            "10_SUMMARY_TABLES", "11_FIGURES", "12_FAILURES",
            "13_ANALYSIS_AND_PAPER", "14_REPRODUCIBILITY",
            "15_GIT_AND_MANIFEST", "16_FINAL_STATUS",
        }
        assert not any(name.lower().endswith(".lic") or "__pycache__" in name for name in archive.namelist())
    digest = hashlib.sha256(ZIP.read_bytes()).hexdigest()
    assert (ROOT / f"{ZIP.name}.sha256").read_text().split()[0] == digest


def test_internal_manifest_hashes() -> None:
    with zipfile.ZipFile(ZIP) as archive:
        rows = list(csv.DictReader(archive.read("15_GIT_AND_MANIFEST/FILE_MANIFEST.csv").decode("utf-8").splitlines()))
        for row in rows:
            data = archive.read(row["path"])
            assert len(data) == int(row["bytes"])
            assert hashlib.sha256(data).hexdigest() == row["sha256"]
