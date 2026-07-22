from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from d5freq.evaluation.closed_loop_metrics import ClosedLoopMetricConfig
from d5freq.evaluation.closed_loop_runner import EpisodeRunnerConfig, run_closed_loop_episode
from d5freq.evaluation.experiment_store import (
    PerRunExperimentStore,
    RunIdentity,
    RunIntegrityError,
)
from d5freq.evaluation.phase6_canonical_journal import (
    _deduplicate_truth,
    load_and_verify_canonical_decision_journal,
    make_canonical_decision_journal_writer,
    replay_simulator_from_canonical_journal,
)
from d5freq.evaluation.phase6_trajectory_export import (
    CANONICAL_JOURNAL_TRACE_SOURCE,
    CanonicalRunEvidence,
    SelectedRun,
    TrajectoryExportError,
    _production_replay_provider,
    build_canonical_journal_replay_capture,
    build_selected_outputs,
)
from d5freq.interfaces import ControlAction, Measurement
from d5freq.models.grid_frequency import GridFrequencyModel, GridParams
from d5freq.models.hidden_mode_ibr import IBRModeParams
from d5freq.simulation.hybrid_simulator import HiddenModeFrequencySimulator, Scenario
from d5freq.simulation.mode_schedules import PiecewiseConstantModeSchedule
from scripts.phase7_support import validate_selected_trajectory_manifest


class _RecordedController:
    def __init__(self) -> None:
        self.step_records: list[dict[str, object]] = []
        self.act_calls = 0

    def reset(self, initial_measurement: Measurement) -> None:
        assert isinstance(initial_measurement, Measurement)
        self.step_records.clear()
        self.act_calls = 0

    def act(self, measurement: Measurement) -> ControlAction:
        index = self.act_calls
        self.act_calls += 1
        u_sg = 0.001 * (index + 1)
        u_ibr = -0.0005 * (index + 1)
        self.step_records.append(
            {
                "time_s": measurement.time_s,
                "sample_index": index,
                "controller_state": "NORMAL",
                "diagnostic_state": "KNOWN",
                "belief_0": 1.0,
                "map_mode": 0,
                "belief_entropy": 0.0,
                "ood_pvalue": 1.0,
                "solver_status": "optimal",
                "solver_outcome": "success",
                "solve_time_s": 0.01,
                "max_freq_slack_hz": 0.0,
                "max_rocof_slack_hz_per_s": 0.0,
                "max_power_slack_pu": 0.0,
                "u_sg_pu": u_sg,
                "u_ibr_pu": u_ibr,
            }
        )
        return ControlAction(
            u_sg,
            u_ibr,
            controller_state="NORMAL",
            solver_status="optimal",
            solve_time_s=0.01,
        )


def _system() -> tuple[GridFrequencyModel, IBRModeParams, Scenario]:
    grid = GridFrequencyModel(
        GridParams(50.0, 8.0, 1.0, 0.5, 0.2, 0.08, 0.1, 0.01)
    )
    mode = IBRModeParams(
        name="nominal",
        command_gain=1.0,
        frequency_gain=4.0,
        command_filter_time_s=0.1,
        power_response_time_s=0.2,
        delay_s=0.0,
        p_max_pos_pu=0.08,
        p_max_neg_pu=0.08,
        ramp_up_pu_per_s=0.05,
        ramp_down_pu_per_s=0.05,
        deadband_pu=0.0005,
    )
    scenario = Scenario(
        PiecewiseConstantModeSchedule("nominal"),
        duration_s=0.2,
        omega_measurement_std_pu=1.0e-6,
        power_measurement_std_pu=1.0e-6,
    )
    return grid, mode, scenario


def _canonical_run(tmp_path: Path):
    stage_root = tmp_path / "smoke"
    identity = RunIdentity("journal-test", "short", "P", 42)
    grid, mode, scenario = _system()
    controller = _RecordedController()
    store = PerRunExperimentStore(stage_root / "per_run")
    outcome = run_closed_loop_episode(
        identity=identity,
        simulator=HiddenModeFrequencySimulator(grid, {"nominal": mode}),
        scenario=scenario,
        controller=controller,
        metric_config=ClosedLoopMetricConfig(),
        store=store,
        runner_config=EpisodeRunnerConfig(
            expected_duration_s=0.2,
            persist_control_trajectory=False,
            persist_high_frequency_trace=False,
            persist_controller_records=False,
        ),
        immutable_run_artifact_writer=make_canonical_decision_journal_writer(
            stage_root=stage_root,
            stage="smoke",
            identity=identity,
        ),
    )
    return outcome, controller, grid, mode, scenario, store


