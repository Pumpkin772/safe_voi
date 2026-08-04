"""Build the self-contained Direction5 Phase-I final-convergence review ZIP."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

import pandas as pd


REPO = Path(__file__).resolve().parents[2]
PACKAGE_ROOT_NAME = "DIRECTION5_PHASE_I_FINAL_CONVERGENCE_SINGLE_REVIEW_PACKAGE"
FINAL_ZIP_NAME = f"{PACKAGE_ROOT_NAME}.zip"
DIRECTORIES = tuple(f"{index:02d}_{name}" for index, name in enumerate((
    "README",
    "SCIENCE",
    "LITERATURE",
    "MODEL",
    "METHOD",
    "THEORY",
    "SOURCE",
    "CONFIG_ENV_SOLVERS",
    "TESTS_VERIFICATION",
    "EXPERIMENT_DESIGN",
    "RAW_RESULTS",
    "SUMMARY_TABLES",
    "FIGURES",
    "FAILURES",
    "PAPER_ANALYSIS",
    "REPRODUCIBILITY",
    "GIT_MANIFEST",
    "FINAL_STATUS",
)))
SOURCE_PREFIXES = (
    "src/direction5freq/",
    # Frozen namespaces needed only to replay I0's correction of historical
    # evidence.  The active Phase-I method imports exclusively direction5freq.
    "src/direction5_freq/",
    "src/direction1freq/",
    "scripts/phase_i/",
    "tests/phase_i/",
    "configs/phase_i/",
    "progress_phase_i/",
    "results_phase_i/",
    "figures_phase_i/",
    "research_outputs_phase_i/",
    "research/direction5_phase_i_final_convergence/",
)
SOURCE_SINGLE_FILES = {
    "AGENTS.md",
    "README.md",
    "environment.yml",
    "pyproject.toml",
    "scripts/__init__.py",
    # Minimal frozen Phase-H assets needed by the I0 forensic tests. They are
    # historical evidence, not active Phase-I runtime dependencies.
    "scripts/phase_h/__init__.py",
    "scripts/phase_h/run_h7_validation.py",
    "results_phase_h/H7/H7_VALIDATION_EPISODES.parquet",
}
CHECKPOINT_NAMES = {
    "ALL_EPISODES_CHECKPOINT.parquet",
    "PLANT_A_EPISODES_CHECKPOINT.parquet",
    "PLANT_A_CYCLES_CHECKPOINT.parquet",
    "NORMAL1H_EPISODES_CHECKPOINT.parquet",
    "INTERRUPTED_RUN_1_ALL_EPISODES_CHECKPOINT.parquet",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=REPO, text=True, encoding="utf-8", stderr=subprocess.DEVNULL
    ).strip()


def tracked_files() -> list[str]:
    return git("ls-files").splitlines()


def copy_file(source: Path, destination: Path) -> None:
    if source.suffix.lower() == ".lic":
        raise RuntimeError(f"solver credential excluded: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def copy_tree(source: Path, destination: Path, *, excluded_parts: set[str] | None = None) -> None:
    if not source.exists():
        return
    exclusions = excluded_parts or set()
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        if any(part in {"__pycache__", ".pytest_cache"} or part in exclusions for part in relative.parts):
            continue
        copy_file(path, destination / relative)


def build_source_snapshot(package_root: Path, tracked: list[str]) -> None:
    snapshot = package_root / "06_SOURCE/repository"
    for relative in tracked:
        if relative == "results_phase_i/I6/VALIDATION_CYCLES.parquet":
            # The complete float32/Zstd cycle trace is provided once in
            # 10_RAW_RESULTS.  A rerun regenerates it; duplicating it in the
            # source snapshot wastes package space and violates the size rule.
            continue
        if relative in SOURCE_SINGLE_FILES or relative.startswith(SOURCE_PREFIXES):
            copy_file(REPO / relative, snapshot / relative)
    forbidden = []
    forbidden_markers = (
        "from scripts.phase_e",
        "from scripts.phase_f",
        "from scripts.phase_g",
        "import scripts.phase_e",
        "import scripts.phase_f",
        "import scripts.phase_g",
    )
    for path in snapshot.rglob("*"):
        if path.is_file() and path.suffix.lower() == ".py":
            if path.name == Path(__file__).name:
                continue
            text = path.read_text("utf-8", errors="ignore")
            if any(marker in text for marker in forbidden_markers):
                forbidden.append(path.relative_to(snapshot).as_posix())
    if forbidden:
        raise RuntimeError(f"Phase-I source snapshot has forbidden historical runtime dependencies: {forbidden}")


def copy_results_for_review(package_root: Path) -> None:
    raw_root = package_root / "10_RAW_RESULTS/results_phase_i"
    excluded = set(CHECKPOINT_NAMES) | {"native_episode_parts", "normal1h_episode_parts", "VALIDATION_CYCLES.parquet"}
    copy_tree(REPO / "results_phase_i", raw_root, excluded_parts=excluded)
    cycles = REPO / "results_phase_i/I6/VALIDATION_CYCLES.parquet"
    if not cycles.is_file():
        raise FileNotFoundError("consolidated I6 control-cycle evidence is missing")
    frame = pd.read_parquet(cycles)
    for column in frame.select_dtypes(include=["float64"]).columns:
        frame[column] = frame[column].astype("float32")
    output = raw_root / "I6/VALIDATION_CYCLES.parquet"
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(output, index=False, compression="zstd")
    copy_tree(REPO / "progress_phase_i", package_root / "10_RAW_RESULTS/progress_phase_i")


def populate_sections(package_root: Path, test_count: int) -> None:
    final_docs = REPO / "research_outputs_phase_i/08_FINAL"
    copy_file(final_docs / "PACKAGE_README.md", package_root / "00_README/README_FIRST.md")
    copy_file(REPO / "research/direction5_phase_i_final_convergence/CODEX_GOAL.md", package_root / "00_README/CODEX_GOAL.md")
    copy_file(REPO / "research/direction5_phase_i_final_convergence/09_FINAL_REVIEW_PACKAGE_SPEC.md", package_root / "00_README/FINAL_REVIEW_PACKAGE_SPEC.md")
    copy_tree(REPO / "research_outputs_phase_i/00_FORENSIC", package_root / "01_SCIENCE/PHASE_H_CORRECTION")
    copy_tree(REPO / "research_outputs_phase_i/01_SCIENCE", package_root / "01_SCIENCE")
    copy_tree(REPO / "research_outputs_phase_i/02_LITERATURE", package_root / "02_LITERATURE")
    copy_tree(REPO / "research_outputs_phase_i/03_MODEL", package_root / "03_MODEL")
    copy_tree(REPO / "research_outputs_phase_i/04_ESTIMATION", package_root / "04_METHOD/ESTIMATION")
    copy_tree(REPO / "research_outputs_phase_i/05_METHOD", package_root / "04_METHOD/DCSV_MPC_AND_BASELINES")
    copy_tree(REPO / "research_outputs_phase_i/06_THEORY", package_root / "05_THEORY")
    copy_tree(REPO / "configs/phase_i", package_root / "07_CONFIG_ENV_SOLVERS/configs_phase_i")
    copy_file(REPO / "environment.yml", package_root / "07_CONFIG_ENV_SOLVERS/environment.yml")
    copy_file(REPO / "pyproject.toml", package_root / "07_CONFIG_ENV_SOLVERS/pyproject.toml")
    copy_tree(REPO / "tests/phase_i", package_root / "08_TESTS_VERIFICATION/tests_phase_i")
    copy_tree(REPO / "logs_phase_i", package_root / "08_TESTS_VERIFICATION/logs_phase_i")
    (package_root / "08_TESTS_VERIFICATION/TEST_RESULT.json").write_text(
        json.dumps({"suite": "tests/phase_i", "passed": test_count, "environment": "topo_sfr"}, indent=2) + "\n",
        "utf-8",
    )
    copy_tree(REPO / "research/direction5_phase_i_final_convergence", package_root / "09_EXPERIMENT_DESIGN/governing_goal")
    copy_tree(REPO / "configs/phase_i", package_root / "09_EXPERIMENT_DESIGN/locked_configs")
    for manifest in (REPO / "results_phase_i").rglob("*MANIFEST*.csv"):
        copy_file(manifest, package_root / "09_EXPERIMENT_DESIGN/manifests" / manifest.relative_to(REPO / "results_phase_i"))
    copy_results_for_review(package_root)
    for path in (REPO / "results_phase_i").rglob("*"):
        if path.is_file() and path.suffix.lower() in {".csv", ".json"} and path.name not in CHECKPOINT_NAMES:
            copy_file(path, package_root / "11_SUMMARY_TABLES" / path.relative_to(REPO / "results_phase_i"))
    copy_tree(REPO / "figures_phase_i", package_root / "12_FIGURES")
    for name in (
        "I6_EXECUTION_REPAIR_1.json",
        "INTERRUPTED_RUN_1_ALL_EPISODES_CHECKPOINT.parquet",
        "FAILURE_LEDGER.csv",
    ):
        for path in (REPO / "results_phase_i").rglob(name):
            copy_file(path, package_root / "13_FAILURES" / path.relative_to(REPO / "results_phase_i"))
    copy_file(
        REPO / "logs_phase_i/I6/run_i6_resume_1_stderr.log",
        package_root / "13_FAILURES/I6_NATIVE_ANDES_INITIALIZATION_WARNINGS.log",
    )
    copy_tree(final_docs, package_root / "14_PAPER_ANALYSIS")
    copy_file(REPO / "scripts/phase_i/package_verify_manifest.py", package_root / "15_REPRODUCIBILITY/verify_manifest.py")
    copy_file(REPO / "scripts/phase_i/package_reproduce_minimal.py", package_root / "15_REPRODUCIBILITY/reproduce_minimal.py")
    (package_root / "15_REPRODUCIBILITY/FULL_RERUN_COMMANDS.md").write_text(
        "# Full Phase-I rerun\n\n"
        "From `06_SOURCE/repository`, create or update the registered `topo_sfr` "
        "environment from `environment.yml`, install with `python -m pip install -e . --no-deps`, "
        "then execute `scripts/phase_i/run_i0_forensic.py` through `run_i6_validation.py` in stage order. "
        "I6 is governed by `configs/phase_i/i6_validation_lock.yaml`. If I6 fails, I7 must remain "
        "NOT_EVALUATED; if it passes, execute the committed I7 final lock exactly once. Finally run "
        "the I8 finalization and package builder. No script requires Phase E, F or G source.\n",
        "utf-8",
    )
    copy_file(REPO / "results_phase_i/final/FINAL_STATUS.json", package_root / "17_FINAL_STATUS/FINAL_STATUS.json")
    copy_file(REPO / "progress_phase_i/I8.json", package_root / "17_FINAL_STATUS/I8_PROGRESS.json")


def write_git_state(package_root: Path, tracked: list[str]) -> None:
    status = git("status", "--short", "--untracked-files=no")
    state = {
        "schema": "direction5.phase_i.git_state.v1",
        "branch": git("branch", "--show-current"),
        "head": git("rev-parse", "HEAD"),
        "tracked_tree_clean": status == "",
        "tracked_status": status.splitlines(),
        "historical_untracked_delivery_artifacts_excluded": True,
    }
    (package_root / "16_GIT_MANIFEST/GIT_STATE.json").write_text(json.dumps(state, indent=2) + "\n", "utf-8")
    (package_root / "16_GIT_MANIFEST/TRACKED_FILES.txt").write_text("\n".join(tracked) + "\n", "utf-8")


def write_manifest(package_root: Path) -> list[dict[str, object]]:
    excluded = {"16_GIT_MANIFEST/MANIFEST.csv", "16_GIT_MANIFEST/MANIFEST.json"}
    rows = []
    for path in sorted(item for item in package_root.rglob("*") if item.is_file()):
        relative = path.relative_to(package_root).as_posix()
        if relative not in excluded:
            rows.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256(path)})
    with (package_root / "16_GIT_MANIFEST/MANIFEST.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("path", "bytes", "sha256"))
        writer.writeheader(); writer.writerows(rows)
    (package_root / "16_GIT_MANIFEST/MANIFEST.json").write_text(json.dumps(rows, indent=2) + "\n", "utf-8")
    return rows


def zip_package(package_root: Path, output: Path) -> None:
    if output.exists():
        output.unlink()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, allowZip64=True) as archive:
        for path in sorted(item for item in package_root.rglob("*") if item.is_file()):
            arcname = (Path(PACKAGE_ROOT_NAME) / path.relative_to(package_root)).as_posix()
            info = zipfile.ZipInfo(arcname, date_time=(2026, 8, 4, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trial", action="store_true")
    parser.add_argument("--test-count", type=int, required=True)
    args = parser.parse_args()
    artifacts = REPO / "artifacts_direction5_phase_i"
    artifacts.mkdir(parents=True, exist_ok=True)
    package_root = artifacts / "direction5_i8_staging"
    if package_root.exists():
        if package_root.parent.resolve() != artifacts.resolve() or package_root.name != "direction5_i8_staging":
            raise RuntimeError("refusing to remove unexpected staging path")
        shutil.rmtree(package_root)
    for directory in DIRECTORIES:
        (package_root / directory).mkdir(parents=True, exist_ok=True)
    tracked = tracked_files()
    build_source_snapshot(package_root, tracked)
    populate_sections(package_root, args.test_count)
    write_git_state(package_root, tracked)
    rows = write_manifest(package_root)
    output = REPO / ("DIRECTION5_PHASE_I_FINAL_CONVERGENCE_TRIAL_REVIEW_PACKAGE.zip" if args.trial else FINAL_ZIP_NAME)
    zip_package(package_root, output)
    digest = sha256(output)
    Path(str(output) + ".sha256").write_text(f"{digest}  {output.name}\n", "utf-8")
    result = {
        "schema": "direction5.phase_i.package_build.v1",
        "trial": args.trial,
        "zip": str(output.resolve()),
        "bytes": output.stat().st_size,
        "megabytes": output.stat().st_size / (1024 * 1024),
        "sha256": digest,
        "manifest_files": len(rows),
        "under_512mb": output.stat().st_size < 512 * 1024 * 1024,
        "git_commit": git("rev-parse", "HEAD"),
    }
    (artifacts / ("TRIAL_PACKAGE_BUILD.json" if args.trial else "FINAL_PACKAGE_BUILD.json")).write_text(
        json.dumps(result, indent=2) + "\n", "utf-8"
    )
    print(json.dumps(result, indent=2))
    if not result["under_512mb"]:
        raise SystemExit("review ZIP exceeds 512 MB")


if __name__ == "__main__":
    main()
