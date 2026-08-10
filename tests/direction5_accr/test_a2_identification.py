from __future__ import annotations

import inspect

import numpy as np

from direction5freq.accr.capability_identification import PassiveCapabilityIdentifier
from direction5freq.models.capability_contract import BESSParameters


def test_identifier_api_has_no_truth_or_load_input() -> None:
    signature = inspect.signature(PassiveCapabilityIdentifier.update)
    assert list(signature.parameters) == [
        "self", "time_s", "requested_total_power_pu", "actual_poi_power_pu"
    ]


def test_no_excitation_keeps_performance_at_contract() -> None:
    parameters = BESSParameters()
    identifier = PassiveCapabilityIdentifier(parameters.contract, 0.25, window_s=8.0)
    snapshot = None
    for index in range(12):
        command = np.array((0.001 * index / 12, -0.001 * index / 12))
        snapshot = identifier.update(0.25 * index, command, 0.2 * command)
    assert snapshot is not None
    assert not snapshot.interval_set.excitation_sufficient.any()
    assert np.all(snapshot.interval_set.delay_candidate_count == 31)
    assert np.allclose(snapshot.candidate_set.performance_power_pu, parameters.contract.upper_power_pu)


def test_incompatible_transition_triggers_grid_reset_and_mhe_reset() -> None:
    parameters = BESSParameters()
    identifier = PassiveCapabilityIdentifier(parameters.contract, 0.25, window_s=8.0)
    reset = False
    snapshot = None
    for index in range(16):
        actual = np.array((0.06, -0.06)) if index < 10 else np.array((-0.06, 0.06))
        snapshot = identifier.update(index * 0.25, np.array((0.08, -0.08)), actual)
        reset |= bool(snapshot.candidate_set.change_reset.any())
    assert reset
    assert snapshot is not None
    assert snapshot.interval_set.samples < 16

