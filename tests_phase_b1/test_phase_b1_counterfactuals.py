from __future__ import annotations

from dataclasses import asdict

from d5freq.evaluation.phase_b1_counterfactuals import COUNTERFACTUAL_FACTORS


SCIENTIFIC_FIELDS = (
    "belief_source",
    "worst_mode_cost",
    "constraint_tightening",
    "transition_prior",
    "ood_authority_policy",
)


def _differences(first: str, second: str) -> set[str]:
    left = COUNTERFACTUAL_FACTORS[first]
    right = COUNTERFACTUAL_FACTORS[second]
    return {
        name for name in SCIENTIFIC_FIELDS if getattr(left, name) != getattr(right, name)
    }


def test_true_arx_factor_ladder_changes_one_factor_per_step() -> None:
    assert _differences("C0_true_arx_expected", "C1_true_arx_worst") == {
        "worst_mode_cost"
    }
    assert _differences("C1_true_arx_worst", "C2_perfect_belief_current_mpc") == {
        "constraint_tightening"
    }


def test_runtime_counterfactuals_each_declare_one_change_from_p_old() -> None:
    expected = {
        "C3_current_belief_expected": "worst_mode_cost_true_to_false",
        "C4_gradual_authority": "binary_ood_fallback_to_continuous_ibr_authority",
        "C5_no_sticky_prior": "sticky_transition_prior_to_uniform_transition_prior",
    }
    for method, factor in expected.items():
        row = asdict(COUNTERFACTUAL_FACTORS[method])
        assert row["differs_from"] == "P_old"
        assert row["sole_changed_factor"] == factor
