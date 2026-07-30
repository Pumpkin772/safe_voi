from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from direction1freq.identification.safe_probe_design import SafeProbeDesigner


ROOT = Path(__file__).resolve().parents[2]


def test_probe_is_zero_mean_locally_compensated_and_backup_checked() -> None:
    designer = SafeProbeDesigner(4.0, 0.04)
    base = np.zeros(4)
    first = designer.apply(8.0, base, np.zeros(2), np.zeros(2), 0.10)
    second = designer.apply(12.0, base, np.zeros(2), np.zeros(2), 0.10)
    assert np.allclose(first.probe_bess + second.probe_bess, 0.0)
    assert np.allclose(first.action[[0, 2]] + first.action[[1, 3]], 0.0)
    assert first.backup_feasible


def test_probe_suppresses_without_sg_backup() -> None:
    designer = SafeProbeDesigner(4.0, 0.04)
    base = np.array([-0.02, 0.0, 0.02, 0.0])
    decision = designer.apply(8.0, base, np.zeros(2), np.zeros(2), 0.03)
    assert np.allclose(decision.probe_bess, 0.0)
    assert decision.suppressed_reason == "sg_backup_reserve_infeasible"


def test_e5_gate_and_branch_are_consistent() -> None:
    progress = json.loads((ROOT / "progress_phase_e" / "E5.json").read_text())
    assert progress["decision"] == ("SELECT_BRANCH_A" if progress["gate_passed"] else "SELECT_BRANCH_R")
    episodes = pd.read_parquet(ROOT / "results_phase_e" / "E5" / "E5_ACTIVE_FEASIBILITY.parquet")
    assert set(episodes.method) == {"no_probe", "fixed_micro_probe", "optimized_probe"}
    assert episodes.physical_success.notna().all()


def test_active_run_respects_registered_budgets() -> None:
    progress = json.loads((ROOT / "progress_phase_e" / "E5.json").read_text())
    within = (
        progress["tests"]["maximum_probe_energy_mwh"] <= 1.50 + 1e-12
        and progress["tests"]["maximum_probe_mileage_pu"] <= 2.50 + 1e-12
    )
    assert progress["gate_components"]["probe_energy_and_mileage_budget"] is within
