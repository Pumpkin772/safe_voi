from __future__ import annotations

import inspect
import json
from pathlib import Path

import numpy as np

from direction1freq.controllers.proposed_robust_tube_mpc import CapabilitySetRobustTubeMPC
from direction1freq.models.plant_a_v2 import TwoAreaPlantAV2
from direction1freq.optimization.tube_propagation import verify_box_tube


ROOT = Path(__file__).resolve().parents[2]


def test_branch_is_uniquely_locked_to_r() -> None:
    selected = json.loads((ROOT / "research_outputs_phase_e" / "06_METHOD" / "SELECTED_BRANCH.json").read_text())
    assert selected["selected_branch"] == "R"
    assert selected["alternate_branches_implemented"] is False


def test_selected_method_is_real_rolling_mpc_and_no_truth_api() -> None:
    source = inspect.getsource(CapabilitySetRobustTubeMPC)
    for token in ("horizon", "optimizer.solve", "predicted_states", "terminal", "fallback"):
        assert token in source
    signature = inspect.signature(CapabilitySetRobustTubeMPC.update)
    for forbidden in ("true_capability", "hidden_parameter", "future_load", "future_event"):
        assert forbidden not in signature.parameters


def test_tube_certificate_and_forced_fallback() -> None:
    controller = CapabilitySetRobustTubeMPC(4.0, 5)
    assert verify_box_tube(controller.tube, controller.optimizer.ad, controller.optimizer.bd) <= 1e-12
    plant = TwoAreaPlantAV2(); state = plant.equilibrium()
    observation = plant.public_observation(0.0, state, np.zeros(4))
    action, diagnostic = controller.update(
        observation, plant.state_vector(state), np.zeros(2), 0.05,
        force_solver_failure=True,
    )
    assert diagnostic.used_fallback
    assert np.allclose(action[[1, 3]], 0.0)


def test_e6_progress_matches_gate() -> None:
    progress = json.loads((ROOT / "progress_phase_e" / "E6_full.json").read_text())
    assert progress["selected_branch"] == "R"
    assert progress["decision"] == (
        "CONTINUE_TO_E7" if progress["gate_passed"] else "METHOD_NOT_SUPPORTED_BY_EVIDENCE"
    )