def test_replay_truth_dedup_preserves_right_continuous_switch_boundary() -> None:
    left = {
        "time_s": 4.499999999999989,
        "omega_true_pu": 0.0,
        "true_mode_eval_only": "nominal",
    }
    right = {
        "time_s": 4.5,
        "omega_true_pu": 0.0,
        "true_mode_eval_only": "asymmetric_limit",
    }

    retained = _deduplicate_truth((left, right, right))

    assert tuple(point["time_s"] for point in retained) == (
        4.499999999999989,
        4.5,
    )
    assert tuple(point["true_mode_eval_only"] for point in retained) == (
        "nominal",
        "asymmetric_limit",
    )
    with pytest.raises(RunIntegrityError, match="differs"):
        _deduplicate_truth((right, {**right, "true_mode_eval_only": "nominal"}))


def test_forced_replay_preserves_real_floating_drift_mode_boundary(
    tmp_path: Path,
) -> None:
    grid, nominal, _ = _system()
    held_out = replace(nominal, name="asymmetric_limit", p_max_neg_pu=0.02)
    scenario = Scenario(
        PiecewiseConstantModeSchedule.from_pairs(
            "nominal", [(4.5, "asymmetric_limit")]
        ),
        duration_s=5.0,
    )
    identity = RunIdentity("journal-switch", "floating-boundary", "P", 7)
    stage_root = tmp_path / "switch"
    outcome = run_closed_loop_episode(
        identity=identity,
        simulator=HiddenModeFrequencySimulator(
            grid, {"nominal": nominal, "asymmetric_limit": held_out}
        ),
        scenario=scenario,
        controller=_RecordedController(),
        metric_config=ClosedLoopMetricConfig(),
        store=PerRunExperimentStore(stage_root / "per_run"),
        runner_config=EpisodeRunnerConfig(expected_duration_s=5.0),
        immutable_run_artifact_writer=make_canonical_decision_journal_writer(
            stage_root=stage_root,
            stage="smoke",
            identity=identity,
        ),
    )
    assert outcome.episode_result.run_completed
    assert outcome.episode_result.metrics_complete
    assert outcome.episode_result.failure_stage is None

    replay = replay_simulator_from_canonical_journal(
        identity=identity,
        scenario=scenario,
        simulator=HiddenModeFrequencySimulator(
            grid, {"nominal": nominal, "asymmetric_limit": held_out}
        ),
        journal=load_and_verify_canonical_decision_journal(outcome.stored_run),
    )

    boundary = tuple(
        (point["time_s"], point["true_mode_eval_only"])
        for point in replay.high_frequency_truth
        if 4.5 - 1.0e-9 < float(point["time_s"]) <= 4.5
    )
    assert len(boundary) == 2
    assert boundary[0][1] == "nominal"
    assert 0.0 < 4.5 - float(boundary[0][0]) <= 1.0e-12
    assert boundary[1] == (4.5, "asymmetric_limit")
    assert replay.consistency_audit["max_abs_truth_difference"] == 0.0


