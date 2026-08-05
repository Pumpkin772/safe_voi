"""Build and fresh-extract verify the final Direction5 closure review ZIP."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE_NAME = "DIRECTION5_CLOSURE_CONFIRMATION_AND_MANUSCRIPT_SINGLE_REVIEW_PACKAGE"
ZIP_PATH = ROOT / f"{PACKAGE_NAME}.zip"
ARTIFACTS = ROOT / "artifacts_closure"
STAGING_PARENT = ARTIFACTS / "review_package_staging"
STAGING = STAGING_PARENT / PACKAGE_NAME
FINAL_STATE = "DIRECTION5_NEGATIVE_RESULT_CONFIRMED_AND_ARCHIVED"
DIRECTORIES = (
    "00_README", "01_AUDIT", "02_SCIENCE", "03_LITERATURE", "04_MODEL_METHOD",
    "05_VALIDATION", "06_CONFIRMATORY", "07_MECHANISM_ANALYSIS", "08_THEORY",
    "09_SOURCE_ENV", "10_TESTS", "11_RAW_RESULTS", "12_SUMMARY_TABLES",
    "13_FIGURES", "14_FAILURES", "15_PAPER_DRAFT", "16_REPRODUCIBILITY",
    "17_GIT_MANIFEST", "18_FINAL_STATUS",
)
EXCLUDED_PARTS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "review_package_staging"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_reset(path: Path, permitted_parent: Path) -> None:
    resolved = path.resolve()
    if resolved.parent != permitted_parent.resolve() or resolved.name != PACKAGE_NAME:
        raise RuntimeError(f"unsafe staging target: {resolved}")
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def allowed(path: Path) -> bool:
    if any(part in EXCLUDED_PARTS for part in path.parts):
        return False
    if path.suffix.lower() in {".pyc", ".pyo", ".lic"}:
        return False
    if path.name.lower() in {"gurobi.lic", "mosek.lic"}:
        return False
    return True


def copy_file(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    if not allowed(source):
        raise RuntimeError(f"excluded file requested: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def copy_tree(source: Path, destination: Path, predicate=None) -> None:
    if not source.is_dir():
        raise FileNotFoundError(source)
    for path in sorted(source.rglob("*")):
        if not path.is_file() or not allowed(path):
            continue
        rel = path.relative_to(source)
        if predicate is not None and not predicate(path, rel):
            continue
        copy_file(path, destination / rel)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, encoding="utf-8", errors="replace").strip()


def assemble() -> None:
    STAGING_PARENT.mkdir(parents=True, exist_ok=True)
    safe_reset(STAGING, STAGING_PARENT)
    for directory in DIRECTORIES:
        (STAGING / directory).mkdir()

    final = json.loads((ROOT / "results_closure/final/FINAL_STATUS.json").read_text(encoding="utf-8"))
    if final["final_status"] != FINAL_STATE:
        raise RuntimeError("closure final state is not the registered negative state")

    readme = f"""# Direction5 closure confirmation and manuscript review package

Final state: `{FINAL_STATE}`

This archive freezes DCSV-CR-MPC and contains the independent C0 audit, C1 mechanism analysis, one-time final-seed C2 confirmation, actual-results manuscript, publication figures, complete active source snapshot, environment, tests, validation/confirmation raw results, all recorded failures, and standard-library fresh-extract replay.

Start with:

```text
python 16_REPRODUCIBILITY/verify_manifest.py
python 16_REPRODUCIBILITY/reproduce_minimal.py
```

