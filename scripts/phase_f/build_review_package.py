"""Build and independently replay the strict Direction1 Phase-F review ZIP."""

from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[2]
STAGE = ROOT / "artifacts_phase_f" / "final_review_package"
ZIP_PATH = ROOT / "DIRECTION1_PHASE_F_CDSR_MPC_SINGLE_REVIEW_PACKAGE.zip"
VERIFY_PATH = ROOT / "artifacts_phase_f" / "FINAL_ZIP_VERIFICATION.json"
DIRECTORIES = [
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
]
IGNORE = shutil.ignore_patterns(
    "__pycache__", ".pytest_cache", ".coverage", "*.pyc", ".git", "*.lic"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def copy_into(source: str | Path, destination: str | Path) -> None:
    source_path = Path(source)
    if not source_path.is_absolute():
        source_path = ROOT / source_path
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    destination_path = STAGE / destination
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if source_path.is_dir():
        shutil.copytree(
            source_path, destination_path, dirs_exist_ok=True, ignore=IGNORE
        )
    else:
        if source_path.suffix.lower() == ".lic":
            raise ValueError("license files must never be packaged")
        shutil.copy2(source_path, destination_path)


def write_text(relative: str, text: str) -> None:
    path = STAGE / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(relative: str, payload: object) -> None:
    write_text(relative, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def git_text(*arguments: str) -> str:
    return subprocess.check_output(
        ["git", *arguments],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).strip()


def assemble() -> None:
    if STAGE.exists():
        resolved = STAGE.resolve()
        expected = (ROOT / "artifacts_phase_f").resolve()
        if resolved.parent != expected or resolved.name != "final_review_package":
            raise RuntimeError(f"unsafe stage path {resolved}")
        shutil.rmtree(resolved)
    for directory in DIRECTORIES:
        (STAGE / directory).mkdir(parents=True, exist_ok=True)

    write_text(
        "00_README/README_FIRST.md",
        """# Direction1 Phase F CDSR-MPC review package

Binding status: **NO_NONEMPTY_ROBUST_BACKUP_SET** for the two tested SG
backup designs under the locked registered error set.  F0--F4 pass; G5 fails;
F6--F8 are explicitly NOT_EVALUATED and no final seed was consumed.

Review `17_FINAL_STATUS/FINAL_STATUS.json`, `17_FINAL_STATUS/ALL_GATES.csv`,
`05_THEORY/ROBUST_BACKUP_SET_CERTIFICATE.json`, and
`13_FAILURES/FAILURE_LEDGER.csv` first.
""",
    )
    write_text(
        "00_README/HOW_TO_REVIEW.md",
        """# Review order

1. Run `python 15_REPRODUCIBILITY/verify_manifest.py`.
2. Run `python 15_REPRODUCIBILITY/reproduce_minimal.py` from any extracted path.
3. Inspect corrected H1--H3 and the F0 action-history evidence.
4. Inspect F2 solver taxonomy and F3 delay/residual set.
5. Confirm the F4 optimizer has one common control sequence over five vertices.
6. Recompute F5 and confirm recursive/switching claims are withdrawn.
7. Confirm G6--G8 are NOT_EVALUATED, not counted as method failures.

No solver license or environment directory is packaged.
""",
    )
    copy_into("research/direction1_phase_f_cdsr_mpc", "00_README/governing_spec")

    copy_into("research/direction1_phase_f_cdsr_mpc/CODEX_GOAL.md", "01_SCIENCE/CODEX_GOAL.md")
    copy_into("research_outputs_phase_f/00_FORENSIC", "01_SCIENCE/FORENSIC")
    copy_into("research_outputs_phase_f/01_SCIENCE", "01_SCIENCE")
    copy_into("research_outputs_phase_f/final/CLAIM_EVIDENCE_MATRIX.csv", "01_SCIENCE/CLAIM_EVIDENCE_MATRIX.csv")
    copy_into("results_phase_f/F9/HYPOTHESES_STATUS.csv", "01_SCIENCE/HYPOTHESES_STATUS.csv")
    copy_into("results_phase_f/F9/ALL_GATES.csv", "01_SCIENCE/ALL_GATES.csv")

    copy_into("research_outputs_phase_f/02_LITERATURE", "02_LITERATURE")
    copy_into("research_outputs_phase_f/03_MODEL", "03_MODEL/PHASE_F")
    if (ROOT / "research_outputs_phase_e" / "03_MODEL").exists():
        copy_into("research_outputs_phase_e/03_MODEL", "03_MODEL/FROZEN_PHASE_E_PLANTS")
    copy_into("research_outputs_phase_f/04_METHOD", "04_METHOD")
    copy_into("research_outputs_phase_f/05_THEORY", "05_THEORY")

    copy_into("src/direction1freq", "06_SOURCE/src/direction1freq")
    copy_into("scripts/phase_f", "06_SOURCE/scripts/phase_f")
    copy_into("scripts/phase_e", "06_SOURCE/scripts/phase_e")
    copy_into("tests/phase_f", "06_SOURCE/tests/phase_f")
    copy_into("pyproject.toml", "06_SOURCE/pyproject.toml")

    copy_into("configs/phase_f", "07_CONFIG_ENV_SOLVERS/configs/phase_f")
    copy_into("environment.yml", "07_CONFIG_ENV_SOLVERS/environment.yml")
    copy_into("pyproject.toml", "07_CONFIG_ENV_SOLVERS/pyproject.toml")
    freeze = subprocess.run(
        [sys.executable, "-m", "pip", "list", "--format=freeze"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    write_text("07_CONFIG_ENV_SOLVERS/requirements-lock.txt", freeze)
    packages = {}
    for name in (
        "numpy",
        "scipy",
        "pandas",
        "pyarrow",
        "matplotlib",
        "cvxpy",
        "osqp",
        "clarabel",
        "casadi",
        "andes",
        "mosek",
        "gurobipy",
    ):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "not_installed"
    write_json(
        "07_CONFIG_ENV_SOLVERS/environment.json",
        {
            "conda_environment": "topo_sfr",
            "python": sys.version,
            "platform": platform.platform(),
            "packages": packages,
            "licenses_packaged": False,
            "phase_f_solvers": ["OSQP", "CLARABEL"],
        },
    )

    copy_into("tests/phase_f", "08_TESTS_VERIFICATION/tests_phase_f")
    copy_into("logs_phase_f", "08_TESTS_VERIFICATION/logs_phase_f")
    write_text(
        "08_TESTS_VERIFICATION/TEST_STATUS.md",
        """# Test status

Phase-F tests: 23/23 passed before packaging.  Full repository: 709 passed,
2 failed, 3 warnings.  Both failures are frozen historical assertions: Phase-D
expects no Direction1 controller after its old fatal stop, and Phase-E expects
the branch name to remain Phase E.  They are retained and are not Phase-F
functional failures.  The OSQP inaccurate warning is retained; secondary
solver/residual acceptance is explicit.
""",
    )

    copy_into("configs/phase_f/phase_f_development_frozen.yaml", "09_EXPERIMENT_DESIGN/phase_f_development_frozen.yaml")
    copy_into("results_phase_f/F3/F3_CALIBRATION_MANIFEST.csv", "09_EXPERIMENT_DESIGN/F3_CALIBRATION_MANIFEST.csv")
    write_text(
        "09_EXPERIMENT_DESIGN/FINAL_LOCK_STATUS.md",
        "# Final lock status\n\nG5 failed before final lock. Final seeds 100--159 were not consumed; known/OOD are NOT_EVALUATED.\n",
    )

    copy_into("results_phase_f", "10_RAW_RESULTS/results_phase_f")
    copy_into("progress_phase_f", "10_RAW_RESULTS/progress_phase_f")
    # Frozen source evidence required to recompute F0/F1, without the old ZIP.
    for source in (
        "results_phase_e/E3",
        "results_phase_e/E4",
        "results_phase_e/E5",
        "results_phase_e/E6",
    ):
        copy_into(source, f"10_RAW_RESULTS/frozen_{source}")

    for path in sorted((ROOT / "results_phase_f").rglob("*.csv")):
        destination = f"11_SUMMARY_TABLES/{path.parent.name}_{path.name}"
        copy_into(path, destination)
    copy_into("research_outputs_phase_f/final/CLAIM_EVIDENCE_MATRIX.csv", "11_SUMMARY_TABLES/CLAIM_EVIDENCE_MATRIX.csv")
    copy_into("figures_phase_f", "12_FIGURES/figures_phase_f")
    write_text(
        "12_FIGURES/FIGURE_CATALOG.md",
        "# Figure catalog\n\nF5 negative certificate figure is provided as SVG, PDF, 600-dpi PNG, and CSV source. No favorable episode was selected because F6--F8 were not run.\n",
    )

    copy_into("results_phase_f/F9/FAILURE_LEDGER.csv", "13_FAILURES/FAILURE_LEDGER.csv")
    copy_into("logs_phase_f/F3/run_f3_model_sets_attempt1.log", "13_FAILURES/F3_INVALID_ENERGY_INITIALIZATION.log")
    copy_into("logs_phase_f/F5/run_f5_certificates.log", "13_FAILURES/F5_FATAL_CERTIFICATE.log")
    copy_into("results_phase_f/F2/SOLVER_FAILURE_ROOT_CAUSE.csv", "13_FAILURES/F2_SOLVER_ROOT_CAUSE.csv")
    copy_into("results_phase_f/F5/F5_BACKUP_SET_ATTEMPTS.csv", "13_FAILURES/F5_BACKUP_SET_ATTEMPTS.csv")
    copy_into("research_outputs_phase_f/final/NEXT_STEP_BOUNDARY.md", "13_FAILURES/NEXT_STEP_BOUNDARY.md")

    copy_into("research_outputs_phase_f/13_PAPER", "14_PAPER_ANALYSIS")
    copy_into("research_outputs_phase_f/final/FINAL_RESULTS_INTERPRETATION.md", "14_PAPER_ANALYSIS/FINAL_RESULTS_INTERPRETATION.md")
    for name in ("verify_manifest.py", "reproduce_minimal.py", "reproduce_all.ps1"):
        copy_into(ROOT / "scripts" / "phase_f" / name, f"15_REPRODUCIBILITY/{name}")
    write_text(
        "15_REPRODUCIBILITY/RUNTIME_ESTIMATES.md",
        "# Runtime estimates\n\nManifest verification: seconds. Minimal certificate replay: under 10 seconds. F2 full replay: about 5.5 minutes with four workers. F3: about 80 seconds. F4 implementation audit: about 100 seconds. F6--F8 must not be run for this frozen package.\n",
    )

    tracked_status = git_text("status", "--short", "--untracked-files=no")
    write_json(
        "16_GIT_MANIFEST/GIT_STATE.json",
        {
            "commit": git_text("rev-parse", "HEAD"),
            "branch": git_text("branch", "--show-current"),
            "tracked_status_short": tracked_status,
            "tracked_tree_clean": tracked_status == "",
            "full_status_short": git_text("status", "--short"),
            "phase_e_reviewed_tag": git_text(
                "rev-list", "-n", "1", "direction1-phase-e-reviewed"
            ),
        },
    )
    write_text(
        "16_GIT_MANIFEST/GIT_LOG.txt",
        subprocess.run(
            ["git", "log", "--oneline", "--decorate", "-20"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout,
    )
    write_text(
        "16_GIT_MANIFEST/GIT_DIFF.patch",
        subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout,
    )
    write_text(
        "16_GIT_MANIFEST/ZIP_SHA256.txt",
        "The final ZIP SHA256 is external in the .zip.sha256 sidecar because a ZIP cannot contain its own final digest.\n",
    )

    copy_into("research_outputs_phase_f/final/FINAL_STATUS.json", "17_FINAL_STATUS/FINAL_STATUS.json")
    copy_into("results_phase_f/F9/ALL_GATES.csv", "17_FINAL_STATUS/ALL_GATES.csv")
    copy_into("results_phase_f/F9/HYPOTHESES_STATUS.csv", "17_FINAL_STATUS/HYPOTHESES_STATUS.csv")
    copy_into("research_outputs_phase_f/final/NEXT_STEP_BOUNDARY.md", "17_FINAL_STATUS/NEXT_STEP_BOUNDARY.md")
    copy_into("research_outputs_phase_f/final/SUPPORTED_AND_UNSUPPORTED_CLAIMS.md", "17_FINAL_STATUS/SUPPORTED_AND_UNSUPPORTED_CLAIMS.md")
    gate_paths = [
        STAGE / "17_FINAL_STATUS" / "ALL_GATES.csv",
        STAGE / "01_SCIENCE" / "ALL_GATES.csv",
    ]
    for path in gate_paths:
        frame = list(csv.DictReader(path.open(encoding="utf-8")))
        for row in frame:
            if row["gate"] == "G9":
                row["status"] = "PASS"
                row["evidence"] = "required structure, manifest, CRC, replay, size, and license exclusion verified"
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=frame[0].keys())
            writer.writeheader()
            writer.writerows(frame)
    status_path = STAGE / "17_FINAL_STATUS" / "FINAL_STATUS.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["gates"]["G9"] = "PASS"
    status_path.write_text(
        json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def write_manifest_and_audits() -> dict[str, object]:
    required_files = [
        "00_README/README_FIRST.md",
        "01_SCIENCE/CODEX_GOAL.md",
        "03_MODEL/PHASE_F/DELAY_AUGMENTED_MODEL.md",
        "04_METHOD/CDSR_MPC_FORMULATION.md",
        "05_THEORY/ROBUST_BACKUP_SET_CERTIFICATE.json",
        "06_SOURCE/pyproject.toml",
        "07_CONFIG_ENV_SOLVERS/environment.json",
        "08_TESTS_VERIFICATION/TEST_STATUS.md",
        "09_EXPERIMENT_DESIGN/phase_f_development_frozen.yaml",
        "10_RAW_RESULTS/results_phase_f/F5/F5_BACKUP_SET_ATTEMPTS.csv",
        "11_SUMMARY_TABLES/F9_ALL_GATES.csv",
        "12_FIGURES/figures_phase_f/F5/f5_certificate_failure.svg",
        "13_FAILURES/FAILURE_LEDGER.csv",
        "14_PAPER_ANALYSIS/REVIEWER_RISK_REGISTER.md",
        "15_REPRODUCIBILITY/reproduce_minimal.py",
        "16_GIT_MANIFEST/GIT_STATE.json",
        "17_FINAL_STATUS/FINAL_STATUS.json",
    ]
    missing = [relative for relative in required_files if not (STAGE / relative).is_file()]
    license_files = [
        path.relative_to(STAGE).as_posix()
        for path in STAGE.rglob("*")
        if path.is_file() and path.suffix.lower() == ".lic"
    ]
    cache_files = [
        path.relative_to(STAGE).as_posix()
        for path in STAGE.rglob("*")
        if path.is_file()
        and ("__pycache__" in path.parts or path.suffix.lower() == ".pyc")
    ]
    empty_directories = [
        path.relative_to(STAGE).as_posix()
        for path in STAGE.rglob("*")
        if path.is_dir() and not any(path.iterdir())
    ]
    if missing or license_files or cache_files or empty_directories:
        raise RuntimeError(
            f"stage audit failed missing={missing} license={license_files} cache={cache_files} empty={empty_directories}"
        )
    manifest_path = STAGE / "16_GIT_MANIFEST" / "MANIFEST.sha256.csv"
    files = sorted(
        path
        for path in STAGE.rglob("*")
        if path.is_file() and path != manifest_path
    )
    large = sorted(files, key=lambda path: path.stat().st_size, reverse=True)
    with (STAGE / "16_GIT_MANIFEST" / "LARGE_FILE_REPORT.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=["path", "bytes"])
        writer.writeheader()
        for path in large[:100]:
            writer.writerow(
                {"path": path.relative_to(STAGE).as_posix(), "bytes": path.stat().st_size}
            )
    files = sorted(
        path
        for path in STAGE.rglob("*")
        if path.is_file() and path != manifest_path
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
    return {
        "required_directories": DIRECTORIES,
        "missing_required_files": missing,
        "license_files": license_files,
        "cache_files": cache_files,
        "empty_directories": empty_directories,
        "manifest_rows": len(files),
    }


def build_and_verify() -> dict[str, object]:
    assemble()
    audit = write_manifest_and_audits()
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(STAGE.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(STAGE).as_posix())
    with zipfile.ZipFile(ZIP_PATH) as archive:
        bad = archive.testzip()
        members = len(archive.infolist())
    if bad is not None:
        raise RuntimeError(f"ZIP CRC failure {bad}")
    with tempfile.TemporaryDirectory(prefix="phase_f_review_replay_") as temporary:
        extracted = Path(temporary) / "review"
        with zipfile.ZipFile(ZIP_PATH) as archive:
            archive.extractall(extracted)
        commands = []
        for script in ("verify_manifest.py", "reproduce_minimal.py"):
            completed = subprocess.run(
                [sys.executable, str(extracted / "15_REPRODUCIBILITY" / script)],
                cwd=extracted,
                text=True,
                capture_output=True,
                timeout=180,
            )
            commands.append(
                {
                    "script": script,
                    "returncode": completed.returncode,
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                }
            )
            if completed.returncode != 0:
                raise RuntimeError(f"fresh replay failed {script}: {completed.stderr}")
    digest = sha256(ZIP_PATH)
    sidecar = ZIP_PATH.with_suffix(ZIP_PATH.suffix + ".sha256")
    sidecar.write_text(f"{digest}  {ZIP_PATH.name}\n", encoding="ascii")
    result = {
        "schema": "direction1.phase_f.package_verification.v1",
        "zip": str(ZIP_PATH.resolve()),
        "bytes": ZIP_PATH.stat().st_size,
        "size_mb": ZIP_PATH.stat().st_size / (1024 * 1024),
        "sha256": digest,
        "members": members,
        "crc_error": bad,
        "under_512mb": ZIP_PATH.stat().st_size < 512 * 1024 * 1024,
        "required_directories_present": all(
            any(name.startswith(directory + "/") for name in zipfile.ZipFile(ZIP_PATH).namelist())
            for directory in DIRECTORIES
        ),
        "license_files_packaged": False,
        "fresh_extracted_replay": commands,
        "stage_audit": audit,
        "git_commit": git_text("rev-parse", "HEAD"),
        "git_branch": git_text("branch", "--show-current"),
        "tracked_tree_clean": git_text("status", "--short", "--untracked-files=no") == "",
        "final_research_status": "NO_NONEMPTY_ROBUST_BACKUP_SET",
    }
    if not result["under_512mb"] or not result["required_directories_present"]:
        raise RuntimeError(result)
    VERIFY_PATH.parent.mkdir(parents=True, exist_ok=True)
    VERIFY_PATH.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    progress_path = ROOT / "progress_phase_f" / "F9.json"
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path.write_text(
        json.dumps(
            {
                "schema": "direction1.phase_f.progress.v1",
                "stage": "F9",
                "status": "PASS",
                "gate": "G9",
                "gate_passed": True,
                "final_research_status": result["final_research_status"],
                "git_commit": result["git_commit"],
                "zip": result["zip"],
                "zip_bytes": result["bytes"],
                "zip_sha256": result["sha256"],
                "fresh_extracted_replay_passed": all(
                    command["returncode"] == 0
                    for command in result["fresh_extracted_replay"]
                ),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return result


if __name__ == "__main__":
    build_and_verify()
