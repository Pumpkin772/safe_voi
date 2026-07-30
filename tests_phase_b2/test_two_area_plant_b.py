from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest

from d5freq.controllers.phase_b2_conventional import ConventionalACEPIController
from d5freq.evaluation.phase_b2_plant import (
    load_plant_b_parameters,
    make_plant_b_simulator,
)
from d5freq.models.two_area_plant_b import (
    PlantBStateIndex,
    TwoAreaPlantB,
    TwoAreaPlantBSimulator,
    UpperCommand,
)


REPOSITORY = Path(__file__).resolve().parents[1]
CONFIG = REPOSITORY / "configs" / "phase_b2_plant_b.yaml"


def _model(sg_level: str = "adequate", period_s: float = 2.0) -> TwoAreaPlantB:
    return TwoAreaPlantB(
        load_plant_b_parameters(
            CONFIG,
            sg_level=sg_level,
            upper_control_period_s=period_s,
        )
    )


@pytest.mark.parametrize("period_s", [2.0, 4.0])
@pytest.mark.parametrize("sg_level", ["adequate", "scarce", "critical"])
def test_registered_periods_and_capability_levels_load(
    period_s: float, sg_level: str
) -> None:
    params = _model(sg_level, period_s).params
    assert params.upper_control_period_s == period_s
    assert params.sg_capability.reserve_up_pu[0] > 0.0
    assert period_s / params.integration_step_s == pytest.approx(
        round(period_s / params.integration_step_s)
    )


def test_unregistered_upper_period_is_rejected() -> None:
    with pytest.raises(ValueError, match="registered candidate"):
        load_plant_b_parameters(CONFIG, upper_control_period_s=3.0)


def test_zero_disturbance_equilibrium() -> None:
    model = _model()
    state = model.initial_state()
    regime = model.params.regimes["nominal_available"]
    derivative = model.derivative(
        state,
        command=UpperCommand(),
        delayed_ibr_command_pu=(0.0, 0.0),
        load_disturbance_pu=(0.0, 0.0),
        regimes=(regime, regime),
    )
    assert derivative == pytest.approx(np.zeros(model.state_size), abs=1.0e-15)


def test_area_one_load_drives_frequency_down_and_tie_export_down() -> None:
    simulator = make_plant_b_simulator(CONFIG)
    for _ in range(20):
        simulator.advance((0.04, 0.0))
    observation = simulator.observation()
    assert observation.frequency_hz[0] < 0.0
    assert observation.frequency_hz[0] < observation.frequency_hz[1]
    assert observation.tie_line_1_to_2_pu < 0.0


def test_tie_line_and_ace_sign_convention() -> None:
    model = _model()
    state = model.initial_state()
    state[PlantBStateIndex.F1] = 0.10
    state[PlantBStateIndex.F2] = -0.05
    state[PlantBStateIndex.PTIE12] = 0.02
    regime = model.params.regimes["nominal_available"]
    derivative = model.derivative(
        state,
        command=UpperCommand(),
        delayed_ibr_command_pu=(0.0, 0.0),
        load_disturbance_pu=(0.0, 0.0),
        regimes=(regime, regime),
    )
    ace = model.ace(state)
    assert derivative[PlantBStateIndex.PTIE12] > 0.0
    assert ace[0] == pytest.approx(0.425 * 0.10 + 0.02)
    assert ace[1] == pytest.approx(0.450 * -0.05 - 0.02)


@pytest.mark.parametrize("sg_level", ["adequate", "scarce", "critical"])
def test_grc_is_applied_at_mechanical_power_layer(sg_level: str) -> None:
    model = _model(sg_level)
    state = model.initial_state()
    state[PlantBStateIndex.PV1] = model.params.sg_capability.reserve_up_pu[0]
    state[PlantBStateIndex.PV2] = -model.params.sg_capability.reserve_down_pu[1]
    regime = model.params.regimes["nominal_available"]
    derivative = model.derivative(
        state,
        command=UpperCommand(),
        delayed_ibr_command_pu=(0.0, 0.0),
        load_disturbance_pu=(0.0, 0.0),
        regimes=(regime, regime),
    )
    assert derivative[PlantBStateIndex.PM1] == pytest.approx(
        model.params.sg_capability.grc_up_pu_per_s[0]
    )
    assert derivative[PlantBStateIndex.PM2] == pytest.approx(
        -model.params.sg_capability.grc_down_pu_per_s[1]
    )
    engineering = model.params.sg_capability.engineering_units(
        model.params.system_base_mw
    )
    assert engineering["grc_up_mw_per_min"][0] == pytest.approx(
        model.params.sg_capability.grc_up_pu_per_s[0] * 60_000.0
    )


def test_headroom_depends_on_soc_availability_and_hidden_regime() -> None:
    model = _model()
    state = model.initial_state(soc=(0.50, 0.50), availability=(1.0, 1.0))
    nominal = model.params.regimes["nominal_available"]
    limited = model.params.regimes["headroom_or_current_limited"]
    nominal_headroom = model.headroom(state, area=0, regime=nominal)
    limited_headroom = model.headroom(state, area=0, regime=limited)
    low_soc = state.copy()
    low_soc[PlantBStateIndex.SOC1] = model.params.bess[0].soc_min + 1.0e-4
    low_soc_headroom = model.headroom(low_soc, area=0, regime=nominal)
    unavailable = state.copy()
    unavailable[PlantBStateIndex.A1] = 0.25
    unavailable_headroom = model.headroom(unavailable, area=0, regime=nominal)
    assert limited_headroom[0] < nominal_headroom[0]
    assert low_soc_headroom[0] < nominal_headroom[0]
    assert unavailable_headroom[0] == pytest.approx(0.25 * nominal_headroom[0])


