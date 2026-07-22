from __future__ import annotations

import csv
from dataclasses import replace
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pandas as pd
import pytest

from d5freq.evaluation.experiment_store import PerRunExperimentStore, RunIdentity
from d5freq.evaluation.phase6_trajectory_export import (
    CanonicalRunEvidence,
    ReplayCapture,
    SelectedRun,
    build_selected_outputs,
)
from d5freq.evaluation.results_schema import EpisodeResult
from scripts.phase7_support import (
    FIGURE_SPECS,
    PACKAGE_ROOT_NAME,
    Phase7AuditError,
    RESULT_CSV_NAMES,
    ZIP_NAME,
    validate_selected_trajectory_manifest,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _load_script(filename: str, module_name: str):
    path = REPOSITORY_ROOT / "scripts" / filename
    specification = importlib.util.spec_from_file_location(module_name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[module_name] = module
    specification.loader.exec_module(module)
    return module


FIGURES = _load_script("06_make_figures.py", "d5freq_phase7_make_figures_test")
PACKAGE = _load_script(
    "07_build_review_package.py", "d5freq_phase7_build_review_package_test"
)


def _write(path: Path, content: str = "evidence\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="")


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame.from_records(rows).to_csv(path, index=False, lineterminator="\n")


def _git(repo: Path, *arguments: str) -> None:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_json(value: object) -> str:
    import json

    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _write_selected_manifest(
    *,
    directory: Path,
    results: Path,
    role: str,
    run_id: str,
    method: str,
    canonical_metrics: dict[str, object],
    canonical_envelope_sha256: str,
    trace_rows: list[dict[str, object]],
) -> None:
    run_directory = directory / run_id
    control = pd.DataFrame.from_records(trace_rows)
    high_frequency = control[
        ["time_s", "frequency_deviation_hz", "true_mode_eval_only", "method", "scenario_id", "seed"]
    ].copy()
    intervals = pd.DataFrame.from_records(
        [
            {
                "start_time_s": 0.0,
                "end_time_s": 1.0,
                "true_mode_eval_only": "nominal",
                "method": method,
                "scenario_id": "scenario",
                "seed": 1000,
            }
        ]
    )
    controller_records = control[
        ["time_s", "mode_belief", "ood_pvalue", "controller_state", "method", "scenario_id", "seed"]
    ].copy()
    tables = {
        "control_trajectory": control,
        "high_frequency_truth": high_frequency,
        "truth_intervals": intervals,
        "controller_records": controller_records,
    }
    files: dict[str, dict[str, object]] = {}
    for name, frame in tables.items():
        path = run_directory / f"{name}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False, compression="zstd")
        files[name] = {
            "relative_path": path.relative_to(directory).as_posix(),
            "sha256": _sha256(path),
            "row_count": len(frame),
            "compression": "zstd",
        }
    replay_body = {
        "identity": {
            "run_id": run_id,
            "scenario_id": "scenario",
            "method": method,
            "seed": 1000,
        },
        "episode_result": canonical_metrics,
        "run_payload": {},
    }
    replay_schema = "d5freq.per-run-envelope.v1"
    replay_sha = _sha256_json(
        {"schema_version": replay_schema, "body": replay_body}
    )
    replay_envelope = {
        "schema_version": replay_schema,
        "sha256": replay_sha,
        "body": replay_body,
    }
    replay_path = run_directory / "replay_envelope.json"
    _write(
        replay_path,
        __import__("json").dumps(replay_envelope, sort_keys=True, indent=2) + "\n",
    )
    payload = {
        "schema_version": "d5freq.selected_trajectory_manifest.v1",
        "hash_algorithm": "sha256",
        "episode_result_hash_serialization": "canonical JSON",
        "episode_result_hash_fields": list(canonical_metrics),
        "selection_policy": {"name": "deterministic tiny fixture", "rank": 1},
        "canonical_results": {
            "metrics": {
                "relative_path": "../per_episode_metrics.csv",
                "sha256": _sha256(results / "per_episode_metrics.csv"),
            },
            "ledger": {
                "relative_path": "../experiment_ledger.csv",
                "sha256": _sha256(results / "experiment_ledger.csv"),
            },
            "protocol_lock": {
                "relative_path": "../protocol_lock.json",
                "sha256": _sha256(results / "protocol_lock.json"),
            },
        },
        "entries": [
            {
                "run_id": run_id,
                "scenario_id": "scenario",
                "method": method,
                "seed": 1000,
                "selection_role": role,
                "selection_rank": 1,
                "selection_basis": "deterministic fixture rank",
                "canonical_envelope_sha256": canonical_envelope_sha256,
                "canonical_episode_result_sha256": _sha256_json(canonical_metrics),
                "canonical_episode_result": canonical_metrics,
                "canonical_metrics": canonical_metrics,
                "replay_envelope_relative_path": replay_path.relative_to(directory).as_posix(),
                "replay_envelope_sha256": replay_sha,
                "replay_envelope_file_sha256": _sha256(replay_path),
                "replay_episode_result_sha256": _sha256_json(canonical_metrics),
                "replay_consistency": {
                    "status": "verified",
                    "compared_fields": sorted(canonical_metrics),
                    "tolerances": {"absolute": 1e-12, "relative": 0.0},
                    "mismatches": [],
                },
                "canonical_store_consistency": {
                    "status": "verified",
                    "compared_fields": sorted(canonical_metrics),
                    "tolerances": {"absolute": 1e-12, "relative": 0.0},
                    "mismatches": [],
                },
                "files": files,
            }
        ],
    }
    _write(
        directory / "trajectory_manifest.json",
        __import__("json").dumps(payload, sort_keys=True, indent=2) + "\n",
    )


def _tiny_repo(tmp_path: Path) -> tuple[Path, Path, Path]:
    repo = tmp_path / "tiny_repo"
    _write(repo / "README.md", "# tiny auditable fixture\n")
    _write(repo / "pyproject.toml", "[project]\nname='tiny-d5'\nversion='0.0.0'\n")
    _write(repo / "environment.yml", "name: topo_sfr\ndependencies:\n  - python=3.11\n")
    _write(
        repo / "src" / "d5freq" / "controllers" / "sd_bmpc.py",
        "class SDBMPCController:\n    def act(self, measurement):\n        return measurement\n",
    )
    _write(repo / "src" / "d5freq" / "estimation" / "online_diagnostic.py")
    _write(repo / "src" / "d5freq" / "simulation" / "hybrid_simulator.py")
    _write(repo / "scripts" / "reproduce.py", "print('reproduce')\n")
    _write(repo / "research_docs" / "MATH_IMPLEMENTATION_MAP.md", "# Math map\n")
    _write(repo / "research_docs" / "METHOD.md", "# Method\n")
    _write(repo / "configs" / "base.yaml", "system:\n  f0_hz: 50.0\n")
    _write(repo / "configs" / "experiments.yaml", "protocol: tiny-test\n")
    _write(repo / "tests" / "test_fixture.py", "def test_fixture():\n    assert True\n")
    for phase in range(8):
        _write(
            repo / "progress" / f"PHASE_{phase}_REPORT.md",
            f"# Phase {phase}\n\n**Status:** PASS\n",
        )
    _write(repo / "progress" / "environment_phase0.json", '{"python":"3.11"}\n')

    reference_docs = repo / "original_reference_docs"
    for name in PACKAGE._REQUIRED_REFERENCE_DOCUMENTS:
        _write(reference_docs / name, f"# Original fixture: {name}\n")

    _write(
        repo / "artifacts" / "phase1" / "known_mode_step_responses.csv",
        "mode,time_s,p_ibr_pu\nnominal,0.0,0.0\nnominal,1.0,0.1\n",
    )

    mode_discovery = repo / "artifacts" / "mode_discovery"
    _write(mode_discovery / "mode_library.json", '{"component_count":6}\n')
    _write(
        mode_discovery / "bic_table.csv",
        "component_count,bic,selected\n1,10,false\n2,5,true\n",
    )
    pd.DataFrame.from_records(
        [
            {"standardized_feature_0": -1.0, "standardized_feature_1": -0.5, "component_id": 0},
            {"standardized_feature_0": -0.8, "standardized_feature_1": -0.2, "component_id": 0},
            {"standardized_feature_0": 0.8, "standardized_feature_1": 0.3, "component_id": 1},
            {"standardized_feature_0": 1.0, "standardized_feature_1": 0.6, "component_id": 1},
        ]
    ).to_parquet(mode_discovery / "episode_features.parquet", index=False, compression="zstd")
    for directory in (
        "online_diagnosis",
        "online_diagnosis_fixed_k4",
        "online_diagnosis_labeled",
    ):
        _write(
            repo / "artifacts" / directory / "ood_calibration_artifact.json",
            '{"calibration":"fixture"}\n',
        )
    _write(
        repo / "artifacts" / "phase6_library_ablations" / "build_manifest.json",
        '{"fixture":true}\n',
    )
    bindings = repo / "artifacts" / "phase6_library_bindings"
    for name in (
        "native_k6_discovered.json",
        "fixed_k4_unlabeled.json",
        "labeled_training_only_k4.json",
    ):
        _write(bindings / name, '{"binding":"fixture"}\n')

    results = repo / "results" / "final"
    episode_rows = [
        {
            "run_id": "run-p",
            "scenario_id": "scenario",
            "method": "P",
            "seed": 1000,
            "run_completed": True,
            "metrics_complete": True,
            "scientific_success": True,
            "freq_iae": 0.8,
            "catastrophic_failure": False,
            "solve_time_mean_s": 0.05,
            "detection_delay_s": 1.0,
            "failure_type": "",
            "wall_time_s": 2.0,
            "per_run_envelope_sha256": "a" * 64,
        },
        {
            "run_id": "run-b1",
            "scenario_id": "scenario",
            "method": "B1",
            "seed": 1000,
            "run_completed": False,
            "metrics_complete": False,
            "scientific_success": False,
            "freq_iae": 1.2,
            "catastrophic_failure": True,
            "solve_time_mean_s": 0.06,
            "detection_delay_s": "",
            "failure_type": "solver_timeout",
            "wall_time_s": 3.0,
            "per_run_envelope_sha256": "b" * 64,
        },
    ]
    _write_csv(results / "per_episode_metrics.csv", episode_rows)
    _write_csv(results / "experiment_ledger.csv", episode_rows)
    _write(results / "protocol_lock.json", '{"locked":true}\n')
    for name in RESULT_CSV_NAMES[1:-1]:
        _write_csv(results / name, [{"schema_version": "fixture", "metric": "freq_iae"}])

    trace_rows = [
        {
            "time_s": 0.0,
            "frequency_deviation_hz": 0.0,
            "u_sg_pu": 0.0,
            "u_ibr_pu": 0.0,
            "p_ibr_true_pu": 0.0,
            "mode_belief": "[0.8, 0.2]",
            "true_mode_eval_only": "nominal",
            "ood_pvalue": 0.9,
            "controller_state": "MPC",
            "method": "P",
            "scenario_id": "scenario",
            "seed": 1000,
        },
        {
            "time_s": 1.0,
            "frequency_deviation_hz": -0.2,
            "u_sg_pu": 0.03,
            "u_ibr_pu": 0.02,
            "p_ibr_true_pu": 0.018,
            "mode_belief": "[0.1, 0.9]",
            "true_mode_eval_only": "sluggish",
            "ood_pvalue": 0.01,
            "controller_state": "FALLBACK",
            "method": "P",
            "scenario_id": "scenario",
            "seed": 1000,
        },
    ]
    representative = results / "representative_trajectories"
    worst = results / "worst_failure_cases"
    _write_selected_manifest(
        directory=representative,
        results=results,
        role="representative",
        run_id="run-p",
        method="P",
        canonical_metrics={"freq_iae": 0.8, "run_completed": True},
        canonical_envelope_sha256="a" * 64,
        trace_rows=trace_rows,
    )
    worst_rows = [dict(row) for row in trace_rows]
    worst_rows[-1]["frequency_deviation_hz"] = -0.7
    for row in worst_rows:
        row["method"] = "B1"
    _write_selected_manifest(
        directory=worst,
        results=results,
        role="worst_failure",
        run_id="run-b1",
        method="B1",
        canonical_metrics={"freq_iae": 1.2, "run_completed": False},
        canonical_envelope_sha256="b" * 64,
        trace_rows=worst_rows,
    )

    _write(repo / "logs" / "pytest_final.txt", "1 passed, 0 failed\n")
    _write(
        repo / "logs" / "pytest_final.xml",
        '<?xml version="1.0"?><testsuites tests="1" failures="0" errors="0" skipped="0"><testsuite tests="1" failures="0" errors="0" skipped="0"/></testsuites>\n',
    )

    # These deliberately dangerous/cache files must never enter the package.
    _write(repo / "src" / ".pytest_cache" / "cache.txt", "cache\n")
    _write(repo / "src" / "private_secret.key", "not a real key\n")
    _write(repo / "scripts" / "mosek.lic", "not a real license\n")
    _write(repo / ".venv" / "environment.bin", "environment\n")

    figures = repo / "results" / "phase7" / "figures"
    FIGURES.make_figures(
        repo_root=repo,
        results_dir=results,
        figures_dir=figures,
        representative_dir=representative,
        worst_dir=worst,
        strict_audit=False,
    )

    _git(repo, "init")
    _git(repo, "config", "user.email", "phase7-test@example.invalid")
    _git(repo, "config", "user.name", "Phase 7 Test")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "tiny fixture")
    return repo, results, figures


def _exporter_backed_evidence(repo: Path) -> tuple[Path, Path]:
    """Build a full frozen selection through the real exporter and plotter."""

    results = repo / "results" / "exporter_integration"
    results.mkdir(parents=True)
    canonical_store = PerRunExperimentStore(results / "_canonical_store")
    replay_store = PerRunExperimentStore(results / "_replay_store")

    representative_specs = [
        ("S2_sluggish_switch_060", method, 1000, "representative_known")
        for method in ("B0", "B1", "B2", "B3", "B4", "P")
    ] + [
        ("S7_ood_asymmetric_limit", method, 1001, "representative_ood")
        for method in ("B1", "B3", "P", "no-OOD")
    ]
    worst_specs = [
        (f"S9_extreme_{index}", method, 2000 + index, "worst_failure")
        for index, method in enumerate(("B0", "B1", "P"))
    ]
    all_specs = [*representative_specs, *worst_specs]

    canonical_runs: dict[str, object] = {}
    captures: dict[str, ReplayCapture] = {}
    results_by_run: dict[str, EpisodeResult] = {}
    for ordinal, (scenario_id, method, seed, role) in enumerate(all_specs):
        run_id = f"{scenario_id}--{method}--{seed}"
        identity = RunIdentity(run_id, scenario_id, method, seed)
        catastrophic = role == "worst_failure"
        result = EpisodeResult(
            run_id=run_id,
            scenario_id=scenario_id,
            method=method,
            seed=seed,
            run_completed=True,
            metrics_complete=True,
            failure_stage="evaluation" if catastrophic else None,
            failure_type="safety_boundary" if catastrophic else None,
            failure_message="fixture catastrophic boundary" if catastrophic else None,
            catastrophic_safety_boundary=catastrophic,
            max_abs_freq_hz=(0.8 + ordinal / 100.0 if catastrophic else 0.1 + ordinal / 100.0),
            freq_iae=0.5 + ordinal / 10.0,
            detection_delay_s=0.2 + ordinal / 100.0,
            solve_time_mean_s=0.01 + ordinal / 10000.0,
            solve_time_p95_s=0.02 + ordinal / 10000.0,
            solve_time_max_s=0.03 + ordinal / 10000.0,
            wall_time_s=1.0 + ordinal / 10.0,
        )
        canonical = canonical_store.save(
            identity,
            result,
            {"provenance": {"fixture": "exporter-to-package"}},
        )
        replay_result = replace(result, wall_time_s=100.0 + ordinal)
        replay = replay_store.save(
            identity,
            replay_result,
            {"provenance": {"fixture": "exporter-to-package-replay"}},
        )
        peak = -float(result.max_abs_freq_hz or 0.0)
        is_ood = scenario_id == "S7_ood_asymmetric_limit"
        control = (
            {
                "time_s": 0.0,
                "frequency_deviation_hz": 0.0,
                "u_sg_pu": 0.0,
                "u_ibr_pu": 0.0,
                "p_ibr_true_pu": 0.0,
                "mode_belief": [0.9, 0.1],
                "ood_pvalue": 0.8,
                "controller_state": "MPC",
            },
            {
                "time_s": 1.0,
                "frequency_deviation_hz": peak,
                "u_sg_pu": 0.03,
                "u_ibr_pu": 0.02,
                "p_ibr_true_pu": 0.018,
                "mode_belief": [0.1, 0.9],
                "ood_pvalue": 0.01 if is_ood else 0.7,
                "controller_state": "FALLBACK" if is_ood or catastrophic else "MPC",
            },
        )
        high_frequency = (
            {"time_s": 0.0, "omega_pu": 0.0, "true_mode_eval_only": "nominal"},
            {
                "time_s": 1.0,
                "omega_pu": peak / 50.0,
                "true_mode_eval_only": "ood" if is_ood else "sluggish",
            },
        )
        intervals = (
            {
                "start_time_s": 0.0,
                "end_time_s": 1.0,
                "true_mode_eval_only": "nominal",
            },
            {
                "start_time_s": 1.0,
                "end_time_s": 2.0,
                "true_mode_eval_only": "ood" if is_ood else "sluggish",
            },
        )
        controller_records = tuple(
            {
                "time_s": row["time_s"],
                "mode_belief": row["mode_belief"],
                "ood_pvalue": row["ood_pvalue"],
                "controller_state": row["controller_state"],
            }
            for row in control
        )
        canonical_runs[run_id] = canonical
        captures[run_id] = ReplayCapture(
            stored_run=replay,
            episode_result=replay_result,
            control_trajectory=control,
            high_frequency_truth=high_frequency,
            truth_intervals=intervals,
            controller_records=controller_records,
        )
        results_by_run[run_id] = result

    metrics = pd.DataFrame.from_records(
        [result.to_row() for result in results_by_run.values()]
    )
    ledger = metrics.copy()
    ledger["per_run_envelope_sha256"] = [
        canonical_runs[str(run_id)].sha256 for run_id in ledger["run_id"]
    ]
    metrics.to_csv(results / "per_episode_metrics.csv", index=False, lineterminator="\n")
    ledger.to_csv(results / "experiment_ledger.csv", index=False, lineterminator="\n")
    _write(results / "protocol_lock.json", '{"locked":true}\n')
    for name in RESULT_CSV_NAMES[1:-1]:
        _write_csv(results / name, [{"schema_version": "fixture", "metric": "freq_iae"}])

    metric_rows = {str(row["run_id"]): row for row in metrics.to_dict("records")}
    ledger_rows = {str(row["run_id"]): row for row in ledger.to_dict("records")}
    representative = tuple(
        SelectedRun(
            run_id=f"{scenario_id}--{method}--{seed}",
            scenario_id=scenario_id,
            method=method,
            seed=seed,
            selection_role=role,
            selection_rank=rank,
            selection_basis="frozen exporter integration fixture",
        )
        for rank, (scenario_id, method, seed, role) in enumerate(
            representative_specs, start=1
        )
    )
    worst = tuple(
        SelectedRun(
            run_id=f"{scenario_id}--{method}--{seed}",
            scenario_id=scenario_id,
            method=method,
            seed=seed,
            selection_role="worst_failure",
            selection_rank=rank,
            selection_basis="retained catastrophic exporter integration fixture",
        )
        for rank, (scenario_id, method, seed, _) in enumerate(worst_specs, start=1)
    )

    def canonical_provider(selection: SelectedRun) -> CanonicalRunEvidence:
        return CanonicalRunEvidence(
            stored_run=canonical_runs[selection.run_id],
            metrics=metric_rows[selection.run_id],
            ledger=ledger_rows[selection.run_id],
        )

    long_staging_root = (
        repo / "results" / "exporter_integration_staging_long_path"
    )
    representative_manifest, worst_manifest = build_selected_outputs(
        results_dir=results,
        metrics_frame=metrics,
        ledger_frame=ledger,
        representative=representative,
        worst=worst,
        canonical_provider=canonical_provider,
        replay_provider=lambda selection, _: captures[selection.run_id],
        staging_root=long_staging_root,
    )
    os.replace(
        representative_manifest.parent, results / "representative_trajectories"
    )
    os.replace(worst_manifest.parent, results / "worst_failure_cases")
    long_staging_root.rmdir()
    validate_selected_trajectory_manifest(
        results / "representative_trajectories",
        results_dir=results,
        expected_role="representative",
        enforce_frozen_selection=True,
    )
    validate_selected_trajectory_manifest(
        results / "worst_failure_cases",
        results_dir=results,
        expected_role="worst",
        enforce_frozen_selection=True,
    )

    figures = repo / "results" / "phase7" / "exporter_figures"
    FIGURES.make_figures(
        repo_root=repo,
        results_dir=results,
        figures_dir=figures,
        representative_dir=results / "representative_trajectories",
        worst_dir=results / "worst_failure_cases",
        strict_audit=True,
    )
    return results, figures


@pytest.fixture()
def tiny_repo(tmp_path: Path) -> tuple[Path, Path, Path]:
    return _tiny_repo(tmp_path)


def _build(
    repo: Path,
    results: Path,
    figures: Path,
    output: Path,
    **kwargs: object,
):
    strict_audit = bool(kwargs.pop("strict_audit", False))
    return PACKAGE.build_review_package(
        repo_root=repo,
        reference_docs=repo / "original_reference_docs",
        results_dir=results,
        figures_dir=figures,
        output=output,
        representative_dir=results / "representative_trajectories",
        worst_dir=results / "worst_failure_cases",
        pytest_text=repo / "logs" / "pytest_final.txt",
        pytest_junit=repo / "logs" / "pytest_final.xml",
        strict_audit=strict_audit,
        **kwargs,
    )


def test_figure_builder_emits_all_required_classes_and_audits_missing_data(
    tiny_repo: tuple[Path, Path, Path],
) -> None:
    _, _, figures = tiny_repo
    with (figures / "figure_manifest.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["filename"] for row in rows] == [name for name, _ in FIGURE_SPECS]
    assert all((figures / row["filename"]).is_file() for row in rows)
    assert all(
        hashlib.sha256((figures / row["filename"]).read_bytes()).hexdigest()
        == row["figure_sha256"]
        for row in rows
    )
    # The hand-written tiny manifest intentionally lacks the frozen scenarios
    # and full method comparison.  Missing evidence must remain explicit.
    assert any(row["status"] in {"partial", "not_available"} for row in rows)
    assert any(row["missing_fields"] for row in rows)


def test_review_zip_structure_hashes_index_exclusions_size_and_determinism(
    tiny_repo: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    repo, results, figures = tiny_repo
    first = _build(repo, results, figures, tmp_path / "out-one")
    second = _build(repo, results, figures, tmp_path / "out-two")
    assert first.zip_path.name == ZIP_NAME
    assert first.size_bytes < 512 * 1024 * 1024
    assert first.sha256 == second.sha256
    assert first.zip_path.read_bytes() == second.zip_path.read_bytes()

    with zipfile.ZipFile(first.zip_path) as archive:
        names = archive.namelist()
        assert names == sorted(names)
        assert all(name.startswith(f"{PACKAGE_ROOT_NAME}/") for name in names)
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist())
        file_names = {info.filename for info in archive.infolist() if not info.is_dir()}
        prefix = f"{PACKAGE_ROOT_NAME}/"
        for required in (
            "00_EXECUTIVE_SUMMARY.md",
            "01_RESEARCH_CLAIMS_AND_STATUS.md",
            "02_MATH_IMPLEMENTATION_MAP.md",
            "03_REPRODUCIBILITY_COMMANDS.md",
            "04_LIMITATIONS_AND_FAILURES.md",
            "05_FILE_INDEX.csv",
            "06_SHA256SUMS.txt",
            *[f"results/{name}" for name in RESULT_CSV_NAMES],
            "git/commit.txt",
            "git/status.txt",
            "git/diff.patch",
            "logs/pytest.txt",
            "logs/pytest_junit.xml",
        ):
            assert prefix + required in file_names
        lowered = "\n".join(file_names).lower()
        assert ".git/" not in lowered
        assert ".pytest_cache" not in lowered
        assert ".venv" not in lowered
        assert "private_secret.key" not in lowered
        assert "mosek.lic" not in lowered
        assert "per_run" not in lowered

        index_text = archive.read(prefix + "05_FILE_INDEX.csv").decode("utf-8")
        index_rows = list(csv.DictReader(index_text.splitlines()))
        indexed = {prefix + row["relative_path"] for row in index_rows}
        assert indexed == file_names
        by_path = {row["relative_path"]: row for row in index_rows}
        for relative, row in by_path.items():
            if relative in {"05_FILE_INDEX.csv", "06_SHA256SUMS.txt"}:
                assert row["sha256"].startswith("SELF_REFERENTIAL_EXCLUDED")
            else:
                assert hashlib.sha256(archive.read(prefix + relative)).hexdigest() == row["sha256"]
        sums = archive.read(prefix + "06_SHA256SUMS.txt").decode("utf-8")
        assert "self-reference" in sums.lower()
        assert "05_FILE_INDEX.csv" not in [
            line.split("  ", 1)[-1]
            for line in sums.splitlines()
            if line and not line.startswith("#")
        ]
        summary = archive.read(prefix + "00_EXECUTIVE_SUMMARY.md").decode("utf-8")
        match = __import__("re").search(r"固定宽度）：(\d{20})", summary)
        assert match is not None
        assert int(match.group(1)) == first.size_bytes


def test_review_builder_rejects_missing_required_result_and_oversize_gate(
    tiny_repo: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    repo, results, figures = tiny_repo
    missing = results / "summary_metrics.csv"
    saved = missing.read_bytes()
    missing.unlink()
    with pytest.raises(Phase7AuditError, match="required file is missing"):
        _build(repo, results, figures, tmp_path / "missing")
    missing.write_bytes(saved)

    output = tmp_path / "too-small-limit"
    with pytest.raises(Phase7AuditError, match="protocol requires"):
        _build(repo, results, figures, output, max_zip_bytes=10)
    assert not (output / ZIP_NAME).exists()


def test_real_exporter_to_figures_to_package_relocates_and_reauthenticates_sources(
    tiny_repo: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    repo, _, _ = tiny_repo
    results, figures = _exporter_backed_evidence(repo)
    built = _build(repo, results, figures, tmp_path / "exporter-package")

    with zipfile.ZipFile(built.zip_path) as archive:
        prefix = f"{PACKAGE_ROOT_NAME}/"
        file_names = {
            info.filename for info in archive.infolist() if not info.is_dir()
        }
        representative_manifest = json.loads(
            archive.read(prefix + "representative_trajectories/trajectory_manifest.json")
        )
        worst_manifest = json.loads(
            archive.read(prefix + "worst_failure_cases/trajectory_manifest.json")
        )
        for manifest in (representative_manifest, worst_manifest):
            canonical = manifest["canonical_results"]
            assert canonical["metrics"]["relative_path"] == "../results/per_episode_metrics.csv"
            assert canonical["ledger"]["relative_path"] == "../results/experiment_ledger.csv"
            assert canonical["protocol_lock"]["relative_path"] == "../results/protocol_lock.json"
        assert len(representative_manifest["entries"]) == 10
        assert len(worst_manifest["entries"]) == 3

        figure_rows = list(
            csv.DictReader(
                archive.read(prefix + "figures/figure_manifest.csv")
                .decode("utf-8")
                .splitlines()
            )
        )
        assert all(row["status"] == "available" for row in figure_rows)
        for row in figure_rows:
            sources = [value for value in row["data_sources"].split(";") if value]
            hashes = [value for value in row["data_source_sha256"].split(";") if value]
            assert len(sources) == len(hashes)
            for source, source_hash in zip(sources, hashes, strict=True):
                recorded_path, digest = source_hash.rsplit("=", 1)
                assert recorded_path == source
                member = prefix + source
                assert member in file_names
                assert hashlib.sha256(archive.read(member)).hexdigest() == digest

        assert prefix + "research_docs/phase_reports/PHASE_7_REPORT.md" in file_names
        for name in PACKAGE._REQUIRED_REFERENCE_DOCUMENTS:
            assert (
                prefix + f"research_docs/original_project_spec/{name}"
                in file_names
            )


def test_review_builder_rejects_tampered_figure_source_and_missing_reference_doc(
    tiny_repo: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    repo, results, figures = tiny_repo
    source = repo / "artifacts" / "phase1" / "known_mode_step_responses.csv"
    source.write_text(source.read_text(encoding="utf-8") + "nominal,2.0,0.2\n", encoding="utf-8")
    with pytest.raises(Phase7AuditError, match="figure source SHA256 mismatch"):
        _build(repo, results, figures, tmp_path / "tampered-source")

    missing_reference = repo / "original_reference_docs" / "CODEX_GOAL.md"
    missing_reference.unlink()
    with pytest.raises(Phase7AuditError, match="original project specification"):
        _build(repo, results, figures, tmp_path / "missing-reference")


def test_figure_builder_rejects_authenticated_trace_identity_mismatch(
    tiny_repo: tuple[Path, Path, Path]
) -> None:
    repo, results, _ = tiny_repo
    representative = results / "representative_trajectories"
    manifest_path = representative / "trajectory_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    record = manifest["entries"][0]["files"]["control_trajectory"]
    trace_path = representative / record["relative_path"]
    trace = pd.read_parquet(trace_path)
    trace["method"] = "B4"
    trace.to_parquet(trace_path, index=False, compression="zstd")
    record["sha256"] = _sha256(trace_path)
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )

    with pytest.raises(Phase7AuditError, match="method disagrees"):
        FIGURES.make_figures(
            repo_root=repo,
            results_dir=results,
            figures_dir=repo / "results" / "phase7" / "identity_mismatch",
            representative_dir=representative,
            worst_dir=results / "worst_failure_cases",
            strict_audit=False,
        )


def test_production_audit_rejects_non_8280_fixture_and_boolean_rates_are_observed(
    tiny_repo: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    repo, results, figures = tiny_repo
    with pytest.raises(
        Phase7AuditError, match="complete Phase-6 final matrix validation failed"
    ):
        _build(
            repo,
            results,
            figures,
            tmp_path / "production-gate",
            strict_audit=True,
        )
    assert PACKAGE._observed_method_boolean_rate(
        [
            {"method": "P", "catastrophic_failure": "False"},
            {"method": "P", "catastrophic_failure": "True"},
            {"method": "B1", "catastrophic_failure": "True"},
        ],
        "P",
        "catastrophic_failure",
    ) == (0.5, 2)
