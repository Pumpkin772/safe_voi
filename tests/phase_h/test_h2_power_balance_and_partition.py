from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from direction5_freq.models.load_parameterized_equilibrium import solve_sustainable_equilibrium


ROOT = Path(__file__).resolve().parents[2]


def test_load_parameterized_equilibrium_has_exact_balance() -> None:
    result = solve_sustainable_equilibrium(
        np.array([0.06, 0.04]),
        np.array([-0.05, -0.05]),
        np.array([0.05, 0.05]),
        0.08,
    )
    assert result.feasible
    assert np.max(np.abs(result.balance_residual_pu)) < 1e-8
    assert np.allclose(result.bess_power_pu, 0.0)
    assert np.allclose(result.state_pu[3:5], result.sg_power_pu)
    assert np.allclose(result.state_pu[5:7], result.sg_power_pu)


def test_all_cells_are_preclassified_and_each_domain_is_nonempty() -> None:
    cells = pd.read_parquet(
        ROOT / "results_phase_h/H2/SUSTAINABILITY_CELLS.parquet"
    )
    expected = {
        "SUSTAINABLE",
        "BRIDGE_ONLY",
        "PHYSICALLY_INFEASIBLE_UNDER_REGISTERED_CAPABILITY",
    }
    assert set(cells.classification) == expected
    assert cells.cell_id.is_unique
    assert cells.classification_locked_before_terminal_calibration.all()
    feasible = cells[cells.equilibrium_feasible]
    assert feasible.equilibrium_balance_residual_max_pu.max() < 1e-8


def test_infeasible_cells_are_not_controller_failures() -> None:
    cells = pd.read_csv(
        ROOT / "results_phase_h/H2/PHYSICALLY_INFEASIBLE_CELLS.csv"
    )
    assert len(cells) > 0
    assert cells.physical_infeasibility_not_controller_failure.all()
    assert cells.binding_constraints.str.len().gt(0).all()


def test_domain_manifest_hash_is_locked_and_final_seeds_are_unused() -> None:
    lock = json.loads(
        (ROOT / "configs/phase_h/H2_DOMAIN_MANIFEST_LOCK.json").read_text()
    )
    progress = json.loads((ROOT / "progress_phase_h/H2.json").read_text())
    assert lock["sha256"] == progress["domain_manifest_sha256"]
    assert lock["locked_before_terminal_calibration"] is True
    assert progress["gate_passed"] is True
    assert progress["final_seeds_consumed"] is False


def test_plant_a_and_native_plant_b_crosschecks_converged() -> None:
    checks = pd.read_csv(
        ROOT / "results_phase_h/H2/EQUILIBRIUM_TIME_DOMAIN_CROSSCHECK.csv"
    )
    assert set(checks.plant) == {"A", "B"}
    assert set(checks.period_s) == {2.0, 4.0}
    assert checks.converged.all()
    assert checks[checks.plant.eq("B")].native_network.all()
