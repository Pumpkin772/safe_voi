from __future__ import annotations
from pathlib import Path
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
terminal = np.load(ROOT / "research_outputs_phase_h/05_THEORY/SUSTAINABLE_TERMINAL_SET.npz")
status = json.loads((ROOT / "research_outputs_phase_h/05_THEORY/SUSTAINABLE_CERTIFICATE.json").read_text("utf-8"))
bridge = pd.read_parquet(ROOT / "research_outputs_phase_h/05_THEORY/BRIDGE_CERTIFICATES.parquet")
infeasible = pd.read_parquet(ROOT / "research_outputs_phase_h/05_THEORY/INFEASIBILITY_CERTIFICATES.parquet")
assert terminal["invariant"].all() and terminal["admissible"].any()
assert bridge.finite_horizon_viable.all()
assert infeasible.certificate_nonempty.all()
assert status["conditional_recursive_feasibility_by_plant"]["A"]
assert not status["conditional_recursive_feasibility_by_plant"]["B"]
print("H6_CERTIFICATES_REPLAYED", len(bridge), len(infeasible))
