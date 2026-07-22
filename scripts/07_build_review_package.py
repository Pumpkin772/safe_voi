"""Build the single deterministic, auditable Phase-7 review ZIP.

Only explicitly selected final evidence enters the archive.  The enormous
per-run store is never copied; full-rate data are accepted only from the
representative and worst-case selections.  Missing mandatory evidence is a
hard error rather than a cue to manufacture a placeholder result.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from typing import Any, Iterable, Mapping, Sequence

try:  # Direct script execution.
    from phase7_support import (
        FIGURE_SPECS,
        MAX_ZIP_BYTES,
        PACKAGE_ROOT_NAME,
        Phase7AuditError,
        REQUIRED_PACKAGE_DIRECTORIES,
        REQUIRED_TOP_LEVEL_DOCUMENTS,
        RESULT_CSV_NAMES,
        ZIP_NAME,
        atomic_write_csv,
        atomic_write_json,
        atomic_write_text,
        collect_regular_files,
        copy_file_strict,
        copy_tree_strict,
        find_first_file,
        parse_bool,
        parse_float,
        read_csv_rows,
        relocate_selected_trajectory_manifest,
        require_file,
        require_nonempty_directory,
        resolved,
        sha256_file,
        validate_result_identity,
        validate_selected_trajectory_manifest,
        verify_no_forbidden_packaged_paths,
    )
except ImportError:  # Imported as scripts.07_build_review_package.
    from scripts.phase7_support import (  # type: ignore[no-redef]
        FIGURE_SPECS,
        MAX_ZIP_BYTES,
        PACKAGE_ROOT_NAME,
        Phase7AuditError,
        REQUIRED_PACKAGE_DIRECTORIES,
        REQUIRED_TOP_LEVEL_DOCUMENTS,
        RESULT_CSV_NAMES,
        ZIP_NAME,
        atomic_write_csv,
        atomic_write_json,
        atomic_write_text,
        collect_regular_files,
        copy_file_strict,
        copy_tree_strict,
        find_first_file,
        parse_bool,
        parse_float,
        read_csv_rows,
        relocate_selected_trajectory_manifest,
        require_file,
        require_nonempty_directory,
        resolved,
        sha256_file,
        validate_result_identity,
        validate_selected_trajectory_manifest,
        verify_no_forbidden_packaged_paths,
    )


_ZIP_SIZE_TOKEN = "00000000000000000000"
_INDEX_SELF_SENTINEL = "SELF_REFERENTIAL_EXCLUDED_SEE_HASH_POLICY"
_INDEX_EXCLUDED = frozenset({"05_FILE_INDEX.csv", "06_SHA256SUMS.txt"})
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)

_REQUIRED_REFERENCE_DOCUMENTS: tuple[str, ...] = (
    "00_PROJECT_OVERVIEW.md",
    "01_PROJECT_PLAN.md",
    "02_SCIENTIFIC_PROBLEM_AND_SCOPE.md",
    "03_FULL_MATHEMATICAL_DERIVATION.md",
    "04_OFFLINE_MODE_DISCOVERY_SPEC.md",
    "05_ONLINE_DIAGNOSIS_AND_OOD_SPEC.md",
    "06_SD_BMPC_CONTROL_SPEC.md",
    "07_SOFTWARE_ARCHITECTURE_AND_APIS.md",
    "08_EXPERIMENT_MATRIX_AND_METRICS.md",
    "09_TESTS_ACCEPTANCE_AND_REPRODUCIBILITY.md",
    "10_PAPER_OUTLINE_AND_CLAIMS.md",
    "11_REVIEW_PACKAGE_SPEC.md",
    "12_LITERATURE_POSITIONING.md",
    "CODEX_GOAL.md",
)

_OOD_ROOTS: tuple[tuple[str, str], ...] = (
    ("native_k6", "online_diagnosis"),
    ("fixed_k4_unlabeled", "online_diagnosis_fixed_k4"),
    ("labeled_training_k4", "online_diagnosis_labeled"),
)
_OOD_ROOT_FILE_ALLOWLIST = frozenset(
    {
        "artifact_manifest.json",
        "artifact_manifest.sha256",
        "component_reference_mapping_eval_only.json",
        "epsilon_sensitivity.csv",
        "ood_calibration_artifact.json",
        "ood_calibration_residuals.parquet",
        "ood_hysteresis_known_only_cv.csv",
        "ood_hysteresis_selection.json",
        "phase4_metrics.json",
        "phase4_summary.json",
        "reliability_bins.csv",
        "reproducibility_provenance.json",
        "resolved_phase4_config.yaml",
        "runtime_diagnostics_manifest.json",
        "scenario_mode_metrics.csv",
        "split_integrity.json",
    }
)


@dataclass(frozen=True, slots=True)
class ReviewPackageResult:
    zip_path: Path
    size_bytes: int
    sha256: str
    file_count: int
    episode_count: int
    pytest_passed: int | None
    pytest_failed: int | None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the strict single-file Phase-7 review package."
    )
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--results-dir", type=Path, default=Path("results/final")
    )
    parser.add_argument(
        "--figures-dir", type=Path, default=Path("results/phase7/figures")
    )
    parser.add_argument(
        "--reference-docs",
        type=Path,
        required=True,
        help=(
            "original supplied project-specification directory containing "
            "00_PROJECT_OVERVIEW.md through 12_LITERATURE_POSITIONING.md and "
            "CODEX_GOAL.md"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(ZIP_NAME),
        help="the fixed ZIP filename, or a directory in which to publish it",
    )
    parser.add_argument("--representative-dir", type=Path, default=None)
    parser.add_argument("--worst-dir", type=Path, default=None)
    parser.add_argument("--pytest-text", type=Path, default=None)
    parser.add_argument("--pytest-junit", type=Path, default=None)
    return parser


def _repo_relative(path: Path, repo_root: Path) -> Path:
    return path if path.is_absolute() else repo_root / path


def _resolve_output(path: Path, repo_root: Path) -> Path:
    candidate = _repo_relative(path, repo_root)
    if candidate.suffix.lower() == ".zip":
        if candidate.name != ZIP_NAME:
            raise Phase7AuditError(
                f"review package filename is fixed by the protocol: {ZIP_NAME}"
            )
        return candidate.resolve()
    return (candidate / ZIP_NAME).resolve()


def _require_repository_inputs(repo_root: Path) -> None:
    for directory in ("src", "scripts", "research_docs", "configs", "tests", "progress"):
        require_nonempty_directory(repo_root / directory, f"repository {directory}/")
    for name in ("README.md", "pyproject.toml", "environment.yml"):
        require_file(repo_root / name, f"repository {name}")
    require_file(
        repo_root / "research_docs" / "MATH_IMPLEMENTATION_MAP.md",
        "mathematics-to-code implementation map",
    )
    for phase in range(8):
        require_file(
            repo_root / "progress" / f"PHASE_{phase}_REPORT.md",
            f"Phase {phase} report",
        )
    proposed = require_file(
        repo_root / "src" / "d5freq" / "controllers" / "sd_bmpc.py",
        "proposed-controller source",
    )
    if re.search(r"\btrue_mode\w*\b", proposed.read_text(encoding="utf-8")):
        raise Phase7AuditError(
            "proposed-controller source contains a true-mode identifier; runtime truth isolation cannot be claimed"
        )


def _require_reference_documents(reference_docs: Path) -> Path:
    root = resolved(reference_docs)
    require_nonempty_directory(root, "original project specification directory")
    for name in _REQUIRED_REFERENCE_DOCUMENTS:
        require_file(root / name, f"original project specification {name}")
    return root


def _validate_figure_manifest(
    figures_dir: Path,
    *,
    source_root: Path,
    require_all_available: bool,
) -> None:
    source_root = resolved(source_root)
    manifest = require_file(figures_dir / "figure_manifest.csv", "figure manifest")
    rows = read_csv_rows(manifest)
    by_name = {row.get("filename", ""): row for row in rows}
    if len(rows) != len(FIGURE_SPECS) or len(by_name) != len(FIGURE_SPECS):
        raise Phase7AuditError(
            "figure_manifest.csv must contain exactly one row for each of the twelve required figures"
        )
    expected = {name for name, _ in FIGURE_SPECS}
    if set(by_name) != expected:
        raise Phase7AuditError(
            f"figure manifest names differ from required set; missing={sorted(expected - set(by_name))}, extra={sorted(set(by_name) - expected)}"
        )
    for name in sorted(expected):
        figure = require_file(figures_dir / name, f"required figure {name}")
        recorded = by_name[name].get("figure_sha256", "")
        if recorded != sha256_file(figure):
            raise Phase7AuditError(f"figure hash mismatch for {name}")
        if by_name[name].get("status") not in {"available", "partial", "not_available"}:
            raise Phase7AuditError(f"invalid availability status for figure {name}")
        if require_all_available and by_name[name].get("status") != "available":
            raise Phase7AuditError(
                f"complete final evidence requires figure {name} to be available; "
                f"observed={by_name[name].get('status')!r}"
            )
        if not by_name[name].get("data_sources") and by_name[name].get("status") == "available":
            raise Phase7AuditError(f"available figure has no traceable data source: {name}")
        source_values = [
            value for value in by_name[name].get("data_sources", "").split(";") if value
        ]
        hash_values = [
            value
            for value in by_name[name].get("data_source_sha256", "").split(";")
            if value
        ]
        if len(source_values) != len(hash_values):
            raise Phase7AuditError(
                f"figure source/hash cardinality mismatch for {name}"
            )
        for source_value, hash_value in zip(source_values, hash_values, strict=True):
            if "=" not in hash_value:
                raise Phase7AuditError(f"malformed figure source hash for {name}")
            hash_path, digest = hash_value.rsplit("=", 1)
            if hash_path != source_value or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise Phase7AuditError(f"malformed figure source hash for {name}")
            relative = Path(source_value)
            if relative.is_absolute():
                raise Phase7AuditError(
                    f"figure source path must be package/repository relative: {source_value}"
                )
            source = (source_root / relative).resolve()
            try:
                source.relative_to(source_root)
            except ValueError as exc:
                raise Phase7AuditError(
                    f"figure source escapes its root: {source_value}"
                ) from exc
            require_file(source, f"figure source for {name}")
            if sha256_file(source) != digest:
                raise Phase7AuditError(
                    f"figure source SHA256 mismatch for {name}: {source_value}"
                )


def _validate_artifact_inputs(repo_root: Path) -> None:
    require_file(
        repo_root / "artifacts" / "phase1" / "known_mode_step_responses.csv",
        "Phase-1 hidden-mode truth response table",
    )
    require_nonempty_directory(
        repo_root / "artifacts" / "mode_discovery", "mode-discovery artifacts"
    )
    require_file(
        repo_root / "artifacts" / "mode_discovery" / "mode_library.json",
        "native K=6 mode library",
    )
    for label, source_name in _OOD_ROOTS:
        require_file(
            repo_root / "artifacts" / source_name / "ood_calibration_artifact.json",
            f"{label} OOD calibration artifact",
        )
    require_nonempty_directory(
        repo_root / "artifacts" / "phase6_library_ablations",
        "Phase-6 library artifacts",
    )
    bindings = require_nonempty_directory(
        repo_root / "artifacts" / "phase6_library_bindings",
        "Phase-6 library bindings",
    )
    for name in (
        "native_k6_discovered.json",
        "fixed_k4_unlabeled.json",
        "labeled_training_only_k4.json",
    ):
        require_file(bindings / name, f"library binding {name}")


def _validate_trajectory_export_audit(
    results_dir: Path, representative_dir: Path, worst_dir: Path
) -> None:
    path = require_file(
        results_dir / "trajectory_export_audit.json",
        "successful selected-trajectory export audit",
    )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise Phase7AuditError("selected-trajectory export audit is invalid JSON") from exc
    if not isinstance(payload, Mapping) or payload.get("status") != "success":
        raise Phase7AuditError("selected-trajectory export audit did not report success")
    expected = {
        "representative_manifest_sha256": sha256_file(
            representative_dir / "trajectory_manifest.json"
        ),
        "worst_manifest_sha256": sha256_file(
            worst_dir / "trajectory_manifest.json"
        ),
    }
    for key, digest in expected.items():
        if payload.get(key) != digest:
            raise Phase7AuditError(f"trajectory export audit {key} mismatch")
    canonical = payload.get("canonical_files")
    if not isinstance(canonical, Mapping):
        raise Phase7AuditError("trajectory export audit lacks canonical_files")
    for name in ("per_episode_metrics.csv", "experiment_ledger.csv", "protocol_lock.json"):
        if canonical.get(name) != sha256_file(results_dir / name):
            raise Phase7AuditError(
                f"trajectory export audit canonical hash mismatch for {name}"
            )


def _resolve_test_logs(
    repo_root: Path,
    pytest_text: Path | None,
    pytest_junit: Path | None,
) -> tuple[Path, Path]:
    text = (
        require_file(_repo_relative(pytest_text, repo_root), "pytest text log")
        if pytest_text is not None
        else find_first_file(
            (
                repo_root / "logs" / "pytest_final.txt",
                repo_root / "logs" / "pytest.txt",
                repo_root / "pytest.txt",
            ),
            "pytest text log",
        )
    )
    junit = (
        require_file(_repo_relative(pytest_junit, repo_root), "pytest JUnit XML")
        if pytest_junit is not None
        else find_first_file(
            (
                repo_root / "logs" / "pytest_final.xml",
                repo_root / "logs" / "pytest.xml",
                repo_root / "test-results.xml",
            ),
            "pytest JUnit XML",
        )
    )
    return text, junit


def _junit_summary(path: Path) -> dict[str, int]:
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise Phase7AuditError(f"pytest JUnit XML cannot be parsed: {path}: {exc}") from exc
    suites = [root] if root.tag.endswith("testsuite") else list(root.iter("testsuite"))
    if not suites:
        raise Phase7AuditError(f"pytest JUnit XML contains no testsuite: {path}")
    # In a testsuites document, summing every nested suite can double-count.
    top = root if root.tag.endswith("testsuite") else root
    attributes = top.attrib
    if "tests" in attributes:
        tests = int(float(attributes.get("tests", 0)))
        failures = int(float(attributes.get("failures", 0)))
        errors = int(float(attributes.get("errors", 0)))
        skipped = int(float(attributes.get("skipped", 0)))
    else:
        direct = [item for item in root if item.tag.endswith("testsuite")]
        tests = sum(int(float(item.attrib.get("tests", 0))) for item in direct)
        failures = sum(int(float(item.attrib.get("failures", 0))) for item in direct)
        errors = sum(int(float(item.attrib.get("errors", 0))) for item in direct)
        skipped = sum(int(float(item.attrib.get("skipped", 0))) for item in direct)
    return {
        "tests": tests,
        "passed": tests - failures - errors - skipped,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
    }


def _git_capture(repo_root: Path, output_zip: Path) -> dict[str, str]:
    def run(*arguments: str) -> str:
        command = [
            "git",
            "-c",
            f"safe.directory={repo_root.as_posix()}",
            *arguments,
        ]
        completed = subprocess.run(
            command,
            cwd=repo_root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if completed.returncode != 0:
            raise Phase7AuditError(
                f"git {' '.join(arguments)} failed ({completed.returncode}): {completed.stderr.strip()}"
            )
        return completed.stdout

    commit = run("rev-parse", "HEAD").strip() + "\n"
    status_lines = run("status", "--short", "--branch", "--untracked-files=all").splitlines()
    try:
        output_relative = output_zip.relative_to(repo_root).as_posix()
    except ValueError:
        output_relative = None
    filtered_status = [
        line
        for line in status_lines
        if output_relative is None
        or not line[3:].strip().replace("\\", "/").endswith(output_relative)
    ]
    status = "\n".join(filtered_status) + ("\n" if filtered_status else "")
    diff = run("diff", "--binary", "--no-ext-diff", "HEAD")
    return {"commit": commit, "status": status, "diff": diff}


def _physical_memory_bytes() -> int | None:
    try:
        import psutil

        return int(psutil.virtual_memory().total)
    except Exception:
        pass
    if os.name == "nt":
        try:
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("length", ctypes.c_ulong),
                    ("memory_load", ctypes.c_ulong),
                    ("total_phys", ctypes.c_ulonglong),
                    ("avail_phys", ctypes.c_ulonglong),
                    ("total_page_file", ctypes.c_ulonglong),
                    ("avail_page_file", ctypes.c_ulonglong),
                    ("total_virtual", ctypes.c_ulonglong),
                    ("avail_virtual", ctypes.c_ulonglong),
                    ("avail_extended_virtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatus()
            status.length = ctypes.sizeof(MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.total_phys)
        except Exception:
            return None
    try:
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, ValueError):
        return None


def _package_versions() -> dict[str, str | None]:
    distributions = {
        "numpy": "numpy",
        "scipy": "scipy",
        "pandas": "pandas",
        "cvxpy": "cvxpy",
        "mosek": "Mosek",
        "gurobipy": "gurobipy",
        "pytest": "pytest",
    }
    versions: dict[str, str | None] = {}
    for label, distribution in distributions.items():
        try:
            versions[label] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            versions[label] = None
    return versions


def _environment_payload(ledger_rows: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    seeds = sorted(
        {
            int(row["seed"])
            for row in ledger_rows
            if row.get("seed") not in (None, "")
        }
    )
    wall_times = [
        value
        for value in (parse_float(row.get("wall_time_s")) for row in ledger_rows)
        if value is not None
    ]
    return {
        "schema_version": "d5freq.phase7.environment.v1",
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "package_versions": _package_versions(),
        "operating_system": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "hardware": {
            "processor": platform.processor() or None,
            "logical_cpu_count": os.cpu_count(),
            "physical_memory_bytes": _physical_memory_bytes(),
        },
        "final_experiment": {
            "episode_rows": len(ledger_rows),
            "unique_random_seeds": seeds,
            "reported_episode_wall_time_sum_s": (
                None if not wall_times else float(sum(wall_times))
            ),
            "reported_episode_wall_time_max_s": (
                None if not wall_times else float(max(wall_times))
            ),
            "wall_time_note": "Sum is episode process wall time and may exceed elapsed wall-clock time under parallel execution.",
        },
    }


def _copy_root_files_allowlisted(
    source: Path, destination: Path, allowlist: frozenset[str]
) -> int:
    copied = 0
    for name in sorted(allowlist):
        candidate = source / name
        if candidate.is_file():
            copy_file_strict(candidate, destination / name)
            copied += 1
    return copied


def _copy_repository_snapshot(
    repo_root: Path, reference_docs: Path, package_root: Path
) -> None:
    copy_tree_strict(repo_root / "src", package_root / "source" / "src")
    copy_tree_strict(repo_root / "scripts", package_root / "source" / "scripts")
    for name in ("README.md", "pyproject.toml", "environment.yml"):
        copy_file_strict(repo_root / name, package_root / "source" / name)
    copy_tree_strict(repo_root / "research_docs", package_root / "research_docs")
    reports = package_root / "research_docs" / "phase_reports"
    for phase in range(8):
        name = f"PHASE_{phase}_REPORT.md"
        copy_file_strict(repo_root / "progress" / name, reports / name)
    copy_tree_strict(repo_root / "configs", package_root / "configs")
    copy_tree_strict(repo_root / "tests", package_root / "tests")
    copy_tree_strict(
        reference_docs,
        package_root / "research_docs" / "original_project_spec",
    )


def _copy_artifacts(repo_root: Path, package_root: Path) -> None:
    source_artifacts = repo_root / "artifacts"
    copy_tree_strict(
        source_artifacts / "phase1",
        package_root / "artifacts" / "phase1",
    )
    copy_tree_strict(
        source_artifacts / "mode_discovery",
        package_root / "artifacts" / "mode_discovery",
    )
    for label, source_name in _OOD_ROOTS:
        destination = package_root / "artifacts" / "ood_calibration" / label
        copied = _copy_root_files_allowlisted(
            source_artifacts / source_name, destination, _OOD_ROOT_FILE_ALLOWLIST
        )
        if copied == 0:
            raise Phase7AuditError(f"no allowlisted OOD artifact copied for {label}")
    library_root = package_root / "artifacts" / "model_library"
    copy_file_strict(
        source_artifacts / "mode_discovery" / "mode_library.json",
        library_root / "native_k6" / "mode_library.json",
    )
    copy_tree_strict(
        source_artifacts / "phase6_library_ablations",
        library_root / "phase6_library_ablations",
    )
    copy_tree_strict(
        source_artifacts / "phase6_library_bindings",
        library_root / "bindings",
    )


def _copy_results_and_selected_traces(
    repo_root: Path,
    results_dir: Path,
    figures_dir: Path,
    representative_dir: Path,
    worst_dir: Path,
    package_root: Path,
    *,
    strict_audit: bool,
) -> None:
    for name in RESULT_CSV_NAMES:
        copy_file_strict(results_dir / name, package_root / "results" / name)
    for optional in (
        "oracle_pairing_audit.csv",
        "protocol_lock.json",
        "protocol_snapshot.json",
        "tuning_selection_record.json",
        "trajectory_export_audit.json",
    ):
        source = results_dir / optional
        if source.is_file():
            copy_file_strict(source, package_root / "results" / optional)
    for name, _ in FIGURE_SPECS:
        copy_file_strict(figures_dir / name, package_root / "figures" / name)
    copy_file_strict(
        figures_dir / "figure_manifest.csv",
        package_root / "figures" / "figure_manifest.csv",
    )
    copy_tree_strict(
        representative_dir, package_root / "representative_trajectories"
    )
    copy_tree_strict(worst_dir, package_root / "worst_failure_cases")
    relocate_selected_trajectory_manifest(
        package_root / "representative_trajectories",
        results_dir=package_root / "results",
        expected_role="representative",
        enforce_frozen_selection=strict_audit,
    )
    relocate_selected_trajectory_manifest(
        package_root / "worst_failure_cases",
        results_dir=package_root / "results",
        expected_role="worst",
        enforce_frozen_selection=strict_audit,
    )
    tuning_source = (
        repo_root
        / "results"
        / "phase6"
        / "tuning"
        / "tuning_selection_record.json"
    )
    if strict_audit:
        require_file(tuning_source, "canonical Phase-6 tuning selection record")
    if tuning_source.is_file():
        copy_file_strict(
            tuning_source,
            package_root
            / "results"
            / "phase6"
            / "tuning"
            / "tuning_selection_record.json",
        )
    _relocate_figure_manifest(
        package_root=package_root,
        repo_root=repo_root,
        original_results_dir=results_dir,
        original_representative_dir=representative_dir,
        original_worst_dir=worst_dir,
        require_all_available=strict_audit,
    )


def _relocated_figure_source(
    source: Path,
    *,
    package_root: Path,
    repo_root: Path,
    original_results_dir: Path,
    original_representative_dir: Path,
    original_worst_dir: Path,
) -> Path:
    roots = (
        (original_representative_dir, package_root / "representative_trajectories"),
        (original_worst_dir, package_root / "worst_failure_cases"),
        (original_results_dir, package_root / "results"),
        (repo_root / "src", package_root / "source" / "src"),
        (repo_root / "scripts", package_root / "source" / "scripts"),
    )
    for original_root, packaged_root in roots:
        try:
            relative = source.relative_to(original_root)
        except ValueError:
            continue
        return packaged_root / relative
    try:
        relative = source.relative_to(repo_root)
    except ValueError as exc:
        raise Phase7AuditError(
            f"figure source is outside the repository and cannot be packaged: {source}"
        ) from exc
    return package_root / relative


def _relocate_figure_manifest(
    *,
    package_root: Path,
    repo_root: Path,
    original_results_dir: Path,
    original_representative_dir: Path,
    original_worst_dir: Path,
    require_all_available: bool,
) -> None:
    manifest = package_root / "figures" / "figure_manifest.csv"
    rows = read_csv_rows(manifest)
    fieldnames = (
        "figure_id",
        "filename",
        "title",
        "status",
        "data_sources",
        "data_source_sha256",
        "missing_fields",
        "notes",
        "figure_sha256",
    )
    relocated_rows: list[dict[str, Any]] = []
    for row in rows:
        sources = [value for value in row.get("data_sources", "").split(";") if value]
        hashes = [
            value
            for value in row.get("data_source_sha256", "").split(";")
            if value
        ]
        if len(sources) != len(hashes):
            raise Phase7AuditError("figure source/hash cardinality mismatch")
        relocated_sources: list[str] = []
        relocated_hashes: list[str] = []
        for source_value, hash_value in zip(sources, hashes, strict=True):
            if "=" not in hash_value:
                raise Phase7AuditError("malformed figure source hash")
            hash_path, digest = hash_value.rsplit("=", 1)
            if hash_path != source_value:
                raise Phase7AuditError("figure source/hash path mismatch")
            original = (repo_root / Path(source_value)).resolve()
            require_file(original, "original figure source")
            if sha256_file(original) != digest:
                raise Phase7AuditError(
                    f"original figure source hash mismatch: {source_value}"
                )
            packaged = _relocated_figure_source(
                original,
                package_root=package_root,
                repo_root=repo_root,
                original_results_dir=original_results_dir,
                original_representative_dir=original_representative_dir,
                original_worst_dir=original_worst_dir,
            )
            require_file(packaged, f"packaged figure source {source_value}")
            if sha256_file(packaged) != digest:
                raise Phase7AuditError(
                    f"packaged figure source hash mismatch: {packaged}"
                )
            relative = packaged.relative_to(package_root).as_posix()
            relocated_sources.append(relative)
            relocated_hashes.append(f"{relative}={digest}")
        rewritten = dict(row)
        rewritten["data_sources"] = ";".join(relocated_sources)
        rewritten["data_source_sha256"] = ";".join(relocated_hashes)
        relocated_rows.append(rewritten)
    atomic_write_csv(manifest, fieldnames, relocated_rows)
    _validate_figure_manifest(
        package_root / "figures",
        source_root=package_root,
        require_all_available=require_all_available,
    )


def _copy_logs_and_environment(
    repo_root: Path,
    results_dir: Path,
    pytest_text: Path,
    pytest_junit: Path,
    package_root: Path,
    test_summary: Mapping[str, int],
) -> None:
    copy_file_strict(pytest_text, package_root / "logs" / "pytest.txt")
    copy_file_strict(pytest_junit, package_root / "logs" / "pytest_junit.xml")
    for name in ("coverage.xml",):
        source = repo_root / name
        if source.is_file():
            copy_file_strict(source, package_root / "logs" / name)
    logs = repo_root / "logs"
    if logs.is_dir():
        for source in sorted(logs.iterdir(), key=lambda item: item.name):
            if source.is_file() and source.resolve() not in {
                pytest_text.resolve(),
                pytest_junit.resolve(),
            }:
                copy_file_strict(source, package_root / "logs" / "additional" / source.name)
    atomic_write_json(package_root / "logs" / "pytest_summary.json", dict(test_summary))
    copy_file_strict(
        repo_root / "environment.yml", package_root / "environment" / "environment.yml"
    )
    for name in (
        "environment_phase0.json",
        "packages_phase0.txt",
        "solver_smoke_phase0.json",
    ):
        source = repo_root / "progress" / name
        if source.is_file():
            copy_file_strict(source, package_root / "environment" / name)
    ledger_rows = read_csv_rows(results_dir / "experiment_ledger.csv")
    atomic_write_json(
        package_root / "environment" / "final_build_environment.json",
        _environment_payload(ledger_rows),
    )


def _copy_git_evidence(git: Mapping[str, str], package_root: Path) -> None:
    atomic_write_text(package_root / "git" / "commit.txt", git["commit"])
    atomic_write_text(package_root / "git" / "status.txt", git["status"])
    atomic_write_text(package_root / "git" / "diff.patch", git["diff"])


def _phase_statuses(repo_root: Path) -> list[tuple[int, str]]:
    statuses: list[tuple[int, str]] = []
    pattern = re.compile(r"\*\*Status:\*\*\s*([^\r\n]+)", re.IGNORECASE)
    for phase in range(8):
        text = (repo_root / "progress" / f"PHASE_{phase}_REPORT.md").read_text(
            encoding="utf-8"
        )
        match = pattern.search(text)
        statuses.append((phase, "not explicitly stated" if match is None else match.group(1).strip()))
    return statuses


def _observed_method_metric(
    episode_rows: Sequence[Mapping[str, str]], method: str, metric: str
) -> tuple[float | None, int]:
    values = [
        value
        for row in episode_rows
        if row.get("method") == method
        for value in [parse_float(row.get(metric))]
        if value is not None
    ]
    return (None if not values else float(sum(values) / len(values)), len(values))


def _observed_method_boolean_rate(
    episode_rows: Sequence[Mapping[str, str]], method: str, metric: str
) -> tuple[float | None, int]:
    values = [
        value
        for row in episode_rows
        if row.get("method") == method
        for value in [parse_bool(row.get(metric))]
        if value is not None
    ]
    return (
        None if not values else float(sum(int(value) for value in values) / len(values)),
        len(values),
    )


def _failure_summary(episode_rows: Sequence[Mapping[str, str]]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for row in episode_rows:
        if parse_bool(row.get("scientific_success")) is False:
            kind = row.get("failure_type") or "scientific criterion not met"
            counts[kind] = counts.get(kind, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def _render_documents(
    *,
    repo_root: Path,
    package_root: Path,
    result_audit: Mapping[str, int],
    test_summary: Mapping[str, int],
) -> None:
    rows = read_csv_rows(package_root / "results" / "per_episode_metrics.csv")
    p_iae, p_iae_n = _observed_method_metric(rows, "P", "freq_iae")
    b1_iae, b1_iae_n = _observed_method_metric(rows, "B1", "freq_iae")
    p_cat, p_cat_n = _observed_method_boolean_rate(
        rows, "P", "catastrophic_failure"
    )
    failures = _failure_summary(rows)
    phase_statuses = _phase_statuses(repo_root)
    p_comparison = (
        "不可用：P 或 B1 缺少可观测 freq_iae。"
        if p_iae is None or b1_iae is None
        else f"P 的观测均值为 {p_iae:.8g} Hz·s（n={p_iae_n}），B1 为 {b1_iae:.8g} Hz·s（n={b1_iae_n}）；这是描述性比较，不代替配对统计检验。"
    )
    catastrophic = (
        "不可用：P 的 catastrophic_failure 指标缺失。"
        if p_cat is None
        else f"P 的观测灾难性失败比例为 {p_cat:.8g}（n={p_cat_n}）。"
    )
    failure_lines = [
        f"- `{name}`：{count} episode" for name, count in failures[:10]
    ] or ["- 结果表未记录 scientific_success=false 行；这不等价于证明没有局限。"]
    summary = f"""# Executive summary

