from __future__ import annotations

import inspect

import numpy as np

from direction1freq.estimation import AugmentedLoadKalman
from direction1freq.identification import CausalCapabilitySetEstimator


def test_capability_estimator_is_causal_by_api_and_source() -> None:
    names = set(inspect.signature(CausalCapabilitySetEstimator.update).parameters)
    assert names == {"self", "issued_total_command_pu", "measured_power_pu"}
    source = inspect.getsource(CausalCapabilitySetEstimator)
    assert "mode='same'" not in source and 'mode="same"' not in source
    assert "future" not in source.casefold()
    assert "source_label" not in source


def test_cusum_has_no_nominal_alarm_and_resets_on_persistent_mismatch() -> None:
    estimator = CausalCapabilitySetEstimator(dt_s=0.05, noise_bound_pu=0.001)
    power = 0.0
    nominal_alarms = 0
    for index in range(120):
        command = 0.04 if index >= 10 else 0.0
        delayed_command = 0.04 if index >= 14 else 0.0
        power += np.clip((delayed_command - power) / 0.15, -0.08, 0.08) * 0.05
        estimate = estimator.update(command, power)
        nominal_alarms += int(estimate.alarm)
    assert nominal_alarms == 0
    alarmed = False
    for _ in range(20):
        estimate = estimator.update(0.09, 0.02)
        alarmed |= estimate.alarm
    assert alarmed
    assert estimate.power_magnitude_interval_pu[0] == 0.0


def test_augmented_load_filter_uses_public_shapes_and_finite_covariance() -> None:
    estimator = AugmentedLoadKalman(dt_s=0.05)
    for _ in range(20):
        estimate = estimator.update(np.array([-0.01, 0.0]), -0.001, np.array([0.01, 0.0, 0.0, 0.0]))
    assert estimate.load_pu.shape == (2,)
    assert np.isfinite(estimate.covariance).all()
    assert np.min(np.linalg.eigvalsh(estimate.covariance)) >= -1e-12

