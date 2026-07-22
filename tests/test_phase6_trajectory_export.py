from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import pytest

from d5freq.evaluation.experiment_store import PerRunExperimentStore, RunIdentity
from d5freq.evaluation.phase6_trajectory_export import (
    CanonicalRunEvidence,
    ReplayCapture,
    SelectedRun,
    TrajectoryExportError,
    _production_staging_root,
    build_selected_outputs,
    compare_episode_results,
    select_representative_runs,
    select_worst_runs,
)
from d5freq.evaluation.results_schema import EpisodeResult
from d5freq.utils.hashing import sha256_file
from scripts.phase7_support import validate_selected_trajectory_manifest


def _selection_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for scenario, values in (
        ("S2_sluggish_switch_060", {1000: 1.0, 1001: 3.0, 1002: 2.0}),
        ("S7_ood_asymmetric_limit", {1000: 4.0, 1001: 2.0, 1002: 3.0}),
    ):
        methods = (
            ("B0", "B1", "B2", "B3", "B4", "P")
            if scenario.startswith("S2")
            else ("B1", "B3", "P", "no-OOD")
        )
        for seed, value in values.items():
            for method in methods:
                rows.append(
                    {
                        "run_id": f"{scenario}::{method}::{seed}",
                        "scenario_id": scenario,
                        "method": method,
                        "seed": seed,
                        "freq_iae": value + (0.1 if method != "P" else 0.0),
                        "max_abs_freq_hz": value / 10.0,
                        "run_completed": True,
                        "metrics_complete": True,
                        "scientific_success": True,
                        "failure_type": None,
                        "catastrophic_failure": False,
                    }
                )
    rows.extend(
        [
            {
                "run_id": "cat-low",
                "scenario_id": "S9",
                "method": "B0",
                "seed": 2000,
                "freq_iae": 1.0,
                "max_abs_freq_hz": 0.8,
                "run_completed": True,
                "metrics_complete": True,
                "scientific_success": False,
                "failure_type": "physical_limit",
                "catastrophic_failure": True,
            },
            {
                "run_id": "cat-high",
                "scenario_id": "S9",
                "method": "B1",
                "seed": 2001,
                "freq_iae": 2.0,
                "max_abs_freq_hz": 1.2,
                "run_completed": True,
                "metrics_complete": True,
                "scientific_success": False,
                "failure_type": "physical_limit",
                "catastrophic_failure": True,
            },
            {
                "run_id": "noncat-high",
                "scenario_id": "S9",
                "method": "P",
                "seed": 2002,
                "freq_iae": 100.0,
                "max_abs_freq_hz": 5.0,
                "run_completed": True,
                "metrics_complete": True,
                "scientific_success": True,
                "failure_type": None,
                "catastrophic_failure": False,
            },
        ]
    )
    return pd.DataFrame.from_records(rows)


def _result(identity: RunIdentity, *, freq_iae: float = 1.0, wall: float = 2.0) -> EpisodeResult:
    return EpisodeResult(
        run_id=identity.run_id,
        scenario_id=identity.scenario_id,
        method=identity.method,
        seed=identity.seed,
        run_completed=True,
        metrics_complete=True,
        freq_iae=freq_iae,
        max_abs_freq_hz=0.2,
        solve_time_mean_s=0.05,
        solve_time_p95_s=0.07,
        solve_time_max_s=0.08,
        wall_time_s=wall,
    )


def test_representative_and_worst_selection_are_frozen_and_stable() -> None:
    frame = _selection_frame()
    representative = select_representative_runs(frame)
    assert len(representative) == 10
    assert {item.seed for item in representative} == {1002}
    assert [item.method for item in representative[:6]] == [
        "B0",
        "B1",
        "B2",
        "B3",
        "B4",
        "P",
    ]
    assert [item.method for item in representative[6:]] == [
        "B1",
        "B3",
        "P",
        "no-OOD",
    ]

    worst = select_worst_runs(frame, maximum_count=3)
    assert [item.run_id for item in worst[:2]] == ["cat-high", "cat-low"]
    assert worst[2].run_id == "noncat-high"