## 项目来源与完成范围

本仓库由 Phase 0 报告记录为独立、从零建立的研究实现；审查包保留最终源码、Git 状态与差异供外部复核，而不把内部声明当作外部血缘证明。Phase 0–7 的报告、原始项目规范和完整数学推导均已纳入。

未完成/失败不会被隐藏：最终表含 {result_audit['episode_count']} 个 episode，其中运行未完成 {result_audit['incomplete_episode_count']} 个、指标不完整 {result_audit['metrics_incomplete_count']} 个、`scientific_success=false` {result_audit['scientific_failure_count']} 个。

## 最重要的三个结果

1. 最终逐 episode 指标与 ledger 的 `run_id` 集合完全一致，共 {result_audit['episode_count']} 行，失败行没有从审查表中删除。
2. {p_comparison}
3. {catastrophic}

## 最严重的三个失败或局限

1. 运行未完成 {result_audit['incomplete_episode_count']} 个；这些行仍在 `results/per_episode_metrics.csv`。
2. 指标不完整 {result_audit['metrics_incomplete_count']} 个、科学失败 {result_audit['scientific_failure_count']} 个；缺失值未插补。
3. 性能差异必须结合 `statistical_tests.csv`、场景分层和 Oracle 的评测侧真值资格解释；描述性均值不能单独建立优越性。

