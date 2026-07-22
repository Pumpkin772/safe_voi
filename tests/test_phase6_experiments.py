from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from d5freq.evaluation.experiment_store import (
    PerRunExperimentStore,
    RunIntegrityError,
    StoredRun,
)
from d5freq.evaluation.phase6_experiments import (
    EXPECTED_FINAL_RUN_COUNT,
    EXPECTED_SMOKE_RUN_COUNT,
    EXPECTED_TUNING_RUN_COUNT,
    Phase6Paths,
    Phase6StageExecutionError,
    WorkerRunReceipt,
    _diagnostic_evaluator,
    _execute_run_spec,
    _metadata_evaluator,
    _runtime_solver_audit,
    build_metric_config,
    build_protocol_material,
    build_run_plan,
    ensure_final_protocol_lock,
    execute_run_plan,
    expected_provenance,
    frozen_tuning_candidate_sha256,
    library_kind_for_method,
    load_frozen_phase6_protocol,
    load_component_mapping_eval_only,
    load_simulator_private_modes_eval_only,
    load_phase6_attempt_receipts,
    protocol_material_sha256,
    refresh_stage_aggregates,
    resolve_repo_or_cwd_path,
    responsibility_event_time_eval_only,
    stable_run_id,
    validate_b1_selection,
    validate_stage_worker_count,
    verified_stage_runs,
    write_tuning_selection_record,
    write_phase6_attempt_receipt,
)
from d5freq.evaluation.phase6_canonical_journal import (
    CANONICAL_DECISION_JOURNAL_PAYLOAD_KEY,
    write_canonical_decision_journal,
)
from d5freq.evaluation.results_schema import EpisodeResult
from d5freq.interfaces import ControlAction, Measurement
from d5freq.utils.config import config_sha256, load_yaml
from d5freq.utils.hashing import sha256_file


ROOT = Path(__file__).resolve().parents[1]


def _paths(tmp_path: Path | None = None) -> Phase6Paths:
    return Phase6Paths.from_repo(
        ROOT,
        output_root=None if tmp_path is None else tmp_path / "phase6-results",
    )


