from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd

from direction5_freq.controllers import DCSVInput, DisturbanceCapabilitySeparatedViabilityMPC


REPO = Path(__file__).resolve().parents[2]
THEORY = REPO / "research_outputs_phase_h/05_THEORY"


def _zero_input() -> DCSVInput:
    return DCSVInput(
        np.zeros(9),
        np.zeros(2),
        np.zeros(4),
        np.zeros(2),
        np.full(2, 25.0),
        np.full(2, 0.05),
        np.full(2, 0.05),
        np.full(2, 0.04),
        np.full(2, 0.04),
        np.array([[0.1, 0.4], [0.1, 0.4]]),
        np.full(2, 10.0),
        np.array([[0.5, 1.0], [0.5, 1.0]]),
    )


def test_sustainable_rpi_scope_is_explicit_and_not_overclaimed() -> None:
    terminal = np.load(THEORY / "SUSTAINABLE_TERMINAL_SET.npz")
    assert terminal["invariant"].all()
    assert terminal["admissible"].tolist() == [True, True, False, False]
    status = json.loads((THEORY / "SUSTAINABLE_CERTIFICATE.json").read_text("utf-8"))
    assert status["conditional_recursive_feasibility_by_plant"] == {
        "A": True,
        "B": False,
    }
    assert not status["conditional_recursive_feasibility_certified"]
    assert "empirical" in status["empirical_set_limitation"].lower()


def test_dcsv_uses_exact_rpi_generator_and_zero_bess_terminal_command() -> None:
    plant_a = DisturbanceCapabilitySeparatedViabilityMPC(2.0, 3, plant="A")
    assert plant_a.terminal_generator_matrix is not None
    _, diagnostic = plant_a.control(_zero_input())
    assert diagnostic.solved and not diagnostic.restoration_used
    assert np.max(np.abs(diagnostic.predicted_actions[-1, [1, 3]])) <= 1e-8
    plant_b = DisturbanceCapabilitySeparatedViabilityMPC(2.0, 3, plant="B")
    assert plant_b.terminal_generator_matrix is None


def test_bridge_and_infeasibility_certificates_are_complete() -> None:
    bridge = pd.read_parquet(THEORY / "BRIDGE_CERTIFICATES.parquet")
    assert len(bridge) == 58
    assert bridge.finite_horizon_viable.all()
    assert not bridge.recursive_feasibility_claimed.any()
    infeasible = pd.read_parquet(THEORY / "INFEASIBILITY_CERTIFICATES.parquet")
    assert len(infeasible) == 26
    assert infeasible.certificate_nonempty.all()
    assert infeasible.not_counted_as_controller_failure.all()


def test_certificate_reproducer_runs_without_external_evidence() -> None:
    completed = subprocess.run(
        [sys.executable, str(THEORY / "REPRODUCE_CERTIFICATES.py")],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "H6_CERTIFICATES_REPLAYED 58 26" in completed.stdout


def test_h6_gate_records_claim_reduction_repair() -> None:
    progress = json.loads((REPO / "progress_phase_h/H6.json").read_text("utf-8"))
    assert progress["gate_passed"]
    assert progress["repairs_used"] == 1
    assert progress["conditional_recursive_feasibility_by_plant"] == {
        "A": True,
        "B": False,
    }
