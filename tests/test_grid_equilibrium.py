from __future__ import annotations

import numpy as np
from numpy.testing import assert_allclose

from d5freq.models import GridFrequencyModel, GridParams, GridStateIndex


def _params() -> GridParams:
    return GridParams(
        f0_hz=50.0,
        M_s=8.0,
        D_pu=1.0,
        T_t_s=0.5,
        T_g_s=0.2,
        R_pu=0.08,
        control_period_s=0.5,
        integration_step_s=0.02,
    )


def test_zero_state_and_zero_inputs_are_an_equilibrium() -> None:
    model = GridFrequencyModel(_params())
    state = model.zero_state()

    derivative = model.derivative(state, u_sg_pu=0.0, p_ibr_pu=0.0)

    assert state.shape == (5,)
    assert_allclose(derivative, np.zeros(5), atol=0.0, rtol=0.0)


def test_nonzero_power_balance_is_an_equilibrium() -> None:
    model = GridFrequencyModel(_params())
    # At omega=0, p_mech + p_ibr = load and p_valve = p_mech = u_sg.
    state = model.initial_state(
        p_mech_pu=0.03,
        p_valve_pu=0.03,
        xi_pu_s=1.7,
        load_disturbance_pu=0.05,
    )

    derivative = model.derivative(state, u_sg_pu=0.03, p_ibr_pu=0.02)

    assert_allclose(derivative, np.zeros(5), atol=1e-15, rtol=0.0)
    assert state[GridStateIndex.LOAD_DISTURBANCE_PU] == 0.05


def test_continuous_matrices_match_equations_7_and_8() -> None:
    params = _params()
    model = GridFrequencyModel(params)
    A_c, B_c, E_c, G_c = model.continuous_matrices()

    assert A_c.shape == (5, 5)
    assert B_c.shape == E_c.shape == G_c.shape == (5, 1)
    assert_allclose(
        A_c,
        [
            [-params.D_pu / params.M_s, 1.0 / params.M_s, 0.0, 0.0, -1.0 / params.M_s],
            [0.0, -1.0 / params.T_t_s, 1.0 / params.T_t_s, 0.0, 0.0],
            [-1.0 / (params.R_pu * params.T_g_s), 0.0, -1.0 / params.T_g_s, 0.0, 0.0],
            [1.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0],
        ],
    )
    assert_allclose(B_c[:, 0], [0.0, 0.0, 1.0 / params.T_g_s, 0.0, 0.0])
    assert_allclose(E_c[:, 0], [1.0 / params.M_s, 0.0, 0.0, 0.0, 0.0])
    assert_allclose(G_c[:, 0], [0.0, 0.0, 0.0, 0.0, 1.0])


def test_matrix_properties_are_defensive_copies() -> None:
    model = GridFrequencyModel(_params())
    external_A = model.A_c
    external_A[0, 0] = 123.0

    assert model.A_c[0, 0] != 123.0
    assert_allclose(model.derivative(model.zero_state(), 0.0, 0.0), 0.0)
