from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]


def test_explicit_factor_manifest_and_seed_independence() -> None:
    frame = pd.read_csv(ROOT / "results_phase_d" / "D7" / "SCENARIO_MANIFEST.csv")
    assert len(frame) == 2400
    assert frame["design_cell"].nunique() == 120
    assert frame["episode_seed"].nunique() == 20
    expected_cells = set(frame["design_cell"].unique())
    for _, group in frame.groupby("episode_seed"):
        assert set(group["design_cell"]) == expected_cells
    assert set(frame["plant"]) == {"A", "B"}
    assert set(frame["sfr_period_s"]) == {2, 4}
    assert set(frame["sg_reserve"]) == {"adequate", "scarce", "critical"}
    assert set(frame["execution_status"]) == {"not_evaluated"}
    assert frame["status_reason"].str.contains("H2_PASSIVE_CAPABILITY").all()


def test_seed_firewall_and_no_modulo_factor_encoding() -> None:
    payload = json.loads((ROOT / "results_phase_d" / "D7" / "SEED_FIREWALL.json").read_text(encoding="utf-8"))
    assert payload["final_seeds_used_for_tuning"] is False
    assert payload["final_episodes_executed"] == 0
    forbidden = ("seed%2", "seed % 2", "seed%3", "seed % 3", "seed%4", "seed % 4", "seed%5", "seed % 5")
    for source in (ROOT / "scripts" / "phase_d").glob("*.py"):
        text = source.read_text(encoding="utf-8").lower()
        assert not any(token in text for token in forbidden), source


def test_locked_hashes_match_and_unimplemented_methods_are_not_failures() -> None:
    hashes = json.loads((ROOT / "artifacts_phase_d" / "D7" / "LOCKED_HASHES.json").read_text(encoding="utf-8"))
    for relative, expected in hashes.items():
        path = ROOT / relative
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
    controllers = pd.read_csv(ROOT / "results_phase_d" / "D7" / "CONTROLLER_MANIFEST.csv")
    assert len(controllers) == 7
    assert set(controllers["execution_status"]) == {"not_evaluated"}
    assert controllers["implementation_status"].str.startswith("not_implemented").all()
