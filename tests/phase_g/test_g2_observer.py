from __future__ import annotations

import inspect

import numpy as np

from direction1freq.estimation.structured_observer import StructuredLoadStateObserver
from direction1freq.models.plant_a_v2 import TwoAreaPlantAV2


def test_observer_api_is_causal_and_does_not_accept_truth_or_future() -> None:
    signature = inspect.signature(StructuredLoadStateObserver.update)
    assert list(signature.parameters) == ["self", "observation"]
    source = inspect.getsource(StructuredLoadStateObserver.update).lower()
    assert "true_load" not in source
    assert "future" not in source


def test_observer_keeps_hidden_valve_distinct_from_mechanical_measurement() -> None:
    plant = TwoAreaPlantAV2()
    observer = StructuredLoadStateObserver(2.0, plant=plant)
    state = plant.equilibrium()
    observation = plant.public_observation(0.0, state, np.zeros(4))
    estimate = observer.update(observation)
    assert estimate.state_pu.shape == (9,)
    assert estimate.load_pu.shape == (2,)
    assert observer.C[:, 3:5].sum() == 0.0
    assert np.all(np.linalg.eigvalsh(estimate.covariance) >= -1e-12)
