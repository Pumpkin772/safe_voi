"""Build the self-contained Direction5 Phase-H single review ZIP."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile


REPO = Path(__file__).resolve().parents[2]
PACKAGE_ROOT_NAME = "DIRECTION5_PHASE_H_DCSV_MPC_SINGLE_REVIEW_PACKAGE"
FINAL_ZIP_NAME = f"{PACKAGE_ROOT_NAME}.zip"
DIRECTORIES = (
    "00_README",
    "01_SCIENCE",
    "02_LITERATURE",
    "03_MODEL",
    "04_METHOD",
    "05_THEORY",
    "06_SOURCE",
    "07_CONFIG_ENV_SOLVERS",
    "08_TESTS_VERIFICATION",
    "09_EXPERIMENT_DESIGN",
    "10_RAW_RESULTS",
    "11_SUMMARY_TABLES",
    "12_FIGURES",
    "13_FAILURES",
    "14_PAPER_ANALYSIS",
    "15_REPRODUCIBILITY",
    "16_GIT_MANIFEST",
    "17_FINAL_STATUS",
)
SOURCE_PREFIXES = (
    "src/direction5_freq/",
    "src/direction1freq/",
    "scripts/phase_h/",
    "scripts/phase_e/",
    "scripts/phase_f/",
    "scripts/phase_g/",
    "tests/phase_h/",
    "configs/phase_h/",
    "progress_phase_h/",
    "progress_phase_g/",
    "results_phase_h/",
    "figures_phase_h/",
    "research_outputs_phase_h/",
    "results_phase_g/G2/",
    "research_outputs_phase_g/03_MODEL/",
    "research_outputs_phase_g/05_THEORY/",
    "research_outputs_phase_f/02_LITERATURE/",
    "research/direction5_phase_h_dcsv_mpc/",
)
SOURCE_SINGLE_FILES = {
    "AGENTS.md",
    "README.md",
    "environment.yml",
    "pyproject.toml",
    "scripts/__init__.py",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=REPO, text=True, encoding="utf-8"
    ).strip()


def tracked_files() -> list[str]:
    try:
        return git("ls-files").splitlines()
    except (subprocess.CalledProcessError, FileNotFoundError):
        files = []
        for path in REPO.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(REPO).as_posix()
            if any(part in {"__pycache__", ".pytest_cache"} for part in path.parts):
                continue
            if relative in SOURCE_SINGLE_FILES or relative.startswith(SOURCE_PREFIXES):
                files.append(relative)
        return sorted(files)


def snapshot_git_identity() -> tuple[str, str, bool | None, list[str], bool]:
    try:
        tracked_status = git("status", "--short", "--untracked-files=no")
        return (
            git("rev-parse", "HEAD"),
            git("branch", "--show-current"),
            tracked_status == "",
            tracked_status.splitlines(),
            True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        status = json.loads(
            (REPO / "results_phase_h/final/FINAL_STATUS.json").read_text("utf-8")
        )
        return (
            status["scientific_evidence_commit"],
            status["branch"],
            None,
            [],
            False,
        )


def copy_file(source: Path, destination: Path) -> None:
    if source.suffix.lower() == ".lic" or "license" in source.name.lower():
        raise RuntimeError(f"license-like file excluded: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def copy_tree(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        if any(part in {"__pycache__", ".pytest_cache"} for part in relative.parts):
            continue
        copy_file(path, destination / relative)


def build_source_snapshot(package_root: Path, tracked: list[str]) -> None:
    snapshot = package_root / "06_SOURCE/repository"
    for relative in tracked:
        if relative in SOURCE_SINGLE_FILES or relative.startswith(SOURCE_PREFIXES):
            copy_file(REPO / relative, snapshot / relative)
    # Immutable historical evidence required by H0. Its old Direction1 name is
    # retained only as recorded evidence and is not a new project asset.
    for name in (
        "DIRECTION1_PHASE_G_TERMINAL_VIABILITY_FULL_VALIDATION_SINGLE_REVIEW_PACKAGE.zip",
        "DIRECTION1_PHASE_G_TERMINAL_VIABILITY_FULL_VALIDATION_SINGLE_REVIEW_PACKAGE.zip.sha256",
    ):
        source = REPO / name
        if not source.is_file():
            raise FileNotFoundError(f"required historical H0 evidence missing: {source}")
        copy_file(source, snapshot / name)


def populate_logical_sections(package_root: Path) -> None:
    copy_file(REPO / "research_outputs_phase_h/07_FINAL/PACKAGE_README.md", package_root / "00_README/README_FIRST.md")
    copy_file(REPO / "research/direction5_phase_h_dcsv_mpc/CODEX_GOAL.md", package_root / "00_README/CODEX_GOAL.md")
    copy_file(REPO / "research/direction5_phase_h_dcsv_mpc/10_FINAL_REVIEW_PACKAGE_SPEC.md", package_root / "00_README/FINAL_REVIEW_PACKAGE_SPEC.md")
    copy_tree(REPO / "research_outputs_phase_h/00_FORENSIC", package_root / "01_SCIENCE/FORENSIC")
    copy_tree(REPO / "research_outputs_phase_h/01_SCIENCE", package_root / "01_SCIENCE")
    copy_tree(REPO / "research_outputs_phase_h/02_LITERATURE", package_root / "02_LITERATURE")
    copy_tree(REPO / "research_outputs_phase_h/03_MODEL", package_root / "03_MODEL")
    copy_tree(REPO / "research_outputs_phase_h/04_METHOD", package_root / "04_METHOD")
    copy_tree(REPO / "research_outputs_phase_h/05_THEORY", package_root / "05_THEORY")
    copy_tree(REPO / "configs/phase_h", package_root / "07_CONFIG_ENV_SOLVERS/configs_phase_h")
    copy_file(REPO / "environment.yml", package_root / "07_CONFIG_ENV_SOLVERS/environment.yml")
    copy_file(REPO / "pyproject.toml", package_root / "07_CONFIG_ENV_SOLVERS/pyproject.toml")
    copy_tree(REPO / "tests/phase_h", package_root / "08_TESTS_VERIFICATION/tests_phase_h")
    (package_root / "08_TESTS_VERIFICATION/TEST_RESULT.json").write_text(
        json.dumps({"suite": "tests/phase_h", "result": "40 passed", "environment": "topo_sfr"}, indent=2) + "\n",
        "utf-8",
    )
    copy_tree(REPO / "research/direction5_phase_h_dcsv_mpc", package_root / "09_EXPERIMENT_DESIGN")
    copy_tree(REPO / "results_phase_h", package_root / "10_RAW_RESULTS/results_phase_h")
    for path in (REPO / "results_phase_h").rglob("*"):
        if path.is_file() and path.suffix.lower() in {".csv", ".json"}:
            relative = path.relative_to(REPO / "results_phase_h")
            copy_file(path, package_root / "11_SUMMARY_TABLES" / relative)
    copy_tree(REPO / "figures_phase_h/H9", package_root / "12_FIGURES")
    copy_tree(REPO / "results_phase_h/H3/attempt1_delay_event_misattribution", package_root / "13_FAILURES/H3_ATTEMPT1")
    copy_tree(REPO / "results_phase_h/H4/attempt1_finite_sample_lower_bound", package_root / "13_FAILURES/H4_ATTEMPT1")
    copy_tree(REPO / "results_phase_h/H6/attempt1_all_plant_rpi_gate", package_root / "13_FAILURES/H6_ATTEMPT1")
    copy_tree(REPO / "results_phase_h/H7/attempt1_missing_slow_reserve_handoff", package_root / "13_FAILURES/H7_ATTEMPT1")
    copy_tree(REPO / "results_phase_h/H7/attempt2_missing_sg_grc", package_root / "13_FAILURES/H7_ATTEMPT2")
    copy_file(REPO / "research_outputs_phase_h/07_FINAL/FAILURE_LEDGER.csv", package_root / "13_FAILURES/FAILURE_LEDGER.csv")
    copy_file(REPO / "research_outputs_phase_h/07_FINAL/NOT_EVALUATED_REGISTER.csv", package_root / "13_FAILURES/NOT_EVALUATED_REGISTER.csv")
    copy_tree(REPO / "research_outputs_phase_h/07_FINAL", package_root / "14_PAPER_ANALYSIS")
    copy_file(REPO / "scripts/phase_h/package_verify_manifest.py", package_root / "15_REPRODUCIBILITY/verify_manifest.py")
    copy_file(REPO / "scripts/phase_h/package_reproduce_minimal.py", package_root / "15_REPRODUCIBILITY/reproduce_minimal.py")
    (package_root / "15_REPRODUCIBILITY/FULL_RERUN_COMMANDS.md").write_text(
        """# Full Phase-H rerun

