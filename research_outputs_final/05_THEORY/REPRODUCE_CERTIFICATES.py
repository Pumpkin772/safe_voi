"""Minimal independent replay for the Direction5 R4 certificates."""

from __future__ import annotations

from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from direction5freq.theory.bridge_certificate import compute_bridge_certificate
from direction5freq.theory.impossibility import construct_same_instant_impossibility_witness
from direction5freq.theory.infeasibility_certificate import compute_infeasibility_certificate
from direction5freq.theory.terminal_set import compute_local_rpi_certificate


terminal = compute_local_rpi_certificate(2.0, np.array((0.06, 0.048)))
bridge = compute_bridge_certificate(np.array((0.145, 0.135)), np.array((0.5, 0.5)))
infeasible = compute_infeasibility_certificate(np.array((0.28, 0.27)), np.array((0.5, 0.5)))
impossible = construct_same_instant_impossibility_witness(
    np.array((0.045, 0.045)), np.array((0.045, 0.045)), np.array((0.010, 0.012))
)
assert terminal.nonempty and terminal.admissible
assert bridge.certified
assert infeasible.certified_infeasible
assert impossible.impossibility_established
print("R4_MINIMAL_CERTIFICATE_REPLAY_PASS")
