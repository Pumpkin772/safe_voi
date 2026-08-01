from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from direction1freq.models.delay_augmented_prediction import (
    exact_fractional_delay_vertex,
)
from direction1freq.models.guaranteed_capability_envelope import (
    GuaranteedCapabilityEnvelope,
)


ROOT = Path(__file__).resolve().parents[2]


def test_delay_augmented_state_keeps_previous_action_and_energy() -> None:
    vertex = exact_fractional_delay_vertex(2.0, 1.999)
    assert vertex.a_augmented.shape == (15, 15)
    assert vertex.b_augmented.shape == (15, 4)
    assert vertex.e_augmented.shape == (15, 2)
    assert np.allclose(vertex.b_augmented[9:13], np.eye(4))
    assert np.allclose(vertex.a_augmented[13:15, 13:15], np.eye(2))
    assert not np.allclose(vertex.b_current[:, 1], vertex.b_previous[:, 1])


def test_total_pfr_sfr_power_and_energy_match_physical_sign_convention() -> None:
    envelope = GuaranteedCapabilityEnvelope.phase_f_registered()
    omega = np.array([-0.002, 0.001])
    sfr = np.array([0.01, -0.02])
    total = envelope.total_bess_power(sfr, omega)
    assert np.allclose(total, sfr - 2.5 * omega)
    energy = np.array([25.0, 25.0])
    updated = envelope.next_energy_mwh(
        energy,
        discharge_pu=np.array([0.03, 0.0]),
        charge_pu=np.array([0.0, 0.03]),
        period_s=4.0,
    )
    expected = energy - 4.0 * 1000.0 / 3600.0 * np.array(
        [0.03 / 0.95, -0.95 * 0.03]
    )
    assert np.allclose(updated, expected)


def test_f3_registered_set_passes_without_truth_controller_fields() -> None:
    progress = json.loads((ROOT / "progress_phase_f" / "F3.json").read_text())
    assert progress["gate_passed"] is True
    assert progress["gate_components"][
        "validation_residual_coverage_at_least_95pct"
    ]
    config = (ROOT / "configs" / "phase_f" / "capability_envelope.yaml").read_text()
    assert "controller_truth_fields: []" in config

