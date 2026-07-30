"""Phase C1 literature-contract tests."""

from __future__ import annotations

import csv
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


def test_literature_preregistration_counts_and_fields() -> None:
    root = REPO / "research_outputs" / "literature"
    with (root / "LITERATURE_MATRIX.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) >= 40
    assert sum(row["formal_peer_reviewed_or_standard"] == "True" for row in rows) >= 25
    assert sum(int(row["year"]) > 2021 for row in rows) * 2 >= len(rows)
    required = {
        "citation", "problem", "plant_model", "black_box", "multiple_modes",
        "online_change", "frequency_service", "multi_area", "ACE_tie_line",
        "diagnosis_before_control_harm", "constraint_guarantee", "active_identification",
        "native_RMS_or_EMT", "data_requirements", "limitations",
    }
    assert required <= set(rows[0])
    assert all(row["title"] and row["year"] and row["source_url"] for row in rows)


def test_metadata_verification_has_no_fabricated_records() -> None:
    payload = json.loads(
        (REPO / "research_outputs/literature/METADATA_VERIFICATION.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["minimum_total_satisfied"] is True
    assert payload["minimum_formal_satisfied"] is True
    assert payload["at_least_half_after_2021_satisfied"] is True
    assert payload["fabricated_records"] == 0
