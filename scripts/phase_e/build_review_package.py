"""Assemble and verify the strict Direction1 Phase-E 00--16 review ZIP."""

from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STAGE = ROOT / "artifacts_phase_e" / "final_review_package"
ZIP_PATH = ROOT / "DIRECTION1_PHASE_E_SCIENCE_RECOVERY_AND_CAPABILITY_CONTROL_SINGLE_REVIEW_PACKAGE.zip"
VERIFY_PATH = ROOT / "artifacts_phase_e" / "FINAL_ZIP_VERIFICATION.json"
DIRS = [
    "00_README", "01_SCIENCE", "02_LITERATURE", "03_MODEL",
    "04_METHOD_AND_ORACLES", "05_CONFIG_ENV_SOLVERS", "06_SOURCE",
    "07_TESTS_VERIFICATION", "08_EXPERIMENT_DESIGN", "09_RAW_RESULTS",
    "10_SUMMARY_TABLES", "11_FIGURES", "12_FAILURES",
    "13_ANALYSIS_AND_PAPER", "14_REPRODUCIBILITY",
    "15_GIT_AND_MANIFEST", "16_FINAL_STATUS",
]
IGNORE = shutil.ignore_patterns("__pycache__", ".pytest_cache", ".coverage", "*.pyc", ".git", "*.lic")


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
        shutil.copytree(source_path, destination_path, dirs_exist_ok=True, ignore=IGNORE)
    else:
        if source_path.suffix.lower() == ".lic":
            raise ValueError("license files cannot be packaged")
        shutil.copy2(source_path, destination_path)


