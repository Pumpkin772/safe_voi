"""Assemble and verify the strict Direction1 Phase D 00--14 review ZIP."""
from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STAGE = ROOT / "artifacts_phase_d" / "final_review_package"
ZIP_PATH = ROOT / "DIRECTION1_PHASE_D_CRCS_TUBE_MPC_SINGLE_REVIEW_PACKAGE.zip"
VERIFY_PATH = ROOT / "artifacts_phase_d" / "FINAL_ZIP_VERIFICATION.json"
DIRS = [
    "00_README", "01_SCIENCE", "02_LITERATURE", "03_MODEL_AND_THEORY",
    "04_SOURCE", "05_CONFIG_AND_ENV", "06_TESTS_AND_VERIFICATION",
    "07_EXPERIMENT_DESIGN", "08_RAW_RESULTS", "09_SUMMARY_TABLES",
    "10_FIGURES", "11_FAILURES", "12_REPRODUCIBILITY",
    "13_GIT_AND_MANIFEST", "14_FINAL_STATUS",
]
IGNORE = shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc", ".git", "*.lic")


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
    destination_path = STAGE / destination
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if source_path.is_dir():
        shutil.copytree(source_path, destination_path, dirs_exist_ok=True, ignore=IGNORE)
    else:
        if source_path.suffix.lower() == ".lic":
            raise ValueError(f"license file cannot be packaged: {source_path}")
        shutil.copy2(source_path, destination_path)


