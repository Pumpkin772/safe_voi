from __future__ import annotations

import inspect

from direction5freq.accr.accr_mpc import ActiveCapabilityCertificationRecourseMPC
from direction5freq.accr.validation import MPC_METHODS
from direction5freq.controllers.dcsv_cr_mpc import DCSVContractRecourseMPC
from direction5freq.models.plant_a_full import PlantAFull


def test_all_named_mpc_comparators_are_registered_as_rolling() -> None:
    required = {
        "contract_only_recourse_mpc", "passive_set_adaptive_mpc",
        "safe_persistent_excitation_mpc", "fixed_periodic_probe_mpc",
        "unsafe_no_gate_probe_mpc", "accr_mpc",
        "perfect_capability_recourse_oracle",
    }
    assert set(MPC_METHODS) == required
    assert DCSVContractRecourseMPC.is_true_rolling_mpc


def test_accr_ordinary_interface_remains_truth_free_after_a6_trigger_extension() -> None:
    for method in (
        ActiveCapabilityCertificationRecourseMPC.observe,
        ActiveCapabilityCertificationRecourseMPC.propose,
        ActiveCapabilityCertificationRecourseMPC.commit,
    ):
        assert "true_capability" not in inspect.signature(method).parameters


def test_development_weight_is_explicit_and_defaults_to_a4_value() -> None:
    controller = DCSVContractRecourseMPC(2.0, 3, PlantAFull().parameters)
    assert controller.delivered_branch_weight == 0.05
