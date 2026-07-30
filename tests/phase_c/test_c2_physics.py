from __future__ import annotations

import numpy as np

from d5freq.models.bess_capability import BESSParameters, BESSState, capability, step_bess
from d5freq.models.plant_a_two_area import PlantAParameters, PlantAState, PlantATwoArea
from d5freq.models.plant_b_native_rms import NativeRMSPlantB, PlantBState


def test_initial_rocof_matches_analytic_below_one_percent() -> None:
    plant = PlantATwoArea(dt_s=1e-5)
    state = PlantAState.equilibrium(plant.params)
    expected = plant.initial_rocof_hz_s((0.06, 0.0))[0]
    next_state, _ = plant.step(state, np.zeros(4), np.array([0.06, 0.0]))
    numeric = plant.params.nominal_frequency_hz * (next_state.omega[0]-state.omega[0])/plant.dt_s
    assert abs(numeric-expected)/abs(expected) < 0.01


def test_bess_energy_conservation_and_no_free_energy_at_boundary() -> None:
    p = BESSParameters()
    s = BESSState(power_pu=0.0, energy_mwh=p.soc_min*p.energy_mwh)
    out = step_bess(s, p, omega_pu=-0.01, sfr_command_pu=1.0, dt_s=0.1)
    assert out.applied_total_pu <= 1e-14
    assert out.state.energy_mwh >= s.energy_mwh
    assert abs(out.energy_residual_mwh) <= 1e-12


def test_pfr_and_sfr_share_one_capability() -> None:
    p = BESSParameters()
    s = BESSState(energy_mwh=0.5*p.energy_mwh)
    out = step_bess(s, p, omega_pu=-0.02, sfr_command_pu=0.08, dt_s=2.0)
    cap = capability(s, p, 2.0)
    assert out.target_total_pu > cap.upper_pu
    assert out.applied_total_pu <= cap.upper_pu + 1e-12


def test_tie_sign_and_ace_sign() -> None:
    plant = PlantATwoArea(dt_s=0.01)
    state = PlantAState.equilibrium(plant.params)
    state = PlantAState(np.array([0.001, 0.0]),0.0,state.sg,state.bess)
    nxt, _ = plant.step(state,np.zeros(4),np.zeros(2))
    assert nxt.tie_pu > 0
    assert plant.ace(nxt)[0] > 0


def test_multi_machine_network_dae_runs_and_observation_excludes_hidden_state() -> None:
    plant = NativeRMSPlantB(dt_s=0.005)
    state = PlantBState.equilibrium(plant.params)
    for _ in range(20):
        state = plant.step(state,np.zeros(4),np.array([0.02,0.0]))
    assert np.isfinite(state.omega).all()
    assert state.omega.shape == (4,)
    obs = plant.observation(state,np.zeros(4))
    assert len(obs) == 13
