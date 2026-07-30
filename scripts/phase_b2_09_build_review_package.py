"""Build and independently verify the Phase B2 scientific review package."""

from __future__ import annotations

from collections.abc import Mapping
import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
from typing import Any
import zipfile


REPO = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "D5_PHASE_B2_SCIENTIFIC_HARDENING_REVIEW_PACKAGE.zip"
PACKAGE_PATH = REPO / PACKAGE_NAME
EXTERNAL_SHA_PATH = REPO / f"{PACKAGE_NAME}.sha256"
PHASE_B2_BASELINE_COMMIT = "9e003ba"
MAX_PACKAGE_BYTES = 512 * 1024 * 1024
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)

TOP_LEVEL_REPORTS = (
    "00_EXECUTIVE_SUMMARY.md",
    "01_CORRECTED_PHASE_B1_AUDIT.md",
    "02_SERVICE_SCOPE_AND_MODEL_REPORT.md",
    "03_PLANT_B_PHYSICAL_VALIDATION.md",
    "04_STRONG_ORACLE_VALIDATION.md",
    "05_MATERIALITY_REPORT.md",
    "06_CONTROL_RELEVANT_IDENTIFIABILITY.md",
    "07_FINAL_DECISION_AND_NEXT_METHOD.md",
    "08_LIMITATIONS_AND_FAILURES.md",
    "09_REPRODUCIBILITY_COMMANDS.md",
)
REQUIRED_TABLES = (
    "per_episode_metrics.csv",
    "paired_failure_outcomes.csv",
    "corrected_materiality.csv",
    "cost_sensitivity.csv",
    "oracle_hierarchy.csv",
    "oracle_solver_quality.csv",
    "prediction_error.csv",
    "control_relevant_regime_distance.csv",
    "critical_window.csv",
    "identifiability.csv",
    "final_decision.json",
)
REQUIRED_FIGURES = (
    "corrected_phase_b1_decision.png",
    "plant_b_block_diagram.png",
    "open_loop_regime_responses.png",
    "oracle_hierarchy_performance.png",
    "cost_frequency_pareto.png",
    "cost_sensitivity.png",
    "detection_vs_Tcritical.png",
    "source_confusion.png",
    "oracle_solver_quality.png",
    "final_failures.png",
)
ALLOWED_DECISIONS = {
    "ACTIVE_IDENTIFICATION_NEEDED",
    "MODEL_ADAPTATION_NEEDED",
    "REGIME_ADAPTIVE_CONTROL_NEEDED",
    "PROBLEM_NOT_MATERIAL",
    "INCONCLUSIVE_NEEDS_REDESIGN",
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(*arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=REPO,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout


def _payload_bytes(value: Path | bytes) -> bytes:
    return value.read_bytes() if isinstance(value, Path) else bytes(value)


def _add_tree(
    mapping: dict[str, Path | bytes],
    source_root: Path,
    archive_root: str,
    *,
    suffixes: set[str] | None = None,
) -> None:
    if not source_root.is_dir():
        return
    for source in sorted(source_root.rglob("*"), key=lambda p: p.as_posix()):
        if not source.is_file():
            continue
        relative = source.relative_to(source_root)
        if "__pycache__" in relative.parts or source.suffix.lower() in {".pyc", ".pyo"}:
            continue
        if suffixes is not None and source.suffix.lower() not in suffixes:
            continue
        mapping[f"{archive_root}/{relative.as_posix()}"] = source


def _add_file(mapping: dict[str, Path | bytes], archive_path: str, source: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    mapping[archive_path] = source


def _package_readme() -> bytes:
    decision = json.loads(
        (REPO / "results_phase_b2/final_analysis/final_decision.json").read_text(
            encoding="utf-8"
        )
    )
    run = json.loads(
        (REPO / "results_phase_b2/final_experiment/run_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    return (
        "# Phase B2 Scientific Hardening Review Package\n\n"
        f"Final preregistered decision: `{decision['final_decision']}`.\n\n"
        "Start with `00_EXECUTIVE_SUMMARY.md`, then read the numbered reports. "
        "Oracle O1/O2/O3 evidence is evaluation-only. O2 is a local IPOPT "
        "multiple-shooting NMPC and is not claimed globally optimal.\n\n"
        "Final-run accounting:\n\n"
        f"- episode-method rows: {run['episode_rows']}\n"
        f"- run completed: {run['run_completed_count']}\n"
        f"- scientific success: {run['scientific_success_count']}\n"
        f"- scientific failure: {run['scientific_failure_count']}\n"
        f"- deleted episodes: {run['deleted_episode_count']}\n\n"
        "`SHA256_MANIFEST.json` authenticates every archive member except itself. "
        "`FILE_INDEX.csv` is included in that manifest. The external `.sha256` "
        "file authenticates the ZIP as a whole.\n"
    ).encode("utf-8")


def build_mapping() -> dict[str, Path | bytes]:
    mapping: dict[str, Path | bytes] = {"README_FIRST.md": _package_readme()}

    for report in TOP_LEVEL_REPORTS:
        _add_file(mapping, report, REPO / "reports_phase_b2" / report)

    for source in sorted((REPO / "configs").glob("phase_b2*.yaml")):
        mapping[f"source/configs/{source.name}"] = source
    for source in sorted((REPO / "scripts").glob("phase_b2_*.py")):
        mapping[f"source/scripts/{source.name}"] = source
    for relative in (
        "src/d5freq/controllers/__init__.py",
        "src/d5freq/controllers/phase_b2_conventional.py",
        "src/d5freq/evaluation/phase_b2_baseline.py",
        "src/d5freq/evaluation/phase_b2_exact_nmpc.py",
        "src/d5freq/evaluation/phase_b2_identifiability.py",
        "src/d5freq/evaluation/phase_b2_identified_mpc.py",
        "src/d5freq/evaluation/phase_b2_plant.py",
        "src/d5freq/evaluation/phase_b2_protocol.py",
        "src/d5freq/evaluation/phase_b2_statistics.py",
        "src/d5freq/models/__init__.py",
        "src/d5freq/models/two_area_plant_b.py",
        "src/d5freq/utils/environment.py",
        "environment.yml",
        "pyproject.toml",
    ):
        _add_file(mapping, f"source/{relative}", REPO / relative)
    _add_tree(mapping, REPO / "tests_phase_b2", "source/tests_phase_b2", suffixes={".py"})
    _add_tree(
        mapping,
        REPO / "research/phase_b2_scientific_hardening",
        "research/phase_b2_scientific_hardening",
        suffixes={".md", ".txt", ".yaml", ".py"},
    )

    mapping["git/phase_b2_baseline_commit.txt"] = (
        PHASE_B2_BASELINE_COMMIT + "\n"
    ).encode("ascii")
    mapping["git/final_commit.txt"] = _git("rev-parse", "HEAD")
    mapping["git/branch.txt"] = _git("branch", "--show-current")
    mapping["git/status.txt"] = _git("status", "--short", "--branch", "--ignored=no")
    mapping["git/log_phase_b2.txt"] = _git(
        "log", "--decorate", "--oneline", f"{PHASE_B2_BASELINE_COMMIT}..HEAD"
    )
    mapping["git/diff_from_phase_b2_baseline.patch"] = _git(
        "diff", "--binary", PHASE_B2_BASELINE_COMMIT, "HEAD"
    )

    _add_tree(mapping, REPO / "artifacts_phase_b2", "artifacts")
    _add_tree(mapping, REPO / "artifacts_phase_b2/resolved_configs", "resolved_configs")

    table_sources = {
        "per_episode_metrics.csv": "results_phase_b2/final_experiment/per_episode_metrics.csv",
        "paired_failure_outcomes.csv": "results_phase_b2/final_experiment/paired_failure_outcomes.csv",
        "corrected_materiality.csv": "results_phase_b2/final_analysis/corrected_materiality.csv",
        "cost_sensitivity.csv": "results_phase_b2/final_analysis/cost_sensitivity.csv",
        "oracle_hierarchy.csv": "results_phase_b2/final_analysis/oracle_hierarchy.csv",
        "oracle_solver_quality.csv": "results_phase_b2/oracle_validation/oracle_solver_quality.csv",
        "prediction_error.csv": "results_phase_b2/oracle_validation/prediction_error.csv",
        "control_relevant_regime_distance.csv": "results_phase_b2/identifiability/control_relevant_regime_distance.csv",
        "critical_window.csv": "results_phase_b2/identifiability/critical_window.csv",
        "identifiability.csv": "results_phase_b2/identifiability/identifiability.csv",
        "final_decision.json": "results_phase_b2/final_analysis/final_decision.json",
    }
    for archive_name, relative in table_sources.items():
        _add_file(mapping, f"tables/{archive_name}", REPO / relative)

    supporting_files = (
        "results_phase_b2/final_experiment/run_manifest.json",
        "results_phase_b2/final_analysis/episode_completeness.csv",
        "results_phase_b2/final_analysis/failure_summary.csv",
        "results_phase_b2/final_analysis/model_mismatch.csv",
        "results_phase_b2/identifiability/information_gramian.csv",
        "results_phase_b2/identifiability/source_confusion.csv",
        "results_phase_b2/oracle_validation/oracle_dense_grid_crosscheck.csv",
        "results_phase_b2/oracle_validation/oracle_horizon_validation.csv",
        "results_phase_b2/oracle_validation/oracle_horizon_validation_initial_failure_run.csv",
        "results_phase_b2/oracle_validation/oracle_solver_quality_initialization_failure_run.csv",
        "results_phase_b2/oracle_validation/prediction_error_summary.csv",
        "results_phase_b2/plant_b_validation/open_loop_regime_response.csv",
        "results_phase_b2/plant_b_validation/physical_validation_checks.csv",
        "results_phase_b2/plant_b_validation/sg_capability_engineering_units.csv",
        "results_phase_b2/plant_b_validation/sg_capability_response.csv",
    )
    for relative in supporting_files:
        _add_file(mapping, f"supporting_tables/{Path(relative).name}", REPO / relative)
    _add_tree(
        mapping,
        REPO / "results_phase_b2/corrected_phase_b1",
        "corrected_phase_b1",
        suffixes={".csv", ".json", ".txt"},
    )

    _add_file(
        mapping,
        "trajectories/representative_trajectories.parquet",
        REPO / "results_phase_b2/final_experiment/representative_trajectories.parquet",
    )
    _add_tree(mapping, REPO / "figures_phase_b2", "figures", suffixes={".png"})
    _add_tree(mapping, REPO / "logs_phase_b2", "environment_and_tests")
    _add_tree(mapping, REPO / "progress_phase_b2", "progress", suffixes={".md", ".txt"})
    return mapping


def _validate_csv_schema(mapping: Mapping[str, Path | bytes]) -> None:
    data = _payload_bytes(mapping["tables/per_episode_metrics.csv"]).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(data))
    required = {
        "scenario_id", "seed", "plant_id", "sg_level", "method",
        "run_completed", "scientific_success", "failure_type", "freq_iae",
        "ace_iae", "max_abs_freq_hz", "max_abs_rocof", "tie_line_iae",
        "settling_time", "sg_energy", "ibr_energy", "sg_mileage", "ibr_mileage",
    }
    missing = required - set(reader.fieldnames or ())
    if missing:
        raise RuntimeError(f"per_episode_metrics.csv missing columns: {sorted(missing)}")
    rows = list(reader)
    if len(rows) != 2150:
        raise RuntimeError(f"expected 2150 retained episode-method rows, got {len(rows)}")
    if not any(row["scientific_success"].strip().lower() == "false" for row in rows):
        raise RuntimeError("scientific failure rows are not retained")


def validate_mapping(mapping: Mapping[str, Path | bytes]) -> dict[str, Any]:
    names = set(mapping)
    missing_reports = set(TOP_LEVEL_REPORTS) - names
    missing_tables = {f"tables/{name}" for name in REQUIRED_TABLES} - names
    missing_figures = {f"figures/{name}" for name in REQUIRED_FIGURES} - names
    if missing_reports or missing_tables or missing_figures:
        raise RuntimeError(
            f"missing reports={sorted(missing_reports)}, tables={sorted(missing_tables)}, "
            f"figures={sorted(missing_figures)}"
        )
    for required in (
        "source/scripts/phase_b2_09_build_review_package.py",
        "git/final_commit.txt",
        "git/status.txt",
        "git/diff_from_phase_b2_baseline.patch",
        "resolved_configs/phase_b2_final_experiment.yaml",
        "artifacts/reproducibility/environment.json",
        "artifacts/reproducibility/solver_versions.json",
        "artifacts/reproducibility/test_summary.json",
        "environment_and_tests/pytest_coverage_phase_b2.log",
        "environment_and_tests/coverage_phase_b2.xml",
        "trajectories/representative_trajectories.parquet",
    ):
        if required not in names:
            raise RuntimeError(f"missing required review evidence: {required}")

    for name, value in mapping.items():
        archive_path = PurePosixPath(name)
        if archive_path.is_absolute() or ".." in archive_path.parts:
            raise RuntimeError(f"unsafe archive path: {name}")
        if "__pycache__" in archive_path.parts or archive_path.suffix.lower() in {
            ".lic", ".pyc", ".pyo", ".tmp",
        }:
            raise RuntimeError(f"forbidden archive content: {name}")
        lowered = name.casefold()
        if "conda-meta/" in lowered or ".pytest_cache" in lowered or ".git/" in lowered:
            raise RuntimeError(f"environment/cache directory is forbidden: {name}")
        if Path(name).suffix.lower() in {".md", ".txt", ".json", ".yaml", ".yml", ".py", ".patch", ".csv"}:
            data = _payload_bytes(value).lower()
            forbidden_windows = b"backup" + b"\\downloads"
            forbidden_posix = b"backup" + b"/downloads"
            if forbidden_windows in data or forbidden_posix in data:
                raise RuntimeError(f"local solver-license path leaked into {name}")

    _validate_csv_schema(mapping)
    decision = json.loads(
        _payload_bytes(mapping["tables/final_decision.json"]).decode("utf-8")
    )
    if decision.get("final_decision") not in ALLOWED_DECISIONS:
        raise RuntimeError("final decision is not one of the preregistered choices")
    if decision.get("active_triggers") == [] and decision.get(
        "fallback_ranking_when_active_empty"
    ) is not None:
        raise RuntimeError("all-false triggers still contain a fallback ranking")
    if decision.get("O2_global_optimality_claim") is not False:
        raise RuntimeError("O2 must not be represented as a globally optimal oracle")

    run = json.loads(
        (REPO / "results_phase_b2/final_experiment/run_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    if run.get("deleted_episode_count") != 0 or run.get("episode_rows") != 2150:
        raise RuntimeError("final episode accounting is incomplete")
    return {
        "final_decision": decision["final_decision"],
        "mapping_file_count_before_manifests": len(mapping),
        "episode_rows": run["episode_rows"],
        "scientific_failure_count": run["scientific_failure_count"],
        "deleted_episode_count": run["deleted_episode_count"],
    }


def _validate_parquet_zstd(path: Path) -> dict[str, Any]:
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(path)
    compressions = {
        str(parquet.metadata.row_group(group).column(column).compression).upper()
        for group in range(parquet.metadata.num_row_groups)
        for column in range(parquet.metadata.row_group(group).num_columns)
    }
    if compressions != {"ZSTD"}:
        raise RuntimeError(f"representative trajectories are not exclusively ZSTD: {compressions}")
    table = parquet.read(
        columns=["trajectory_class", "scenario_id", "seed", "method", "sg_level"]
    )
    frame = table.to_pandas()
    return {
        "compression": sorted(compressions),
        "rows": int(frame.shape[0]),
        "trajectory_classes": sorted(frame["trajectory_class"].dropna().unique().tolist()),
        "unique_scenario_seed_method_cases": int(
            frame[["scenario_id", "seed", "method", "sg_level"]].drop_duplicates().shape[0]
        ),
    }


def _index_bytes(mapping: Mapping[str, Path | bytes]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(("archive_path", "size_bytes", "sha256"))
    for name in sorted(mapping):
        data = _payload_bytes(mapping[name])
        writer.writerow((name, len(data), _sha256(data)))
    return buffer.getvalue().encode("utf-8")


def _manifest_bytes(mapping: Mapping[str, Path | bytes]) -> bytes:
    files = []
    for name in sorted(mapping):
        data = _payload_bytes(mapping[name])
        files.append({"path": name, "size_bytes": len(data), "sha256": _sha256(data)})
    return (
        json.dumps(
            {
                "schema_version": "d5freq.phase_b2.review_package_manifest.v1",
                "manifest_scope": "all_archive_members_except_SHA256_MANIFEST.json",
                "file_count": len(files),
                "files": files,
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def build_package() -> dict[str, Any]:
    mapping = build_mapping()
    summary = validate_mapping(mapping)
    parquet_summary = _validate_parquet_zstd(
        REPO / "results_phase_b2/final_experiment/representative_trajectories.parquet"
    )
    mapping["FILE_INDEX.csv"] = _index_bytes(mapping)
    mapping["SHA256_MANIFEST.json"] = _manifest_bytes(mapping)

    temporary = PACKAGE_PATH.with_suffix(".zip.tmp")
    if temporary.exists():
        temporary.unlink()
    with zipfile.ZipFile(
        temporary,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        allowZip64=True,
    ) as archive:
        for name in sorted(mapping):
            info = zipfile.ZipInfo(name, date_time=ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, _payload_bytes(mapping[name]), compresslevel=9)
    temporary.replace(PACKAGE_PATH)

    if PACKAGE_PATH.stat().st_size >= MAX_PACKAGE_BYTES:
        raise RuntimeError("review package is not below 512 MiB")
    sha256 = _file_sha256(PACKAGE_PATH)
    EXTERNAL_SHA_PATH.write_text(f"{sha256}  {PACKAGE_NAME}\n", encoding="ascii")
    verification = verify_package(PACKAGE_PATH)
    return {
        **summary,
        "parquet": parquet_summary,
        "zip_path": str(PACKAGE_PATH),
        "zip_size_bytes": PACKAGE_PATH.stat().st_size,
        "zip_sha256": sha256,
        "external_sha256_path": str(EXTERNAL_SHA_PATH),
        **verification,
    }


def verify_package(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path, "r") as archive:
        corrupt = archive.testzip()
        if corrupt is not None:
            raise RuntimeError(f"ZIP CRC verification failed at {corrupt}")
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise RuntimeError("ZIP contains duplicate archive members")
        manifest = json.loads(archive.read("SHA256_MANIFEST.json"))
        manifest_rows = {row["path"]: row for row in manifest["files"]}
        expected_manifest_names = set(names) - {"SHA256_MANIFEST.json"}
        if set(manifest_rows) != expected_manifest_names:
            raise RuntimeError("manifest member set does not match ZIP member set")
        for name, row in manifest_rows.items():
            data = archive.read(name)
            if len(data) != row["size_bytes"] or _sha256(data) != row["sha256"]:
                raise RuntimeError(f"manifest verification failed at {name}")
        decision = json.loads(archive.read("tables/final_decision.json"))
        if decision["final_decision"] not in ALLOWED_DECISIONS:
            raise RuntimeError("packaged decision is invalid")
    external_line = EXTERNAL_SHA_PATH.read_text(encoding="ascii").strip().split()
    if not external_line or external_line[0] != _file_sha256(path):
        raise RuntimeError("external ZIP SHA256 verification failed")
    return {
        "zip_crc_verified": True,
        "manifest_verified": True,
        "external_sha256_verified": True,
        "archive_member_count": len(names),
        "size_below_512_mib": path.stat().st_size < MAX_PACKAGE_BYTES,
    }


def main() -> None:
    print(json.dumps(build_package(), ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