The registered positive Gate failed in validation and confirmation. This is a bounded negative result for the frozen realization and protocol, not a method-class impossibility claim. Final seeds are consumed and no post-result tuning or new Direction5 phase is permitted.
"""
    write_text(STAGING / "00_README/README_FIRST.md", readme)
    copy_file(ROOT / "research/DIRECTION5_CLOSURE_CONFIRMATION_AND_MANUSCRIPT_CODEX_PACKAGE/04_FINAL_PACKAGE_SPEC.md", STAGING / "00_README/FINAL_PACKAGE_SPEC.md")
    copy_file(ROOT / "research/DIRECTION5_CLOSURE_CONFIRMATION_AND_MANUSCRIPT_CODEX_PACKAGE/README_FIRST.md", STAGING / "00_README/GOVERNING_PACKAGE_README.md")

    # Independent audit and the exact frozen package it audited.
    copy_tree(ROOT / "research_outputs_closure/00_AUDIT", STAGING / "01_AUDIT/C0_INDEPENDENT_AUDIT")
    copy_tree(ROOT / "research_outputs_closure/02_CONFIRMATORY/AUDIT", STAGING / "01_AUDIT/C2_POSTRUN_AUDIT")
    copy_file(ROOT / "progress_closure/C0.json", STAGING / "01_AUDIT/C0.json")
    copy_file(ROOT / "DIRECTION5_FINAL_REPAIR_AND_DECISION_SINGLE_REVIEW_PACKAGE.zip", STAGING / "01_AUDIT/FROZEN_R_PACKAGE/DIRECTION5_FINAL_REPAIR_AND_DECISION_SINGLE_REVIEW_PACKAGE.zip")
    copy_file(ROOT / "DIRECTION5_FINAL_REPAIR_AND_DECISION_SINGLE_REVIEW_PACKAGE.zip.sha256", STAGING / "01_AUDIT/FROZEN_R_PACKAGE/DIRECTION5_FINAL_REPAIR_AND_DECISION_SINGLE_REVIEW_PACKAGE.zip.sha256")

    # Governing science, literature, method, and theory.
    copy_tree(ROOT / "research/DIRECTION5_CLOSURE_CONFIRMATION_AND_MANUSCRIPT_CODEX_PACKAGE", STAGING / "02_SCIENCE/GOVERNING_GOAL")
    copy_tree(ROOT / "research_outputs_final/01_SCIENCE", STAGING / "02_SCIENCE/FROZEN_SCIENCE")
    copy_tree(ROOT / "research_outputs_final/02_LITERATURE", STAGING / "03_LITERATURE")
    copy_tree(ROOT / "research_outputs_final/03_MODEL", STAGING / "04_MODEL_METHOD/MODEL")
    copy_tree(ROOT / "research_outputs_final/04_METHOD", STAGING / "04_MODEL_METHOD/METHOD")
    copy_tree(ROOT / "research_outputs_final/02_ESTIMATION", STAGING / "04_MODEL_METHOD/ESTIMATION")
    copy_tree(ROOT / "research_outputs_final/05_THEORY", STAGING / "08_THEORY/REPORTS")
    copy_tree(ROOT / "results_final/R4", STAGING / "08_THEORY/CERTIFICATES")

    # Validation summaries (raw evidence is retained separately without deletion).
    r5 = ROOT / "results_final/R5"
    validation_names = (
        "R5_SUMMARY.json", "CORE_METRIC_GATES.csv", "CORRECTED_METRIC_SUMMARY.csv",
        "HIERARCHICAL_BOOTSTRAP.csv", "PAIRED_FAILURE_TABLE.csv", "KNOWN_OOD_SUMMARY.csv",
        "DOMAIN_STATISTICS.csv", "PLANT_DIRECTION_CONSISTENCY.csv", "SOLVER_DENOMINATOR.csv",
        "SOLVER_STATUS_COUNTS.csv", "ALL_BASELINE_RANKING.csv", "NORMAL1H_QUALITY.csv",
        "CONTRACT_VIOLATION_SUMMARY.csv", "FAILURE_LEDGER.csv", "PLANT_A_VALIDATION_MANIFEST.csv",
        "PLANT_B_VALIDATION_MANIFEST.csv", "NORMAL1H_MANIFEST.csv", "CONTRACT_VIOLATION_MANIFEST.csv",
        "FACTOR_INDEPENDENCE_AUDIT.csv", "R5_REPAIR_AUDIT.csv",
    )
    for name in validation_names:
        copy_file(r5 / name, STAGING / "05_VALIDATION" / name)
    copy_tree(ROOT / "research_outputs_final/07_VALIDATION", STAGING / "05_VALIDATION/REPORTS")

    # Confirmation evidence and mechanism analysis.
    copy_tree(ROOT / "research_outputs_closure/02_CONFIRMATORY", STAGING / "06_CONFIRMATORY")
    for name in ("C2_SUMMARY.json", "FINAL_SEEDS_CONSUMED.json", "FINAL_PAIRED_ROWS.parquet"):
        copy_file(ROOT / "results_closure/C2" / name, STAGING / "06_CONFIRMATORY" / name)
    copy_tree(ROOT / "research_outputs_closure/01_MECHANISM", STAGING / "07_MECHANISM_ANALYSIS")

    # Complete active repository source/environment snapshot.
    repository = STAGING / "09_SOURCE_ENV/repository"
    for tree in (
        "src/direction5freq", "scripts/direction5_final", "scripts/direction5_closure",
        "tests/direction5_final", "tests/direction5_closure", "configs/direction5_final",
        "configs/direction5_closure", "research/DIRECTION5_CLOSURE_CONFIRMATION_AND_MANUSCRIPT_CODEX_PACKAGE",
    ):
        copy_tree(ROOT / tree, repository / tree)
    for name in ("AGENTS.md", "README.md", "environment.yml", "pyproject.toml", "scripts/__init__.py"):
        copy_file(ROOT / name, repository / name)
    copy_tree(ROOT / "research_outputs_closure/05_ARCHIVE", STAGING / "09_SOURCE_ENV/ARCHIVE_DOCUMENTATION")

    # Focused tests plus a test run produced by this builder.
    copy_tree(ROOT / "tests/direction5_final", STAGING / "10_TESTS/tests/direction5_final")
    copy_tree(ROOT / "tests/direction5_closure", STAGING / "10_TESTS/tests/direction5_closure")
    test_command = [sys.executable, "-m", "pytest", "tests/direction5_final", "tests/direction5_closure", "-q"]
    test_run = subprocess.run(test_command, cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True)
    write_text(STAGING / "10_TESTS/TEST_COMMANDS.md", "# Test commands\n\n`python -m pytest tests/direction5_final tests/direction5_closure -q`\n")
    write_text(STAGING / "10_TESTS/FOCUSED_TEST_RUN.txt", test_run.stdout + "\n" + test_run.stderr)
    write_text(STAGING / "10_TESTS/FOCUSED_TEST_STATUS.json", json.dumps({"command": test_command[1:], "returncode": test_run.returncode, "passed": test_run.returncode == 0}, indent=2))
    if test_run.returncode != 0:
        raise RuntimeError("focused package tests failed")

    # Full raw validation and confirmatory evidence, including every failed part.
    copy_tree(ROOT / "results_final", STAGING / "11_RAW_RESULTS/results_final")
    copy_tree(ROOT / "results_closure/C2", STAGING / "11_RAW_RESULTS/results_closure/C2")
    copy_tree(ROOT / "research_outputs_final/11_SUMMARY_TABLES", STAGING / "12_SUMMARY_TABLES/VALIDATION")
    copy_tree(ROOT / "research_outputs_closure/04_FIGURES/SOURCE_DATA", STAGING / "12_SUMMARY_TABLES/FIGURE_SOURCE_DATA")
    copy_tree(ROOT / "results_closure/final", STAGING / "12_SUMMARY_TABLES/FINAL")

    copy_tree(ROOT / "figures_closure/C4", STAGING / "13_FIGURES/CLOSURE")
    copy_tree(ROOT / "figures_final", STAGING / "13_FIGURES/VALIDATION")
    copy_file(ROOT / "research_outputs_closure/04_FIGURES/FIGURE_INDEX.csv", STAGING / "13_FIGURES/FIGURE_INDEX.csv")

    # Failures and logs are retained, not filtered by outcome.
    copy_tree(ROOT / "research_outputs_final/13_FAILURES", STAGING / "14_FAILURES/VALIDATION")
    copy_tree(ROOT / "logs_final", STAGING / "14_FAILURES/logs_final")
    copy_tree(ROOT / "logs_closure/C2", STAGING / "14_FAILURES/logs_closure/C2")
    copy_file(ROOT / "results_final/R5/FAILURE_LEDGER.csv", STAGING / "14_FAILURES/VALIDATION_FAILURE_LEDGER.csv")
    copy_file(ROOT / "research_outputs_closure/02_CONFIRMATORY/FINAL_PAIRED_FAILURES.csv", STAGING / "14_FAILURES/CONFIRMATORY_PAIRED_FAILURES.csv")
    copy_file(ROOT / "research_outputs_closure/01_MECHANISM/FALLBACK_ROOT_CAUSE_SUMMARY.csv", STAGING / "14_FAILURES/FALLBACK_ROOT_CAUSE_SUMMARY.csv")
    copy_file(ROOT / "research_outputs_closure/01_MECHANISM/NORMAL1H_ROOT_CAUSE.md", STAGING / "14_FAILURES/NORMAL1H_ROOT_CAUSE.md")

    copy_tree(ROOT / "research_outputs_closure/03_PAPER", STAGING / "15_PAPER_DRAFT")
    copy_file(ROOT / "scripts/direction5_closure/package_verify_manifest.py", STAGING / "16_REPRODUCIBILITY/verify_manifest.py")
    copy_file(ROOT / "scripts/direction5_closure/package_reproduce_minimal.py", STAGING / "16_REPRODUCIBILITY/reproduce_minimal.py")
    copy_file(ROOT / "research_outputs_closure/05_ARCHIVE/REPRODUCIBILITY_MAP.md", STAGING / "16_REPRODUCIBILITY/REPRODUCIBILITY_MAP.md")
    write_text(STAGING / "16_REPRODUCIBILITY/REPRODUCE_ALL.md", """# Full reproduction boundary