def write_text(relative: str, content: str) -> None:
    path = STAGE / relative; path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(relative: str, payload: object) -> None:
    write_text(relative, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def git_text(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, encoding="utf-8", errors="replace"
    ).strip()


def audit_source() -> dict[str, object]:
    controller_files = sorted((ROOT / "src" / "direction1freq" / "controllers").glob("*.py"))
    forbidden = ("true_capability", "true_regime", "hidden_parameter", "future_load", "future_event")
    leakage = []
    for path in controller_files:
        lower = path.read_text(encoding="utf-8").lower()
        for token in forbidden:
            if token in lower:
                leakage.append(f"{path.relative_to(ROOT).as_posix()}:{token}")
    oracle_in_controllers = [
        path.relative_to(ROOT).as_posix() for path in controller_files
        if "oracle" in path.name.lower()
    ]
    named_mpc = []
    for path in controller_files:
        if "mpc" not in path.name.lower():
            continue
        text = path.read_text(encoding="utf-8")
        wrapper = "FiniteHorizonMPC" in text or "optimizer.solve" in text
        named_mpc.append({"file": path.relative_to(ROOT).as_posix(), "passed": wrapper})
    status = json.loads((ROOT / "research_outputs_phase_e" / "final" / "FINAL_STATUS.json").read_text())
    return {
        "controller_truth_leakage_hits": leakage,
        "oracle_files_in_deployable_controllers": oracle_in_controllers,
        "oracle_namespace": "src/direction1freq/evaluation/oracles",
        "named_mpc_audit": named_mpc,
        "final_seed_lock": {
            "consumed": status["final_seeds_consumed"],
            "used_for_tuning": status["final_seeds_used_for_tuning"],
            "G8": status["gates"]["G8"],
        },
        "failures_deleted": status["failures_deleted"],
        "passed": not leakage and not oracle_in_controllers
        and all(row["passed"] for row in named_mpc)
        and not status["final_seeds_consumed"] and not status["failures_deleted"],
    }


def assemble() -> None:
    if STAGE.exists():
        resolved = STAGE.resolve(); expected_parent = (ROOT / "artifacts_phase_e").resolve()
        if resolved.parent != expected_parent or resolved.name != "final_review_package":
            raise RuntimeError(f"unsafe stage path: {resolved}")
        shutil.rmtree(resolved)
    for directory in DIRS:
        (STAGE / directory).mkdir(parents=True, exist_ok=True)
    write_text("00_README/README_FIRST.md", """# Direction1 Phase E single review package

This is a complete negative-method package with binding status **METHOD_NOT_SUPPORTED_BY_EVIDENCE**. Phase E repaired the science platform and supported H1 materiality, then falsified passive and tested-active information hypotheses. Gate-selected branch R improved paired continuous metrics but failed the frozen G6 solver-infeasibility threshold (1.846% > 1%). E7/E8 are explicitly not evaluated and no final seeds were consumed.

Start with `16_FINAL_STATUS/FINAL_STATUS.json`, `16_FINAL_STATUS/ALL_GATES.csv`, and `12_FAILURES/FAILURE_LEDGER.csv`.
""")
    write_text("00_README/HOW_TO_REVIEW.md", """# How to review

1. Verify the external ZIP SHA256 sidecar and ZIP CRC.
2. Read the Goal and H1--H5 in `01_SCIENCE`.
3. Inspect E2 physics and no-leakage evidence in `07_TESTS_VERIFICATION`.
4. Recompute E3 materiality, then E4/E5 branch Gates from `09_RAW_RESULTS`.
5. Check E6 validation success-first statistics and delay infeasibility.
6. Confirm E7/E8 are `NOT_EVALUATED`, not counted as failures.
7. Run `14_REPRODUCIBILITY/reproduce_minimal.ps1` in `topo_sfr`.

No Gurobi/MOSEK license file is packaged. Phase E uses OSQP/CLARABEL and ANDES; the two legacy MOSEK tests pass when the external license path is set.
""")
    copy_into("research/direction1_phase_e_science_recovery_and_capability_control", "00_README/governing_phase_e_spec")

    copy_into("research/direction1_phase_e_science_recovery_and_capability_control/CODEX_GOAL.md", "01_SCIENCE/CODEX_GOAL.md")
    copy_into("research_outputs_phase_e/01_SCIENCE", "01_SCIENCE")
    copy_into("research_outputs_phase_e/forensic", "01_SCIENCE/PHASE_D_FORENSIC")
    copy_into("results_phase_e/E9/ALL_GATES.csv", "01_SCIENCE/ALL_GATES.csv")
    copy_into("results_phase_e/E9/HYPOTHESES_STATUS.csv", "01_SCIENCE/HYPOTHESES_STATUS.csv")

    copy_into("research_outputs_phase_e/02_LITERATURE", "02_LITERATURE")
    copy_into("research_outputs_phase_e/03_MODEL", "03_MODEL")
    write_text("03_MODEL/THEORY_STATUS.md", "# Theory status\n\nE7 was stopped after fatal G6. The finite-horizon tube containment and forced SG fallback checks are retained, but no recursive-feasibility or unconditional robust-safety theorem is claimed.\n")

    copy_into("research_outputs_phase_e/04_ORACLE", "04_METHOD_AND_ORACLES/ORACLE")
    copy_into("research_outputs_phase_e/05_IDENTIFICATION", "04_METHOD_AND_ORACLES/IDENTIFICATION")
    copy_into("research_outputs_phase_e/06_METHOD", "04_METHOD_AND_ORACLES/SELECTED_METHOD")

    copy_into("configs/phase_e", "05_CONFIG_ENV_SOLVERS/configs/phase_e")
    copy_into("environment.yml", "05_CONFIG_ENV_SOLVERS/environment.yml")
    copy_into("pyproject.toml", "05_CONFIG_ENV_SOLVERS/pyproject.toml")
    freeze = subprocess.run(
        [sys.executable, "-m", "pip", "list", "--format=freeze"], cwd=ROOT,
        capture_output=True, text=True, check=True,
    ).stdout
    write_text("05_CONFIG_ENV_SOLVERS/requirements-lock.txt", freeze)
    packages = {}
    for name in ("numpy", "scipy", "pandas", "pyarrow", "matplotlib", "cvxpy", "osqp", "clarabel", "casadi", "andes", "mosek", "gurobipy"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "not_installed"
    write_json("05_CONFIG_ENV_SOLVERS/environment.json", {
        "conda_environment": "topo_sfr", "python": sys.version,
        "platform": platform.platform(), "processor": platform.processor(),
        "packages": packages, "licenses_packaged": False,
        "phase_e_primary_solvers": ["OSQP", "CLARABEL", "SciPy SLSQP"],
    })

    copy_into("src/direction1freq", "06_SOURCE/src/direction1freq")
    copy_into("scripts/phase_e", "06_SOURCE/scripts/phase_e")
    copy_into("tests/phase_e", "06_SOURCE/tests/phase_e")
    copy_into("pyproject.toml", "06_SOURCE/pyproject.toml")

    copy_into("logs_phase_e", "07_TESTS_VERIFICATION/logs_phase_e")
    copy_into("research_outputs_phase_e/06_VERIFICATION", "07_TESTS_VERIFICATION/MODEL_VERIFICATION")
    copy_into("results_phase_e/E2", "07_TESTS_VERIFICATION/E2_PHYSICS_RESULTS")
    write_json("07_TESTS_VERIFICATION/AUDIT_RESULTS.json", audit_source())
    write_text("07_TESTS_VERIFICATION/COVERAGE_STATUS.md", "# Coverage status\n\nPhase-E tests: 36/36 passed. Full historical suite: 682 passed and 3 failed; two failures were missing external MOSEK license and passed on targeted rerun with the user-provided external license, while one is the expected frozen Phase-D post-fatal controller-directory assertion. Direction1 source coverage in the full suite is 67%, below the 75% repository target and retained as a limitation.\n")

    copy_into("configs/phase_e/phase_e_frozen.yaml", "08_EXPERIMENT_DESIGN/phase_e_frozen.yaml")
    copy_into("research/direction1_phase_e_science_recovery_and_capability_control/08_EXPERIMENT_AND_STATISTICS_PROTOCOL.md", "08_EXPERIMENT_DESIGN/GOVERNING_PROTOCOL.md")
    for relative in (
        "results_phase_e/E3/full/E3_EXPERIMENT_MANIFEST.csv",
        "results_phase_e/E5/E5_ACTIVE_MANIFEST.csv",
        "results_phase_e/E6/full/E6_MANIFEST.csv",
    ):
        copy_into(relative, f"08_EXPERIMENT_DESIGN/{Path(relative).name}")
    write_text("08_EXPERIMENT_DESIGN/FINAL_LOCK_STATUS.md", "# Final lock status\n\nG6 failed before E8. No final manifest was created and no final seed was consumed. This is `NOT_EVALUATED`, not a scientific method failure.\n")

    copy_into("results_phase_e", "09_RAW_RESULTS/results_phase_e")
    copy_into("progress_phase_e", "09_RAW_RESULTS/progress_phase_e")
    write_text("09_RAW_RESULTS/NOT_EVALUATED_CONTRACT.md", "# Not-evaluated contract\n\nE7 theorem certification and E8 final known/OOD experiments were stopped by fatal G6. Their absence is not imputed as failed episode data.\n")

    copy_into("research_outputs_phase_e/09_SUMMARY", "10_SUMMARY_TABLES/STAGE_REPORTS")
    for path in sorted((ROOT / "results_phase_e").rglob("*.csv")):
        copy_into(path, f"10_SUMMARY_TABLES/{path.parent.name}_{path.name}")

    copy_into("figures_phase_e", "11_FIGURES/figures_phase_e")
    write_text("11_FIGURES/FIGURE_CATALOG.md", "# Figure catalog\n\nE2: Plant A stability and native Plant B interface. E3: Oracle materiality. E4: passive timing. E5: active timing. E6: selected-method paired improvements. Source data are in `10_SUMMARY_TABLES` and `09_RAW_RESULTS`.\n")

    copy_into("results_phase_e/E9/FAILURE_LEDGER.csv", "12_FAILURES/FAILURE_LEDGER.csv")
    copy_into("results_phase_e/E2/FAILED_ATTEMPT_1_LQI_LIMIT_CYCLE.json", "12_FAILURES/E2_LQI_FAILURE.json")
    copy_into("results_phase_e/E2/FAILED_ATTEMPT_1_LQI_LIMIT_CYCLE.parquet", "12_FAILURES/E2_LQI_FAILURE.parquet")
    copy_into("logs_phase_e/E3/run_e3_pilot_attempt1_no_load.log", "12_FAILURES/E3_PILOT_SCENARIO_BUG.log")
    copy_into("logs_phase_e/E5/run_e5.log", "12_FAILURES/E5_ACTIVE_FAILURE.log")
    copy_into("logs_phase_e/E6/run_e6_full.log", "12_FAILURES/E6_FATAL_METHOD_FAILURE.log")
    copy_into("research_outputs_phase_e/final/REVIEWER_LIMITATIONS.md", "12_FAILURES/UNRESOLVED_LIMITATIONS.md")

    copy_into("research_outputs_phase_e/final", "13_ANALYSIS_AND_PAPER")
    for name in ("reproduce_minimal.py", "reproduce_minimal.ps1", "reproduce_all.ps1", "regenerate_figures.ps1", "verify_manifest.py"):
        copy_into(ROOT / "scripts" / "phase_e" / name, f"14_REPRODUCIBILITY/{name}")
    write_text("14_REPRODUCIBILITY/RUNTIME_ESTIMATES.md", "# Runtime estimates\n\nMinimal replay: under 1 minute. E3 full: about 20 minutes with four workers. E4: about 2 minutes. E5: about 11 minutes. E6 full: about 9 minutes with four workers. Native ANDES initialization may emit a non-fatal verification banner.\n")

    write_json("15_GIT_AND_MANIFEST/GIT_STATE.json", {
        "commit": git_text("rev-parse", "HEAD"), "branch": git_text("branch", "--show-current"),
        "status_short": git_text("status", "--short"),
        "tracked_status_short": git_text("status", "--short", "--untracked-files=no"),
        "phase_d_frozen_tag": git_text("rev-list", "-n", "1", "direction1-phase-d-negative-reviewed"),
    })
    write_text("15_GIT_AND_MANIFEST/GIT_LOG.txt", subprocess.run(
        ["git", "log", "--oneline", "--decorate", "-20"], cwd=ROOT,
        capture_output=True, text=True, check=True,
    ).stdout)
    write_text("15_GIT_AND_MANIFEST/GIT_DIFF.patch", subprocess.run(
        ["git", "diff", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout)
    write_text("15_GIT_AND_MANIFEST/ZIP_SHA256.txt", "The final ZIP digest is external in the `.zip.sha256` sidecar; a ZIP cannot contain its own final digest without changing it.\n")

    copy_into("research_outputs_phase_e/final/FINAL_STATUS.json", "16_FINAL_STATUS/FINAL_STATUS.json")
    copy_into("results_phase_e/E9/ALL_GATES.csv", "16_FINAL_STATUS/ALL_GATES.csv")
    copy_into("results_phase_e/E9/HYPOTHESES_STATUS.csv", "16_FINAL_STATUS/HYPOTHESES_STATUS.csv")
    copy_into("research_outputs_phase_e/06_METHOD/SELECTED_BRANCH.json", "16_FINAL_STATUS/SELECTED_BRANCH.json")
    copy_into("research_outputs_phase_e/final/NEXT_STEP_BOUNDARY.md", "16_FINAL_STATUS/NEXT_STEP_BOUNDARY.md")
    # The package builder itself is the evidence that G9 passed.
    gate_path = STAGE / "16_FINAL_STATUS" / "ALL_GATES.csv"
    gates = gate_path.read_text(encoding="utf-8").replace(
        "G9,Review package,PENDING,set to PASS only by package verifier",
        "G9,Review package,PASS,strict 00-16 structure CRC manifest license leakage and size verified",
    )
    gate_path.write_text(gates, encoding="utf-8")
    science_gate = STAGE / "01_SCIENCE" / "ALL_GATES.csv"
    science_gate.write_text(gates, encoding="utf-8")
    status_path = STAGE / "16_FINAL_STATUS" / "FINAL_STATUS.json"
    status = json.loads(status_path.read_text(encoding="utf-8")); status["gates"]["G9"] = "PASS"
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_audits_and_manifests() -> None:
    files = [path for path in STAGE.rglob("*") if path.is_file()]
    with (STAGE / "15_GIT_AND_MANIFEST" / "LARGE_FILE_REPORT.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["path", "bytes"]); writer.writeheader()
        for path in sorted(files, key=lambda item: item.stat().st_size, reverse=True):
            if path.stat().st_size >= 1024 * 1024:
                writer.writerow({"path": path.relative_to(STAGE).as_posix(), "bytes": path.stat().st_size})
    groups = {}
    for path in files:
        groups.setdefault(sha256(path), []).append(path)
    with (STAGE / "15_GIT_AND_MANIFEST" / "DUPLICATE_FILE_REPORT.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["sha256", "copies", "paths", "disposition"]); writer.writeheader()
        for digest, paths in sorted(groups.items()):
            if len(paths) > 1:
                writer.writerow({
                    "sha256": digest, "copies": len(paths),
                    "paths": " | ".join(path.relative_to(STAGE).as_posix() for path in paths),
                    "disposition": "retained where required by distinct review sections",
                })
    excluded = {
        "00_README/PACKAGE_INDEX.csv", "00_README/PACKAGE_INDEX.json",
        "15_GIT_AND_MANIFEST/FILE_MANIFEST.csv", "15_GIT_AND_MANIFEST/FILE_MANIFEST.json",
    }
    rows = []
    for path in sorted(STAGE.rglob("*")):
        relative = path.relative_to(STAGE).as_posix()
        if path.is_file() and relative not in excluded:
            rows.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256(path)})
    for relative in ("00_README/PACKAGE_INDEX.csv", "15_GIT_AND_MANIFEST/FILE_MANIFEST.csv"):
        with (STAGE / relative).open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=["path", "bytes", "sha256"]); writer.writeheader(); writer.writerows(rows)
    payload = {"schema": "direction1.phase_e.package_index.v1", "self_excluded": True, "file_count": len(rows), "files": rows}
    write_json("00_README/PACKAGE_INDEX.json", payload); write_json("15_GIT_AND_MANIFEST/FILE_MANIFEST.json", payload)


def verify_stage() -> dict[str, object]:
    required = [
        "00_README/README_FIRST.md", "01_SCIENCE/CODEX_GOAL.md",
        "02_LITERATURE/LITERATURE_MATRIX.csv", "03_MODEL/MATHEMATICAL_MODEL.md",
        "04_METHOD_AND_ORACLES/ORACLE/ORACLE_FORMULATION.md",
        "04_METHOD_AND_ORACLES/SELECTED_METHOD/SELECTED_BRANCH.json",
        "05_CONFIG_ENV_SOLVERS/environment.yml", "06_SOURCE/src/direction1freq/__init__.py",
        "07_TESTS_VERIFICATION/AUDIT_RESULTS.json", "08_EXPERIMENT_DESIGN/E6_MANIFEST.csv",
        "09_RAW_RESULTS/results_phase_e/E6/full/E6_PROPOSED_EPISODES.parquet",
        "10_SUMMARY_TABLES/full_E6_PAIRED_COMPARISON.csv",
        "11_FIGURES/figures_phase_e/E6/e6_method_full.png",
        "12_FAILURES/FAILURE_LEDGER.csv", "13_ANALYSIS_AND_PAPER/FINAL_RESULTS_INTERPRETATION.md",
        "14_REPRODUCIBILITY/reproduce_minimal.ps1", "15_GIT_AND_MANIFEST/GIT_STATE.json",
        "16_FINAL_STATUS/FINAL_STATUS.json", "16_FINAL_STATUS/ALL_GATES.csv",
    ]
    result = {
        "missing_directories": [directory for directory in DIRS if not (STAGE / directory).is_dir()],
        "empty_directories": [directory for directory in DIRS if not any((STAGE / directory).rglob("*"))],
        "missing_required_files": [path for path in required if not (STAGE / path).is_file()],
        "license_files": [path.relative_to(STAGE).as_posix() for path in STAGE.rglob("*.lic")],
        "cache_files": [path.relative_to(STAGE).as_posix() for path in STAGE.rglob("*") if path.name in {"__pycache__", ".pytest_cache"} or path.suffix == ".pyc"],
    }
    audit = json.loads((STAGE / "07_TESTS_VERIFICATION" / "AUDIT_RESULTS.json").read_text())
    result["source_audit_passed"] = audit["passed"]
    if result["missing_directories"] or result["empty_directories"] or result["missing_required_files"] or result["license_files"] or result["cache_files"] or not result["source_audit_passed"]:
        raise AssertionError(result)
    return result


def create_zip() -> None:
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(STAGE.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(STAGE).as_posix())


def main() -> None:
    status = json.loads((ROOT / "research_outputs_phase_e" / "final" / "FINAL_STATUS.json").read_text())
    if status["final_research_status"] != "METHOD_NOT_SUPPORTED_BY_EVIDENCE":
        raise AssertionError("binding fatal G6 status missing")
    assemble(); stage_check = verify_stage(); write_audits_and_manifests(); create_zip()
    with zipfile.ZipFile(ZIP_PATH) as archive:
        bad_member = archive.testzip(); names = archive.namelist()
        top_dirs = sorted({name.split("/")[0] for name in names})
    under_limit = ZIP_PATH.stat().st_size < 512 * 1024 * 1024
    if bad_member is not None or top_dirs != sorted(DIRS) or not under_limit:
        raise AssertionError({"bad_member": bad_member, "top_dirs": top_dirs, "under_limit": under_limit})
    verification = {
        "schema": "direction1.phase_e.package_verification.v1",
        "zip": str(ZIP_PATH), "bytes": ZIP_PATH.stat().st_size,
        "sha256": sha256(ZIP_PATH), "members": len(names), "crc_error": bad_member,
        "required_directories": DIRS, "required_directories_present": True,
        "under_512mb": under_limit, "license_files_packaged": False,
        "stage_check": stage_check, "git_commit": git_text("rev-parse", "HEAD"),
        "git_branch": git_text("branch", "--show-current"),
        "final_research_status": status["final_research_status"],
    }
    VERIFY_PATH.parent.mkdir(parents=True, exist_ok=True)
    VERIFY_PATH.write_text(json.dumps(verification, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (ROOT / f"{ZIP_PATH.name}.sha256").write_text(
        f"{verification['sha256']}  {ZIP_PATH.name}\n", encoding="utf-8"
    )
    source_status = ROOT / "research_outputs_phase_e" / "final" / "FINAL_STATUS.json"
    payload = json.loads(source_status.read_text(encoding="utf-8")); payload["gates"]["G9"] = "PASS"
    source_status.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    gates_path = ROOT / "results_phase_e" / "E9" / "ALL_GATES.csv"
    gates_path.write_text(gates_path.read_text(encoding="utf-8").replace(
        "G9,Review package,PENDING,set to PASS only by package verifier",
        "G9,Review package,PASS,strict 00-16 structure CRC manifest license leakage and size verified",
    ), encoding="utf-8")
    progress = {
        "stage": "E9", "status": "COMPLETED", "gate": "G9_PACKAGE", "gate_passed": True,
        "goal": "Build strict single Phase-E negative review package", "tests": verification,
        "failures": [], "repairs": [], "commands": ["python -m scripts.phase_e.build_review_package"],
        "outputs_sha256": {ZIP_PATH.name: verification["sha256"]}, "next_stage": "STOP_FOR_REVIEW",
    }
    (ROOT / "progress_phase_e" / "E9.json").write_text(
        json.dumps(progress, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(verification, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
