from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]


def test_g2_stop_preserves_not_evaluated_and_final_seed_firewall() -> None:
    status = json.loads(
        (ROOT / "research_outputs_phase_g/final/FINAL_STATUS.json").read_text()
    )
    assert status["final_research_status"] == "LOCAL_TERMINAL_MODEL_NOT_CERTIFIABLE"
    assert status["final_seeds_consumed"] is False
    assert status["gates"]["G2"] == "FAIL"
    assert all(status["gates"][f"G{i}"] == "NOT_EVALUATED" for i in range(3, 9))
    assert status["conditional_recursive_feasibility_certified"] is False


def test_every_effective_one_step_terminal_quantity_is_incompatible() -> None:
    table = pd.read_csv(
        ROOT / "results_phase_g/G2/LOCAL_ONE_STEP_TERMINAL_COMPATIBILITY.csv"
    )
    assert len(table) == 5
    assert not table.compatible.any()
    certificate = json.loads(
        (
            ROOT
            / "research_outputs_phase_g/05_THEORY/LOCAL_TERMINAL_INCOMPATIBILITY_CERTIFICATE.json"
        ).read_text()
    )
    assert certificate["all_registered_terminal_metrics_incompatible"] is True
    assert certificate["cvxpy_required_for_verification"] is False


def test_stopped_stages_are_explicitly_not_evaluated() -> None:
    manifest = pd.read_csv(
        ROOT
        / "research_outputs_phase_g/03_MODEL/SUSTAINABLE_BRIDGE_INFEASIBLE_MANIFEST.csv"
    )
    assert manifest.shape[0] == 1
    assert manifest.loc[0, "classification"] == "NOT_EVALUATED"
    assert int(manifest.loc[0, "episodes"]) == 0
    assert (
        ROOT
        / "research_outputs_phase_g/05_THEORY/G4_TERMINAL_AND_BRIDGE_CERTIFICATE_STATUS.md"
    ).is_file()
    assert (
        ROOT / "research_outputs_phase_g/04_METHOD/G5_CDSR_REPAIR_STATUS.md"
    ).is_file()
