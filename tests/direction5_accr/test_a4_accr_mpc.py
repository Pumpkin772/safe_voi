from __future__ import annotations

import inspect

import numpy as np

from direction5freq.accr.accr_mpc import ActiveCapabilityCertificationRecourseMPC
from direction5freq.accr.probing import CapabilityHypothesis
from direction5freq.models.plant_a_full import PlantAFull


def test_accr_public_interfaces_have_no_truth_load_or_future_arguments() -> None:
    for method in (
        ActiveCapabilityCertificationRecourseMPC.observe,
        ActiveCapabilityCertificationRecourseMPC.propose,
        ActiveCapabilityCertificationRecourseMPC.commit,
    ):
        parameters = set(inspect.signature(method).parameters)
        assert not parameters & {"true_capability", "true_load", "future_event", "future_mode"}


def test_certificate_is_finite_and_constructed_from_candidate_set() -> None:
    parameters = PlantAFull().parameters
    controller = ActiveCapabilityCertificationRecourseMPC(2.0, 3, parameters)
    retained = [CapabilityHypothesis(0.065, 0.040, 0.80)]
    certificate = controller.accept_public_candidate_set(retained, 10.0)
    assert certificate is not None
    assert certificate.valid_at(10.0)
    assert not certificate.valid_at(50.1)
    assert np.allclose(certificate.power_lower_pu, 0.065)


def test_core_is_true_rolling_and_contains_loss_branch() -> None:
    controller = ActiveCapabilityCertificationRecourseMPC(2.0, 3, PlantAFull().parameters)
    assert controller.is_true_rolling_mpc
    assert {branch.name for branch in controller.core.tree.branches} == {"DELIVERED", "SURPLUS_LOSS"}

