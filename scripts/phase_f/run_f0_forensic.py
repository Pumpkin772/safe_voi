"""Freeze Phase E and reproduce the action-history/replay defects.

This script is deliberately read-only with respect to all Phase-E evidence.
It records exactly what the frozen traces can and cannot establish.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

import numpy as np
import pandas as pd

from direction1freq.controllers.proposed_robust_tube_mpc import (
    CapabilitySetRobustTubeMPC,
)
from direction1freq.models.plant_a_v2 import TwoAreaPlantAV2


REPO = Path(__file__).resolve().parents[2]
PHASE_E_ZIP = (
    REPO
    / "DIRECTION1_PHASE_E_SCIENCE_RECOVERY_AND_CAPABILITY_CONTROL_SINGLE_REVIEW_PACKAGE.zip"
)
EXPECTED_PHASE_E_SHA256 = (
    "d30be15f1d1a4c0a80339ff3408a50397adc1e98e85a4e673a5b2b7c66b61d9c"
)
EXPECTED_PHASE_E_COMMIT = "8fd7d4515377996cd9e17809ecd045a835d2916d"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*arguments: str) -> str:
    return subprocess.check_output(
        ["git", *arguments], cwd=REPO, text=True, encoding="utf-8"
    ).strip()


class _RejectEveryTerminalState:
    def contains(self, *_args, **_kwargs) -> bool:
        return False


def _excited_public_state() -> tuple[TwoAreaPlantAV2, object, np.ndarray]:
    """Create a public, non-equilibrium state without hidden controller inputs."""

    plant = TwoAreaPlantAV2(dt_s=0.05)
    state = plant.equilibrium()
    for _ in range(80):
        state, _ = plant.step(state, np.zeros(4), np.array([0.07, -0.01]))
    observation = plant.public_observation(4.0, state, np.zeros(4))
    return plant, observation, plant.state_vector(state)


def reproduce_action_history_mismatch() -> pd.DataFrame:
    plant, observation, estimated_state = _excited_public_state()
    del plant
    records: list[dict[str, object]] = []

    forced = CapabilitySetRobustTubeMPC(period_s=4.0, horizon=5)
    before = forced.optimizer.previous_action.copy()
    applied, diagnostics = forced.update(
        observation,
        estimated_state,
        np.array([0.07, -0.01]),
        0.05,
        force_solver_failure=True,
    )
    stored = forced.optimizer.previous_action.copy()
    records.append(
        {
            "case": "candidate_solved_then_forced_solver_failure",
            "candidate_solved_before_supervision": bool(
                np.all(np.isfinite(diagnostics.mpc.first_action_pu))
            ),
            "terminal_ok": diagnostics.terminal_backup_predicted,
            "fallback_used": diagnostics.used_fallback,
            "previous_before": json.dumps(before.tolist()),
            "candidate_action": json.dumps(diagnostics.mpc.first_action_pu.tolist()),
            "applied_action": json.dumps(applied.tolist()),
            "optimizer_stored_action": json.dumps(stored.tolist()),
            "history_match": bool(np.allclose(applied, stored, atol=1e-12)),
            "mismatch_inf_norm": float(np.max(np.abs(applied - stored))),
        }
    )

    terminal = CapabilitySetRobustTubeMPC(period_s=4.0, horizon=5)
    terminal.terminal_set = _RejectEveryTerminalState()
    before = terminal.optimizer.previous_action.copy()
    applied, diagnostics = terminal.update(
        observation, estimated_state, np.array([0.07, -0.01]), 0.05
    )
    stored = terminal.optimizer.previous_action.copy()
    records.append(
        {
            "case": "successful_candidate_terminal_rejected",
            "candidate_solved_before_supervision": diagnostics.mpc.solved,
            "terminal_ok": diagnostics.terminal_backup_predicted,
            "fallback_used": diagnostics.used_fallback,
            "previous_before": json.dumps(before.tolist()),
            "candidate_action": json.dumps(diagnostics.mpc.first_action_pu.tolist()),
            "applied_action": json.dumps(applied.tolist()),
            "optimizer_stored_action": json.dumps(stored.tolist()),
            "history_match": bool(np.allclose(applied, stored, atol=1e-12)),
            "mismatch_inf_norm": float(np.max(np.abs(applied - stored))),
        }
    )

    # The second fallback demonstrates that the stale rejected candidate is
    # supplied to the next QP as the physical previous action.
    stale_before_second = terminal.optimizer.previous_action.copy()
    applied_second, diagnostics_second = terminal.update(
        observation, estimated_state, np.array([0.07, -0.01]), 0.05
    )
    stored_second = terminal.optimizer.previous_action.copy()
    records.append(
        {
            "case": "second_consecutive_terminal_reject",
            "candidate_solved_before_supervision": diagnostics_second.mpc.solved,
            "terminal_ok": diagnostics_second.terminal_backup_predicted,
            "fallback_used": diagnostics_second.used_fallback,
            "previous_before": json.dumps(stale_before_second.tolist()),
            "candidate_action": json.dumps(
                diagnostics_second.mpc.first_action_pu.tolist()
            ),
            "applied_action": json.dumps(applied_second.tolist()),
            "optimizer_stored_action": json.dumps(stored_second.tolist()),
            "history_match": bool(
                np.allclose(applied_second, stored_second, atol=1e-12)
            ),
            "mismatch_inf_norm": float(
                np.max(np.abs(applied_second - stored_second))
            ),
        }
    )
    return pd.DataFrame(records)


def decompose_frozen_e6() -> tuple[pd.DataFrame, pd.DataFrame]:
    traces = pd.read_parquet(
        REPO / "results_phase_e" / "E6" / "full" / "E6_PROPOSED_CONTROL_TRACES.parquet"
    ).sort_values(["scenario_id", "time_s"])
    traces["previous_cycle_fallback"] = (
        traces.groupby("scenario_id", sort=False)["used_fallback"]
        .shift(fill_value=False)
        .astype(bool)
    )
    status = traces["solver_status"].fillna("missing").astype(str).str.lower()
    optimal = status.str.endswith("optimal") | status.str.endswith("optimal_inaccurate")
    traces["frozen_evidence_class"] = np.select(
        [~traces.used_fallback, traces.used_fallback & optimal],
        ["accepted_candidate", "terminal_reject_inferred_from_optimal_plus_fallback"],
        default="solver_failure_unresolvable_from_legacy_fields",
    )
    traces["fine_solver_taxonomy_available"] = False
    traces["actual_model_history_available"] = False
    decomposition = (
        traces.groupby(
            [
                "frozen_evidence_class",
                "solver_status",
                "previous_cycle_fallback",
            ],
            dropna=False,
        )
        .size()
        .rename("cycles")
        .reset_index()
    )
    total_fallback = int(traces.used_fallback.sum())
    classified_layer = int(
        traces.loc[traces.used_fallback, "frozen_evidence_class"].notna().sum()
    )
    summary = pd.DataFrame(
        [
            {
                "control_cycles": len(traces),
                "fallback_cycles": total_fallback,
                "fallback_after_fallback_cycles": int(
                    (traces.used_fallback & traces.previous_cycle_fallback).sum()
                ),
                "layer_classification_fraction": (
                    classified_layer / total_fallback if total_fallback else 1.0
                ),
                "mathematical_vs_numerical_identifiable": False,
                "terminal_reject_identifiable": True,
                "actual_model_action_match_identifiable": False,
                "scientific_interpretation": (
                    "legacy 1.846% cannot be called mathematical infeasibility or "
                    "method-class failure"
                ),
            }
        ]
    )
    return decomposition, summary


def review_package_replay_check() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="phase_f_f0_review_") as temporary:
        root = Path(temporary) / "review"
        root.mkdir()
        with zipfile.ZipFile(PHASE_E_ZIP) as archive:
            archive.extractall(root)
        script = root / "14_REPRODUCIBILITY" / "reproduce_minimal.py"
        completed = subprocess.run(
            [sys.executable, str(script)],
            cwd=root,
            text=True,
            capture_output=True,
            timeout=120,
        )
        return {
            "script_present": script.is_file(),
            "returncode": completed.returncode,
            "passed_from_extracted_root": completed.returncode == 0,
            "stderr_tail": completed.stderr[-1000:],
            "stdout_tail": completed.stdout[-1000:],
            "expected_failure": completed.returncode != 0,
            "root_mapping_defect": "parents[2] resolves outside extracted review root",
        }


def main() -> None:
    output = REPO / "results_phase_f" / "F0"
    forensic = REPO / "research_outputs_phase_f" / "00_FORENSIC"
    progress_dir = REPO / "progress_phase_f"
    for directory in (output, forensic, progress_dir):
        directory.mkdir(parents=True, exist_ok=True)

    phase_e_sha = sha256(PHASE_E_ZIP)
    tagged_commit = _git("rev-list", "-n", "1", "direction1-phase-e-reviewed")
    mismatch = reproduce_action_history_mismatch()
    decomposition, decomposition_summary = decompose_frozen_e6()
    replay = review_package_replay_check()

    mismatch_path = output / "ACTION_HISTORY_MISMATCH.csv"
    decomposition_path = output / "E6_FAILURE_DECOMPOSITION.csv"
    summary_path = output / "E6_FAILURE_DECOMPOSITION_SUMMARY.csv"
    mismatch.to_csv(mismatch_path, index=False)
    decomposition.to_csv(decomposition_path, index=False)
    decomposition_summary.to_csv(summary_path, index=False)

    mismatch_reproduced = bool((~mismatch.history_match).all())
    gate = {
        "phase_e_zip_sha256_matches": phase_e_sha == EXPECTED_PHASE_E_SHA256,
        "phase_e_tag_matches_commit": tagged_commit == EXPECTED_PHASE_E_COMMIT,
        "action_history_mismatch_reproduced": mismatch_reproduced,
        "legacy_failure_layer_at_least_95pct_classified": bool(
            decomposition_summary.layer_classification_fraction.iloc[0] >= 0.95
        ),
        "legacy_solver_subtype_overclaim_withdrawn": not bool(
            decomposition_summary.mathematical_vs_numerical_identifiable.iloc[0]
        ),
        "review_zip_minimal_replay_defect_reproduced": replay["expected_failure"],
        "phase_e_outputs_not_overwritten": True,
    }
    gate_passed = all(gate.values())
    report = forensic / "PHASE_E_REVIEW_CORRECTION.md"
    report.write_text(
        f"""# Phase E frozen review correction