## 信息边界

proposed controller 的运行 API 不读取 true mode；打包前对 `source/src/d5freq/controllers/sd_bmpc.py` 进行了 true-mode 标识符硬扫描。Oracle 位于评测侧并明确使用 `*_eval_only` 真值接口，不能与 proposed controller 混为一谈。

## 压缩包与最小复现

- 最终压缩包大小（字节，固定宽度）：{_ZIP_SIZE_TOKEN}
- 最小核心结果重跑：`conda run -n topo_sfr python scripts/05_run_full_experiments.py --repo-root . --config configs/experiments.yaml --workers 4`

精确 ZIP SHA256 在构建命令的标准输出中给出；不把 ZIP 的自身 SHA256 写入 ZIP，以避免密码学自引用。
"""
    claims_rows = "\n".join(
        f"| Phase {phase} | {status} | `research_docs/phase_reports/PHASE_{phase}_REPORT.md` |"
        for phase, status in phase_statuses
    )
    claims = f"""# Research claims and status

| Claim/evidence stage | Recorded status | Primary packaged evidence |
|---|---|---|
{claims_rows}
| Final episode retention | {result_audit['episode_count']} rows; {result_audit['incomplete_episode_count']} incomplete retained | `results/per_episode_metrics.csv`, `results/experiment_ledger.csv` |
| Proposed runtime truth isolation | Static source gate passed | `source/src/d5freq/controllers/sd_bmpc.py`, tests |
| P versus fixed ARX MPC (descriptive) | {p_comparison} | `results/per_episode_metrics.csv`, `results/statistical_tests.csv` |
| P catastrophic outcome (descriptive) | {catastrophic} | `results/per_episode_metrics.csv` |

