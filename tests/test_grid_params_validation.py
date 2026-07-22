from __future__ import annotations

import numpy as np
import pytest

from d5freq.models import GRID_STATE_NAMES, GridFrequencyModel, GridParams


BASE = {
    "f0_hz": 50.0,
    "M_s": 8.0,
    "D_pu": 1.0,
    "T_t_s": 0.5,
    "T_g_s": 0.2,
    "R_pu": 0.08,
    "control_period_s": 0.5,
    "integration_step_s": 0.02,
}


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("f0_hz", 0.0, "strictly positive"),
        ("M_s", -1.0, "strictly positive"),
        ("D_pu", -0.1, "non-negative"),
        ("T_t_s", np.nan, "finite"),
        ("T_g_s", np.inf, "finite"),
        ("R_pu", 0.0, "strictly positive"),
        ("integration_step_s", 0.6, "must not exceed"),
        ("integration_step_s", 0.03, "integer multiple"),
    ],
)
def test_grid_params_reject_invalid_values(
    name: str, value: float, message: str
) -> None:
    values = BASE | {name: value}
    with pytest.raises(ValueError, match=message):
        GridParams(**values)


def test_grid_params_reject_boolean_and_text_values() -> None:
    with pytest.raises(TypeError, match="real number"):
        GridParams(**(BASE | {"M_s": True}))
    with pytest.raises(TypeError, match="real number"):
        GridParams(**(BASE | {"M_s": "8.0"}))  # type: ignore[arg-type]


def test_state_builder_uses_documented_order_and_rejects_wrong_shape() -> None:
    model = GridFrequencyModel(GridParams(**BASE))
    state = model.initial_state(
        omega_pu=1.0,
        p_mech_pu=2.0,
        p_valve_pu=3.0,
        xi_pu_s=4.0,
        load_disturbance_pu=5.0,
    )

    assert GRID_STATE_NAMES == (
        "omega_pu",
        "p_mech_pu",
        "p_valve_pu",
        "xi_pu_s",
        "load_disturbance_pu",
    )
    assert state.tolist() == [1.0, 2.0, 3.0, 4.0, 5.0]
    with pytest.raises(ValueError, match="shape"):
        model.derivative(np.zeros((5, 1)), 0.0, 0.0)