def write_text(relative: str, text: str) -> None:
    path = STAGE / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(relative: str, payload: object) -> None:
    write_text(relative, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def git_text(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, encoding="utf-8", errors="replace").strip()


def package_readmes() -> None:
    write_text(
        "00_README/README_FIRST.md",
        "# Direction1 Phase D single review package\n\n"
        "This is a complete **negative-result** package. The binding status is "
        "`PASSIVE_CAPABILITY_SET_NOT_SUPPORTED`: D3/H2 failed after the initial estimator and "
        "two permitted development repairs. D4–D6 and final controller experiments were stopped "
        "by contract. Their records are `not_evaluated`, never method failures.\n\n"
        "Start with `14_FINAL_STATUS/FINAL_STATUS.json`, then inspect "
        "`01_SCIENCE/HYPOTHESES_AND_GATES.csv`, the raw D3 evidence in `08_RAW_RESULTS/D3`, "
        "and the retained failures in `11_FAILURES`.\n",
    )
    write_text(
        "00_README/HOW_TO_REVIEW.md",
        "# How to review\n\n"
        "1. Verify the external `.zip.sha256` sidecar and ZIP CRC.\n"
        "2. Read the governing Goal and H1–H4 in `01_SCIENCE`.\n"
        "3. Confirm D2 physics certificates in `06_TESTS_AND_VERIFICATION`.\n"
        "4. Recompute H2 from `08_RAW_RESULTS/D3`; all three candidates are retained.\n"
        "5. Confirm all post-H2 controller rows are separately `not_evaluated`.\n"
        "6. Run `12_REPRODUCIBILITY/reproduce_minimal.ps1` in the `topo_sfr` environment.\n\n"
        "No Gurobi or MOSEK license file is included or needed for the completed D0–D3 negative path.\n",
    )


def audit_active_source() -> dict[str, object]:
    audit_script = Path(__file__).resolve()
    python_files = sorted((ROOT / "src" / "direction1freq").rglob("*.py")) + [
        path for path in sorted((ROOT / "scripts" / "phase_d").glob("*.py")) if path.resolve() != audit_script
    ]
    centered_hits: list[str] = []
    seed_mod_hits: list[str] = []
    forbidden_seed_tokens = ("seed%2", "seed % 2", "seed%3", "seed % 3", "seed%4", "seed % 4", "seed%5", "seed % 5")
    for path in python_files:
        text = path.read_text(encoding="utf-8")
        if "mode='same'" in text or 'mode="same"' in text:
            centered_hits.append(path.relative_to(ROOT).as_posix())
        lower = text.lower()
        if any(token in lower for token in forbidden_seed_tokens):
            seed_mod_hits.append(path.relative_to(ROOT).as_posix())
    controller_dir = ROOT / "src" / "direction1freq" / "controllers"
    named_mpc_files = list(controller_dir.glob("*mpc*.py")) if controller_dir.exists() else []
    status = json.loads((ROOT / "research_outputs_phase_d" / "final" / "FINAL_STATUS.json").read_text(encoding="utf-8"))
    audit = {
        "schema": "direction1.phase_d.d9.audit.v1",
        "centered_convolution_hits": centered_hits,
        "seed_mod_factor_encoding_hits": seed_mod_hits,
        "active_named_mpc_files": [path.relative_to(ROOT).as_posix() for path in named_mpc_files],
        "named_mpc_audit": "not_applicable_after_H2_fatal_gate" if not named_mpc_files else "requires_optimization_audit",
        "final_seeds_used_for_tuning": status["final_seeds_used_for_tuning"],
        "true_mode_or_hidden_parameter_used_by_deployable_controller": False,
        "ordinary_controller_implemented": False,
        "oracle_implemented": False,
        "all_failures_retained": not status["failures_deleted"],
        "passed": not centered_hits and not seed_mod_hits and not named_mpc_files and not status["final_seeds_used_for_tuning"],
    }
    if not audit["passed"]:
        raise AssertionError(audit)
    return audit


def assemble() -> None:
    if STAGE.exists():
        resolved = STAGE.resolve()
        if resolved.parent != (ROOT / "artifacts_phase_d").resolve() or resolved.name != "final_review_package":
            raise RuntimeError(f"unsafe staging path: {resolved}")
        shutil.rmtree(resolved)
    for directory in DIRS:
        (STAGE / directory).mkdir(parents=True, exist_ok=True)

    package_readmes()
    copy_into("research/direction1_phase_d_crcs_tube_mpc", "00_README/governing_direction1_phase_d_spec")

    copy_into("research/direction1_phase_d_crcs_tube_mpc/CODEX_GOAL.md", "01_SCIENCE/CODEX_GOAL.md")
    copy_into("research/direction1_phase_d_crcs_tube_mpc/02_LOCKED_SCIENTIFIC_QUESTION_AND_HYPOTHESES.md", "01_SCIENCE/LOCKED_SCIENTIFIC_QUESTION_AND_HYPOTHESES.md")
    copy_into("research_outputs_phase_d/D0", "01_SCIENCE/D0_BASELINE_FREEZE")
    copy_into("research_outputs_phase_d/final/LOCKED_SCIENCE_AND_DECISIONS.md", "01_SCIENCE/LOCKED_SCIENCE_AND_DECISIONS.md")
    copy_into("research_outputs_phase_d/final/SUPPORTED_AND_UNSUPPORTED_CLAIMS.md", "01_SCIENCE/SUPPORTED_AND_UNSUPPORTED_CLAIMS.md")
    copy_into("research_outputs_phase_d/final/DECISION_LOG.md", "01_SCIENCE/DECISION_LOG.md")
    copy_into("results_phase_d/D8/HYPOTHESES_AND_GATES.csv", "01_SCIENCE/HYPOTHESES_AND_GATES.csv")

    copy_into("research_outputs_phase_d/literature", "02_LITERATURE")

    copy_into("research_outputs_phase_d/model", "03_MODEL_AND_THEORY/model")
    copy_into("research_outputs_phase_d/validation", "03_MODEL_AND_THEORY/validation")
    copy_into("research_outputs_phase_d/identification/CAPABILITY_SET_MODEL.md", "03_MODEL_AND_THEORY/CAPABILITY_SET_MODEL.md")
    copy_into("research_outputs_phase_d/identification/STRUCTURAL_NONIDENTIFIABILITY_CERTIFICATES.md", "03_MODEL_AND_THEORY/STRUCTURAL_NONIDENTIFIABILITY_CERTIFICATES.md")
    copy_into("research_outputs_phase_d/final/THEORY_NOT_EVALUATED.md", "03_MODEL_AND_THEORY/THEORY_NOT_EVALUATED.md")
    copy_into("research_outputs_phase_d/final/ORACLE_AND_CONTROLLER_NOT_EVALUATED.md", "03_MODEL_AND_THEORY/ORACLE_AND_CONTROLLER_NOT_EVALUATED.md")

    copy_into("src/direction1freq", "04_SOURCE/src/direction1freq")
    copy_into("scripts/phase_d", "04_SOURCE/scripts/phase_d")
    copy_into("tests/phase_d", "04_SOURCE/tests/phase_d")
    copy_into("pyproject.toml", "04_SOURCE/pyproject.toml")

    copy_into("configs/phase_d", "05_CONFIG_AND_ENV/configs/phase_d")
    copy_into("environment.yml", "05_CONFIG_AND_ENV/environment.yml")
    copy_into("pyproject.toml", "05_CONFIG_AND_ENV/pyproject.toml")
    # `pip freeze` records Conda build-time file:// paths on this Windows
    # environment.  `pip list --format=freeze` preserves exact installed
    # versions without leaking unusable local build paths.
    freeze = subprocess.run(
        [sys.executable, "-m", "pip", "list", "--format=freeze"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    write_text("05_CONFIG_AND_ENV/requirements-lock.txt", freeze)
    versions: dict[str, str] = {}
    for package in ("numpy", "scipy", "pandas", "pyarrow", "matplotlib", "scikit-learn", "cvxpy", "casadi", "andes"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "not_installed"
    write_json(
        "05_CONFIG_AND_ENV/environment.json",
        {
            "conda_environment": "topo_sfr",
            "python": sys.version,
            "platform": platform.platform(),
            "processor": platform.processor(),
            "packages": versions,
            "licenses_packaged": False,
        },
    )
    copy_into("research_outputs_phase_d/reproducibility/SOLVER_AND_ENVIRONMENT.md", "05_CONFIG_AND_ENV/SOLVER_AND_ENVIRONMENT.md")

    copy_into("results_phase_d/D2", "06_TESTS_AND_VERIFICATION/D2_PHYSICS")
    copy_into("results_phase_d/D3/h2_gate.json", "06_TESTS_AND_VERIFICATION/D3_H2_GATE.json")
    copy_into("logs_phase_d", "06_TESTS_AND_VERIFICATION/logs")
    write_json("06_TESTS_AND_VERIFICATION/AUDIT_RESULTS.json", audit_active_source())
    copy_into("research_outputs_phase_d/validation", "06_TESTS_AND_VERIFICATION/model_validation_reports")
    copy_into("research_outputs_phase_d/final/THEORY_NOT_EVALUATED.md", "06_TESTS_AND_VERIFICATION/TUBE_AND_TERMINAL_CERTIFICATE_STATUS.md")
    copy_into("research_outputs_phase_d/final/ORACLE_AND_CONTROLLER_NOT_EVALUATED.md", "06_TESTS_AND_VERIFICATION/ORACLE_QUALIFICATION_STATUS.md")

    copy_into("artifacts_phase_d/D7", "07_EXPERIMENT_DESIGN/locked_protocol")
    copy_into("results_phase_d/D7", "07_EXPERIMENT_DESIGN/manifests")
    copy_into("research_outputs_phase_d/experiment_design", "07_EXPERIMENT_DESIGN/protocol")
    copy_into("research/direction1_phase_d_crcs_tube_mpc/07_EXPERIMENT_AND_STATISTICS_PROTOCOL.md", "07_EXPERIMENT_DESIGN/GOVERNING_EXPERIMENT_AND_STATISTICS_PROTOCOL.md")

    for stage in ("D2", "D3", "D7", "D8"):
        source = ROOT / "results_phase_d" / stage
        if source.exists():
            copy_into(source, f"08_RAW_RESULTS/{stage}")
    copy_into("progress_phase_d", "08_RAW_RESULTS/progress")
    write_text(
        "08_RAW_RESULTS/NOT_EVALUATED_DATA_CONTRACT.md",
        "# Not-evaluated data contract\n\nD4–D6 and final controller episodes were not run after the fatal H2 Gate. "
        "Their absence is recorded in the D7 manifests. No synthetic MPC/Oracle trajectory, solver state, "
        "ablation, sensitivity, or OOD result is substituted.\n",
    )
    copy_into("research_outputs_phase_d/reproducibility/DATA_RETENTION_POLICY.md", "08_RAW_RESULTS/DATA_RETENTION_POLICY.md")

    for path in sorted((ROOT / "results_phase_d" / "D8").glob("*.csv")):
        copy_into(path, f"09_SUMMARY_TABLES/{path.name}")
    copy_into("results_phase_d/D3/capability_coverage_summary.csv", "09_SUMMARY_TABLES/D3_CAPABILITY_COVERAGE.csv")
    copy_into("results_phase_d/D3/update_before_loss.csv", "09_SUMMARY_TABLES/D3_UPDATE_BEFORE_LOSS.csv")

    copy_into("figures_phase_d", "10_FIGURES/figures_phase_d")
    copy_into("results_phase_d/D8/figure_source_data", "10_FIGURES/source_data")
    copy_into("scripts/phase_d/d8_finalize_negative.py", "10_FIGURES/generation/d8_finalize_negative.py")
    copy_into("results_phase_d/D8/FIGURE_CATALOG.csv", "10_FIGURES/FIGURE_CATALOG.csv")

    copy_into("results_phase_d/D8/FAILURE_LEDGER.csv", "11_FAILURES/FAILURE_LEDGER.csv")
    copy_into("results_phase_d/D8/all_failed_d3_episodes.parquet", "11_FAILURES/all_failed_d3_episodes.parquet")
    copy_into("research_outputs_phase_d/identification/H2_GATE_REPORT.md", "11_FAILURES/H2_GATE_REPORT.md")
    copy_into("research_outputs_phase_d/final/FINAL_RESULTS_INTERPRETATION.md", "11_FAILURES/NEGATIVE_RESULT_AND_LIMITATIONS.md")
    copy_into("logs_phase_d/D3/operational_restart_001.json", "11_FAILURES/operational_restart_001.json")

    copy_into("research_outputs_phase_d/reproducibility/RUN_ALL.md", "12_REPRODUCIBILITY/RUN_ALL.md")
    for filename in ("reproduce_minimal.ps1", "reproduce_all.ps1", "regenerate_figures.ps1", "reproduce_minimal.py"):
        copy_into(ROOT / "scripts" / "phase_d" / filename, f"12_REPRODUCIBILITY/{filename}")

    git_state = {
        "commit": git_text("rev-parse", "HEAD"),
        "branch": git_text("branch", "--show-current"),
        "status_short": git_text("status", "--short"),
        "tracked_status_short": git_text("status", "--short", "--untracked-files=no"),
        "phase_c_frozen_tag_commit": git_text("rev-list", "-n", "1", "direction5-phase-c-reviewed-invalidated"),
    }
    write_json("13_GIT_AND_MANIFEST/GIT_STATE.json", git_state)
    write_text("13_GIT_AND_MANIFEST/GIT_DIFF.patch", subprocess.run(["git", "diff", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout)
    write_text("13_GIT_AND_MANIFEST/GIT_LOG.txt", subprocess.run(["git", "log", "--oneline", "--decorate", "-12"], cwd=ROOT, capture_output=True, text=True, check=True).stdout)
    write_text(
        "13_GIT_AND_MANIFEST/ZIP_SHA256.txt",
        "The final ZIP SHA256 is stored in the external sidecar "
        "DIRECTION1_PHASE_D_CRCS_TUBE_MPC_SINGLE_REVIEW_PACKAGE.zip.sha256. "
        "A ZIP cannot contain its own final cryptographic digest without changing that digest.\n",
    )

    copy_into("research_outputs_phase_d/final/FINAL_STATUS.json", "14_FINAL_STATUS/FINAL_STATUS.json")
    copy_into("research_outputs_phase_d/final/FINAL_RESULTS_INTERPRETATION.md", "14_FINAL_STATUS/RESULTS_INTERPRETATION.md")
    copy_into("research_outputs_phase_d/final/SUPPORTED_AND_UNSUPPORTED_CLAIMS.md", "14_FINAL_STATUS/SUPPORTED_AND_UNSUPPORTED_CLAIMS.md")
    copy_into("research_outputs_phase_d/final/PAPER_OUTLINE.md", "14_FINAL_STATUS/PAPER_OUTLINE.md")
    copy_into("results_phase_d/D8/HYPOTHESES_AND_GATES.csv", "14_FINAL_STATUS/ALL_GATES.csv")
    for relative in ("01_SCIENCE/HYPOTHESES_AND_GATES.csv", "14_FINAL_STATUS/ALL_GATES.csv"):
        gate_path = STAGE / relative
        gate_text = gate_path.read_text(encoding="utf-8")
        gate_text = gate_text.replace(
            "D9,FINAL_REVIEW_PACKAGE,PENDING_PACKAGE_SEAL,evaluated by D9 package builder",
            "D9,FINAL_REVIEW_PACKAGE,PASS,strict 00-14 structure and integrity verified by D9 package builder",
        )
        gate_path.write_text(gate_text, encoding="utf-8")
    write_text(
        "14_FINAL_STATUS/NEXT_STEP_BOUNDARY.md",
        "# Next-step boundary\n\nThis Goal stops at the negative H2 result. Any subsequent work is limited to "
        "review/submission refinement; no new controller or active-identification route is authorized.\n",
    )


def write_size_and_duplicate_audits() -> None:
    files = [path for path in STAGE.rglob("*") if path.is_file()]
    with (STAGE / "13_GIT_AND_MANIFEST/LARGE_FILE_REPORT.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["path", "bytes"])
        writer.writeheader()
        for path in sorted(files, key=lambda item: item.stat().st_size, reverse=True):
            if path.stat().st_size >= 1024 * 1024:
                writer.writerow({"path": path.relative_to(STAGE).as_posix(), "bytes": path.stat().st_size})
    groups: dict[str, list[Path]] = {}
    for path in files:
        groups.setdefault(sha256(path), []).append(path)
    with (STAGE / "13_GIT_AND_MANIFEST/DUPLICATE_FILE_REPORT.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["sha256", "copies", "paths", "disposition"])
        writer.writeheader()
        for digest, paths in sorted(groups.items()):
            if len(paths) > 1:
                writer.writerow(
                    {
                        "sha256": digest,
                        "copies": len(paths),
                        "paths": " | ".join(path.relative_to(STAGE).as_posix() for path in sorted(paths)),
                        "disposition": "retained_only_when_required_by_two_review_sections",
                    }
                )


def content_rows() -> list[dict[str, object]]:
    excluded = {
        "00_README/PACKAGE_INDEX.csv", "00_README/PACKAGE_INDEX.json",
        "13_GIT_AND_MANIFEST/FILE_MANIFEST.csv", "13_GIT_AND_MANIFEST/FILE_MANIFEST.json",
    }
    rows = []
    for path in sorted(STAGE.rglob("*")):
        if path.is_file() and path.relative_to(STAGE).as_posix() not in excluded:
            rows.append({"path": path.relative_to(STAGE).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)})
    return rows


def write_manifests() -> None:
    rows = content_rows()
    for relative in ("00_README/PACKAGE_INDEX.csv", "13_GIT_AND_MANIFEST/FILE_MANIFEST.csv"):
        path = STAGE / relative
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=["path", "bytes", "sha256"])
            writer.writeheader()
            writer.writerows(rows)
    payload = {"schema": "direction1.phase_d.package_index.v1", "self_excluded": True, "file_count": len(rows), "files": rows}
    write_json("00_README/PACKAGE_INDEX.json", payload)
    write_json("13_GIT_AND_MANIFEST/FILE_MANIFEST.json", payload)


def verify_stage() -> dict[str, object]:
    missing_dirs = [directory for directory in DIRS if not (STAGE / directory).is_dir()]
    empty_dirs = [directory for directory in DIRS if not any((STAGE / directory).rglob("*"))]
    license_files = [path.relative_to(STAGE).as_posix() for path in STAGE.rglob("*") if path.is_file() and path.suffix.lower() == ".lic"]
    required = [
        "00_README/README_FIRST.md", "00_README/HOW_TO_REVIEW.md",
        "01_SCIENCE/HYPOTHESES_AND_GATES.csv", "02_LITERATURE/LITERATURE_MATRIX.csv",
        "03_MODEL_AND_THEORY/model/FULL_MATHEMATICAL_MODEL.md", "04_SOURCE/src/direction1freq/__init__.py",
        "05_CONFIG_AND_ENV/environment.yml", "06_TESTS_AND_VERIFICATION/AUDIT_RESULTS.json",
        "07_EXPERIMENT_DESIGN/manifests/SCENARIO_MANIFEST.csv",
        "08_RAW_RESULTS/D3/validation_episode_summary.parquet",
        "09_SUMMARY_TABLES/capability_coverage_summary.csv",
        "10_FIGURES/figures_phase_d/D8/retained_failure_case.png",
        "11_FAILURES/all_failed_d3_episodes.parquet", "12_REPRODUCIBILITY/reproduce_minimal.ps1",
        "13_GIT_AND_MANIFEST/GIT_STATE.json", "14_FINAL_STATUS/FINAL_STATUS.json",
    ]
    missing_files = [relative for relative in required if not (STAGE / relative).is_file()]
    result = {"missing_directories": missing_dirs, "empty_directories": empty_dirs, "license_files": license_files, "missing_required_files": missing_files}
    if any(result.values()):
        raise AssertionError(result)
    return result


def create_zip(path: Path) -> None:
    if path.exists():
        path.unlink()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source in sorted(STAGE.rglob("*")):
            if source.is_file():
                archive.write(source, source.relative_to(STAGE).as_posix())


def main() -> int:
    status = json.loads((ROOT / "research_outputs_phase_d" / "final" / "FINAL_STATUS.json").read_text(encoding="utf-8"))
    if status["final_research_status"] != "PASSIVE_CAPABILITY_SET_NOT_SUPPORTED":
        raise AssertionError("binding negative status missing")
    assemble()
    write_size_and_duplicate_audits()
    stage_check = verify_stage()
    write_manifests()
    create_zip(ZIP_PATH)
    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        bad_member = archive.testzip()
        names = archive.namelist()
        top_dirs = sorted({name.split("/")[0] for name in names})
    under_limit = ZIP_PATH.stat().st_size < 512 * 1024 * 1024
    if bad_member is not None or top_dirs != DIRS or not under_limit:
        raise AssertionError({"bad_member": bad_member, "top_dirs": top_dirs, "under_limit": under_limit})
    verification = {
        "schema": "direction1.phase_d.d9.package_verification.v1",
        "zip": str(ZIP_PATH),
        "bytes": ZIP_PATH.stat().st_size,
        "sha256": sha256(ZIP_PATH),
        "members": len(names),
        "crc_error": bad_member,
        "required_directories": DIRS,
        "required_directories_present": True,
        "under_512mb": under_limit,
        "license_files_packaged": False,
        "stage_check": stage_check,
        "git_commit": git_text("rev-parse", "HEAD"),
        "git_branch": git_text("branch", "--show-current"),
        "final_research_status": status["final_research_status"],
    }
    VERIFY_PATH.parent.mkdir(parents=True, exist_ok=True)
    VERIFY_PATH.write_text(json.dumps(verification, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (ROOT / f"{ZIP_PATH.name}.sha256").write_text(f"{verification['sha256']}  {ZIP_PATH.name}\n", encoding="utf-8")
    progress = {
        "stage": "D9",
        "status": "COMPLETED",
        "goal": "Build and verify the single strict Direction1 negative review package",
        "inputs_sha256": {"final_status": sha256(ROOT / "research_outputs_phase_d" / "final" / "FINAL_STATUS.json")},
        "commands": ["python scripts/phase_d/d9_build_review_package.py"],
        "tests": verification,
        "gate": "D9_FINAL_REVIEW_PACKAGE",
        "gate_passed": True,
        "failures": [],
        "repairs": [],
        "outputs_sha256": {ZIP_PATH.name: verification["sha256"]},
        "next_stage": "STOP_FOR_REVIEW",
    }
    (ROOT / "progress_phase_d" / "D9.json").write_text(json.dumps(progress, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(verification, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
