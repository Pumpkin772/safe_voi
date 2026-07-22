from __future__ import annotations

import pytest

from d5freq.models import GridFrequencyModel, GridParams, GridStateIndex


@pytest.fixture
def model() -> GridFrequencyModel:
    return GridFrequencyModel(
        GridParams(50.0, 8.0, 1.0, 0.5, 0.2, 0.08, 0.5, 0.02)
    )


def test_load_increase_drives_frequency_down(model: GridFrequencyModel) -> None:
    state = model.zero_state(load_disturbance_pu=0.04)
    derivative = model.derivative(state, u_sg_pu=0.0, p_ibr_pu=0.0)

    assert derivative[GridStateIndex.OMEGA_PU] == pytest.approx(-0.04 / 8.0)
    assert derivative[GridStateIndex.OMEGA_PU] < 0.0


def test_generation_and_ibr_power_drive_frequency_up(
    model: GridFrequencyModel,
) -> None:
    mechanical_state = model.initial_state(p_mech_pu=0.03)
    from_mechanical = model.derivative(mechanical_state, 0.0, 0.0)
    from_ibr = model.derivative(model.zero_state(), 0.0, 0.03)

    assert from_mechanical[GridStateIndex.OMEGA_PU] == pytest.approx(0.03 / 8.0)
    assert from_ibr[GridStateIndex.OMEGA_PU] == pytest.approx(0.03 / 8.0)


def test_primary_droop_opposes_frequency_deviation(
    model: GridFrequencyModel,
) -> None:
    positive_frequency = model.initial_state(omega_pu=0.001)
    derivative = model.derivative(positive_frequency, 0.0, 0.0)

    expected_valve_rate = -0.001 / (model.params.R_pu * model.params.T_g_s)
    assert derivative[GridStateIndex.P_VALVE_PU] == pytest.approx(
        expected_valve_rate
    )
    assert derivative[GridStateIndex.P_VALVE_PU] < 0.0
    assert derivative[GridStateIndex.XI_PU_S] == pytest.approx(0.001)


def test_load_random_walk_channel_changes_only_load_state(
    model: GridFrequencyModel,
) -> None:
    derivative = model.derivative(
        model.zero_state(),
        u_sg_pu=0.0,
        p_ibr_pu=0.0,
        load_derivative_pu_per_s=0.015,
    )

    assert derivative.tolist() == [0.0, 0.0, 0.0, 0.0, 0.015]