“PASS”只表示对应阶段报告所记录的验收状态。研究质量目标不是可修改的硬门槛；未达到目标时应阅读 `04_LIMITATIONS_AND_FAILURES.md` 和完整失败行。
"""
    reproduction = """# Reproducibility commands

以下命令在最终源码仓库根目录执行。输出目录必须是新目录或已由相同协议生成的可恢复目录；不得在解压后的审查证据上直接覆盖 artifact。

```powershell
conda env update --name topo_sfr --file environment.yml
conda run -n topo_sfr python -m pip install -e .
conda run -n topo_sfr python -m pytest -q -W error --junitxml=logs/pytest_final.xml tests | Tee-Object -FilePath logs/pytest_final.txt

conda run -n topo_sfr python scripts/01_generate_id_data.py --config configs/base.yaml
conda run -n topo_sfr python scripts/02_discover_modes.py --config configs/base.yaml
conda run -n topo_sfr python scripts/03_calibrate_ood.py --config configs/base.yaml
conda run -n topo_sfr python scripts/phase6_build_library_ablations.py --config configs/base.yaml --experiments-config configs/experiments.yaml
conda run -n topo_sfr python scripts/03_calibrate_ood.py --config configs/base.yaml --mode-library artifacts/phase6_library_ablations/fixed_k4_unlabeled/mode_library.json --cluster-assignments artifacts/phase6_library_ablations/fixed_k4_unlabeled/cluster_assignments.csv --output-dir artifacts/online_diagnosis_fixed_k4
conda run -n topo_sfr python scripts/03_calibrate_ood.py --config configs/base.yaml --mode-library artifacts/phase6_library_ablations/labeled_training_library/runtime/mode_library.json --cluster-assignments artifacts/phase6_library_ablations/labeled_training_library/evaluation_only/cluster_assignments.csv --output-dir artifacts/online_diagnosis_labeled
conda run -n topo_sfr python scripts/phase6_finalize_library_bindings.py

conda run -n topo_sfr python scripts/04_run_smoke_experiments.py --stage smoke --repo-root . --config configs/experiments.yaml --workers 4
conda run -n topo_sfr python scripts/04_run_smoke_experiments.py --stage tuning --repo-root . --config configs/experiments.yaml --workers 4
conda run -n topo_sfr python scripts/05_run_full_experiments.py --repo-root . --config configs/experiments.yaml --workers 4
conda run -n topo_sfr python scripts/phase6_export_selected_trajectories.py --repo-root . --results-dir results/final
conda run -n topo_sfr python scripts/06_make_figures.py --repo-root . --results-dir results/final --representative-dir results/final/representative_trajectories --worst-dir results/final/worst_failure_cases --figures-dir results/phase7/figures --replace
conda run -n topo_sfr python scripts/07_build_review_package.py --repo-root . --results-dir results/final --figures-dir results/phase7/figures --reference-docs ../D5_SD_BMPC_FROM_SCRATCH_CODEX_PACKAGE_V2
```

