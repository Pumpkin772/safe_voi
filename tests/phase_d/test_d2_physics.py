from __future__ import annotations

import inspect

import numpy as np

from direction1freq.models import (
    AndesKundurPlantB, BESSFleetState, BESSParameters, CapabilityRegime,
    TwoAreaPlantA, step_bess_fleet,
)


def test_plant_a_initial_rocof_and_balance() -> None:
    plant = TwoAreaPlantA(dt_s=1e-4)
    state = plant.equilibrium()
    expected = plant.initial_rocof_hz_s(np.array([0.06, 0.0]))[0]
    next_state, diagnostics = plant.step(state, np.zeros(4), np.array([0.06, 0.0]))
    measured = plant.params.nominal_frequency_hz * (next_state.omega_pu[0] - state.omega_pu[0]) / plant.dt_s
    assert abs(measured - expected) / abs(expected) < 0.01
    assert np.max(np.abs(diagnostics.power_balance_residual_pu)) <= 1e-12


def test_bess_shared_capability_energy_and_delay() -> None:
    params = BESSParameters(maximum_delay_s=2.0)
    state = BESSFleetState.equilibrium(params, 0.01, soc=(0.5, 0.5))
    regime = CapabilityRegime(delay_s=(0.2, 0.2))
    first_nonzero = None
    max_energy_residual = 0.0
    for step in range(40):
        state, diagnostics = step_bess_fleet(state, np.zeros(2), np.array([0.2, 0.0]), params, regime, 0.01)
        max_energy_residual = max(max_energy_residual, float(np.max(np.abs(diagnostics.energy_residual_mwh))))
        assert diagnostics.total_target_pu[0] <= diagnostics.upper_power_pu[0] + 1e-12
        if first_nonzero is None and state.power_pu[0] > 0:
            first_nonzero = step + 1
    assert abs(first_nonzero * 0.01 - 0.2) <= 0.01 + 1e-12
    assert max_energy_residual <= 1e-12


def test_direction1_runtime_namespace_does_not_import_historical_controller() -> None:
    import direction1freq
    source = inspect.getsource(direction1freq)
    assert "d5freq" not in source


def test_native_andes_external_bridge_matches_native_events() -> None:
    plant = AndesKundurPlantB(dt_s=0.01)
    external = plant.run_validation_profile(duration_s=4.0, interface="external")
    native = plant.run_validation_profile(duration_s=4.0, interface="native_events")
    assert external.converged and native.converged
    assert external.algebraic_power_balance_p99_pu <= 1e-7
    assert native.algebraic_power_balance_p99_pu <= 1e-7
    grid = np.linspace(0.0, 4.0, 401)
    e = np.interp(grid, external.time_s, external.coi_frequency_hz)
    n = np.interp(grid, native.time_s, native.coi_frequency_hz)
    assert np.max(np.abs(e - n)) <= 2e-4
    assert np.max(external.bess_injection_pu[:, 0]) >= 0.004