def test_replay_consistency_excludes_only_declared_timing_fields() -> None:
    identity = RunIdentity("run", "scenario", "P", 1000)
    canonical = _result(identity, freq_iae=1.0, wall=2.0).to_row()
    replay = _result(identity, freq_iae=1.0, wall=99.0).to_row()
    replay["solve_time_mean_s"] = 9.0
    replay["solve_time_p95_s"] = 9.0
    replay["solve_time_max_s"] = 9.0
    consistent = compare_episode_results(canonical, replay)
    assert consistent["status"] == "verified"
    assert not consistent["mismatches"]
    assert "wall_time_s" in consistent["excluded_nondeterministic_fields"]

    replay["freq_iae"] = 1.01
    mismatch = compare_episode_results(canonical, replay)
    assert mismatch["status"] == "mismatch"
    assert [row["field"] for row in mismatch["mismatches"]] == ["freq_iae"]


def test_production_staging_is_short_and_on_the_publication_filesystem(
    tmp_path: Path,
) -> None:
    results = tmp_path / ("long_workspace_segment_" * 3) / "results" / "final"
    results.mkdir(parents=True)
    staging = _production_staging_root(results)
    try:
        assert staging.name.startswith("d5x_")
        assert os.stat(staging).st_dev == os.stat(results).st_dev
    finally:
        staging.rmdir()


