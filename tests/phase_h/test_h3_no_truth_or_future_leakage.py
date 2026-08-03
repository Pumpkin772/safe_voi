from __future__ import annotations

import inspect
import json
from pathlib import Path

import numpy as np
import pandas as pd

from direction5_freq.estimation.capability_set_estimator import CapabilitySetEstimator
from direction5_freq.estimation.grid_disturbance_observer import (
    GridDisturbanceObserver,
    GridPublicMeasurement,
)


ROOT = Path(__file__).resolve().parents[2]


def test_load_observer_is_invariant_to_absent_bess_command() -> None:
    observer_a = GridDisturbanceObserver(2.0)
    observer_b = GridDisturbanceObserver(2.0)
    measurement = GridPublicMeasurement(
        2.0,
        np.array([-0.02, 0.01]),
        0.001,
        np.array([0.03, -0.01]),
        np.array([0.015, -0.005]),
        np.array([0.02, -0.01]),
    )
    assert np.allclose(observer_a.update(measurement).load_pu, observer_b.update(measurement).load_pu)
    signature = inspect.signature(GridDisturbanceObserver.update)
    assert "issued_bess" not in str(signature).lower()


def test_capability_estimator_api_has_no_truth_or_future_input() -> None:
    signature = str(inspect.signature(CapabilitySetEstimator.update)).lower()
    assert "truth" not in signature
    assert "future" not in signature
    assert "mode" not in signature


def test_no_excitation_holds_wide_set_without_false_shrinkage() -> None:
    estimator = CapabilitySetEstimator(0.05)
    estimate = None
    for index in range(100):
        estimate = estimator.update(
            index * 0.05,
            np.zeros(2),
            np.zeros(2),
            np.zeros(2),
            np.full(2, 0.5),
        )
    assert estimate is not None
    assert not estimate.excitation_sufficient.any()
    assert np.allclose(estimate.power_discharge_interval_pu[:, 0], 0.0)
    assert np.allclose(estimate.power_discharge_interval_pu[:, 1], 0.10)
    assert np.allclose(estimate.delay_interval_s, [[0.0, 2.0], [0.0, 2.0]])


def test_h3_gate_and_public_information_boundary() -> None:
    progress = json.loads((ROOT / "progress_phase_h/H3.json").read_text())
    assert progress["gate_passed"] is True
    assert progress["validation_minimum_capability_coverage"] >= 0.95
    assert progress["validation_maximum_false_shrinkage"] <= 0.05
    assert progress["final_seeds_consumed"] is False
    trajectories = pd.read_parquet(
        ROOT / "results_phase_h/H3/ESTIMATOR_CONTROL_CYCLE_TRAJECTORIES.parquet"
    )
    assert trajectories.actual_bess_poi_used.all()
    assert not trajectories.issued_bess_command_used_by_load_observer.any()
