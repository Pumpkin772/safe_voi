from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from direction1freq.evaluation.control_critical_window import causal_control_relevant_update_time
from direction1freq.identification.passive_set_membership import (
    CapabilitySetEstimate, GLOBAL_LOWER, GLOBAL_UPPER,
)


ROOT = Path(__file__).resolve().parents[2]


def _estimate(time_s: float, changed: bool) -> CapabilitySetEstimate:
    lower = GLOBAL_LOWER.copy(); upper = GLOBAL_UPPER.copy()
    if changed:
        lower[2] = 0.7
    return CapabilitySetEstimate(
        time_s, lower, upper, False, changed, "delay", 0.03, 0.01,
        0.0, 1.0, "updated" if changed else "uncertain",
    )


def test_update_time_is_causal_and_requires_set_change_and_coverage() -> None:
    estimates = [_estimate(0.0, False), _estimate(4.0, False), _estimate(8.0, True)]
    capability = [np.array([1, 1, 0.2, 1, 1]), np.array([1, 1, 1.6, 1, 1]), np.array([1, 1, 1.6, 1, 1])]
    first = causal_control_relevant_update_time(estimates, capability, 4.0)
    assert first == 8.0
    # Appending arbitrary future information cannot change the earlier answer.
    assert causal_control_relevant_update_time(estimates + [_estimate(12.0, False)], capability + [capability[-1]], 4.0) == first


def test_e4_retains_not_evaluated_and_all_three_estimators() -> None:
    episodes = pd.read_parquet(ROOT / "results_phase_e" / "E4" / "E4_PASSIVE_EPISODES.parquet")
    assert set(episodes.estimator) == {"set_membership", "glr_set_reset", "imm_interval"}
    assert (~episodes.timing_evaluated).any()
    assert episodes.failure_cause.notna().all()


def test_passive_gate_is_not_forced_when_all_candidates_fail() -> None:
    progress = json.loads((ROOT / "progress_phase_e" / "E4.json").read_text())
    gates = pd.read_csv(ROOT / "results_phase_e" / "E4" / "E4_ESTIMATOR_GATE_SUMMARY.csv")
    if not gates.passive_gate_pass.any():
        assert progress["selected_passive_estimator"] == "none_qualified"
        assert progress["decision"] == "CONTINUE_TO_E5"


def test_no_change_false_alarm_and_truth_coverage_are_explicit() -> None:
    false_alarm = pd.read_csv(ROOT / "results_phase_e" / "E4" / "E4_NO_CHANGE_FALSE_ALARM.csv")
    summary = pd.read_csv(ROOT / "results_phase_e" / "E4" / "E4_PASSIVE_COVERAGE_TIMING.csv")
    assert false_alarm.false_alarm_rate.between(0, 1).all()
    assert summary.joint_truth_coverage.between(0, 1).all()
