from __future__ import annotations

from pathlib import Path

import numpy as np

from d5freq.evaluation.phase_b2_identifiability import (
    ControlDistanceWeights,
    control_relevant_distance_rows,
    critical_window,
    rollout_expected_block,
    visible_output,
)
from d5freq.evaluation.phase_b2_plant import load_plant_b_parameters
from d5freq.models.two_area_plant_b import TwoAreaPlantB
from scripts.phase_b2_06_run_final_experiment import (
    KNOWN_SCENARIOS,
    OOD_SCENARIOS,
    scenario_definitions,
)


REPOSITORY = Path(__file__).resolve().parents[1]
CONFIG = REPOSITORY / "configs" / "phase_b2_plant_b.yaml"


def test_visible_output_and_expected_block_shapes() -> None:
    params = load_plant_b_parameters(CONFIG, sg_level="scarce")
    state = TwoAreaPlantB(params).initial_state()
    trajectory = rollout_expected_block(
        params,
        state=state,
        action=(0.03, 0.0, 0.04, 0.0),
        load_pu=(0.04, 0.0),
        regime_pair=("nominal_available", "nominal_available"),
    )
    assert trajectory.shape == (15, 21)
    assert visible_output(trajectory).shape == (7, 21)
    assert np.isfinite(trajectory).all()


def test_control_distance_has_all_pairs_and_bounded_components() -> None:
    params = load_plant_b_parameters(CONFIG, sg_level="scarce")
    regimes = (
        "nominal_available",
        "headroom_or_current_limited",
        "energy_limited",
        "communication_degraded",
    )
    rows = control_relevant_distance_rows(
        params, regimes, weights=ControlDistanceWeights()
    )
    assert len(rows) == 6
    for row in rows:
        assert 0.0 <= row["d_pred"] <= 1.0
        assert 0.0 <= row["d_act"] <= 1.0
        assert 0.0 <= row["d_cap"] <= 1.0
        assert 0.0 <= row["d_ctrl"] <= 1.0


def test_nominal_vs_nominal_critical_window_is_censored() -> None:
    params = load_plant_b_parameters(CONFIG, sg_level="scarce")
    row = critical_window(
        params,
        actual_regime="nominal_available",
        episode_s=4.0,
    )
    assert row["right_censored"]
    assert row["threshold_cause"] == "right_censored"


def test_final_scenario_registry_covers_timing_and_all_physical_regimes() -> None:
    known = scenario_definitions("known")
    ood = scenario_definitions("ood_extreme")
    assert tuple(row.scenario_id for row in known) == KNOWN_SCENARIOS
    assert tuple(row.scenario_id for row in ood) == OOD_SCENARIOS
    assert {row.timing_class for row in known} >= {
        "load_only",
        "mode_only",
        "before",
        "coincident",
        "after",
    }
    observed_regimes = {
        regime
        for row in (*known, *ood)
        for time_s in (0.0, 3.0, 5.0, 7.0, 10.0)
        for regime in row.regimes(time_s)
    }
    assert observed_regimes >= {
        "nominal_available",
        "headroom_or_current_limited",
        "energy_limited",
        "communication_degraded",
        "service_disabled",
        "recovery",
        "structural_ood",
    }
    assert {row.scenario_id for row in known if row.o2_eligible} == {
        "load_only_step",
        "coincident_communication_load",
    }