仅复核审查包内现有结果和重画图表：

```powershell
conda run -n topo_sfr python -m pip install -e source
conda run -n topo_sfr python -m pytest -q tests
conda run -n topo_sfr python source/scripts/06_make_figures.py --repo-root . --results-dir results --representative-dir representative_trajectories --worst-dir worst_failure_cases --figures-dir reproduced_figures
```

完整最终矩阵计算量大；`environment/final_build_environment.json` 保留随机种子、版本、硬件和已记录 episode 运行时。图表必须从保存的数据重建，不能把审计占位图解释为可用结果。
"""
    limitations = f"""# Limitations and failures

本文件由真实最终 CSV 汇总生成，不删除失败 episode，不把空值换成零，也不把“not available”审计图当成结果。

## 完整性

- episode 总数：{result_audit['episode_count']}
- `run_completed=false`：{result_audit['incomplete_episode_count']}
- `metrics_complete=false`：{result_audit['metrics_incomplete_count']}
- `scientific_success=false`：{result_audit['scientific_failure_count']}

## 失败类型（完整结果表中的科学失败）

{chr(10).join(failure_lines)}

## 研究目标审计

- P 与固定 ARX MPC：{p_comparison}
- 灾难性失败：{catastrophic}
- 是否显著、是否在已知切换/OOD子集一致，必须查看配对样本数、Holm校正结果和场景分层；这里不根据总体均值伪造结论。
- Oracle 使用评测侧真值并标注资格，只能作为上界/遗憾基准。
- 12 类图中若数据不足，图面和 `figures/figure_manifest.csv` 会明确标为 `partial` 或 `not_available`。

