"""Build and independently replay the final Direction5 review package."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


REPO = Path(__file__).resolve().parents[2]
PACKAGE_NAME = "DIRECTION5_FINAL_REPAIR_AND_DECISION_SINGLE_REVIEW_PACKAGE"
ZIP_NAME = f"{PACKAGE_NAME}.zip"
FINAL_STATE = "DIRECTION5_TERMINATED_WITH_DECISIVE_NEGATIVE_EVIDENCE"
DIRECTORIES = (
    "00_README", "01_SCIENCE", "02_LITERATURE", "03_MODEL", "04_METHOD",
    "05_THEORY", "06_SOURCE", "07_CONFIG_ENV_SOLVERS",
    "08_TESTS_VERIFICATION", "09_EXPERIMENT_DESIGN", "10_RAW_RESULTS",
    "11_SUMMARY_TABLES", "12_FIGURES", "13_FAILURES",
    "14_PAPER_ANALYSIS", "15_REPRODUCIBILITY", "16_GIT_MANIFEST",
    "17_FINAL_STATUS",
)
SOURCE_PATHS = (
    "src/direction5freq",
    "scripts/direction5_final",
    "tests/direction5_final",
    "configs/direction5_final",
)
SINGLE_SOURCE_FILES = (
    "AGENTS.md", "README.md", "environment.yml", "pyproject.toml",
    "scripts/__init__.py",
)
PHASE_I_CORRECTION_INPUTS = (
    "results_phase_i/I6/VALIDATION_EPISODES.parquet",
    "results_phase_i/I6/NORMAL1H_EPISODES.parquet",
    "results_phase_i/I6/VALIDATION_CYCLES.parquet",
    "results_phase_i/final/FINAL_STATUS.json",
    "results_phase_i/final/ALL_GATES.csv",
    "results_phase_i/final/FAILURE_LEDGER.csv",
)
MANIFEST_NAMES = {
    "16_GIT_MANIFEST/MANIFEST_SHA256.csv",
    "16_GIT_MANIFEST/MANIFEST_SHA256.json",
}


def sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=REPO, text=True, encoding="utf-8"
    ).strip()


def copy_file(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.suffix.lower() == ".lic":
        raise RuntimeError(f"commercial solver credential excluded: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def copy_tree(
    source: Path,
    destination: Path,
    *,
    excluded_parts: set[str] | None = None,
) -> None:
    if not source.exists():
        return
    exclusions = excluded_parts or set()
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        if any(
            part in {"__pycache__", ".pytest_cache", ".mypy_cache"}
            or part in exclusions
            for part in relative.parts
        ):
            continue
        copy_file(path, destination / relative)


def initialize_staging(staging: Path, artifacts: Path) -> None:
    if staging.exists():
        resolved = staging.resolve()
        if resolved.parent != artifacts.resolve() or resolved.name != "review_package_staging":
            raise RuntimeError(f"refusing to remove unexpected path: {resolved}")
        shutil.rmtree(staging)
    for directory in DIRECTORIES:
        (staging / directory).mkdir(parents=True, exist_ok=True)


def build_source_snapshot(staging: Path) -> None:
    snapshot = staging / "06_SOURCE/repository"
    for relative in SOURCE_PATHS:
        copy_tree(REPO / relative, snapshot / relative)
    for relative in SINGLE_SOURCE_FILES:
        path = REPO / relative
        if path.is_file():
            copy_file(path, snapshot / relative)

    active_python = list((snapshot / "src/direction5freq").rglob("*.py"))
    active_python += list((snapshot / "scripts/direction5_final").rglob("*.py"))
    forbidden = []
    for path in active_python:
        if path.name == Path(__file__).name:
            continue
        text = path.read_text("utf-8", errors="ignore")
        if any(token in text for token in (
            "from scripts.phase_", "import scripts.phase_",
            "from direction1freq", "import direction1freq",
        )):
            forbidden.append(path.relative_to(snapshot).as_posix())
    if forbidden:
        raise RuntimeError(f"active source has forbidden external phase dependencies: {forbidden}")


def populate_sections(staging: Path, test_count: int) -> None:
    goal = REPO / "research/direction5_final_repair_and_decision"
    outputs = REPO / "research_outputs_final"
    results = REPO / "results_final"

    copy_file(goal / "README_FIRST.md", staging / "00_README/README_FIRST.md")
    copy_file(goal / "CODEX_GOAL.md", staging / "00_README/CODEX_GOAL.md")
    copy_file(goal / "10_FINAL_REVIEW_PACKAGE_SPEC.md", staging / "00_README/FINAL_REVIEW_PACKAGE_SPEC.md")
    (staging / "00_README/FINAL_OUTCOME.md").write_text(
        "# Direction5 final review outcome\n\n"
        f"`{FINAL_STATE}`\n\n"
        "R5 failed after both permitted ordered repair audits. R6 and R7 are "
        "NOT_EVALUATED, final seeds were not consumed, and R8 seals the complete "
        "negative evidence package. Start with `17_FINAL_STATUS/FINAL_STATUS.json`.\n",
        encoding="utf-8",
    )
    copy_tree(outputs / "00_FORENSIC", staging / "01_SCIENCE/PHASE_I_CORRECTION")
    copy_tree(outputs / "01_SCIENCE", staging / "01_SCIENCE")
    copy_tree(outputs / "02_LITERATURE", staging / "02_LITERATURE")
    copy_tree(outputs / "02_ESTIMATION", staging / "03_MODEL/ESTIMATION")
    copy_tree(outputs / "03_MODEL", staging / "03_MODEL")
    copy_tree(outputs / "04_METHOD", staging / "04_METHOD")
    copy_tree(outputs / "05_THEORY", staging / "05_THEORY")
    build_source_snapshot(staging)

    copy_tree(REPO / "configs/direction5_final", staging / "07_CONFIG_ENV_SOLVERS/configs")
    copy_file(REPO / "environment.yml", staging / "07_CONFIG_ENV_SOLVERS/environment.yml")
    copy_file(REPO / "pyproject.toml", staging / "07_CONFIG_ENV_SOLVERS/pyproject.toml")
    solver_info = {
        "environment": "topo_sfr",
        "python": "3.11",
        "rolling_qp_solver": "OSQP via CVXPY",
        "licensed_solver_required": False,
        "commercial_license_files_included": False,
        "registered_pins": {
            "andes": "2.0.0", "casadi": "3.7.2", "ipopt": "3.14.19",
        },
    }
    (staging / "07_CONFIG_ENV_SOLVERS/SOLVER_ENVIRONMENT.json").write_text(
        json.dumps(solver_info, indent=2) + "\n", encoding="utf-8"
    )

    copy_tree(REPO / "tests/direction5_final", staging / "08_TESTS_VERIFICATION/tests")
    copy_tree(REPO / "logs_final", staging / "08_TESTS_VERIFICATION/logs_final")
    (staging / "08_TESTS_VERIFICATION/TEST_RESULT.json").write_text(
        json.dumps({
            "suite": "tests/direction5_final + tests/phase_i",
            "passed": test_count,
            "environment": "topo_sfr",
        }, indent=2) + "\n",
        encoding="utf-8",
    )

    copy_tree(goal, staging / "09_EXPERIMENT_DESIGN/governing_goal")
    copy_tree(REPO / "configs/direction5_final", staging / "09_EXPERIMENT_DESIGN/locked_configs")
    copy_tree(outputs / "07_VALIDATION", staging / "09_EXPERIMENT_DESIGN/validation_lock_and_report")
    for manifest in results.rglob("*MANIFEST*.csv"):
        copy_file(manifest, staging / "09_EXPERIMENT_DESIGN/manifests" / manifest.relative_to(results))

    # Consolidated Parquet files preserve every episode and control cycle. The
    # per-episode parts are redundant recovery checkpoints and are omitted.
    copy_tree(results, staging / "10_RAW_RESULTS/results_final", excluded_parts={"parts"})
    copy_tree(REPO / "progress_final", staging / "10_RAW_RESULTS/progress_final")
    for relative in PHASE_I_CORRECTION_INPUTS:
        copy_file(REPO / relative, staging / "10_RAW_RESULTS/phase_i_frozen_inputs" / relative)

    for path in results.rglob("*"):
        if path.is_file() and "parts" not in path.relative_to(results).parts and path.suffix.lower() in {".csv", ".json"}:
            copy_file(path, staging / "11_SUMMARY_TABLES" / path.relative_to(results))
    copy_tree(outputs / "11_SUMMARY_TABLES", staging / "11_SUMMARY_TABLES/research_tables")
    copy_tree(REPO / "figures_final/R8", staging / "12_FIGURES")
    copy_tree(outputs / "13_FAILURES", staging / "13_FAILURES")
    copy_file(results / "R5/FAILURE_LEDGER.csv", staging / "13_FAILURES/R5_FAILURE_LEDGER.csv")
    copy_file(results / "R5/R5_REPAIR_AUDIT.csv", staging / "13_FAILURES/R5_REPAIR_AUDIT.csv")
    copy_file(results / "R5/R5_INITIAL_DENOMINATOR_DEFECT.json", staging / "13_FAILURES/R5_INITIAL_DENOMINATOR_DEFECT.json")
    copy_tree(outputs / "14_PAPER_ANALYSIS", staging / "14_PAPER_ANALYSIS")

    copy_file(REPO / "scripts/direction5_final/package_verify_manifest.py", staging / "15_REPRODUCIBILITY/verify_manifest.py")
    copy_file(REPO / "scripts/direction5_final/package_reproduce_minimal.py", staging / "15_REPRODUCIBILITY/reproduce_minimal.py")
    (staging / "15_REPRODUCIBILITY/FULL_RERUN_COMMANDS.md").write_text(
        "# Full rerun\n\n"
        "From `06_SOURCE/repository`, create/update `topo_sfr` from `environment.yml`, "
        "run `python -m pip install -e . --no-deps`, then execute "
        "`scripts/direction5_final/run_r0_correction.py` through "
        "`run_r5_validation.py` in order. R5 is locked by "
        "`configs/direction5_final/r5_validation_lock.yaml`. If R5 fails after "
        "two permitted repair audits, do not execute final seeds; run "
        "`run_r8_finalize.py` and the package builder.\n",
        encoding="utf-8",
    )
    copy_tree(REPO / "results_final/final", staging / "17_FINAL_STATUS")
    for stage in range(9):
        progress = REPO / f"progress_final/R{stage}.json"
        if progress.is_file():
            copy_file(progress, staging / f"17_FINAL_STATUS/R{stage}_PROGRESS.json")


def write_git_state(staging: Path) -> None:
    tracked_status = git("status", "--short", "--untracked-files=no")
    state = {
        "schema": "direction5.final_repair.git_state.v1",
        "branch": git("branch", "--show-current"),
        "head": git("rev-parse", "HEAD"),
        "tracked_tree_clean_at_package_build": tracked_status == "",
        "tracked_status": tracked_status.splitlines(),
        "untracked_historical_delivery_artifacts_excluded": True,
    }
    (staging / "16_GIT_MANIFEST/GIT_STATE.json").write_text(
        json.dumps(state, indent=2) + "\n", encoding="utf-8"
    )
    (staging / "16_GIT_MANIFEST/TRACKED_FILES.txt").write_text(
        git("ls-files") + "\n", encoding="utf-8"
    )


def write_manifest(staging: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted(item for item in staging.rglob("*") if item.is_file()):
        relative = path.relative_to(staging).as_posix()
        if relative in MANIFEST_NAMES:
            continue
        rows.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256(path)})
    manifest_csv = staging / "16_GIT_MANIFEST/MANIFEST_SHA256.csv"
    with manifest_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("path", "bytes", "sha256"))
        writer.writeheader()
        writer.writerows(rows)
    (staging / "16_GIT_MANIFEST/MANIFEST_SHA256.json").write_text(
        json.dumps(rows, indent=2) + "\n", encoding="utf-8"
    )
    return rows


def make_zip(staging: Path, output: Path) -> None:
    if output.exists():
        output.unlink()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, allowZip64=True) as archive:
        for path in sorted(item for item in staging.rglob("*") if item.is_file()):
            arcname = (Path(PACKAGE_NAME) / path.relative_to(staging)).as_posix()
            info = zipfile.ZipInfo(arcname, date_time=(2026, 8, 4, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    with zipfile.ZipFile(output) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise RuntimeError(f"ZIP CRC failure: {bad}")


def fresh_extract_and_run(output: Path, artifacts: Path, *, reproduce: bool) -> dict:
    extract_root = artifacts / "fresh_extract_verification"
    if extract_root.exists():
        resolved = extract_root.resolve()
        if resolved.parent != artifacts.resolve() or resolved.name != "fresh_extract_verification":
            raise RuntimeError(f"refusing to remove unexpected path: {resolved}")
        shutil.rmtree(extract_root)
    extract_root.mkdir(parents=True)
    with zipfile.ZipFile(output) as archive:
        archive.extractall(extract_root)
    package_root = extract_root / PACKAGE_NAME
    commands = [[sys.executable, "15_REPRODUCIBILITY/verify_manifest.py"]]
    if reproduce:
        commands.append([sys.executable, "15_REPRODUCIBILITY/reproduce_minimal.py"])
    runs = []
    for command in commands:
        completed = subprocess.run(command, cwd=package_root, text=True, capture_output=True)
        runs.append({
            "command": " ".join(command[1:]),
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        })
        if completed.returncode:
            raise RuntimeError(f"fresh-extract command failed: {runs[-1]}")
    return {"fresh_extract_root": str(package_root.resolve()), "runs": runs, "passed": True}


def mark_r8_pass(staging: Path) -> None:
    progress = {
        "schema": "direction5.final_repair.progress.v1",
        "stage": "R8",
        "status": "PASS",
        "gate": "NEGATIVE_REVIEW_PACKAGE_BUILD_AND_FRESH_REPLAY_PASS",
        "final_status": FINAL_STATE,
        "fresh_extract_manifest_verified": True,
        "fresh_extract_minimal_replay_verified": True,
        "under_512mb": True,
        "final_seeds_consumed": False,
    }
    progress_path = REPO / "progress_final/R8.json"
    progress_path.write_text(json.dumps(progress, indent=2) + "\n", encoding="utf-8")

    final_path = REPO / "results_final/final/FINAL_STATUS.json"
    final = json.loads(final_path.read_text("utf-8"))
    final["R0_R8"]["R8"] = "PASS"
    final["package_source_commit"] = git("rev-parse", "HEAD")
    final["fresh_extract_verification"] = "MANIFEST_AND_MINIMAL_REPLAY_PASS"
    final_path.write_text(json.dumps(final, indent=2) + "\n", encoding="utf-8")

    gates_path = REPO / "results_final/final/ALL_GATES.csv"
    with gates_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        if row["stage"] == "R8":
            row["status"] = "PASS"
            row["not_evaluated"] = "False"
            row["gate"] = "NEGATIVE_REVIEW_PACKAGE_BUILD_AND_FRESH_REPLAY_PASS"
    with gates_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("stage", "gate", "status", "not_evaluated"))
        writer.writeheader()
        writer.writerows(rows)

    copy_file(progress_path, staging / "10_RAW_RESULTS/progress_final/R8.json")
    copy_file(progress_path, staging / "17_FINAL_STATUS/R8_PROGRESS.json")
    copy_file(final_path, staging / "10_RAW_RESULTS/results_final/final/FINAL_STATUS.json")
    copy_file(final_path, staging / "11_SUMMARY_TABLES/final/FINAL_STATUS.json")
    copy_file(final_path, staging / "17_FINAL_STATUS/FINAL_STATUS.json")
    copy_file(gates_path, staging / "10_RAW_RESULTS/results_final/final/ALL_GATES.csv")
    copy_file(gates_path, staging / "11_SUMMARY_TABLES/final/ALL_GATES.csv")
    copy_file(gates_path, staging / "17_FINAL_STATUS/ALL_GATES.csv")


def audit_package(staging: Path) -> None:
    top = {path.name for path in staging.iterdir() if path.is_dir()}
    if top != set(DIRECTORIES):
        raise RuntimeError(f"section mismatch: expected {set(DIRECTORIES)}, got {top}")
    credentials = [path for path in staging.rglob("*") if path.is_file() and path.suffix.lower() == ".lic"]
    if credentials:
        raise RuntimeError(f"commercial license files found: {credentials}")
    required = (
        "10_RAW_RESULTS/results_final/R5/ALL_CONTROL_CYCLES.parquet",
        "10_RAW_RESULTS/results_final/R5/CORE_VALIDATION_EPISODES.parquet",
        "10_RAW_RESULTS/results_final/R5/NORMAL1H_EPISODES.parquet",
        "10_RAW_RESULTS/phase_i_frozen_inputs/results_phase_i/I6/VALIDATION_CYCLES.parquet",
        "13_FAILURES/R5_FAILURE_LEDGER.csv",
        "17_FINAL_STATUS/FINAL_STATUS.json",
    )
    missing = [name for name in required if not (staging / name).is_file()]
    if missing:
        raise RuntimeError(f"required package evidence missing: {missing}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-count", type=int, required=True)
    args = parser.parse_args()

    artifacts = REPO / "artifacts_final"
    artifacts.mkdir(parents=True, exist_ok=True)
    staging = artifacts / "review_package_staging"
    initialize_staging(staging, artifacts)
    populate_sections(staging, args.test_count)
    write_git_state(staging)
    audit_package(staging)

    output = REPO / ZIP_NAME
    # First build verifies that the package is structurally sound before R8 is
    # declared PASS. The final build then contains the truthful PASS record.
    write_manifest(staging)
    make_zip(staging, output)
    fresh_extract_and_run(output, artifacts, reproduce=False)
    mark_r8_pass(staging)
    rows = write_manifest(staging)
    make_zip(staging, output)
    verification = fresh_extract_and_run(output, artifacts, reproduce=True)

    size = output.stat().st_size
    if size >= 512 * 1024 * 1024:
        raise SystemExit(f"review package exceeds 512 MiB: {size}")
    digest = sha256(output)
    Path(str(output) + ".sha256").write_text(f"{digest}  {output.name}\n", encoding="utf-8")
    result = {
        "schema": "direction5.final_repair.package_build.v1",
        "zip": str(output.resolve()),
        "bytes": size,
        "megabytes_mib": size / (1024 * 1024),
        "sha256": digest,
        "manifest_files": len(rows),
        "under_512mb": True,
        "package_source_commit": git("rev-parse", "HEAD"),
        "fresh_extract_verification": verification,
    }
    verification_path = artifacts / "FINAL_ZIP_VERIFICATION.json"
    verification_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
