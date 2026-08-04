from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from direction5freq.theory.bridge_certificate import compute_bridge_certificate
from direction5freq.theory.infeasibility_certificate import compute_infeasibility_certificate
from direction5freq.theory.terminal_set import compute_local_rpi_certificate


REPO = Path(__file__).resolve().parents[2]


def test_load_parameterized_terminal_rpi_is_recomputable_nonempty_and_admissible() -> None:
    certificate = compute_local_rpi_certificate(2.0, [0.06, 0.048])
    assert certificate.nonempty
    assert certificate.admissible
    assert certificate.invariance_residual <= 1e-12
    assert certificate.closed_loop_spectral_radius < 1.0
    assert certificate.minimum_state_margin_pu > 0.0
    assert certificate.minimum_input_margin_pu > 0.0
    assert certificate.claim_level == "CONDITIONAL_LOCAL_LINEAR_RPI"


def test_bridge_and_infeasibility_certificates_keep_distinct_claims() -> None:
    bridge = compute_bridge_certificate([0.165, 0.145], [0.5, 0.5])
    assert bridge.certified
    assert bridge.handoff_time_s > 0.0
    assert bridge.energy_margin_mwh >= 0.0
    infeasible = compute_infeasibility_certificate([0.28, 0.27], [0.5, 0.5])
    assert infeasible.certified_infeasible
    assert infeasible.certificate_type == "STEADY_POWER_INFEASIBLE"


def test_dense_delay_and_claim_boundary_are_bounded() -> None:
    dense = pd.read_csv(REPO / "results_phase_i/I5/DENSE_DELAY_VALIDATION.csv")
    assert len(dense) >= 100
    assert dense.finite_horizon_constraints_hold.all()
    claims = (REPO / "research_outputs_phase_i/06_THEORY/CLAIM_BOUNDARY.md").read_text("utf-8")
    assert "Recursive feasibility is not claimed for native Plant B" in claims
    assert "finite-horizon" in claims


def test_i5_gate_and_certificate_status_pass() -> None:
    progress = json.loads((REPO / "progress_phase_i/I5.json").read_text("utf-8"))
    assert progress["gate_passed"]
    assert progress["certificate_status"] == "CONDITIONAL_LOCAL_RPI_PLUS_FINITE_HORIZON_BRIDGE"
    assert progress["native_plant_b_theory"] == "EMPIRICAL_VALIDATION_ONLY"
    assert not progress["final_seeds_consumed"]
