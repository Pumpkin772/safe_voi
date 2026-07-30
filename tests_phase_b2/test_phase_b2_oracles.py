from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from d5freq.evaluation.phase_b2_exact_nmpc import (
    ExactMultipleShootingNMPC,
    ExactNMPCConfig,
)
from d5freq.evaluation.phase_b2_identified_mpc import (
    TruthRegimeIdentifiedMPC,
    fit_identified_regime_model,
    load_identified_model,
    save_identified_model,
)
from d5freq.evaluation.phase_b2_plant import load_plant_b_parameters
from d5freq.models.two_area_plant_b import TwoAreaPlantB, UpperCommand


REPOSITORY = Path(__file__).resolve().parents[1]
PLANT_CONFIG = REPOSITORY / "configs" / "phase_b2_plant_b.yaml"


def test_exact_nmpc_has_multiple_independent_actions_and_no_global_claim() -> None:
    config = ExactNMPCConfig(horizon_s=8.0)
    assert config.number_of_control_blocks == 4
    assert config.integration_steps_per_block == 20
    assert 4 * config.number_of_control_blocks == 16


def test_o2_rejects_future_load_and_future_regime() -> None:
    params = load_plant_b_parameters(PLANT_CONFIG, sg_level="scarce")
    config = ExactNMPCConfig(horizon_s=4.0, ipopt_max_iterations=20)
    with pytest.raises(ValueError, match="future regime"):
        ExactMultipleShootingNMPC(
            params,
            regime_schedule=(
                ("nominal_available", "nominal_available"),
                ("service_disabled", "service_disabled"),
            ),
            config=config,
            oracle_level="O2",
        )
    controller = ExactMultipleShootingNMPC.for_current_regime(
        params,
        ("nominal_available", "nominal_available"),
        config=config,
    )
    loads = np.asarray(((0.04, 0.06), (0.0, 0.0)))
    with pytest.raises(ValueError, match="future load"):
        controller.solve(TwoAreaPlantB(params).initial_state(), load_forecast_pu=loads)


@pytest.fixture(scope="module")
def solved_o2() -> tuple[ExactMultipleShootingNMPC, np.ndarray, object]:
    params = load_plant_b_parameters(PLANT_CONFIG, sg_level="scarce")
    controller = ExactMultipleShootingNMPC.for_current_regime(
        params,
        ("nominal_available", "nominal_available"),
        config=ExactNMPCConfig(horizon_s=8.0, ipopt_max_iterations=300),
    )
    state = TwoAreaPlantB(params).initial_state()
    record = controller.solve(
        state,
        load_forecast_pu=(0.06, 0.0),
        initializations=("split_load",),
    )
    return controller, state, record


def test_o2_solver_quality_and_action_sequence(solved_o2: tuple[object, ...]) -> None:
    _, _, record = solved_o2
    assert record.success
    assert record.local_optimum_only
    assert not record.global_optimality_claim
    assert record.solver_status in {"Solve_Succeeded", "Solved_To_Acceptable_Level"}
    assert record.max_constraint_residual <= 1.0e-4
    assert record.kkt_residual_inf <= 1.0e-1
    assert record.independent_actions == 16
    assert record.action_sequence.shape == (4, 4)
    assert np.max(np.ptp(record.action_sequence, axis=1)) > 1.0e-3


def test_o2_symbolic_rollout_matches_independent_simulator(
    solved_o2: tuple[object, ...],
) -> None:
    controller, state, record = solved_o2
    independent = controller.independent_rollout(
        state,
        action_sequence=record.action_sequence,
        load_forecast_pu=(0.06, 0.0),
    )
    objective = controller.evaluate_action_sequence(
        state,
        action_sequence=record.action_sequence,
        load_forecast_pu=(0.06, 0.0),
    )
    assert np.max(np.abs(independent - record.state_nodes)) <= 1.0e-5
    assert objective == pytest.approx(record.objective, abs=1.0e-4)


def test_o3_accepts_clairvoyant_load_and_regime_schedule() -> None:
    params = load_plant_b_parameters(PLANT_CONFIG, sg_level="scarce")
    config = ExactNMPCConfig(horizon_s=4.0, ipopt_max_iterations=20)
    controller = ExactMultipleShootingNMPC(
        params,
        regime_schedule=(
            ("nominal_available", "nominal_available"),
            ("service_disabled", "service_disabled"),
        ),
        config=config,
        oracle_level="O3",
    )
    assert controller.uses_future_load
    assert controller.uses_future_regime


def test_o1_identification_roundtrip_and_truth_regime_solve(tmp_path: Path) -> None:
    params = load_plant_b_parameters(PLANT_CONFIG, sg_level="scarce")
    pair = ("nominal_available", "nominal_available")
    model = fit_identified_regime_model(
        params,
        regime_pair=pair,
        sample_count=100,
        development_seed=700,
    )
    path = save_identified_model(model, tmp_path / "nominal.npz")
    loaded = load_identified_model(path)
    assert loaded.regime_pair == pair
    assert loaded.state_matrix == pytest.approx(model.state_matrix)
    controller = TruthRegimeIdentifiedMPC(
        params,
        {pair: loaded},
        config=ExactNMPCConfig(horizon_s=4.0),
    )
    record = controller.solve(
        TwoAreaPlantB(params).initial_state(),
        regime_pair=pair,
        current_load_pu=(0.04, 0.0),
        previous_command=UpperCommand(),
    )
    assert record.success
    assert record.max_constraint_residual <= 1.0e-6
    assert record.command.ibr_pu != (0.0, 0.0)
    assert controller.evaluation_only
    assert controller.uses_true_regime
    assert controller.uses_true_internal_state

