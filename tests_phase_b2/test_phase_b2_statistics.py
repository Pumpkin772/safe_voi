from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from d5freq.evaluation.phase_b2_statistics import (
    add_total_cost_columns,
    pair_methods,
    scenario_balanced_effect,
    strict_bottleneck_decision,
)


TRIGGERS = {
    "MODEL_MISMATCH_DOMINANT": False,
    "IDENTIFIABILITY_DOMINANT": False,
    "CONTROL_DESIGN_DOMINANT": False,
}
SCORES = {
    "MODEL_MISMATCH_DOMINANT": 0.81,
    "IDENTIFIABILITY_DOMINANT": 0.73,
    "CONTROL_DESIGN_DOMINANT": 0.86,
}


def test_all_false_triggers_are_inconclusive() -> None:
    assert (
        strict_bottleneck_decision(
            problem_material=True,
            triggers=TRIGGERS,
            normalized_scores=SCORES,
        )
        == "INCONCLUSIVE_REQUIRES_MORE_EVIDENCE"
    )


def test_single_active_trigger_is_the_only_decision() -> None:
    assert (
        strict_bottleneck_decision(
            problem_material=True,
            triggers={**TRIGGERS, "MODEL_MISMATCH_DOMINANT": True},
            normalized_scores=SCORES,
        )
        == "MODEL_MISMATCH_DOMINANT"
    )


def test_combined_contains_only_active_triggers() -> None:
    decision = strict_bottleneck_decision(
        problem_material=True,
        triggers={
            **TRIGGERS,
            "MODEL_MISMATCH_DOMINANT": True,
            "IDENTIFIABILITY_DOMINANT": True,
        },
        normalized_scores=SCORES,
    )
    assert decision == "COMBINED:MODEL_MISMATCH_DOMINANT+IDENTIFIABILITY_DOMINANT"
    assert "CONTROL_DESIGN" not in decision


def test_ratio_of_balanced_means_is_not_episode_ratio_mean() -> None:
    paired = pd.DataFrame(
        {
            "scenario_id": ["s1", "s1", "s2", "s2"],
            "method": [0.02, 0.02, 2.0, 2.0],
            "reference": [0.01, 0.01, 2.0, 2.0],
        }
    )
    effect = scenario_balanced_effect(
        paired,
        method_col="method",
        reference_col="reference",
        bootstrap_resamples=0,
    )
    episode_ratio_mean = ((paired["method"] - paired["reference"]) / paired["reference"]).mean()
    assert episode_ratio_mean == pytest.approx(0.5)
    assert effect.relative_effect == pytest.approx(0.01 / 2.01)
    assert effect.relative_effect < 0.01


def test_reference_only_failure_is_retained() -> None:
    episodes = pd.DataFrame(
        [
            {
                "scenario_id": "s",
                "seed": 1,
                "sg_level": "C",
                "method": "M",
                "scientific_success": True,
                "catastrophic_failure": False,
                "freq_iae": 1.0,
            },
            {
                "scenario_id": "s",
                "seed": 1,
                "sg_level": "C",
                "method": "R",
                "scientific_success": False,
                "catastrophic_failure": True,
                "freq_iae": 9.0,
            },
        ]
    )
    paired = pair_methods(
        episodes, method="M", reference="R", metrics=("freq_iae",)
    )
    assert len(paired) == 1
    assert bool(paired.iloc[0]["reference_only_failure"])
    assert not bool(paired.iloc[0]["both_success"])


def test_total_cost_contains_sg_and_ibr_energy_and_mileage() -> None:
    episodes = pd.DataFrame(
        {
            "sg_abs_energy_pu_s": [2.0],
            "ibr_abs_energy_pu_s": [3.0],
            "sg_mileage": [4.0],
            "ibr_mileage": [5.0],
        }
    )
    output, columns = add_total_cost_columns(
        episodes,
        ratios=(0.5,),
        sg_energy_weight=1.0,
        sg_mileage_weight=0.1,
    )
    assert output.iloc[0][columns[0.5]] == pytest.approx(
        2.0 + 0.5 * 3.0 + 0.1 * 4.0 + 0.5 * 0.1 * 5.0
    )


def test_corrected_phase_b1_decision_has_no_active_trigger() -> None:
    repo = Path(__file__).resolve().parents[1]
    path = (
        repo
        / "results_phase_b2"
        / "corrected_phase_b1"
        / "corrected_phase_b1_decision.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["corrected_phase_b1_decision"] == (
        "INCONCLUSIVE_NO_DOMINANT_BOTTLENECK"
    )
    assert payload["active_triggers"] == []
    assert not any(payload["triggers"].values())
    assert payload["b5_is_exact_optimal_oracle"] is False


def test_corrected_phase_b1_retains_sixty_b0_sg_c_failures() -> None:
    repo = Path(__file__).resolve().parents[1]
    path = (
        repo
        / "results_phase_b2"
        / "corrected_phase_b1"
        / "corrected_phase_b1_materiality.csv"
    )
    frame = pd.read_csv(path)
    level_c = frame.loc[frame["sg_level"] == "C"]
    assert set(level_c["attempted_pair_count"]) == {690}
    assert set(level_c["both_success"]) == {630}
    assert set(level_c["reference_only_failure"]) == {60}
