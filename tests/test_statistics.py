from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from d5freq.evaluation.statistics import (
    apply_holm,
    attach_oracle_regret,
    bootstrap_mean_ci,
    exact_mcnemar,
    holm_adjust,
    pair_episode_rows,
    paired_method_comparison,
    sign_flip_permutation_test,
    summarize_episode_metric,
    validate_episode_unit,
)


def test_group_summary_keeps_failed_missing_and_censored_episode_counts() -> None:
    frame = pd.DataFrame(
        {
            "run_id": ["r1", "r2", "r3", "r4", "r5"],
            "scenario_id": ["s"] * 5,
            "method": ["m"] * 5,
            "run_completed": [True, True, False, True, True],
            "scientific_success": [True, True, False, False, True],
            "delay_s": [1.0, 2.0, None, None, 3.0],
            "delay_censored": [False, False, False, True, False],
        }
    )

    first = summarize_episode_metric(
        frame,
        "delay_s",
        censor_column="delay_censored",
        rng_seed=123,
    )
    second = summarize_episode_metric(
        frame,
        "delay_s",
        censor_column="delay_censored",
        rng_seed=123,
    )

    pd.testing.assert_frame_equal(first, second)
    row = first.iloc[0]
    assert row["episode_count"] == 5
    assert row["finite_count"] == 3
    assert row["missing_count"] == 2
    assert row["run_incomplete_count"] == 1
    assert row["scientific_failure_count"] == 2
    assert row["censored_count"] == 1
    assert row["mean"] == 2.0
    assert row["median"] == 2.0
    assert row["std"] == 1.0
    assert row["q05"] == pytest.approx(1.1)
    assert row["q95"] == pytest.approx(2.9)
    assert row["bootstrap_resamples"] == 10_000


def test_summary_rejects_numeric_delay_on_a_censored_episode_and_duplicate_episode_rows() -> None:
    ambiguous = pd.DataFrame(
        {
            "run_id": ["r"],
            "scenario_id": ["s"],
            "method": ["m"],
            "delay_s": [4.0],
            "censored": [True],
        }
    )
    with pytest.raises(ValueError, match="censored episodes"):
        summarize_episode_metric(
            ambiguous,
            "delay_s",
            censor_column="censored",
            rng_seed=1,
        )

    duplicated = pd.concat([ambiguous, ambiguous], ignore_index=True)
    with pytest.raises(ValueError, match="one statistical row"):
        validate_episode_unit(duplicated)


def test_seed_paired_comparison_reports_unmatched_missing_and_reproducible_ci() -> None:
    frame = pd.DataFrame(
        {
            "run_id": ["a1", "a2", "a3", "b1", "b2", "b4"],
            "scenario_id": ["s"] * 6,
            "method": ["A", "A", "A", "B", "B", "B"],
            "seed": [1, 2, 3, 1, 2, 4],
            "cost": [3.0, None, 8.0, 1.0, 1.0, 0.0],
        }
    )

    first = paired_method_comparison(
        frame,
        "cost",
        method="A",
        reference_method="B",
        rng_seed=99,
        n_resamples=500,
    )
    second = paired_method_comparison(
        frame,
        "cost",
        method="A",
        reference_method="B",
        rng_seed=99,
        n_resamples=500,
    )

    pd.testing.assert_frame_equal(first, second)
    row = first.iloc[0]
    assert row["method_episode_count"] == 3
    assert row["reference_episode_count"] == 3
    assert row["matched_pair_count"] == 2
    assert row["finite_pair_count"] == 1
    assert row["missing_pair_count"] == 1
    assert row["unmatched_method_count"] == 1
    assert row["unmatched_reference_count"] == 1
    assert row["mean_difference"] == 2.0
    assert row["ci95_low"] == 2.0
    assert row["ci95_high"] == 2.0

    audit = pair_episode_rows(
        frame,
        method="A",
        reference_method="B",
    )
    assert audit["pair_status"].value_counts().to_dict() == {
        "both": 2,
        "left_only": 1,
        "right_only": 1,
    }


def test_oracle_regret_is_attached_only_after_scenario_seed_pairing() -> None:
    frame = pd.DataFrame(
        {
            "run_id": ["o1", "a1", "o2", "a2", "a3"],
            "scenario_id": ["s", "s", "s", "s", "s"],
            "method": ["Oracle", "A", "Oracle", "A", "A"],
            "seed": [1, 1, 2, 2, 3],
            "cost": [1.0, 2.5, None, 5.0, 9.0],
            "oracle_regret": [None] * 5,
        }
    )

    attached = attach_oracle_regret(frame, "cost")

    assert attached.table["run_id"].tolist() == frame["run_id"].tolist()
    assert attached.table.loc[0, "oracle_regret"] == 0.0
    assert attached.table.loc[1, "oracle_regret"] == 1.5
    assert attached.table.loc[2:, "oracle_regret"].isna().all()
    method_audit = attached.pairing_audit.set_index("method").loc["A"]
    assert method_audit["episode_count"] == 3
    assert method_audit["oracle_matched_count"] == 1
    assert method_audit["finite_regret_count"] == 1
    assert method_audit["missing_oracle_count"] == 2


def test_bootstrap_and_sign_flip_use_explicit_local_rng_and_exact_small_test() -> None:
    with pytest.raises(TypeError, match="rng_seed"):
        bootstrap_mean_ci([1.0, 2.0], rng_seed=True)

    first = bootstrap_mean_ci([1.0, 2.0, 3.0], rng_seed=17, n_resamples=1000)
    second = bootstrap_mean_ci([1.0, 2.0, 3.0], rng_seed=17, n_resamples=1000)
    assert first == second

    sign_flip = sign_flip_permutation_test([1.0, 1.0], rng_seed=5)
    assert sign_flip.exact
    assert sign_flip.permutation_count == 4
    assert sign_flip.statistic == 1.0
    assert sign_flip.pvalue == 0.5


def test_exact_mcnemar_retains_missing_pairs_and_holm_is_stable() -> None:
    result = exact_mcnemar(
        [False, False, True, True, None],
        [False, True, False, False, True],
    )
    assert result.paired_count == 4
    assert result.missing_pair_count == 1
    assert result.both_false == 1
    assert result.first_false_second_true == 1
    assert result.first_true_second_false == 2
    assert result.both_true == 0
    assert result.discordant_count == 3
    assert result.pvalue == 1.0

    holm = holm_adjust([0.01, 0.04, 0.03, None])
    assert holm.adjusted_pvalues == pytest.approx((0.03, 0.06, 0.06, None))
    assert holm.rejected == (True, False, False, None)

    frame = pd.DataFrame({"name": ["a", "b"], "pvalue": [0.01, 0.2]})
    adjusted = apply_holm(frame)
    assert adjusted["pvalue_holm"].tolist() == pytest.approx([0.02, 0.2])
    assert adjusted["reject_holm"].tolist() == [True, False]