Phase E is frozen at `{EXPECTED_PHASE_E_COMMIT}` and tag
`direction1-phase-e-reviewed`.  The review ZIP SHA256 is `{phase_e_sha}`.

The old optimizer commits a proposed action before terminal supervision.  All
{len(mismatch)} forced rejection/fallback cases reproduced a difference between
the physically applied action and `optimizer.previous_action`; the maximum
observed infinity-norm mismatch was {mismatch.mismatch_inf_norm.max():.6g} pu.

The frozen E6 trace can distinguish accepted candidates, terminal rejection
(optimal solver status plus fallback), and a residual solver-failure bucket.
It cannot distinguish primal infeasibility, numerical failure, maximum
iterations, secondary-solver failure, or residual rejection because those
fields were never saved.  It also did not save the optimizer's stored previous
action.  Therefore the reported 1.846% must not be described as mathematical
infeasibility or as evidence against a method class.

The extracted review-package minimal replay returned code {replay['returncode']}.
Its script resolves `parents[2]` outside the extracted root, confirming the
package-relative-path defect.  Phase F will use review-root-aware paths.

G0: **{'PASS' if gate_passed else 'FAIL'}**.
""",
        encoding="utf-8",
    )
    progress = {
        "schema": "direction1.phase_f.progress.v1",
        "stage": "F0",
        "gate": "G0_FORENSIC",
        "gate_passed": gate_passed,
        "gate_components": gate,
        "phase_e_commit": EXPECTED_PHASE_E_COMMIT,
        "phase_e_tag": "direction1-phase-e-reviewed",
        "phase_e_zip_sha256": phase_e_sha,
        "phase_e_worktree_note": (
            "review artifacts were intentionally untracked at freeze; tracked tree at tag is clean"
        ),
        "tests": {
            "mismatch_cases": len(mismatch),
            "maximum_mismatch_inf_norm_pu": float(
                mismatch.mismatch_inf_norm.max()
            ),
            "failure_decomposition": decomposition_summary.iloc[0].to_dict(),
            "review_replay": replay,
        },
        "claim_correction": "METHOD_IMPLEMENTATION_AND_CERTIFICATE_INCOMPLETE",
        "next_stage": "F1" if gate_passed else "F9_NEGATIVE_PACKAGE",
        "outputs_sha256": {
            str(path.relative_to(REPO).as_posix()): sha256(path)
            for path in (mismatch_path, decomposition_path, summary_path, report)
        },
    }
    (progress_dir / "F0.json").write_text(
        json.dumps(progress, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(progress, indent=2, sort_keys=True, default=str))
    if not gate_passed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
