from __future__ import annotations

import numpy as np

from direction5freq.accr.probing import allocation_neutral_action
from direction5freq.theory.impossibility import construct_same_instant_impossibility_witness
from direction5freq.theory.terminal_set import compute_local_rpi_certificate


def test_probe_allocation_identity_is_exact() -> None:
    base = np.array((0.02, 0.01, 0.0, 0.0))
    action = allocation_neutral_action(base, 0.0025)
    assert abs(action[0] + action[1] - base[0] - base[1]) <= 1e-12


def test_same_instant_loss_witness_is_constructive() -> None:
    witness = construct_same_instant_impossibility_witness(
        np.array((0.06, 0.06)), np.array((0.065, 0.065)), np.array((0.04, 0.04))
    )
    assert witness.impossibility_established


def test_registered_local_terminal_box_is_admissible() -> None:
    certificate = compute_local_rpi_certificate(2.0, np.array((0.03, 0.024)))
    assert certificate.nonempty
    assert certificate.admissible
    assert certificate.invariance_residual <= 1e-12
