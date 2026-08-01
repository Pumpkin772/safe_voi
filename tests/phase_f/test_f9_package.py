from __future__ import annotations

import json
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[2]


def test_phase_f_review_zip_verification() -> None:
    verification = json.loads(
        (ROOT / "artifacts_phase_f" / "FINAL_ZIP_VERIFICATION.json").read_text()
    )
    path = Path(verification["zip"])
    assert path.is_file()
    assert verification["under_512mb"]
    assert verification["crc_error"] is None
    assert verification["required_directories_present"]
    assert not verification["license_files_packaged"]
    assert verification["tracked_tree_clean"]
    assert all(
        item["returncode"] == 0 for item in verification["fresh_extracted_replay"]
    )
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None

