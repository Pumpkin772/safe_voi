from __future__ import annotations

import inspect

import pytest

from direction5freq.controllers.voi_accr_mpc import (
    VOIActiveCapabilityCertificationRecourseMPC,
)
from direction5freq.accr.probing import CapabilityHypothesis


def test_registered_a3_diameter_weights_delay_at_one_half() -> None:
    full = [
        CapabilityHypothesis(power, ramp, delay)
        for power in (0.045, 0.080)
        for ramp in (0.025, 0.060)
        for delay in (0.20, 1.50)
    ]
    fixed_delay = [model for model in full if model.delay_s == 0.20]
    diameter = VOIActiveCapabilityCertificationRecourseMPC._diameter
    assert diameter(full) == pytest.approx(1.0)
    assert diameter(fixed_delay) == pytest.approx(0.5)


def test_ordinary_controller_interfaces_have_no_evaluation_truth_argument() -> None:
    propose = inspect.signature(VOIActiveCapabilityCertificationRecourseMPC.propose)
    observe = inspect.signature(VOIActiveCapabilityCertificationRecourseMPC.observe)
    forbidden = {"true_capability", "true_load", "future_event", "future_mode", "evaluation_truth"}
    assert forbidden.isdisjoint(propose.parameters)
    assert forbidden.isdisjoint(observe.parameters)


def test_selected_probe_has_no_fixed_bess_base() -> None:
    source = inspect.getsource(VOIActiveCapabilityCertificationRecourseMPC)
    assert "probe_base_bess_pu=None" in source
    assert "0.05 pu BESS" not in source