## 测试

JUnit 记录：{test_summary['passed']} passed, {test_summary['failures']} failed, {test_summary['errors']} errors, {test_summary['skipped']} skipped。原始文本和 XML 均在 `logs/`。
"""
    atomic_write_text(package_root / "00_EXECUTIVE_SUMMARY.md", summary)
    atomic_write_text(package_root / "01_RESEARCH_CLAIMS_AND_STATUS.md", claims)
    copy_file_strict(
        repo_root / "research_docs" / "MATH_IMPLEMENTATION_MAP.md",
        package_root / "02_MATH_IMPLEMENTATION_MAP.md",
    )
    atomic_write_text(package_root / "03_REPRODUCIBILITY_COMMANDS.md", reproduction)
    atomic_write_text(package_root / "04_LIMITATIONS_AND_FAILURES.md", limitations)


def _category(relative: str) -> str:
    if "/" not in relative:
        return "document" if relative.endswith(".md") else "audit-index"
    return relative.split("/", 1)[0]


def _write_indexes(package_root: Path) -> None:
    index_path = package_root / "05_FILE_INDEX.csv"
    sums_path = package_root / "06_SHA256SUMS.txt"
    if not index_path.exists():
        atomic_write_text(index_path, "")
    if not sums_path.exists():
        atomic_write_text(sums_path, "")
    files = collect_regular_files(package_root)
    relative_paths = [path.relative_to(package_root).as_posix() for path in files]
    index_rows: list[dict[str, Any]] = []
    for path, relative in zip(files, relative_paths):
        if relative in _INDEX_EXCLUDED:
            digest = _INDEX_SELF_SENTINEL
            size: int | str = ""
            policy = "Path is indexed; digest/size omitted because 05 and 06 mutually describe the package and cannot recursively hash themselves."
        else:
            digest = sha256_file(path)
            size = path.stat().st_size
            policy = "SHA256 and size cover exact packaged bytes."
        index_rows.append(
            {
                "relative_path": relative,
                "sha256": digest,
                "size_bytes": size,
                "category": _category(relative),
                "description": "Packaged review evidence",
                "hash_policy": policy,
            }
        )
    atomic_write_csv(
        index_path,
        (
            "relative_path",
            "sha256",
            "size_bytes",
            "category",
            "description",
            "hash_policy",
        ),
        index_rows,
    )
    lines = [
        "# SHA256 for every regular packaged file except 05_FILE_INDEX.csv and 06_SHA256SUMS.txt.",
        "# Both excluded paths are still listed in 05_FILE_INDEX.csv with an explicit self-reference policy.",
    ]
    for path in collect_regular_files(package_root):
        relative = path.relative_to(package_root).as_posix()
        if relative not in _INDEX_EXCLUDED:
            lines.append(f"{sha256_file(path)}  {relative}")
    atomic_write_text(sums_path, "\n".join(lines) + "\n")
    # Rebuild the path-only aspect of the index after sums are final.  Its own
    # and the sums file's size/digest remain deliberately excluded.
    files_after = collect_regular_files(package_root)
    actual = {path.relative_to(package_root).as_posix() for path in files_after}
    indexed = {row["relative_path"] for row in read_csv_rows(index_path)}
    if actual != indexed:
        raise Phase7AuditError(
            f"file index does not cover the package exactly; missing={sorted(actual-indexed)}, extra={sorted(indexed-actual)}"
        )


def _verify_staged_structure(package_root: Path) -> None:
    for relative in REQUIRED_PACKAGE_DIRECTORIES:
        require_nonempty_directory(package_root / relative, f"package {relative}/")
    for relative in REQUIRED_TOP_LEVEL_DOCUMENTS:
        require_file(package_root / relative, f"package {relative}")
    for name in RESULT_CSV_NAMES:
        require_file(package_root / "results" / name, f"package result {name}")
    verify_no_forbidden_packaged_paths(package_root)
    indexed = read_csv_rows(package_root / "05_FILE_INDEX.csv")
    indexed_paths = {row.get("relative_path", "") for row in indexed}
    actual_paths = {
        path.relative_to(package_root).as_posix()
        for path in collect_regular_files(package_root)
    }
    if indexed_paths != actual_paths:
        raise Phase7AuditError("final staged file index has incomplete path coverage")
    for row in indexed:
        relative = row["relative_path"]
        if relative in _INDEX_EXCLUDED:
            if row.get("sha256") != _INDEX_SELF_SENTINEL:
                raise Phase7AuditError("self-referential index rows lack the declared sentinel")
            continue
        path = package_root / relative
        if row.get("sha256") != sha256_file(path):
            raise Phase7AuditError(f"indexed SHA256 mismatch before ZIP build: {relative}")


def _zip_info(name: str, *, directory: bool, stored: bool = False) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, _ZIP_TIMESTAMP)
    info.create_system = 3
    info.flag_bits |= 0x800
    info.external_attr = ((0o40755 if directory else 0o100644) << 16)
    if directory:
        info.external_attr |= 0x10
    info.compress_type = zipfile.ZIP_STORED if stored or directory else zipfile.ZIP_DEFLATED
    return info


def _write_deterministic_zip(package_root: Path, archive: Path) -> None:
    if archive.exists():
        archive.unlink()
    files = collect_regular_files(package_root)
    directories = {""}
    for file in files:
        relative = file.relative_to(package_root)
        for parent in relative.parents:
            if parent != Path("."):
                directories.add(parent.as_posix())
    entries: list[tuple[str, Path | None]] = [
        (f"{PACKAGE_ROOT_NAME}/", None)
    ]
    entries.extend(
        (f"{PACKAGE_ROOT_NAME}/{relative}/", None)
        for relative in directories - {""}
    )
    entries.extend(
        (f"{PACKAGE_ROOT_NAME}/{file.relative_to(package_root).as_posix()}", file)
        for file in files
    )
    entries.sort(key=lambda item: item[0])
    with zipfile.ZipFile(
        archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as handle:
        for member_name, file in entries:
            if file is None:
                handle.writestr(_zip_info(member_name, directory=True), b"")
                continue
            relative = file.relative_to(package_root).as_posix()
            # These fixed-size self-describing documents are stored rather
            # than deflated.  Updating the fixed-width archive-size field and
            # its fixed-width hashes therefore cannot change archive length.
            stored = relative in {
                "00_EXECUTIVE_SUMMARY.md",
                "05_FILE_INDEX.csv",
                "06_SHA256SUMS.txt",
            }
            info = _zip_info(member_name, directory=False, stored=stored)
            if stored:
                handle.writestr(info, file.read_bytes(), compress_type=zipfile.ZIP_STORED)
            else:
                handle.writestr(
                    info,
                    file.read_bytes(),
                    compress_type=zipfile.ZIP_DEFLATED,
                    compresslevel=9,
                )
    with archive.open("rb+") as handle:
        os.fsync(handle.fileno())


def _inject_exact_zip_size(package_root: Path, archive: Path) -> int:
    _write_indexes(package_root)
    _verify_staged_structure(package_root)
    _write_deterministic_zip(package_root, archive)
    first_size = archive.stat().st_size
    summary_path = package_root / "00_EXECUTIVE_SUMMARY.md"
    text = summary_path.read_text(encoding="utf-8")
    if text.count(_ZIP_SIZE_TOKEN) != 1:
        raise Phase7AuditError("executive summary must contain one fixed-width ZIP-size token")
    replacement = f"{first_size:020d}"
    if len(replacement) != len(_ZIP_SIZE_TOKEN):
        raise Phase7AuditError("ZIP size exceeds fixed-width self-description field")
    atomic_write_text(summary_path, text.replace(_ZIP_SIZE_TOKEN, replacement))
    _write_indexes(package_root)
    _verify_staged_structure(package_root)
    _write_deterministic_zip(package_root, archive)
    second_size = archive.stat().st_size
    if second_size != first_size:
        raise Phase7AuditError(
            "deterministic fixed-width ZIP-size self-description changed archive length"
        )
    return second_size


def _audit_zip(archive: Path, expected_file_count: int) -> None:
    with zipfile.ZipFile(archive, "r") as handle:
        names = handle.namelist()
        if len(names) != len(set(names)):
            raise Phase7AuditError("ZIP contains duplicate member names")
        if names != sorted(names):
            raise Phase7AuditError("ZIP members are not in deterministic lexical order")
        prefix = f"{PACKAGE_ROOT_NAME}/"
        if any(not name.startswith(prefix) for name in names):
            raise Phase7AuditError("ZIP contains a member outside the single required root")
        file_members = [info for info in handle.infolist() if not info.is_dir()]
        if len(file_members) != expected_file_count:
            raise Phase7AuditError("ZIP file count differs from staged package")
        if any(info.date_time != _ZIP_TIMESTAMP for info in handle.infolist()):
            raise Phase7AuditError("ZIP contains a non-deterministic timestamp")
        bad = handle.testzip()
        if bad is not None:
            raise Phase7AuditError(f"ZIP CRC audit failed at {bad}")


def _uniform_ledger_value(
    ledger: Any, column: str, expected: str
) -> None:
    if column not in ledger.columns:
        raise Phase7AuditError(f"final experiment ledger lacks provenance column {column}")
    observed = {str(value) for value in ledger[column].dropna().tolist()}
    if observed != {expected}:
        raise Phase7AuditError(
            f"final experiment ledger {column} differs from locked evidence; "
            f"observed={sorted(observed)}"
        )


def _validate_complete_final_evidence(repo_root: Path, results_dir: Path) -> None:
    """Revalidate the 8,280-row matrix and every aggregate provenance root."""

    import pandas as pd

    from d5freq.evaluation.experiment_store import strict_json_value
    from d5freq.evaluation.phase6_analysis import validate_phase6_inputs
    from d5freq.evaluation.phase6_experiments import (
        Phase6Paths,
        build_protocol_material,
        protocol_material_sha256,
    )

    metrics = pd.read_csv(results_dir / "per_episode_metrics.csv")
    ledger = pd.read_csv(results_dir / "experiment_ledger.csv")
    try:
        validate_phase6_inputs(metrics, ledger, require_complete_final=True)
    except Exception as exc:
        raise Phase7AuditError(f"complete Phase-6 final matrix validation failed: {exc}") from exc

    lock_path = require_file(results_dir / "protocol_lock.json", "final protocol lock")
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise Phase7AuditError("final protocol lock is invalid JSON") from exc
    if not isinstance(lock, Mapping) or not isinstance(lock.get("material"), Mapping):
        raise Phase7AuditError("final protocol lock lacks material")
    material = lock["material"]
    material_sha = protocol_material_sha256(material)
    if lock.get("protocol_material_sha256") != material_sha:
        raise Phase7AuditError("final protocol lock material hash mismatch")

    paths = Phase6Paths.from_repo(repo_root)
    tuning_path = require_file(
        paths.tuning_selection_record, "canonical Phase-6 tuning selection record"
    )
    current = build_protocol_material(paths, include_tuning_selection=True)
    if strict_json_value(current) != strict_json_value(material):
        raise Phase7AuditError(
            "current configs/code/artifacts/tuning record differ from the final protocol lock"
        )
    tuning_sha = sha256_file(tuning_path)
    if material.get("tuning_selection_record_sha256") != tuning_sha:
        raise Phase7AuditError("tuning selection record differs from final protocol lock")
    lock_file_sha = sha256_file(lock_path)
    for column in (
        "protocol_material_sha256",
        "aggregate_protocol_material_sha256",
        "execution_artifact_state_sha256",
    ):
        _uniform_ledger_value(ledger, column, material_sha)
    for column in (
        "tuning_selection_record_sha256",
        "aggregate_tuning_selection_record_sha256",
    ):
        _uniform_ledger_value(ledger, column, tuning_sha)
    _uniform_ledger_value(
        ledger, "final_protocol_lock_file_sha256", lock_file_sha
    )
    code = material.get("code")
    configs = material.get("configs")
    if not isinstance(code, Mapping) or not isinstance(configs, Mapping):
        raise Phase7AuditError("final protocol material lacks code/config provenance")
    _uniform_ledger_value(ledger, "code_sha256", str(code.get("logical_sha256")))
    config_columns = {
        "experiments": "experiments_config_sha256",
        "base": "base_config_sha256",
        "mpc": "mpc_config_sha256",
    }
    for config_name, column in config_columns.items():
        record = configs.get(config_name)
        if not isinstance(record, Mapping):
            raise Phase7AuditError(
                f"final protocol material lacks {config_name} config provenance"
            )
        _uniform_ledger_value(ledger, column, str(record.get("logical_sha256")))
    if "per_run_envelope_sha256" not in ledger.columns or not all(
        re.fullmatch(r"[0-9a-f]{64}", str(value))
        for value in ledger["per_run_envelope_sha256"].tolist()
    ):
        raise Phase7AuditError("final ledger contains malformed per-run envelope hashes")


def build_review_package(
    *,
    repo_root: Path,
    reference_docs: Path,
    results_dir: Path,
    figures_dir: Path,
    output: Path,
    representative_dir: Path | None = None,
    worst_dir: Path | None = None,
    pytest_text: Path | None = None,
    pytest_junit: Path | None = None,
    max_zip_bytes: int = MAX_ZIP_BYTES,
    strict_audit: bool = True,
) -> ReviewPackageResult:
    repo_root = resolved(repo_root)
    reference_docs = _require_reference_documents(reference_docs)
    results_dir = resolved(results_dir)
    figures_dir = resolved(figures_dir)
    output_zip = _resolve_output(output, repo_root)
    representative_dir = resolved(
        representative_dir or results_dir / "representative_trajectories"
    )
    worst_dir = resolved(worst_dir or results_dir / "worst_failure_cases")
    if max_zip_bytes <= 0:
        raise ValueError("max_zip_bytes must be positive")

    _require_repository_inputs(repo_root)
    for name in RESULT_CSV_NAMES:
        require_file(results_dir / name, f"final result CSV {name}")
    result_audit = validate_result_identity(results_dir)
    if strict_audit:
        _validate_complete_final_evidence(repo_root, results_dir)
    _validate_figure_manifest(
        figures_dir,
        source_root=repo_root,
        require_all_available=strict_audit,
    )
    require_nonempty_directory(
        representative_dir, "selected representative trajectories"
    )
    require_nonempty_directory(worst_dir, "retained worst failure cases")
    validate_selected_trajectory_manifest(
        representative_dir,
        results_dir=results_dir,
        expected_role="representative",
        enforce_frozen_selection=strict_audit,
    )
    validate_selected_trajectory_manifest(
        worst_dir,
        results_dir=results_dir,
        expected_role="worst",
        enforce_frozen_selection=strict_audit,
    )
    if strict_audit:
        _validate_trajectory_export_audit(
            results_dir, representative_dir, worst_dir
        )
    _validate_artifact_inputs(repo_root)
    pytest_text_path, pytest_junit_path = _resolve_test_logs(
        repo_root, pytest_text, pytest_junit
    )
    test_summary = _junit_summary(pytest_junit_path)
    git_evidence = _git_capture(repo_root, output_zip)

    output_zip.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(
        tempfile.mkdtemp(prefix=".p7_", dir=str(output_zip.parent))
    )
    # Keep the physical staging path short on Windows; the ZIP still has the
    # full protocol-mandated logical root name.
    package_root = temporary_root / "package"
    package_root.mkdir()
    temporary_archive = temporary_root / ZIP_NAME
    try:
        _copy_repository_snapshot(repo_root, reference_docs, package_root)
        _copy_artifacts(repo_root, package_root)
        _copy_results_and_selected_traces(
            repo_root,
            results_dir,
            figures_dir,
            representative_dir,
            worst_dir,
            package_root,
            strict_audit=strict_audit,
        )
        _copy_logs_and_environment(
            repo_root,
            results_dir,
            pytest_text_path,
            pytest_junit_path,
            package_root,
            test_summary,
        )
        _copy_git_evidence(git_evidence, package_root)
        _render_documents(
            repo_root=repo_root,
            package_root=package_root,
            result_audit=result_audit,
            test_summary=test_summary,
        )
        size_bytes = _inject_exact_zip_size(package_root, temporary_archive)
        if size_bytes >= max_zip_bytes:
            raise Phase7AuditError(
                f"review ZIP is {size_bytes} bytes; protocol requires < {max_zip_bytes} bytes"
            )
        file_count = len(collect_regular_files(package_root))
        _audit_zip(temporary_archive, file_count)
        os.replace(temporary_archive, output_zip)
        return ReviewPackageResult(
            zip_path=output_zip,
            size_bytes=size_bytes,
            sha256=sha256_file(output_zip),
            file_count=file_count,
            episode_count=result_audit["episode_count"],
            pytest_passed=test_summary.get("passed"),
            pytest_failed=(
                test_summary.get("failures", 0) + test_summary.get("errors", 0)
            ),
        )
    finally:
        if temporary_root.exists():
            shutil.rmtree(temporary_root)


def main() -> int:
    arguments = _parser().parse_args()
    repo_root = resolved(arguments.repo_root)
    result = build_review_package(
        repo_root=repo_root,
        reference_docs=_repo_relative(arguments.reference_docs, repo_root),
        results_dir=_repo_relative(arguments.results_dir, repo_root),
        figures_dir=_repo_relative(arguments.figures_dir, repo_root),
        output=arguments.output,
        representative_dir=(
            None
            if arguments.representative_dir is None
            else _repo_relative(arguments.representative_dir, repo_root)
        ),
        worst_dir=(
            None
            if arguments.worst_dir is None
            else _repo_relative(arguments.worst_dir, repo_root)
        ),
        pytest_text=(
            None
            if arguments.pytest_text is None
            else _repo_relative(arguments.pytest_text, repo_root)
        ),
        pytest_junit=(
            None
            if arguments.pytest_junit is None
            else _repo_relative(arguments.pytest_junit, repo_root)
        ),
    )
    print(
        json.dumps(
            {
                "zip_path": str(result.zip_path),
                "size_bytes": result.size_bytes,
                "sha256": result.sha256,
                "packaged_file_count": result.file_count,
                "episode_count": result.episode_count,
                "pytest_passed": result.pytest_passed,
                "pytest_failed_or_errors": result.pytest_failed,
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
