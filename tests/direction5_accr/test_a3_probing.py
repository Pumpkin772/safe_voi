from __future__ import annotations

import numpy as np

from direction5freq.accr.probing import (
    CapabilityHypothesis, ProbeCandidate, allocation_neutral_action,
    filter_models, simulate_hypothesis,
)


def test_probe_is_allocation_neutral_at_command_level_only() -> None:
    base = np.array((0.035, 0.045, 0.020, 0.0))
    action = allocation_neutral_action(base, 0.0025)
    assert np.isclose(action[0] + action[1], base[0] + base[1])
    assert action[0] != base[0] and action[1] != base[1]


def test_true_hypothesis_survives_bounded_measurement_error() -> None:
    probe = ProbeCandidate("alternating", 0.0025, np.array((1.0, -1.0, 1.0, -1.0)))
    truth = CapabilityHypothesis(0.065, 0.040, 0.80)
    models = [truth, CapabilityHypothesis(0.045, 0.025, 1.50)]
    measured = simulate_hypothesis(truth, probe, period_s=2.0, dt_s=0.05, base_power_pu=0.045)
    measured += 0.0001
    retained = filter_models(
        models, measured, probe, period_s=2.0, dt_s=0.05,
        base_power_pu=0.045, residual_bound_pu=0.00055,
    )
    assert truth in retained


def test_probe_sequence_is_zero_sum() -> None:
    probe = ProbeCandidate("alternating", 0.0025, np.array((1.0, -1.0, 1.0, -1.0)))
    assert abs(float(probe.sequence_pu.sum())) < 1e-12

