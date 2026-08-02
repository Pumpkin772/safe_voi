"""Build and independently replay the single Phase-G negative review package."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile


REPO = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = REPO / "artifacts_phase_g"
STAGE = ARTIFACT_ROOT / "final_review_package"
ZIP = REPO / "DIRECTION1_PHASE_G_TERMINAL_VIABILITY_FULL_VALIDATION_SINGLE_REVIEW_PACKAGE.zip"
SIDECAR = Path(str(ZIP) + ".sha256")
REQUIRED_DIRECTORIES = tuple(f"{index:02d}_{name}" for index, name in enumerate((
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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def copy_tree(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    shutil.copytree(
        source,
        destination,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", ".pytest_tmp*"),
    )


def git(*arguments: str) -> str:
    return subprocess.check_output(
        ["git", *arguments], cwd=REPO, text=True, encoding="utf-8"
    ).strip()


def tracked_tree_clean() -> bool:
    unstaged = subprocess.run(["git", "diff", "--quiet"], cwd=REPO).returncode == 0
    staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO).returncode == 0
    return unstaged and staged


def stage_package() -> None:
    resolved_artifacts = ARTIFACT_ROOT.resolve()
    resolved_stage = STAGE.resolve()
    if resolved_stage.parent != resolved_artifacts:
        raise RuntimeError("refusing to replace a staging directory outside artifacts_phase_g")
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    for directory in REQUIRED_DIRECTORIES:
        (STAGE / directory).mkdir()

    launch = REPO / "research" / "direction1_phase_g_terminal_viability_full_validation"
    for name in ("README_FIRST.md", "CODEX_GOAL.md", "PACKAGE_INDEX.csv", "PACKAGE_INDEX.json"):
        copy_file(launch / name, STAGE / "00_README" / name)
    (STAGE / "00_README" / "REVIEW_ORDER.md").write_text(
        """# Review order

1. Read `17_FINAL_STATUS/FINAL_STATUS.json` and `ALL_GATES.csv`.
2. Read `01_SCIENCE` and the G0 reclassification.
3. Inspect G2 coverage, all retained repair attempts, and the local one-step certificate.
4. Run from the extracted root:

