from __future__ import annotations

import json
from pathlib import Path

from d5freq.evaluation.phase_b1_execution import (
    attempt_failure_path,
    write_attempt_failure,
)
from d5freq.evaluation.phase_b1_experiments import PhaseB1RunSpec
from d5freq.evaluation.phase_b1_protocol import PhaseB1Paths


def _spec(root: Path) -> PhaseB1RunSpec:
    return PhaseB1RunSpec(
        stage="final",
        scenario_id="S0_nominal_stochastic",
        method_id="B0",
        seed=3000,
        sg_level="A",
        solver_tier="FINAL",
        oracle_candidate_id=None,
        oracle_horizon_s=None,
        repo_root=root,
    )


def test_final_attempt_failure_is_immutable_retained_and_not_marked_retryable(
    tmp_path: Path,
) -> None:
    paths = PhaseB1Paths.from_repo(tmp_path)
    spec = _spec(tmp_path)
    first = write_attempt_failure(paths, spec, RuntimeError("first failure"))
    second = write_attempt_failure(paths, spec, RuntimeError("must not overwrite"))
    assert first == second == attempt_failure_path(paths, spec)
    payload = json.loads(first.read_text(encoding="utf-8"))
    assert payload["body"]["failure_message"] == "first failure"
    assert payload["body"]["retry_forbidden_without_explicit_review"] is True
    assert payload["body"]["run_identity"]["seed"] == 3000


def test_final_feedback_policy_and_representatives_are_frozen_before_execution() -> None:
    repo = Path(__file__).resolve().parents[1]
    from d5freq.utils.config import load_yaml

    payload = load_yaml(repo / "configs/phase_b1_audit.yaml")
    assert payload["final_feedback_policy"]["tune_on_final"] is False
    assert payload["final_feedback_policy"]["run_final_once_after_protocol_lock"] is True
    representative = payload["representative_trajectories"]
    assert representative["selection_status"] == "preregistered_before_final"
    assert representative["seed"] == 3000
    assert representative["persist_high_frequency_truth"] is False