def test_soc_efficiency_has_correct_direction() -> None:
    model = _model()
    regime = model.params.regimes["nominal_available"]
    state = model.initial_state()
    state[PlantBStateIndex.PB1] = 0.04
    state[PlantBStateIndex.PB2] = -0.04
    derivative = model.derivative(
        state,
        command=UpperCommand(),
        delayed_ibr_command_pu=(0.0, 0.0),
        load_disturbance_pu=(0.0, 0.0),
        regimes=(regime, regime),
    )
    assert derivative[PlantBStateIndex.SOC1] < 0.0
    assert derivative[PlantBStateIndex.SOC2] > 0.0
    assert abs(derivative[PlantBStateIndex.SOC1]) > abs(
        derivative[PlantBStateIndex.SOC2]
    )


def test_bess_power_and_ramp_constraints_hold() -> None:
    model = _model()
    regime = model.params.regimes["nominal_available"]
    state = model.initial_state()
    state[PlantBStateIndex.Z1] = 1.0
    state[PlantBStateIndex.Z2] = -1.0
    derivative = model.derivative(
        state,
        command=UpperCommand(),
        delayed_ibr_command_pu=(0.0, 0.0),
        load_disturbance_pu=(0.0, 0.0),
        regimes=(regime, regime),
    )
    assert derivative[PlantBStateIndex.PB1] <= 0.04 + 1.0e-12
    assert derivative[PlantBStateIndex.PB2] >= -0.04 - 1.0e-12
    for _ in range(200):
        state = model.step(
            state,
            command=UpperCommand(),
            delayed_ibr_command_pu=(0.0, 0.0),
            load_disturbance_pu=(0.0, 0.0),
            regimes=(regime, regime),
        )
    assert abs(state[PlantBStateIndex.PB1]) <= model.params.bess[0].rating_pu
    assert abs(state[PlantBStateIndex.PB2]) <= model.params.bess[1].rating_pu


def test_regime_switch_preserves_all_physical_state() -> None:
    simulator = make_plant_b_simulator(CONFIG)
    simulator.issue_command(UpperCommand(ibr_pu=(0.05, -0.03)))
    for _ in range(10):
        simulator.advance((0.02, 0.0))
    state_before = simulator.state.copy()
    time_before = simulator.time_s
    simulator.set_regimes(("communication_degraded", "energy_limited"))
    assert simulator.state == pytest.approx(state_before)
    assert simulator.time_s == pytest.approx(time_before)


def test_controller_observation_excludes_hidden_truth() -> None:
    simulator = make_plant_b_simulator(CONFIG)
    observation = simulator.observation()
    public_fields = set(asdict(observation))
    forbidden = {"soc", "availability", "regime", "headroom", "internal_parameters"}
    assert not (public_fields & forbidden)
    assert observation.as_array().shape == (13,)
    truth = simulator.evaluation_truth_snapshot()
    assert {"regime_ids", "soc", "availability", "headroom_up_down_pu"} <= set(
        truth
    )


def test_service_disabled_blocks_central_command_but_keeps_local_droop() -> None:
    model = _model()
    state = model.initial_state()
    state[PlantBStateIndex.F1] = -0.10
    disabled = model.params.regimes["service_disabled"]
    nominal = model.params.regimes["nominal_available"]
    derivative = model.derivative(
        state,
        command=UpperCommand(ibr_pu=(0.08, 0.0)),
        delayed_ibr_command_pu=(0.08, 0.0),
        load_disturbance_pu=(0.0, 0.0),
        regimes=(disabled, nominal),
    )
    assert derivative[PlantBStateIndex.Z1] == pytest.approx(0.0)
    assert derivative[PlantBStateIndex.PB1] > 0.0
    assert model.headroom(state, area=0, regime=disabled) == (0.0, 0.0)


def test_physical_command_delay_is_not_bypassed() -> None:
    model = _model()
    simulator = TwoAreaPlantBSimulator(model, random_seed=17)
    simulator.issue_command(UpperCommand(ibr_pu=(0.05, 0.0)))
    simulator.advance((0.0, 0.0))
    assert simulator.state[PlantBStateIndex.Z1] == pytest.approx(0.0)
    simulator.advance((0.0, 0.0))
    assert simulator.state[PlantBStateIndex.Z1] == pytest.approx(0.0)
    simulator.advance((0.0, 0.0))
    assert simulator.state[PlantBStateIndex.Z1] > 0.0


def test_o0_uses_only_public_observation_and_never_commands_ibr() -> None:
    simulator = make_plant_b_simulator(CONFIG)
    controller = ConventionalACEPIController(
        simulator.model.params.sg_capability,
        control_period_s=simulator.model.params.upper_control_period_s,
    )
    command = controller.command(simulator.observation())
    assert command == UpperCommand()
    assert not controller.uses_true_regime
    assert not controller.uses_true_internal_state
    assert not controller.uses_future_load
    assert not controller.uses_future_regime


def test_o0_restores_ace_for_adequate_development_step() -> None:
    simulator = make_plant_b_simulator(CONFIG, sg_level="adequate")
    controller = ConventionalACEPIController(
        simulator.model.params.sg_capability,
        control_period_s=simulator.model.params.upper_control_period_s,
    )
    block_steps = round(
        simulator.model.params.upper_control_period_s
        / simulator.model.params.integration_step_s
    )
    for step in range(round(180.0 / simulator.model.params.integration_step_s)):
        if step % block_steps == 0:
            simulator.issue_command(controller.command(simulator.observation()))
        simulator.advance((0.04 if simulator.time_s >= 5.0 else 0.0, 0.0))
    assert max(abs(value) for value in simulator.observation().ace_pu) < 0.002