Install the pinned environment from `09_SOURCE_ENV/repository/environment.yml`, install the snapshot editable, and run the focused tests. Validation and analysis scripts are retained with locked configuration and all raw data. The final-seed confirmation is scientifically consumed and must not be rerun as a new independent sample or used for retuning. Re-analysis of archived rows is permitted; any rerun must be labeled a replay, not new confirmation evidence.
""")

    # Git provenance and final status.
    git_state = {
        "schema": "direction5.closure.git_state.v1",
        "commit": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
        "tracked_status": git("status", "--short", "--untracked-files=no"),
        "tagged_frozen_parent": git("rev-parse", "direction5-final-repair-reviewed"),
        "untracked_delivery_artifacts_excluded_from_status": True,
    }
    write_text(STAGING / "17_GIT_MANIFEST/GIT_STATE.json", json.dumps(git_state, indent=2))
    write_text(STAGING / "17_GIT_MANIFEST/GIT_LOG.txt", git("log", "--oneline", "--decorate", "-30"))
    write_text(STAGING / "17_GIT_MANIFEST/TRACKED_FILES.txt", git("ls-files"))
    copy_file(ROOT / "research_outputs_closure/05_ARCHIVE/ARCHIVE_INPUT_SHA256.csv", STAGING / "17_GIT_MANIFEST/REPOSITORY_INPUT_SHA256.csv")

    copy_tree(ROOT / "results_closure/final", STAGING / "18_FINAL_STATUS")
    copy_tree(ROOT / "progress_closure", STAGING / "18_FINAL_STATUS/progress_closure")
    copy_tree(ROOT / "progress_final", STAGING / "18_FINAL_STATUS/progress_final")
    copy_file(ROOT / "research_outputs_closure/06_FINAL/FINAL_DECISION.md", STAGING / "18_FINAL_STATUS/FINAL_DECISION.md")

    # Required naming/directories and credential exclusion.
    if {path.name for path in STAGING.iterdir() if path.is_dir()} != set(DIRECTORIES):
        raise RuntimeError("package directory specification mismatch")
    forbidden = [path for path in STAGING.rglob("*") if path.is_file() and path.suffix.lower() == ".lic"]
    if forbidden:
        raise RuntimeError(f"license files found: {forbidden}")

    # Package manifest excludes only its own CSV/JSON representations.
    excluded = {"17_GIT_MANIFEST/MANIFEST_SHA256.csv", "17_GIT_MANIFEST/MANIFEST_SHA256.json"}
    rows = []
    for path in sorted(STAGING.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(STAGING).as_posix()
        if rel in excluded:
            continue
        rows.append({"path": rel, "bytes": path.stat().st_size, "sha256": sha256(path)})
    manifest_csv = STAGING / "17_GIT_MANIFEST/MANIFEST_SHA256.csv"
    with manifest_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["path", "bytes", "sha256"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    write_text(STAGING / "17_GIT_MANIFEST/MANIFEST_SHA256.json", json.dumps({"schema": "direction5.closure.package_manifest.v1", "files": rows}, indent=2))


def build_zip() -> None:
    if ZIP_PATH.exists():
        if ZIP_PATH.parent.resolve() != ROOT.resolve() or ZIP_PATH.name != f"{PACKAGE_NAME}.zip":
            raise RuntimeError("unsafe ZIP overwrite target")
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, allowZip64=True) as archive:
        for path in sorted(STAGING.rglob("*")):
            if path.is_file():
                archive.write(path, f"{PACKAGE_NAME}/{path.relative_to(STAGING).as_posix()}")
    if ZIP_PATH.stat().st_size >= 512 * 1024 * 1024:
        raise RuntimeError("review ZIP exceeds 512 MiB")
    with zipfile.ZipFile(ZIP_PATH) as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC failure: {bad}")


def fresh_extract_replay() -> tuple[dict, dict]:
    with tempfile.TemporaryDirectory(prefix="direction5_closure_verify_") as temp:
        target = Path(temp)
        with zipfile.ZipFile(ZIP_PATH) as archive:
            archive.extractall(target)
        root = target / PACKAGE_NAME
        outputs = []
        for script in ("verify_manifest.py", "reproduce_minimal.py"):
            run = subprocess.run([sys.executable, f"16_REPRODUCIBILITY/{script}"], cwd=root, text=True, encoding="utf-8", errors="replace", capture_output=True)
            if run.returncode != 0:
                raise RuntimeError(f"fresh-extract {script} failed:\n{run.stdout}\n{run.stderr}")
            outputs.append(json.loads(run.stdout))
        return outputs[0], outputs[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=ARTIFACTS / "FINAL_ZIP_VERIFICATION.json")
    args = parser.parse_args()
    assemble()
    build_zip()
    manifest_result, replay_result = fresh_extract_replay()
    sidecar = ROOT / f"{ZIP_PATH.name}.sha256"
    digest = sha256(ZIP_PATH)
    write_text(sidecar, f"{digest}  {ZIP_PATH.name}")
    report = {
        "schema": "direction5.closure.zip_verification.v1",
        "package": ZIP_PATH.name,
        "zip_absolute_path": str(ZIP_PATH.resolve()),
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_mib": ZIP_PATH.stat().st_size / (1024 * 1024),
        "zip_sha256": digest,
        "under_512_mib": ZIP_PATH.stat().st_size < 512 * 1024 * 1024,
        "manifest_verification": manifest_result,
        "minimal_replay": replay_result,
        "git_commit": git("rev-parse", "HEAD"),
        "built_utc": datetime.now(timezone.utc).isoformat(),
    }
    report["passed"] = bool(report["under_512_mib"] and manifest_result["passed"] and replay_result["passed"])
    report_path = args.report if args.report.is_absolute() else ROOT / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