def test_forced_replay_uses_only_canonical_actions_and_verifies_every_endpoint(
    tmp_path: Path,
) -> None:
    outcome, controller, grid, mode, scenario, _ = _canonical_run(tmp_path)
    assert outcome.episode_result.scientific_success
    canonical_act_calls = controller.act_calls
    journal = load_and_verify_canonical_decision_journal(outcome.stored_run)

    replay = replay_simulator_from_canonical_journal(
        identity=outcome.identity,
        scenario=scenario,
        simulator=HiddenModeFrequencySimulator(grid, {"nominal": mode}),
        journal=journal,
    )

    assert controller.act_calls == canonical_act_calls
    assert replay.consistency_audit["controller_or_solver_invoked"] is False
    assert replay.consistency_audit["trace_source"] == (
        "canonical_action_journal_forced_simulator_replay"
    )
    assert replay.consistency_audit["measurement_endpoint_count_verified"] == 3
    assert replay.consistency_audit["truth_endpoint_count_verified"] == 3
    assert replay.consistency_audit["max_abs_measurement_difference"] == 0.0
    assert replay.consistency_audit["max_abs_truth_difference"] == 0.0
    assert len(replay.actions) == 2
    assert len(replay.control_trajectory) == 3
    assert replay.control_trajectory[-1]["terminal_endpoint"] is True
    assert len(replay.controller_records) == 2
    assert replay.high_frequency_truth[0]["time_s"] == 0.0
    assert replay.high_frequency_truth[-1]["time_s"] == 0.2

    def timeout_flip(_measurement: Measurement) -> ControlAction:
        raise TimeoutError("deadline outcome flipped after canonical execution")

    controller.act = timeout_flip  # type: ignore[method-assign]
    capture = build_canonical_journal_replay_capture(
        canonical_stored_run=outcome.stored_run,
        scenario=scenario,
        simulator=HiddenModeFrequencySimulator(grid, {"nominal": mode}),
        metric_config=ClosedLoopMetricConfig(),
        work_root=tmp_path / "forced_export",
    )
    assert controller.act_calls == canonical_act_calls
    assert capture.trace_source == CANONICAL_JOURNAL_TRACE_SOURCE
    assert capture.trace_source_audit["endpoint_consistency_audit"][
        "controller_or_solver_invoked"
    ] is False
    assert capture.trace_source_audit["scientific_recomputation_audit"][
        "status"
    ] == "verified"
    assert capture.episode_result.freq_iae == outcome.episode_result.freq_iae
    assert capture.stored_run.run_payload["trace_source"] == (
        CANONICAL_JOURNAL_TRACE_SOURCE
    )

    results = tmp_path / "manifest_results"
    results.mkdir()
    metrics = pd.DataFrame.from_records([outcome.episode_result.to_row()])
    ledger = metrics.copy()
    ledger["per_run_envelope_sha256"] = outcome.stored_run.sha256
    metrics.to_csv(results / "per_episode_metrics.csv", index=False)
    ledger.to_csv(results / "experiment_ledger.csv", index=False)
    (results / "protocol_lock.json").write_text('{"locked":true}\n', encoding="utf-8")
    representative = SelectedRun(
        outcome.identity.run_id,
        outcome.identity.scenario_id,
        outcome.identity.method,
        outcome.identity.seed,
        "representative_known",
        1,
        "canonical journal fixture",
    )
    worst = SelectedRun(
        outcome.identity.run_id,
        outcome.identity.scenario_id,
        outcome.identity.method,
        outcome.identity.seed,
        "worst_failure",
        1,
        "canonical journal fixture",
    )
    canonical = CanonicalRunEvidence(
        outcome.stored_run,
        metrics.iloc[0].to_dict(),
        ledger.iloc[0].to_dict(),
    )
    representative_manifest, worst_manifest = build_selected_outputs(
        results_dir=results,
        metrics_frame=metrics,
        ledger_frame=ledger,
        representative=(representative,),
        worst=(worst,),
        canonical_provider=lambda _: canonical,
        replay_provider=lambda *_: capture,
        staging_root=tmp_path / "manifest_staging",
    )
    entry = json.loads(representative_manifest.read_text(encoding="utf-8"))[
        "entries"
    ][0]
    assert entry["trace_source"] == CANONICAL_JOURNAL_TRACE_SOURCE
    assert entry["canonical_journal"]["sha256"] == journal.metadata["sha256"]
    assert entry["canonical_journal"]["schema_version"] == journal.metadata[
        "schema_version"
    ]
    assert entry["canonical_journal"]["row_count"] == journal.metadata[
        "row_count"
    ]
    assert entry["endpoint_consistency_audit"]["controller_or_solver_invoked"] is False
    assert entry["scientific_recomputation_audit"]["status"] == "verified"
    assert {
        record["source"] for record in entry["files"].values()
    } == {CANONICAL_JOURNAL_TRACE_SOURCE}
    os.replace(
        representative_manifest.parent, results / "representative_trajectories"
    )
    os.replace(worst_manifest.parent, results / "worst_failure_cases")
    validated = validate_selected_trajectory_manifest(
        results / "representative_trajectories",
        results_dir=results,
        expected_role="representative",
    )
    assert validated["entries"][0]["canonical_journal"]["sha256"] == (
        journal.metadata["sha256"]
    )


@pytest.mark.parametrize("mutation", ["missing", "tampered"])
def test_missing_or_tampered_journal_is_rejected(
    tmp_path: Path, mutation: str
) -> None:
    outcome, _, grid, mode, scenario, _ = _canonical_run(tmp_path)
    journal = load_and_verify_canonical_decision_journal(outcome.stored_run)
    if mutation == "missing":
        journal.path.unlink()
        message = "missing"
    else:
        with journal.path.open("ab") as handle:
            handle.write(b"tamper")
        message = "size differs"

    with pytest.raises(RunIntegrityError, match=message):
        build_canonical_journal_replay_capture(
            canonical_stored_run=outcome.stored_run,
            scenario=scenario,
            simulator=HiddenModeFrequencySimulator(grid, {"nominal": mode}),
            metric_config=ClosedLoopMetricConfig(),
            work_root=tmp_path / "rejected_export",
        )


def test_forced_replay_fails_closed_when_recomputed_science_changes(
    tmp_path: Path,
) -> None:
    outcome, _, grid, mode, scenario, _ = _canonical_run(tmp_path)
    with pytest.raises(
        TrajectoryExportError, match="scientific recomputation differs"
    ):
        build_canonical_journal_replay_capture(
            canonical_stored_run=outcome.stored_run,
            scenario=scenario,
            simulator=HiddenModeFrequencySimulator(grid, {"nominal": mode}),
            metric_config=ClosedLoopMetricConfig(nominal_frequency_hz=60.0),
            work_root=tmp_path / "scientific_mismatch",
        )