def _attach_test_journal(
    paths: Phase6Paths,
    spec: object,
    result: EpisodeResult,
    payload: dict[str, object],
) -> None:
    identity = spec.identity
    if result.run_completed:
        initial = Measurement(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        terminal = Measurement(0.5, 0.0, 0.0, 0.0, 0.01, -0.01)
        action = ControlAction(
            0.01,
            -0.01,
            controller_state="NORMAL",
            solver_status="optimal",
            solve_time_s=0.01,
        )
        first_truth = {
            "time_s": 0.0,
            "omega_true_pu": 0.0,
            "rocof_true_hz_per_s": 0.0,
            "p_mech_true_pu": 0.0,
            "p_ibr_true_pu": 0.0,
            "load_disturbance_pu": 0.0,
            "true_mode_eval_only": "nominal",
        }
        final_truth = {**first_truth, "time_s": 0.5}
        data = SimpleNamespace(
            identity=identity,
            run_completed=True,
            measurements=(initial, terminal),
            actions=(action,),
            simulator_evaluations=(
                {
                    "true_trace_points_eval_only": (first_truth, final_truth),
                    "true_trace_intervals_eval_only": (),
                    "done": True,
                },
            ),
            controller_records=(
                {
                    "time_s": 0.0,
                    "controller_state": "NORMAL",
                    "diagnostic_state": "KNOWN",
                    "belief_0": 1.0,
                    "map_mode": 0,
                    "belief_entropy": 0.0,
                    "ood_pvalue": 1.0,
                    "solver_status": "optimal",
                    "solver_outcome": "success",
                },
            ),
        )
    else:
        data = SimpleNamespace(
            identity=identity,
            run_completed=False,
            measurements=(),
            actions=(),
            simulator_evaluations=(),
            controller_records=(),
        )
    metadata = write_canonical_decision_journal(
        stage_root=paths.stage_root(spec.stage),
        stage=spec.stage,
        identity=identity,
        data=data,
        episode_result=result,
    )
    payload[CANONICAL_DECISION_JOURNAL_PAYLOAD_KEY] = dict(metadata)


def test_frozen_run_plans_have_exact_counts_seed_rules_and_stable_ids() -> None:
    paths = _paths()
    smoke = build_run_plan(paths, stage="smoke")
    tuning = build_run_plan(paths, stage="tuning")
    final = build_run_plan(paths, stage="final")

    assert len(smoke) == EXPECTED_SMOKE_RUN_COUNT == 504
    assert len(tuning) == EXPECTED_TUNING_RUN_COUNT == 210
    assert len(final) == EXPECTED_FINAL_RUN_COUNT == 8_280
    assert {row.identity.method for row in tuning} == {"P"}
    assert {row.identity.seed for row in tuning} == set(range(100, 110))
    assert sum(row.identity.method == "P" for row in final) == 690
    assert {
        row.identity.seed
        for row in final
        if row.identity.scenario_id == "S0_nominal_stochastic"
    } == set(range(1000, 1030))
    assert {
        row.identity.seed
        for row in final
        if row.identity.scenario_id == "S7_ood_asymmetric_limit"
    } == set(range(1000, 1050))
    first = smoke[0].identity
    assert first.run_id == stable_run_id(
        stage="smoke",
        revision="phase6-preregistered-v2",
        scenario_id=first.scenario_id,
        method_id=first.method,
        seed=first.seed,
    )


def test_subsets_are_smoke_only_and_final_tier_is_not_downgradable() -> None:
    paths = _paths()
    subset = build_run_plan(
        paths,
        stage="smoke",
        method_ids=("P",),
        scenario_ids=("S0_nominal_stochastic",),
        max_runs=1,
    )
    assert len(subset) == 1
    assert subset[0].identity.method == "P"
    assert subset[0].solver_tier == "DEBUG"

    with pytest.raises(ValueError, match="final runs forbid"):
        build_run_plan(paths, stage="final", method_ids=("P",))
    with pytest.raises(ValueError, match="tuning must cover"):
        build_run_plan(paths, stage="tuning", max_runs=1)
    with pytest.raises(ValueError, match="require the FINAL"):
        build_run_plan(paths, stage="final", solver_tier="DEBUG")


def test_tuning_and_final_worker_count_is_frozen_because_timeout_is_wall_time() -> None:
    assert validate_stage_worker_count("smoke", 1) == 1
    assert validate_stage_worker_count("smoke", 12) == 12
    assert validate_stage_worker_count("tuning", 4) == 4
    assert validate_stage_worker_count("final", 4) == 4
    with pytest.raises(ValueError, match="wall-time limits"):
        validate_stage_worker_count("tuning", 3)
    with pytest.raises(ValueError, match="wall-time limits"):
        validate_stage_worker_count("final", 8)


def test_method_routes_choose_only_native_k6_k4_or_labeled_factory() -> None:
    native = {
        "B0",
        "B1",
        "B2",
        "B3",
        "P",
        "no-worst",
        "no-OOD",
        "no-tightening",
        "no-transition-prior",
    }
    assert {library_kind_for_method(value) for value in native} == {"native_k6"}
    assert library_kind_for_method("fixed-K4-unlabeled") == "fixed_k4_unlabeled"
    assert library_kind_for_method("labeled-library") == "labeled_training_k4"
    assert library_kind_for_method("B4") == "labeled_training_k4"


def test_eval_only_component_mappings_and_diagnostic_qualifications(monkeypatch) -> None:
    paths = _paths()
    assert load_component_mapping_eval_only(paths, "native_k6") == {
        0: "derated",
        1: "derated",
        2: "unavailable",
        3: "nominal",
        4: "derated",
        5: "sluggish",
    }
    assert set(load_component_mapping_eval_only(paths, "fixed_k4_unlabeled")) == {
        0,
        1,
        2,
        3,
    }
    assert set(load_component_mapping_eval_only(paths, "labeled_training_k4")) == {
        0,
        1,
        2,
        3,
    }

    captured: list[dict[str, object]] = []

    def fake_make(**kwargs: object) -> object:
        captured.append(kwargs)
        return object()

    import d5freq.evaluation.closed_loop_diagnostics as diagnostics

    monkeypatch.setattr(diagnostics, "make_closed_loop_diagnostic_evaluator", fake_make)
    plans = {
        method: build_run_plan(
            paths,
            stage="smoke",
            method_ids=(method,),
            scenario_ids=("S0_nominal_stochastic",),
            max_runs=1,
        )[0]
        for method in ("B0", "B4", "P", "fixed-K4-unlabeled", "labeled-library")
    }
    for spec in plans.values():
        _diagnostic_evaluator(spec)

    by_method = dict(zip(plans, captured, strict=True))
    assert by_method["B0"]["diagnostic_qualification"] == "none"
    assert by_method["B0"]["component_to_semantic_eval_only"] is None
    assert by_method["B4"]["diagnostic_qualification"] == "truth_informed"
    assert by_method["B4"]["component_to_semantic_eval_only"] is None
    assert by_method["P"]["diagnostic_qualification"] == "runtime"
    assert len(by_method["P"]["component_to_semantic_eval_only"]) == 6
    assert len(
        by_method["fixed-K4-unlabeled"]["component_to_semantic_eval_only"]
    ) == 4
    assert len(by_method["labeled-library"]["component_to_semantic_eval_only"]) == 4


def test_metadata_evaluator_persists_compact_actual_solver_audit() -> None:
    @dataclass(frozen=True)
    class Metadata:
        method_id: str

    records = (
        {
            "solver_name": "CLARABEL",
            "solver_version": "0.11.0",
            "solver_outcome": "success",
            "solver_status": "optimal",
        },
        {
            "solver_name": "CLARABEL",
            "solver_version": "0.11.0",
            "solver_outcome": "timeout",
            "solver_status": "timeout",
        },
        {
            "solver_name": "SCS",
            "solver_version": "3.2.8",
            "solver_outcome": "inaccurate",
            "solver_status": "optimal_inaccurate",
        },
        {
            "solver_name": None,
            "solver_version": None,
            "solver_outcome": "error",
            "solver_status": "solver_error",
        },
        {
            "solver_name": None,
            "solver_version": None,
            "solver_outcome": "not_run",
            "solver_status": "not_run_recovery_hold",
        },
    )

    contribution = _metadata_evaluator(Metadata("P"))(
        SimpleNamespace(controller_records=records)
    )
    audit = contribution.artifacts["runtime_solver_audit"]

    assert audit == _runtime_solver_audit(records)
    assert audit["controller_record_count"] == 5
    assert audit["solver_attempt_count"] == 4
    assert audit["named_solver_attempt_count"] == 3
    assert audit["unnamed_solver_attempt_count"] == 1
    assert audit["solver_not_run_count"] == 1
    assert audit["solver_outcome_counts"] == {
        "error": 1,
        "inaccurate": 1,
        "not_run": 1,
        "success": 1,
        "timeout": 1,
    }
    assert [row["solver_name"] for row in audit["solver_invocations"]] == [
        "CLARABEL",
        "SCS",
    ]
    assert audit["solver_invocations"][0]["solver_version"] == "0.11.0"
    assert audit["solver_invocations"][0]["outcome_counts"] == {
        "success": 1,
        "timeout": 1,
    }


def test_metric_config_is_the_frozen_base_contract() -> None:
    config = build_metric_config(ROOT / "configs" / "base.yaml")
    assert config.nominal_frequency_hz == 50.0
    assert config.frequency_limit_hz == 0.5
    assert config.rocof_limit_hz_per_s == 0.5
    assert config.safety_frequency_limit_hz == 0.5
    assert config.settling_band_hz == 0.05
    assert (config.sg_command_min_pu, config.sg_command_max_pu) == (-0.12, 0.12)
    assert config.sg_slew_limit_pu_per_s == 0.02
    assert (config.ibr_command_min_pu, config.ibr_command_max_pu) == (-0.08, 0.08)
    assert config.ibr_slew_limit_pu_per_s == 0.04
    assert config.command_sample_period_s == 0.5


def test_simulator_private_loader_combines_known_and_held_out_truth_only() -> None:
    modes = load_simulator_private_modes_eval_only(_paths())
    assert set(modes) == {
        "nominal",
        "sluggish",
        "derated",
        "unavailable",
        "asymmetric_limit",
        "time_varying_delay",
    }
    assert modes["time_varying_delay"].delay_profile is not None

    protocol = load_frozen_phase6_protocol(_paths().experiments_config)
    assert responsibility_event_time_eval_only(
        protocol.build_scenario("S5_multi_switch_stochastic")
    ) == 45.0
    assert responsibility_event_time_eval_only(
        protocol.build_scenario("S1_step_pos_002")
    ) is None


def test_b1_selection_matches_experiments_logical_and_validation_hashes() -> None:
    paths = _paths()
    selection, train_sha, validation_sha = validate_b1_selection(paths)
    assert selection.protocol_sha256 == config_sha256(
        load_yaml(paths.experiments_config)
    )
    assert selection.selection_dataset_sha256 == validation_sha
    assert selection.selected_component_id == 3
    assert len(train_sha) == len(validation_sha) == 64


def test_final_lock_precedes_first_run_and_refuses_changed_resume(tmp_path) -> None:
    selection = tmp_path / "tuning_selection_record.json"
    selection.write_text("{}\n", encoding="utf-8")
    store = tmp_path / "per_run"
    store.mkdir()
    lock = tmp_path / "protocol_lock.json"
    material = {"configs": {"experiments": "a"}, "code": {"sha": "b"}}

    created = ensure_final_protocol_lock(
        lock_path=lock,
        run_store_root=store,
        tuning_selection_record_path=selection,
        material=material,
    )
    assert created == lock.resolve()
    ensure_final_protocol_lock(
        lock_path=lock,
        run_store_root=store,
        tuning_selection_record_path=selection,
        material=material,
    )
    (store / "one.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="protocol changed"):
        ensure_final_protocol_lock(
            lock_path=lock,
            run_store_root=store,
            tuning_selection_record_path=selection,
            material={"configs": {"experiments": "changed"}},
        )


def test_worker_setup_exception_writes_attempt_receipt_without_consuming_run_id(
    tmp_path,
) -> None:
    paths = _paths(tmp_path)
    missing_binding = tmp_path / "deliberately-missing-native-binding.json"
    paths = replace(paths, native_binding=missing_binding)
    spec = build_run_plan(
        paths,
        stage="smoke",
        method_ids=("P",),
        scenario_ids=("S0_nominal_stochastic",),
        max_runs=1,
    )[0]

    with pytest.raises(Phase6StageExecutionError, match="attempt receipt"):
        _execute_run_spec(spec)
    stored = PerRunExperimentStore(paths.run_store_root("smoke")).load(spec.identity)
    receipts = load_phase6_attempt_receipts(paths, "smoke")

    assert stored is None
    assert len(receipts) == 1
    assert receipts[0].body["failure_stage"] == "orchestration_setup"
    assert receipts[0].body["run_identity"] == spec.identity.to_dict()
    assert receipts[0].body["canonical_run_envelope_written"] is False
    assert receipts[0].body["retryable_without_consuming_run_id"] is True


def test_failed_attempt_remains_auditable_after_retry_completes_exact_plan(
    monkeypatch, tmp_path
) -> None:
    import d5freq.evaluation.phase6_experiments as experiments

    paths = _paths(tmp_path)
    specs = build_run_plan(
        paths,
        stage="smoke",
        method_ids=("P",),
        scenario_ids=("S0_nominal_stochastic",),
        max_runs=2,
    )

    def fail_first(spec, attempt_id):
        error = RuntimeError("injected pre-episode setup failure")
        write_phase6_attempt_receipt(
            paths=spec.paths,
            stage=spec.stage,
            attempt_id=attempt_id,
            failure_stage="orchestration_setup",
            origin="test_worker",
            error=error,
            spec=spec,
        )
        raise Phase6StageExecutionError(str(error))

    monkeypatch.setattr(experiments, "_execute_run_spec", fail_first)
    with pytest.raises(Phase6StageExecutionError, match="remains retryable"):
        execute_run_plan(specs, workers=1)
    assert not tuple(paths.run_store_root("smoke").glob("*.json"))
    failed_receipts = load_phase6_attempt_receipts(paths, "smoke")
    assert len(failed_receipts) == 1

    def succeed(spec, _attempt_id):
        result = EpisodeResult(
            run_id=spec.identity.run_id,
            scenario_id=spec.identity.scenario_id,
            method=spec.identity.method,
            seed=spec.identity.seed,
            run_completed=True,
            metrics_complete=True,
            freq_iae=1.0,
        )
        payload: dict[str, object] = {
            "provenance": dict(expected_provenance(spec))
        }
        _attach_test_journal(paths, spec, result, payload)
        stored = PerRunExperimentStore(paths.run_store_root("smoke")).save(
            spec.identity, result, payload
        )
        return WorkerRunReceipt(
            run_id=spec.identity.run_id,
            envelope_sha256=stored.sha256,
            resumed=False,
            scientific_success=True,
        )

    monkeypatch.setattr(experiments, "_execute_run_spec", succeed)
    executed = execute_run_plan(specs, workers=1)
    resumed = execute_run_plan(specs, workers=1)

    assert len(executed) == len(resumed) == len(specs) == 2
    assert all(receipt.resumed for receipt in resumed)
    assert len(verified_stage_runs(specs)) == len(specs)
    retained = load_phase6_attempt_receipts(paths, "smoke")
    assert [receipt.sha256 for receipt in retained] == [
        failed_receipts[0].sha256
    ]


def test_aggregate_csvs_are_rebuilt_only_from_verified_per_run_store(tmp_path) -> None:
    paths = _paths(tmp_path)
    native_library = tmp_path / "library.json"
    native_calibration = tmp_path / "calibration.json"
    native_ood_selection = tmp_path / "ood-selection.json"
    native_component_mapping = tmp_path / "component-mapping.json"
    native_binding = tmp_path / "binding.json"
    fixed_selection = tmp_path / "fixed-selection.json"
    for path, value in (
        (native_library, "library"),
        (native_calibration, "calibration"),
        (native_ood_selection, "ood-selection"),
        (native_component_mapping, "component-mapping"),
        (native_binding, "binding"),
        (fixed_selection, "selection"),
    ):
        path.write_text(value, encoding="utf-8")
    paths = replace(
        paths,
        native_library=native_library,
        native_calibration=native_calibration,
        native_ood_hysteresis_selection=native_ood_selection,
        native_component_mapping_eval_only=native_component_mapping,
        native_binding=native_binding,
        fixed_reference_selection=fixed_selection,
    )
    material = build_protocol_material(paths, include_tuning_selection=False)
    specs = build_run_plan(
        paths,
        stage="smoke",
        method_ids=("P",),
        scenario_ids=("S0_nominal_stochastic",),
        protocol_material=material,
    )
    store = PerRunExperimentStore(paths.run_store_root("smoke"))
    for ordinal, spec in enumerate(specs):
        if ordinal == 0:
            result = EpisodeResult(
                run_id=spec.identity.run_id,
                scenario_id=spec.identity.scenario_id,
                method=spec.identity.method,
                seed=spec.identity.seed,
                run_completed=True,
                metrics_complete=True,
                freq_iae=1.0,
            )
            payload = {
                "evaluation_artifacts": {
                    "evaluator_0": {
                        "controller_metadata": {
                            "method_id": "P",
                            "display_name": "SD-BMPC",
                            "evaluator_information_visible": False,
                            "online_adaptation": "soft belief",
                            "ood_policy": "fallback",
                            "solver_tier": "debug",
                            "eligible_for_final_solver_claims": False,
                            "library_artifact_id": "native_k6_discovered",
                            "library_construction_protocol": (
                                "discovered_bic_label_free"
                            ),
                            "library_file_sha256": "1" * 64,
                            "library_logical_sha256": "2" * 64,
                            "qualifications": ["solver_allowlist=CLARABEL"],
                        },
                        "runtime_solver_audit": dict(
                            _runtime_solver_audit(
                                (
                                    {
                                        "solver_name": "CLARABEL",
                                        "solver_version": "0.11.0",
                                        "solver_outcome": "success",
                                        "solver_status": "optimal",
                                    },
                                )
                            )
                        ),
                    }
                }
            }
        else:
            result = EpisodeResult.failed(
                run_id=spec.identity.run_id,
                scenario_id=spec.identity.scenario_id,
                method=spec.identity.method,
                seed=spec.identity.seed,
                failure_stage="simulator_reset",
                failure_type="RuntimeError",
                failure_message="injected simulator failure",
                catastrophic_not_recovered=True,
            )
            payload = {
                "evaluation_artifacts": {
                    "evaluator_0": {
                        "controller_metadata": {
                            "method_id": "P",
                            "display_name": "SD-BMPC",
                            "evaluator_information_visible": False,
                            "online_adaptation": "soft belief",
                            "ood_policy": "fallback",
                            "solver_tier": "debug",
                            "eligible_for_final_solver_claims": False,
                            "library_artifact_id": "native_k6_discovered",
                            "library_construction_protocol": (
                                "discovered_bic_label_free"
                            ),
                            "library_file_sha256": "1" * 64,
                            "library_logical_sha256": "2" * 64,
                            "qualifications": ["solver_allowlist=CLARABEL"],
                        },
                        "runtime_solver_audit": dict(_runtime_solver_audit(())),
                    }
                }
            }
        payload["provenance"] = dict(expected_provenance(spec))
        _attach_test_journal(paths, spec, result, payload)
        store.save(spec.identity, result, payload)

    metrics_path, ledger_path = refresh_stage_aggregates(
        specs, protocol_material=material
    )
    metrics = pd.read_csv(metrics_path)
    ledger = pd.read_csv(ledger_path)

    assert len(verified_stage_runs(specs)) == len(metrics) == len(ledger) == 2
    assert ledger["per_run_envelope_sha256"].str.len().eq(64).all()
    assert set(ledger["mode_library_file_sha256"]) == {sha256_file(native_library)}
    assert set(ledger["execution_artifact_state_sha256"]) == {
        protocol_material_sha256(material)
    }
    assert set(ledger["code_sha256"]) == {
        expected_provenance(specs[0])["code_sha256"]
    }
    assert metrics.loc[0, "freq_iae"] == 1.0
    assert pd.isna(metrics.loc[1, "freq_iae"])
    assert ledger["controller_metadata_status"].tolist() == [
        "verified",
        "verified",
    ]
    assert ledger["runtime_solver_audit_status"].tolist() == [
        "verified",
        "verified",
    ]
    assert ledger.loc[0, "runtime_solver_attempt_count"] == 1
    assert "CLARABEL" in ledger.loc[0, "runtime_solver_invocations_json"]
    assert ledger.loc[0, "display_name"] == "SD-BMPC"
    assert not bool(ledger.loc[0, "eligible_for_final_solver_claims"])
    assert "solver_allowlist=CLARABEL" in ledger.loc[0, "qualifications"]
    assert ledger.loc[1, "runtime_solver_attempt_count"] == 0
    assert "solver_allowlist=CLARABEL" in ledger.loc[1, "qualifications"]
    assert not bool(ledger.loc[1, "eligible_for_final_solver_claims"])
    assert ledger["canonical_decision_journal_sha256"].str.len().eq(64).all()
    assert set(ledger["canonical_decision_journal_compression"]) == {"zstd"}


def test_phase6_rejects_stale_envelope_at_every_resume_boundary(tmp_path) -> None:
    paths = _paths(tmp_path)
    material = build_protocol_material(paths, include_tuning_selection=False)
    spec = build_run_plan(
        paths,
        stage="smoke",
        method_ids=("P",),
        scenario_ids=("S0_nominal_stochastic",),
        max_runs=1,
        protocol_material=material,
    )[0]
    provenance = dict(expected_provenance(spec))
    assert provenance["artifact_state_sha256"] == protocol_material_sha256(
        material
    )
    assert provenance["protocol_material_sha256"] == provenance[
        "artifact_state_sha256"
    ]
    assert set(provenance["configs"]) >= {"experiments", "base", "mpc"}
    assert len(provenance["code_sha256"]) == 64
    provenance["code_sha256"] = "f" * 64
    result = EpisodeResult(
        run_id=spec.identity.run_id,
        scenario_id=spec.identity.scenario_id,
        method=spec.identity.method,
        seed=spec.identity.seed,
        run_completed=True,
        metrics_complete=True,
    )
    PerRunExperimentStore(paths.run_store_root("smoke")).save(
        spec.identity,
        result,
        {"provenance": provenance},
    )

    with pytest.raises(RunIntegrityError, match="provenance differs"):
        _execute_run_spec(spec)
    with pytest.raises(RunIntegrityError, match="provenance differs"):
        execute_run_plan((spec,), workers=1)
    with pytest.raises(RunIntegrityError, match="provenance differs"):
        verified_stage_runs((spec,))
    with pytest.raises(RunIntegrityError, match="provenance differs"):
        refresh_stage_aggregates((spec,), protocol_material=material)


def test_tuning_candidate_hash_changes_with_phase6_code(monkeypatch, tmp_path) -> None:
    binding = tmp_path / "binding.json"
    selection = tmp_path / "ood-selection.json"
    binding.write_text("binding", encoding="utf-8")
    selection.write_text("selection", encoding="utf-8")
    paths = replace(
        _paths(tmp_path),
        native_binding=binding,
        native_ood_hysteresis_selection=selection,
    )
    import d5freq.evaluation.phase6_experiments as experiments

    monkeypatch.setattr(experiments, "_code_manifest", lambda _paths: {"a.py": "1" * 64})
    first = frozen_tuning_candidate_sha256(paths)
    monkeypatch.setattr(experiments, "_code_manifest", lambda _paths: {"a.py": "2" * 64})
    second = frozen_tuning_candidate_sha256(paths)
    assert first != second


def test_cli_help_exposes_required_config_and_stage_interfaces() -> None:
    for script in (
        ROOT / "scripts" / "04_run_smoke_experiments.py",
        ROOT / "scripts" / "05_run_full_experiments.py",
    ):
        completed = subprocess.run(
            [sys.executable, str(script), "--help"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30.0,
        )
        assert "--config CONFIG" in completed.stdout
        assert "--stage" in completed.stdout
    assert resolve_repo_or_cwd_path(
        "configs/experiments.yaml", ROOT
    ) == (ROOT / "configs" / "experiments.yaml").resolve()


def test_tuning_selection_uses_exactly_210_p_rows_and_no_final_feedback(tmp_path) -> None:
    paths = _paths(tmp_path)
    protocol = load_frozen_phase6_protocol(paths.experiments_config)
    specs = build_run_plan(paths, stage="tuning")
    stored: list[StoredRun] = []
    for spec in specs:
        result = EpisodeResult(
            run_id=spec.identity.run_id,
            scenario_id=spec.identity.scenario_id,
            method="P",
            seed=spec.identity.seed,
            run_completed=True,
            metrics_complete=True,
            freq_iae=1.0,
            max_abs_freq_hz=0.1,
            solve_time_mean_s=0.01,
        )
        stored.append(
            StoredRun(
                identity=spec.identity,
                episode_result=result,
                run_payload={},
                sha256=f"{len(stored):064x}",
                path=tmp_path / f"{len(stored)}.json",
            )
        )
    destination = tmp_path / "selection.json"
    write_tuning_selection_record(
        path=destination,
        protocol=protocol,
        stored_runs=stored,
        experiments_logical_sha256=config_sha256(
            load_yaml(paths.experiments_config)
        ),
        resolved_candidate_sha256="a" * 64,
    )
    payload = json.loads(destination.read_text(encoding="utf-8"))

    assert payload["registered_run_count"] == 210
    assert payload["candidate_count"] == 1
    assert payload["selected_candidate_id"] == "phase5_carried_forward_P"
    assert payload["final_test_feedback_used"] is False
    assert payload["objective_values"]["catastrophic_failure_rate"] == 0.0
