from __future__ import annotations

import numpy as np

from direction5freq.models.capability_contract import (
    BESSParameters,
    BESSState,
    CapabilityRealization,
    step_bess,
)


def test_local_pfr_is_not_delayed_with_remote_sfr_command() -> None:
    parameters = BESSParameters()
    dt_s = 0.05
    state = BESSState.equilibrium(parameters, dt_s)
    realization = CapabilityRealization(delay_s=(1.5, 1.5))

    next_state, diagnostics = step_bess(
        state,
        omega_pu=np.array((-0.002, -0.002)),
        sfr_command_pu=np.zeros(2),
        parameters=parameters,
        realization=realization,
        dt_s=dt_s,
    )

    assert np.all(diagnostics.delayed_sfr_request_pu == 0.0)
    assert np.all(diagnostics.delayed_request_pu > 0.0)
    assert np.all(next_state.power_pu > 0.0)


def test_remote_sfr_command_still_uses_hidden_delay_pipeline() -> None:
    parameters = BESSParameters()
    dt_s = 0.05
    state = BESSState.equilibrium(parameters, dt_s)
    realization = CapabilityRealization(delay_s=(1.5, 1.5))

    next_state, diagnostics = step_bess(
        state,
        omega_pu=np.zeros(2),
        sfr_command_pu=np.array((0.04, 0.04)),
        parameters=parameters,
        realization=realization,
        dt_s=dt_s,
    )

    assert np.all(diagnostics.delayed_sfr_request_pu == 0.0)
    assert np.all(diagnostics.delayed_request_pu == 0.0)
    assert np.all(next_state.power_pu == 0.0)
