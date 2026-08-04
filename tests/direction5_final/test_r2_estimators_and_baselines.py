from __future__ import annotations

import inspect
import json
from pathlib import Path

import numpy as np
import pandas as pd

from direction5freq.controllers.anti_windup_pi import FixedAllocationAntiWindupPI
from direction5freq.estimation.deliverability_set_membership import DeliverabilitySetMembership
from direction5freq.estimation.grid_load_mhe import (
    AugmentedKalmanLoadObserver,
    ConstrainedGridLoadMHE,
    UnknownInputLoadObserver,
)
from direction5freq.models.plant_a_full import PlantAFull


REPO = Path(__file__).resolve().parents[2]


def test_load_observer_apis_use_actual_poi_and_have_no_command_or_truth() -> None:
    for observer in (AugmentedKalmanLoadObserver, UnknownInputLoadObserver, ConstrainedGridLoadMHE):
        source = inspect.getsource(observer)
        assert "true_load" not in source
        assert "issued_command" not in source
    input_source = inspect.getsource(__import__(
        "direction5freq.estimation.grid_load_observer", fromlist=["LoadObserverInput"]
    ).LoadObserverInput)
    assert "bess_actual_poi_power_pu" in input_source


def test_set_membership_no_excitation_stays_at_contract() -> None:
    contract = PlantAFull().parameters.bess.contract
    estimator = DeliverabilitySetMembership(contract, 0.25)
    snapshot = None
    for index in range(12):
        command = np.array((0.002 * index / 12, -0.002 * index / 12))
        snapshot = estimator.update(0.25 * index, command, 0.25 * command)
    assert snapshot is not None
    assert not snapshot.excitation_sufficient.any()
    assert np.allclose(snapshot.performance_power_pu, contract.upper_power_pu)
    assert snapshot.parameter_bounds_ab.shape[-1] == 4


def test_anti_windup_back_calculation_bounds_integrator() -> None:
    plant = PlantAFull()
    observation = plant.public_observation(0.0, plant.equilibrium(), np.zeros(4))
    controller = FixedAllocationAntiWindupPI(4.0)
    forced = observation.__class__(
        **{**{name: getattr(observation, name) for name in observation.__dataclass_fields__}, "ace_pu": np.array((2.0, -2.0))}
    )
    for _ in range(100):
        controller.propose(forced)
    assert np.linalg.norm(controller.integral) < 100.0
    assert controller.saturation_count == 100


def test_performance_witness_is_revoked_when_excitation_changes_sign() -> None:
    plant = PlantAFull()
    estimator = DeliverabilitySetMembership(plant.parameters.bess.contract, 0.25)
    snapshot = estimator.update(0.0, np.array((0.08, 0.08)), np.zeros(2))
    for index in range(1, 9):
        snapshot = estimator.update(
            0.25 * index,
            np.array((0.08, 0.08)),
            np.array((0.06, 0.06)),
        )
    assert np.all(snapshot.performance_power_pu >= snapshot.contract_power_pu)
    snapshot = estimator.update(
        2.25, np.array((-0.08, -0.08)), np.array((0.055, 0.055))
    )
    assert np.allclose(snapshot.performance_power_pu, snapshot.contract_power_pu)


def test_r2_outputs_pass_registered_gates() -> None:
    progress = json.loads((REPO / "progress_final/R2.json").read_text("utf-8"))
    assert progress["status"] == "PASS"
    assert progress["coverage"]["delay_coverage"] >= 0.95
    assert progress["coverage"]["false_optimism"] <= 0.01
    structures = pd.read_csv(REPO / "results_final/R2/BASELINE_MPC_STRUCTURE.csv")
    mpc = structures[structures.solver_status.ne("NOT_AN_MPC")]
    assert mpc.true_rolling.all()
    assert (mpc.predicted_input_steps > 0).all()
    assert mpc.has_dynamics_constraints.all()
