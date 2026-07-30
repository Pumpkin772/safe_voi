from __future__ import annotations

import inspect
import json
from pathlib import Path

import numpy as np

from direction1freq.controllers import (
    ACEPIAntiWindup, DiscreteLQIBaseline, design_discrete_lqi, design_stable_pi,
)
from direction1freq.models.bess_capability_v2 import (
    BESSParametersV2, BESSStateV2, CapabilityTruthV2, step_bess_v2,
)
from direction1freq.models.plant_a_v2 import TwoAreaPlantAV2
from direction1freq.models.plant_b_andes_v2 import AndesKundurPlantBV2


ROOT = Path(__file__).resolve().parents[2]


def test_nominal_closed_loop_small_signal_decay() -> None:
    result = json.loads((ROOT / "results_phase_e/E2/E2_MODEL_AND_STABILITY_RESULTS.json").read_text())
    assert result["small_terminal_hz"] <= max(1e-8, 0.10 * result["small_peak_hz"])
    assert result["zero_max_hz"] <= 1e-12


def test_background_load_controller_does_not_destabilize() -> None:
    result = json.loads((ROOT / "results_phase_e/E2/E2_MODEL_AND_STABILITY_RESULTS.json").read_text())
    assert result["background_pi_rms_hz"] <= 1.05 * result["background_no_sfr_rms_hz"]


def test_delay_applied_in_all_entrypoints() -> None:
    parameters = BESSParametersV2(maximum_delay_s=2.0)
    state = BESSStateV2.equilibrium(parameters, 0.01)
    first = None
    for step in range(40):
        state, _ = step_bess_v2(
            state, np.zeros(2), np.array([0.05, 0.0]), parameters,
            CapabilityTruthV2(delay_s=(0.2, 0.2)), 0.01,
        )
        if first is None and state.power_pu[0] > 0.0:
            first = (step + 1) * 0.01
    assert first is not None and abs(first - 0.2) <= 0.01 + 1e-12
    plant_source = inspect.getsource(TwoAreaPlantAV2.step)
    assert "step_bess_v2" in plant_source


def test_bess_energy_no_projection_or_free_energy() -> None:
    parameters = BESSParametersV2()
    state = BESSStateV2.equilibrium(parameters, 0.01, soc=(0.11, 0.89))
    initial_energy = state.energy_mwh.copy()
    for _ in range(1000):
        previous = state.energy_mwh.copy()
        state, diagnostic = step_bess_v2(
            state, np.zeros(2), np.array([0.2, -0.2]), parameters,
            CapabilityTruthV2(), 0.01,
        )
        assert np.max(np.abs(diagnostic.energy_residual_mwh)) <= 1e-12
        # Zero change during the causal delay is physical; after delivery,
        # discharge can only lower E0 and charge can only raise E1.
        assert state.energy_mwh[0] <= previous[0] + 1e-12
        assert state.energy_mwh[1] >= previous[1] - 1e-12
    assert state.energy_mwh[0] < initial_energy[0]
    assert state.energy_mwh[1] > initial_energy[1]
    source = inspect.getsource(step_bess_v2)
    assert "next_energy = np.clip" not in source


def test_pfr_sfr_share_same_power_and_energy_set() -> None:
    parameters = BESSParametersV2()
    state = BESSStateV2.equilibrium(parameters, 0.01)
    state, diagnostic = step_bess_v2(
        state, np.array([-0.01, 0.0]), np.array([0.2, 0.0]), parameters,
        CapabilityTruthV2(delay_s=(0.0, 0.0)), 0.01,
    )
    assert np.isclose(
        diagnostic.requested_total_pu[0],
        diagnostic.pfr_target_pu[0] + diagnostic.sfr_target_pu[0],
    )
    assert diagnostic.feasible_target_pu[0] <= diagnostic.capability.upper_power_pu[0] + 1e-12


def test_plant_b_bess_power_enters_network_balance() -> None:
    result = json.loads((ROOT / "results_phase_e/E2/E2_MODEL_AND_STABILITY_RESULTS.json").read_text())
    assert result["plant_b_max_bess_injection_pu"] >= 0.004
    assert result["plant_b_balance_p99_pu"] <= 1e-7
    assert "Shunt.set" in inspect.getsource(AndesKundurPlantBV2.run_causal_closed_loop)


def test_plant_b_same_input_external_vs_native_event() -> None:
    result = json.loads((ROOT / "results_phase_e/E2/E2_MODEL_AND_STABILITY_RESULTS.json").read_text())
    assert result["plant_b_external_converged"]
    assert result["plant_b_native_events_converged"]
    assert result["plant_b_interface_max_error_hz"] <= 2e-4


def test_plant_b_2s_4s_native_closed_loop_stability() -> None:
    result = json.loads((ROOT / "results_phase_e/E2/E2_MODEL_AND_STABILITY_RESULTS.json").read_text())
    for period in ("2.0", "4.0"):
        metrics = result["plant_b_closed_loop"][period]
        assert metrics["converged"]
        assert metrics["max_abs_frequency_hz"] <= 0.20
        assert metrics["terminal_abs_frequency_hz"] <= 0.01
        assert metrics["balance_p99_pu"] <= 1e-7


def test_2s_4s_discrete_closed_loop_stability() -> None:
    plant = TwoAreaPlantAV2()
    assert design_stable_pi(plant, 2.0)[2] < 0.98
    assert design_stable_pi(plant, 4.0)[2] < 0.98
    assert design_discrete_lqi(plant, 2.0).closed_loop_spectral_radius < 0.98
    assert design_discrete_lqi(plant, 4.0).closed_loop_spectral_radius < 0.98


def test_no_hidden_truth_in_deployable_api() -> None:
    for method in (ACEPIAntiWindup.update, DiscreteLQIBaseline.update):
        signature = inspect.signature(method)
        names = set(signature.parameters)
        assert not names & {"truth", "regime", "true_load", "future", "capability_truth"}
    assert "CapabilityTruthV2" not in inspect.getsource(ACEPIAntiWindup)
    assert "CapabilityTruthV2" not in inspect.getsource(DiscreteLQIBaseline)