```text
python 15_REPRODUCIBILITY/verify_manifest.py
python 15_REPRODUCIBILITY/reproduce_minimal.py
python 15_REPRODUCIBILITY/verify_negative_boundary.py
```
""",
        encoding="utf-8",
    )

    copy_tree(REPO / "research_outputs_phase_g" / "01_SCIENCE", STAGE / "01_SCIENCE")
    copy_tree(launch, STAGE / "01_SCIENCE" / "REGISTERED_PHASE_G_GOAL")
    copy_file(
        REPO / "research_outputs_phase_g/00_FORENSIC/PHASE_F_RECLASSIFICATION.md",
        STAGE / "01_SCIENCE/PHASE_F_RECLASSIFICATION.md",
    )
    copy_tree(REPO / "research_outputs_phase_g" / "02_LITERATURE", STAGE / "02_LITERATURE")
    copy_tree(REPO / "research_outputs_phase_g" / "03_MODEL", STAGE / "03_MODEL")
    for name in ("03_SUSTAINABILITY_TERMINAL_BRIDGE_SPEC.md", "04_CDSR_MPC_REPAIR_AND_ACCELERATION_SPEC.md"):
        copy_file(launch / name, STAGE / "04_METHOD" / name)
    copy_tree(REPO / "research_outputs_phase_g" / "04_METHOD", STAGE / "04_METHOD")
    copy_tree(REPO / "research_outputs_phase_g" / "05_THEORY", STAGE / "05_THEORY")
    copy_tree(REPO / "src", STAGE / "06_SOURCE" / "src")
    copy_tree(REPO / "scripts" / "phase_g", STAGE / "06_SOURCE" / "scripts" / "phase_g")
    copy_tree(REPO / "tests" / "phase_g", STAGE / "06_SOURCE" / "tests" / "phase_g")
    copy_file(REPO / "pyproject.toml", STAGE / "06_SOURCE" / "pyproject.toml")
    copy_file(REPO / "environment.yml", STAGE / "07_CONFIG_ENV_SOLVERS" / "environment.yml")
    copy_tree(REPO / "configs" / "phase_g", STAGE / "07_CONFIG_ENV_SOLVERS" / "phase_g")
    solver_info = {
        "python": sys.version,
        "licenses_packaged": False,
        "phase_g_licensed_solver_required": False,
        "registered_phase_g_solvers": ["OSQP", "CLARABEL"],
    }
    (STAGE / "07_CONFIG_ENV_SOLVERS" / "SOLVER_ENVIRONMENT.json").write_text(
        json.dumps(solver_info, indent=2) + "\n", encoding="utf-8"
    )
    copy_tree(REPO / "logs_phase_g", STAGE / "08_TESTS_VERIFICATION" / "logs_phase_g")
    copy_tree(REPO / "progress_phase_g", STAGE / "08_TESTS_VERIFICATION" / "progress_phase_g")
    copy_file(launch / "06_EXPERIMENT_STATISTICS_AND_BASELINES.md", STAGE / "09_EXPERIMENT_DESIGN/REGISTERED_PROTOCOL.md")
    copy_tree(REPO / "configs" / "phase_g", STAGE / "09_EXPERIMENT_DESIGN" / "configs")
    copy_tree(REPO / "results_phase_g", STAGE / "10_RAW_RESULTS" / "results_phase_g")
    for source in (
        REPO / "results_phase_g/G1/MATERIALITY_SCOPE.csv",
        REPO / "results_phase_g/G2/VALIDATION_COVERAGE.csv",
        REPO / "results_phase_g/G2/LOCAL_ONE_STEP_TERMINAL_COMPATIBILITY.csv",
        REPO / "results_phase_g/G9/ALL_GATES.csv",
    ):
        copy_file(source, STAGE / "11_SUMMARY_TABLES" / source.name)
    (STAGE / "12_FIGURES" / "README.md").write_text(
        "# Figures\n\nNo final/performance figures were generated because G2 stopped before G3-G8.\n",
        encoding="utf-8",
    )
    copy_file(REPO / "results_phase_g/G9/FAILURE_LEDGER.csv", STAGE / "13_FAILURES/FAILURE_LEDGER.csv")
    copy_tree(REPO / "results_phase_g/G2/attempt1_worst_all_vertices_double_counted", STAGE / "13_FAILURES/G2_ATTEMPT1")
    copy_tree(REPO / "results_phase_g/G2/attempt2_preregistered_delay_truth", STAGE / "13_FAILURES/G2_ATTEMPT2")
    copy_tree(REPO / "research_outputs_phase_g" / "13_PAPER", STAGE / "14_PAPER_ANALYSIS")
    copy_file(REPO / "research_outputs_phase_g/final/FINAL_RESULTS_INTERPRETATION.md", STAGE / "14_PAPER_ANALYSIS/FINAL_RESULTS_INTERPRETATION.md")
    for name in ("verify_manifest.py", "reproduce_minimal.py", "verify_negative_boundary.py"):
        copy_file(REPO / "scripts" / "phase_g" / name, STAGE / "15_REPRODUCIBILITY" / name)
    (STAGE / "15_REPRODUCIBILITY" / "requirements_minimal.txt").write_text(
        "numpy>=1.24\n", encoding="utf-8"
    )
    copy_tree(REPO / "research_outputs_phase_g" / "final", STAGE / "17_FINAL_STATUS")
    copy_file(REPO / "results_phase_g/G9/ALL_GATES.csv", STAGE / "17_FINAL_STATUS/ALL_GATES.csv")
    copy_file(REPO / "results_phase_g/G9/FAILURE_LEDGER.csv", STAGE / "17_FINAL_STATUS/FAILURE_LEDGER.csv")

    # G9 can only be marked PASS inside the staged, subsequently verified
    # artifact (and in the external post-package record). The repository copy
    # remains PENDING before assembly so it cannot claim verification early.
    staged_gate_paths = (
        STAGE / "17_FINAL_STATUS" / "ALL_GATES.csv",
        STAGE / "11_SUMMARY_TABLES" / "ALL_GATES.csv",
    )
    for gate_path in staged_gate_paths:
        with gate_path.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        for row in rows:
            if row["gate"] == "G9":
                row["status"] = "PASS"
                row["evidence"] = (
                    "required structure, manifest, CRC, size, license exclusion, "
                    "and fresh extracted replay verified"
                )
        with gate_path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
    staged_status_path = STAGE / "17_FINAL_STATUS" / "FINAL_STATUS.json"
    staged_status = json.loads(staged_status_path.read_text(encoding="utf-8"))
    staged_status["gates"]["G9"] = "PASS"
    staged_status_path.write_text(
        json.dumps(staged_status, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    git_dir = STAGE / "16_GIT_MANIFEST"
    (git_dir / "GIT_COMMIT.txt").write_text(git("rev-parse", "HEAD") + "\n", encoding="utf-8")
    (git_dir / "GIT_BRANCH.txt").write_text(git("branch", "--show-current") + "\n", encoding="utf-8")
    (git_dir / "TRACKED_STATUS.txt").write_text(
        git("status", "--short", "--untracked-files=no") + "\n", encoding="utf-8"
    )
    (git_dir / "UNTRACKED_DELIVERY_ARTIFACTS_NOTE.md").write_text(
        "Untracked historical review ZIPs, extracted packages, and logs are intentionally preserved outside this package.\n",
        encoding="utf-8",
    )

    manifest_path = git_dir / "MANIFEST.sha256.csv"
    files = sorted(
        path for path in STAGE.rglob("*") if path.is_file() and path != manifest_path
    )
    with manifest_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["path", "bytes", "sha256"])
        writer.writeheader()
        for path in files:
            writer.writerow(
                {
                    "path": path.relative_to(STAGE).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )


def build_and_verify() -> dict[str, object]:
    if not tracked_tree_clean():
        raise RuntimeError("tracked tree must be clean before package assembly")
    stage_package()
    license_files = [
        path.relative_to(STAGE).as_posix()
        for path in STAGE.rglob("*")
        if path.is_file()
        and (path.suffix.lower() == ".lic" or "gurobi.lic" in path.name.lower() or "mosek.lic" in path.name.lower())
    ]
    if license_files:
        raise RuntimeError(f"license files staged: {license_files}")
    if ZIP.exists():
        ZIP.unlink()
    with zipfile.ZipFile(ZIP, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(STAGE.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(STAGE).as_posix())
    size = ZIP.stat().st_size
    if size >= 512 * 1024 * 1024:
        raise RuntimeError("review package exceeds 512 MiB")
    with zipfile.ZipFile(ZIP) as archive:
        crc_error = archive.testzip()
        members = len(archive.infolist())
    if crc_error is not None:
        raise RuntimeError(f"ZIP CRC failure: {crc_error}")

    replay = []
    with tempfile.TemporaryDirectory(prefix="phase_g_review_") as temporary:
        root = Path(temporary) / "review"
        with zipfile.ZipFile(ZIP) as archive:
            archive.extractall(root)
        for script in ("verify_manifest.py", "reproduce_minimal.py", "verify_negative_boundary.py"):
            result = subprocess.run(
                [sys.executable, str(root / "15_REPRODUCIBILITY" / script)],
                cwd=root,
                text=True,
                capture_output=True,
                encoding="utf-8",
            )
            replay.append(
                {
                    "script": script,
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
            )
            if result.returncode != 0:
                raise RuntimeError(f"fresh replay failed: {script}\n{result.stderr}")
    digest = sha256(ZIP)
    SIDECAR.write_text(f"{digest}  {ZIP.name}\n", encoding="utf-8")
    return {
        "schema": "direction1.phase_g.package_verification.v1",
        "status": "PASS",
        "final_research_status": "LOCAL_TERMINAL_MODEL_NOT_CERTIFIABLE",
        "zip": str(ZIP.resolve()),
        "bytes": size,
        "size_mb": size / 1024**2,
        "sha256": digest,
        "members": members,
        "under_512mb": True,
        "crc_error": crc_error,
        "required_directories_present": all((STAGE / name).is_dir() for name in REQUIRED_DIRECTORIES),
        "license_files_packaged": False,
        "tracked_tree_clean": True,
        "git_commit": git("rev-parse", "HEAD"),
        "git_branch": git("branch", "--show-current"),
        "fresh_extracted_replay": replay,
    }


def main() -> None:
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    verification = build_and_verify()
    verification_path = ARTIFACT_ROOT / "FINAL_ZIP_VERIFICATION.json"
    verification_path.write_text(
        json.dumps(verification, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    progress = {
        "schema": "direction1.phase_g.progress.v1",
        "stage": "G9",
        "gate": "G9_PACKAGE",
        "gate_passed": True,
        **verification,
    }
    (REPO / "progress_phase_g" / "G9.json").write_text(
        json.dumps(progress, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(verification, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
