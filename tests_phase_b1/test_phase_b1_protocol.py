from __future__ import annotations

from pathlib import Path

from d5freq.utils.config import load_yaml


REPO = Path(__file__).resolve().parents[1]


def test_sg_capability_levels_are_exactly_preregistered() -> None:
    payload = load_yaml(REPO / "configs/phase_b1_sg_levels.yaml")
    assert payload["protocol_status"] == "preregistered"
    assert payload["frozen_before_final"] is True
    assert payload["levels"] == {
        "A": {
            "command_min_pu": -0.12,
            "command_max_pu": 0.12,
            "ramp_pu_per_s": 0.020,
            "interpretation": "current_baseline_ample_sg",
        },
        "B": {
            "command_min_pu": -0.08,
            "command_max_pu": 0.08,
            "ramp_pu_per_s": 0.012,
            "interpretation": "moderate_sg_flexibility",
        },
        "C": {
            "command_min_pu": -0.055,
            "command_max_pu": 0.055,
            "ramp_pu_per_s": 0.006,
            "interpretation": "low_sg_flexibility_fixed_even_if_infeasible",
        },
    }


def test_phase_b1_seed_splits_are_disjoint_and_final_is_not_tunable() -> None:
    payload = load_yaml(REPO / "configs/phase_b1_audit.yaml")

    def values(name: str) -> set[int]:
        row = payload["seed_sets"][name]
        result = set(range(row["start"], row["stop_inclusive"] + 1))
        assert len(result) == row["count"]
        return result

    smoke = values("smoke")
    validation = values("validation")
    final_known = values("final_known")
    final_ood = values("final_ood_extreme")
    assert smoke.isdisjoint(validation | final_known | final_ood)
    assert validation.isdisjoint(final_known | final_ood)
    assert final_known <= final_ood
    assert payload["final_feedback_policy"] == {
        "tune_on_final": False,
        "run_final_once_after_protocol_lock": True,
        "delete_or_filter_failed_episode": False,
    }


def test_oracle_preregistration_forbids_future_truth_and_fallback_substitution() -> None:
    payload = load_yaml(REPO / "configs/phase_b1_oracle.yaml")
    assert payload["evaluation_only"] is True
    assert payload["ordinary_controller_factory_exposure"] == "forbidden"
    assert payload["failure_policy"] == (
        "retain_episode_and_report_without_fallback_substitution"
    )
    boundary = payload["information_boundary"]
    assert boundary["future_mode_schedule"] == "forbidden_to_planner"
    assert boundary["future_load_disturbance"] == "forbidden_to_planner"
    assert [row["candidate_id"] for row in payload["validation_candidates"]] == [
        "H2",
        "H4",
        "H6",
    ]