def test_production_replay_provider_never_builds_a_controller_or_solver(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import d5freq.evaluation.phase6_experiments as experiments
    import d5freq.evaluation.phase6_trajectory_export as exporter
    from d5freq.evaluation.closed_loop_runner import EvaluationContribution

    outcome, _, grid, mode, scenario, _ = _canonical_run(tmp_path)
    paths = SimpleNamespace(
        experiments_config=tmp_path / "unused_experiments.yaml",
        base_config=tmp_path / "unused_base.yaml",
    )
    spec = SimpleNamespace(paths=paths, identity=outcome.identity)

    def forbidden_controller_build(_spec: object) -> object:
        raise AssertionError("production replay attempted controller construction")

    monkeypatch.setattr(experiments, "_controller_for_spec", forbidden_controller_build)
    monkeypatch.setattr(
        experiments,
        "load_frozen_phase6_protocol",
        lambda _path: SimpleNamespace(build_scenario=lambda _scenario_id: scenario),
    )
    monkeypatch.setattr(
        experiments, "load_simulator_private_modes_eval_only", lambda _paths: {"nominal": mode}
    )
    monkeypatch.setattr(
        experiments, "build_metric_config", lambda _path: ClosedLoopMetricConfig()
    )
    monkeypatch.setattr(
        experiments, "responsibility_event_time_eval_only", lambda _scenario: None
    )
    monkeypatch.setattr(
        experiments,
        "_diagnostic_evaluator",
        lambda _spec: (lambda _data: EvaluationContribution()),
    )
    monkeypatch.setattr(exporter, "_grid_model_for_forced_replay", lambda _path: grid)
    evidence = CanonicalRunEvidence(outcome.stored_run, {}, {})
    selection = SelectedRun(
        outcome.identity.run_id,
        outcome.identity.scenario_id,
        outcome.identity.method,
        outcome.identity.seed,
        "representative_known",
        1,
        "production provider fixture",
    )
    capture = _production_replay_provider(
        {outcome.identity.run_id: spec},
        {outcome.identity.run_id: evidence},
    )(selection, tmp_path / "production_provider")
    assert capture.trace_source == CANONICAL_JOURNAL_TRACE_SOURCE
    assert capture.trace_source_audit["endpoint_consistency_audit"][
        "controller_or_solver_invoked"
    ] is False


def test_journal_publication_failure_leaves_no_canonical_envelope_or_temp_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import d5freq.evaluation.phase6_canonical_journal as journal_module

    stage_root = tmp_path / "smoke"
    identity = RunIdentity("journal-atomic", "short", "P", 43)
    grid, mode, scenario = _system()
    store = PerRunExperimentStore(stage_root / "per_run")

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("injected atomic publication failure")

    monkeypatch.setattr(journal_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected atomic"):
        run_closed_loop_episode(
            identity=identity,
            simulator=HiddenModeFrequencySimulator(grid, {"nominal": mode}),
            scenario=scenario,
            controller=_RecordedController(),
            metric_config=ClosedLoopMetricConfig(),
            store=store,
            runner_config=EpisodeRunnerConfig(expected_duration_s=0.2),
            immutable_run_artifact_writer=(
                make_canonical_decision_journal_writer(
                    stage_root=stage_root,
                    stage="smoke",
                    identity=identity,
                )
            ),
        )

    assert store.load(identity) is None
    journal_root = stage_root / "j"
    assert not tuple(journal_root.rglob("*.tmp"))
    assert not tuple(journal_root.rglob("*.parquet"))


def test_windows_deep_output_root_fails_before_partial_journal_publication(
    tmp_path: Path,
) -> None:
    import d5freq.evaluation.phase6_canonical_journal as journal_module

    if journal_module.os.name != "nt":
        pytest.skip("the conservative path budget is Windows-specific")

    deep_root = tmp_path
    prospective = deep_root / "smoke" / "j" / f"{'0' * 64}.parquet"
    while len(str(prospective.resolve())) < 250:
        deep_root = deep_root / ("nested" * 4)
        prospective = deep_root / "smoke" / "j" / f"{'0' * 64}.parquet"

    with pytest.raises(RuntimeError, match="shorter Phase-6 output_root"):
        make_canonical_decision_journal_writer(
            stage_root=deep_root / "smoke",
            stage="smoke",
            identity=RunIdentity("too-deep", "short", "P", 1),
        )

    journal_root = deep_root / "smoke" / "j"
    assert not journal_root.exists()