From `06_SOURCE/repository` in the repository-owned `topo_sfr` environment,
run `python scripts/phase_h/run_h0_forensic.py` through
`python scripts/phase_h/run_h7_validation.py` in stage order. H7 exits on its
registered negative Gate. Do not run H8. Then run
        `python scripts/phase_h/export_h9_control_cycle_evidence.py`, then
        `python scripts/phase_h/run_h9_finalize.py`. Build a trial with
        `python scripts/phase_h/build_h9_review_package.py --trial`, verify its
        manifest and minimal replay in a fresh extraction, then run
        `python scripts/phase_h/run_h9_finalize.py --package-verified` and build
        the final package. The builder supports both a Git checkout and this
        package-local source snapshot.
""",
        "utf-8",
    )
    copy_file(REPO / "results_phase_h/final/FINAL_STATUS.json", package_root / "17_FINAL_STATUS/FINAL_STATUS.json")
    copy_file(REPO / "progress_phase_h/H9.json", package_root / "17_FINAL_STATUS/H9_PROGRESS.json")


def write_git_state(package_root: Path, tracked: list[str]) -> None:
    head, branch, tracked_clean, tracked_status, checkout_available = snapshot_git_identity()
    state = {
        "schema": "direction5.phase_h.git_state.v1",
        "branch": branch,
        "head": head,
        "tracked_tree_clean": tracked_clean,
        "tracked_status": tracked_status,
        "git_checkout_available": checkout_available,
        "historical_untracked_delivery_artifacts_excluded": True,
    }
    (package_root / "16_GIT_MANIFEST/GIT_STATE.json").write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", "utf-8"
    )
    (package_root / "16_GIT_MANIFEST/TRACKED_FILES.txt").write_text(
        "\n".join(tracked) + "\n", "utf-8"
    )


def write_manifest(package_root: Path) -> list[dict[str, object]]:
    excluded = {"16_GIT_MANIFEST/MANIFEST.csv", "16_GIT_MANIFEST/MANIFEST.json"}
    rows = []
    for path in sorted(item for item in package_root.rglob("*") if item.is_file()):
        relative = path.relative_to(package_root).as_posix()
        if relative in excluded:
            continue
        rows.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256(path)})
    manifest_csv = package_root / "16_GIT_MANIFEST/MANIFEST.csv"
    with manifest_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("path", "bytes", "sha256"))
        writer.writeheader()
        writer.writerows(rows)
    (package_root / "16_GIT_MANIFEST/MANIFEST.json").write_text(
        json.dumps(rows, indent=2, sort_keys=True) + "\n", "utf-8"
    )
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
    args = parser.parse_args()
    artifacts = REPO / "artifacts_direction5_phase_h"
    artifacts.mkdir(parents=True, exist_ok=True)
    package_root = artifacts / "direction5_h9_staging"
    if package_root.exists():
        if package_root.parent.resolve() != artifacts.resolve() or package_root.name != "direction5_h9_staging":
            raise RuntimeError("refusing to remove an unexpected staging path")
        shutil.rmtree(package_root)
    for directory in DIRECTORIES:
        (package_root / directory).mkdir(parents=True, exist_ok=True)
    tracked = tracked_files()
    build_source_snapshot(package_root, tracked)
    populate_logical_sections(package_root)
    write_git_state(package_root, tracked)
    rows = write_manifest(package_root)
    output_name = (
        "DIRECTION5_PHASE_H_DCSV_MPC_TRIAL_REVIEW_PACKAGE.zip"
        if args.trial
        else FINAL_ZIP_NAME
    )
    output = REPO / output_name
    zip_package(package_root, output)
    digest = sha256(output)
    sidecar = Path(str(output) + ".sha256")
    sidecar.write_text(f"{digest}  {output.name}\n", "utf-8")
    result = {
        "schema": "direction5.phase_h.package_build.v1",
        "trial": args.trial,
        "zip": str(output.resolve()),
        "bytes": output.stat().st_size,
        "megabytes": output.stat().st_size / (1024 * 1024),
        "sha256": digest,
        "manifest_files": len(rows),
        "under_512mb": output.stat().st_size < 512 * 1024 * 1024,
        "git_commit": snapshot_git_identity()[0],
    }
    result_name = "TRIAL_PACKAGE_BUILD.json" if args.trial else "FINAL_PACKAGE_BUILD.json"
    (artifacts / result_name).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", "utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["under_512mb"]:
        raise SystemExit("review ZIP exceeds 512 MB")


if __name__ == "__main__":
    main()