def _write_canonical_files(results: Path, result: EpisodeResult, envelope_sha: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    metrics = pd.DataFrame.from_records([result.to_row()])
    ledger = metrics.copy()
    ledger["per_run_envelope_sha256"] = envelope_sha
    metrics.to_csv(results / "per_episode_metrics.csv", index=False, lineterminator="\n")
    ledger.to_csv(results / "experiment_ledger.csv", index=False, lineterminator="\n")
    (results / "protocol_lock.json").write_text(
        json.dumps({"locked": True}, sort_keys=True) + "\n", encoding="utf-8"
    )
    return metrics, ledger


def test_dependency_injected_export_writes_authenticated_zstd_bundle_once(
    tmp_path: Path,
) -> None:
    results = tmp_path / "results" / "final"
    results.mkdir(parents=True)
    identity = RunIdentity("run", "scenario", "P", 1000)
    canonical_store = PerRunExperimentStore(tmp_path / "canonical_store")
    canonical_result = _result(identity)
    canonical_stored = canonical_store.save(
        identity, canonical_result, {"provenance": {"fixture": True}}
    )
    metrics, ledger = _write_canonical_files(
        results, canonical_result, canonical_stored.sha256
    )

    replay_store = PerRunExperimentStore(tmp_path / "replay_store")
    replay_result = _result(identity, wall=77.0)
    replay_stored = replay_store.save(
        identity, replay_result, {"provenance": {"fixture": True}}
    )
    capture = ReplayCapture(
        stored_run=replay_stored,
        episode_result=replay_result,
        control_trajectory=(
            {
                "time_s": 0.0,
                "u_sg_pu": 0.0,
                "u_ibr_pu": 0.0,
                "p_ibr_true_pu": 0.0,
                "mode_belief": [0.8, 0.2],
            },
        ),
        high_frequency_truth=(
            {"time_s": 0.0, "omega_pu": 0.0, "true_mode_eval_only": "nominal"},
        ),
        truth_intervals=(
            {"start_time_s": 0.0, "end_time_s": 0.1, "true_mode_eval_only": "nominal"},
        ),
        controller_records=(
            {"time_s": 0.0, "controller_state": "MPC", "mode_belief": [0.8, 0.2]},
        ),
    )
    selection_rep = SelectedRun(
        run_id="run",
        scenario_id="scenario",
        method="P",
        seed=1000,
        selection_role="representative_known",
        selection_rank=1,
        selection_basis="fixture representative",
    )
    selection_worst = SelectedRun(
        run_id="run",
        scenario_id="scenario",
        method="P",
        seed=1000,
        selection_role="worst_failure",
        selection_rank=1,
        selection_basis="fixture worst",
    )
    calls = 0

    def canonical_provider(_: SelectedRun) -> CanonicalRunEvidence:
        return CanonicalRunEvidence(
            stored_run=canonical_stored,
            metrics=metrics.iloc[0].to_dict(),
            ledger=ledger.iloc[0].to_dict(),
        )

    def replay_provider(_: SelectedRun, __: Path) -> ReplayCapture:
        nonlocal calls
        calls += 1
        return capture

    representative_manifest, worst_manifest = build_selected_outputs(
        results_dir=results,
        metrics_frame=metrics,
        ledger_frame=ledger,
        representative=(selection_rep,),
        worst=(selection_worst,),
        canonical_provider=canonical_provider,
        replay_provider=replay_provider,
        staging_root=tmp_path / "staging",
    )
    assert calls == 1
    os.replace(representative_manifest.parent, results / "representative_trajectories")
    os.replace(worst_manifest.parent, results / "worst_failure_cases")
    representative_payload = validate_selected_trajectory_manifest(
        results / "representative_trajectories",
        results_dir=results,
        expected_role="representative",
    )
    validate_selected_trajectory_manifest(
        results / "worst_failure_cases",
        results_dir=results,
        expected_role="worst",
    )
    entry = representative_payload["entries"][0]
    assert entry["canonical_envelope_sha256"] == canonical_stored.sha256
    assert entry["replay_envelope_sha256"] == replay_stored.sha256
    assert entry["replay_consistency"]["status"] == "verified"
    for record in entry["files"].values():
        assert record["compression"] == "zstd"
        path = results / "representative_trajectories" / record["relative_path"]
        assert sha256_file(path) == record["sha256"]
        frame = pd.read_parquet(path)
        if not frame.empty:
            assert set(frame["run_id"]) == {"run"}
            assert set(frame["scenario_id"]) == {"scenario"}
            assert set(frame["method"]) == {"P"}
            assert set(frame["seed"]) == {1000}


def test_export_refuses_scientific_mismatch_without_manifest(tmp_path: Path) -> None:
    results = tmp_path / "results"
    results.mkdir()
    identity = RunIdentity("run", "scenario", "P", 1000)
    canonical_store = PerRunExperimentStore(tmp_path / "canonical")
    canonical_result = _result(identity, freq_iae=1.0)
    canonical_stored = canonical_store.save(identity, canonical_result, {})
    metrics, ledger = _write_canonical_files(
        results, canonical_result, canonical_stored.sha256
    )
    replay_store = PerRunExperimentStore(tmp_path / "replay")
    replay_result = _result(identity, freq_iae=2.0)
    replay_stored = replay_store.save(identity, replay_result, {})
    selection = SelectedRun(
        "run", "scenario", "P", 1000, "representative_known", 1, "fixture"
    )
    worst_selection = SelectedRun(
        "run", "scenario", "P", 1000, "worst_failure", 1, "fixture worst"
    )

    with pytest.raises(TrajectoryExportError, match="differs from canonical"):
        build_selected_outputs(
            results_dir=results,
            metrics_frame=metrics,
            ledger_frame=ledger,
            representative=(selection,),
            worst=(worst_selection,),
            canonical_provider=lambda _: CanonicalRunEvidence(
                canonical_stored,
                metrics.iloc[0].to_dict(),
                ledger.iloc[0].to_dict(),
            ),
            replay_provider=lambda *_: ReplayCapture(
                replay_stored,
                replay_result,
                (),
                (),
                (),
                (),
            ),
            staging_root=tmp_path / "failed_staging",
        )
    assert not (tmp_path / "failed_staging" / "representative_trajectories" / "trajectory_manifest.json").exists()
