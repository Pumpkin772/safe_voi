"""Build and fresh-extract replay the Direction5 VOI-ACCR review package."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


REPO = Path(__file__).resolve().parents[2]
ARTIFACTS = REPO / "artifacts_direction5_voi_accr"
STAGING = ARTIFACTS / "p"
FRESH = ARTIFACTS / "x"
ZIP_PATH = REPO / "DIRECTION5_VOI_ACCR_MPC_SINGLE_REVIEW_PACKAGE.zip"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def copy_path(source: Path, target: Path) -> None:
    if not source.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(
            source,
            target,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", ".pytest_cache", "*.egg-info", "*.lic"
            ),
        )
    else:
        shutil.copy2(source, target)


def _assert_artifact_target(path: Path) -> None:
    resolved = path.resolve()
    root = ARTIFACTS.resolve()
    if root not in resolved.parents:
        raise RuntimeError(f"refusing broad artifact deletion: {resolved}")


def _write_reproduction_scripts() -> None:
    root = STAGING / "16_REPRODUCIBILITY"
    root.mkdir(parents=True, exist_ok=True)
    root.joinpath("verify_manifest.py").write_text(
        """from pathlib import Path
import csv, hashlib

root = Path(__file__).resolve().parents[1]
manifest = root / '17_GIT_MANIFEST/MANIFEST.csv'
rows = list(csv.DictReader(manifest.open(encoding='utf-8', newline='')))
for row in rows:
    path = root / row['path']
    assert path.is_file(), row['path']
    assert path.stat().st_size == int(row['bytes']), row['path']
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    assert value.hexdigest() == row['sha256'], row['path']
print(f'MANIFEST_OK files={len(rows)}')
""",
        encoding="utf-8",
    )
    root.joinpath("reproduce_minimal.py").write_text(
        """from pathlib import Path
import csv, json

root = Path(__file__).resolve().parents[1]
status = json.loads((root / '18_FINAL_STATUS/FINAL_STATUS.json').read_text('utf-8'))
assert status['final_status'] == 'DIRECTION5_TERMINATED_WITH_DECISIVE_NEGATIVE_EVIDENCE'
assert status['m1'] == 'PASS_DEVELOPMENT_ONLY'
assert status['m2'] == 'FAIL'
assert status['final'] == 'NOT_EVALUATED'
assert status['final_seeds_consumed'] is False

paired_path = root / '11_RAW_RESULTS/M2/M2_PAIRED.csv'
paired = list(csv.DictReader(paired_path.open(encoding='utf-8', newline='')))
assert len(paired) == status['scenario_count'] == 60
high = [row for row in paired if row['probe_worthwhile_preregistered'].lower() == 'true']
low = [row for row in paired if row['probe_worthwhile_preregistered'].lower() == 'false']
probed = [row for row in paired if float(row['voi_probe_triggers__voi_accr_mpc']) > 0]
assert len(high) == 30 and len(low) == 30 and len(probed) == 24
assert all(float(row['voi_probe_triggers__voi_accr_mpc']) == 0 for row in low)

screen_path = root / '08_DEVELOPMENT_SEARCH/ORACLE_HORIZON_SCREEN/SUMMARY.csv'
screen = list(csv.DictReader(screen_path.open(encoding='utf-8', newline='')))
assert [int(row['horizon_steps']) for row in screen] == [3, 4, 6]
assert all(row['oracle_materiality_pass'].lower() == 'false' for row in screen)
assert max(float(row['oracle_ace_iae_pu_s_aggregate_improvement']) for row in screen) < 0.04
assert max(float(row['oracle_tie_iae_pu_s_aggregate_improvement']) for row in screen) < 0.04

episodes_path = root / '11_RAW_RESULTS/M2/M2_EPISODES.csv'
episodes = list(csv.DictReader(episodes_path.open(encoding='utf-8', newline='')))
attempted = sum(int(float(row['attempted_optimization_calls'])) for row in episodes)
failures = sum(int(float(row['solver_failure_calls'])) for row in episodes)
fallbacks = sum(int(float(row['fallback_calls'])) for row in episodes)
assert attempted == status['attempted_optimization_calls'] == 32043
assert failures == status['solver_failure_calls'] == 0
assert fallbacks == status['fallback_calls'] == 0
print(status['final_status'])
print('MINIMAL_REPLAY_OK')
""",
        encoding="utf-8",
    )
    root.joinpath("reproduce_all.py").write_text(
        """from pathlib import Path
import argparse, os, subprocess, sys

parser = argparse.ArgumentParser()
parser.add_argument('--execute-expensive', action='store_true')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
subprocess.run([sys.executable, '16_REPRODUCIBILITY/verify_manifest.py'], cwd=root, check=True)
subprocess.run([sys.executable, '16_REPRODUCIBILITY/reproduce_minimal.py'], cwd=root, check=True)
snapshot = root / '06_SOURCE_ENV/repo_snapshot'
environment = os.environ.copy()
environment['PYTHONPATH'] = str(snapshot / 'src')
subprocess.run(
    [sys.executable, '-m', 'pytest', 'tests/direction5_voi_accr', '-q'],
    cwd=snapshot,
    env=environment,
    check=True,
)
if args.execute_expensive:
    subprocess.run(
        [sys.executable, 'scripts/direction5_voi_accr/run_m2_guarded.py', '--oracle-horizon-screen'],
        cwd=snapshot,
        env=environment,
        check=True,
    )
else:
    print('EXPENSIVE_SIMULATION_SKIPPED; pass --execute-expensive to rerun the guarded Oracle screen')
print('REPRODUCE_ALL_OK')
""",
        encoding="utf-8",
    )


def populate() -> None:
    for target in (STAGING, FRESH):
        _assert_artifact_target(target)
        if target.exists():
            shutil.rmtree(target)
    STAGING.mkdir(parents=True)
    for name in (
        "00_README", "01_SCIENCE", "02_LITERATURE", "03_MATHEMATICS",
        "04_METHOD", "05_PLATFORM", "06_SOURCE_ENV", "07_TESTS",
        "08_DEVELOPMENT_SEARCH", "09_VALIDATION", "10_FINAL",
        "11_RAW_RESULTS", "12_SUMMARY_TABLES", "13_FIGURES",
        "14_FAILURES", "15_PAPER_DRAFT", "16_REPRODUCIBILITY",
        "17_GIT_MANIFEST", "18_FINAL_STATUS",
    ):
        (STAGING / name).mkdir(parents=True, exist_ok=True)

    STAGING.joinpath("00_README/README_FIRST.md").write_text(
        """# Direction5 VOI-ACCR-MPC single review package

Read `18_FINAL_STATUS/FINAL_STATUS.json` and `01_SCIENCE/FINAL_RESEARCH_DECISION.md` first. The terminal result is a bounded decisive negative. M1 is development-only, M2 failed independent validation, Final is not evaluated, and final seeds 6200--6299 remain unconsumed. No failed or invalidated run was removed.
""",
        encoding="utf-8",
    )

    mappings = (
        (REPO / "research/direction5_voi_accr_mpc_result_driven/README_FIRST.md", STAGING / "00_README/ORIGINAL_README_FIRST.md"),
        (REPO / "research/direction5_voi_accr_mpc_result_driven/CODEX_GOAL.md", STAGING / "01_SCIENCE/CODEX_GOAL.md"),
        (REPO / "research/direction5_voi_accr_mpc_result_driven/01_LOCKED_SCIENTIFIC_QUESTION_AND_TARGET.md", STAGING / "01_SCIENCE/LOCKED_SCIENTIFIC_QUESTION_AND_TARGET.md"),
        (REPO / "research/direction5_voi_accr_mpc_result_driven/03_RESULT_DRIVEN_RESEARCH_PLAN.md", STAGING / "01_SCIENCE/RESULT_DRIVEN_RESEARCH_PLAN.md"),
        (REPO / "research/direction5_voi_accr_mpc_result_driven/FINAL_RESEARCH_DECISION.md", STAGING / "01_SCIENCE/FINAL_RESEARCH_DECISION.md"),
        (REPO / "research_outputs_accr/02_LITERATURE", STAGING / "02_LITERATURE/HISTORICAL_ACCR_LITERATURE"),
        (REPO / "research/direction5_voi_accr_mpc_result_driven/02_VOI_ACCR_MATHEMATICAL_AND_METHOD_SPEC.md", STAGING / "03_MATHEMATICS/VOI_ACCR_MATHEMATICAL_AND_METHOD_SPEC.md"),
        (REPO / "research/direction5_voi_accr_mpc_result_driven/M1_SELECTED_PROTOTYPE.md", STAGING / "04_METHOD/M1_SELECTED_PROTOTYPE.md"),
        (REPO / "research/direction5_voi_accr_mpc_result_driven/00_DIAGNOSIS_OF_CURRENT_PACKAGE.md", STAGING / "04_METHOD/INITIAL_INTEGRATION_DIAGNOSIS.md"),
        (REPO / "research_outputs_working/M1/M1_INTEGRATION_AUDIT.md", STAGING / "05_PLATFORM/M1_INTEGRATION_AUDIT.md"),
        (REPO / "logs_direction5_voi_accr/M2/ORACLE_HORIZON_SCREEN_MEMORY_MONITOR_SUMMARY.json", STAGING / "05_PLATFORM/ORACLE_HORIZON_SCREEN_MEMORY_MONITOR_SUMMARY.json"),
        (REPO / "logs_direction5_voi_accr", STAGING / "05_PLATFORM/logs_direction5_voi_accr"),
        (REPO / "src", STAGING / "06_SOURCE_ENV/repo_snapshot/src"),
        (REPO / "scripts/direction5_voi_accr", STAGING / "06_SOURCE_ENV/repo_snapshot/scripts/direction5_voi_accr"),
        (REPO / "scripts/direction5_accr", STAGING / "06_SOURCE_ENV/repo_snapshot/scripts/direction5_accr"),
        (REPO / "configs/direction5_voi_accr", STAGING / "06_SOURCE_ENV/repo_snapshot/configs/direction5_voi_accr"),
        (REPO / "tests/direction5_voi_accr", STAGING / "06_SOURCE_ENV/repo_snapshot/tests/direction5_voi_accr"),
        (REPO / "environment.yml", STAGING / "06_SOURCE_ENV/repo_snapshot/environment.yml"),
        (REPO / "pyproject.toml", STAGING / "06_SOURCE_ENV/repo_snapshot/pyproject.toml"),
        (REPO / "tests/direction5_voi_accr", STAGING / "07_TESTS/tests_direction5_voi_accr"),
        (REPO / "research_outputs_working/M1", STAGING / "08_DEVELOPMENT_SEARCH/M1"),
        (REPO / "research_outputs_working/M1_R1_POST_M2", STAGING / "08_DEVELOPMENT_SEARCH/M1_R1_POST_M2"),
        (REPO / "research_outputs_working/M1_R2_POST_M2", STAGING / "08_DEVELOPMENT_SEARCH/M1_R2_POST_M2"),
        (REPO / "research_outputs_working/M2_FAIRNESS_SMOKE", STAGING / "08_DEVELOPMENT_SEARCH/M2_FAIRNESS_SMOKE"),
        (REPO / "research_outputs_working/ORACLE_HORIZON_SCREEN", STAGING / "08_DEVELOPMENT_SEARCH/ORACLE_HORIZON_SCREEN"),
        (REPO / "results_direction5_voi_accr/M2", STAGING / "09_VALIDATION/V2_VALID_FAIL"),
        (REPO / "results_direction5_voi_accr/M2_V1_INVALIDATED_BASELINE_CLASS_MISMATCH", STAGING / "09_VALIDATION/V1_INVALIDATED"),
        (REPO / "results_direction5_voi_accr/final/FINAL_SEED_AUDIT.json", STAGING / "10_FINAL/FINAL_SEED_AUDIT.json"),
        (REPO / "results_direction5_voi_accr/M2", STAGING / "11_RAW_RESULTS/M2"),
        (REPO / "results_direction5_voi_accr/M2_V1_INVALIDATED_BASELINE_CLASS_MISMATCH", STAGING / "11_RAW_RESULTS/V1_INVALIDATED"),
        (REPO / "results_direction5_voi_accr/final", STAGING / "12_SUMMARY_TABLES"),
        (REPO / "research_outputs_direction5_voi_accr/figures", STAGING / "13_FIGURES"),
        (REPO / "research_outputs_direction5_voi_accr/failures", STAGING / "14_FAILURES"),
        (REPO / "results_direction5_voi_accr/final/FAILURE_LEDGER.csv", STAGING / "14_FAILURES/FAILURE_LEDGER.csv"),
        (REPO / "research_outputs_direction5_voi_accr/paper", STAGING / "15_PAPER_DRAFT"),
        (REPO / "results_direction5_voi_accr/final/FINAL_STATUS.json", STAGING / "18_FINAL_STATUS/FINAL_STATUS.json"),
        (REPO / "results_direction5_voi_accr/final/ALL_GATES.csv", STAGING / "18_FINAL_STATUS/ALL_GATES.csv"),
        (REPO / "results_direction5_voi_accr/final/MILESTONE_STATUS.csv", STAGING / "18_FINAL_STATUS/MILESTONE_STATUS.csv"),
    )
    for source, target in mappings:
        copy_path(source, target)

    git_dir = STAGING / "17_GIT_MANIFEST"
    git_dir.joinpath("GIT_COMMIT.txt").write_text(
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True), encoding="utf-8"
    )
    git_dir.joinpath("GIT_BRANCH.txt").write_text(
        subprocess.check_output(["git", "branch", "--show-current"], cwd=REPO, text=True), encoding="utf-8"
    )
    git_dir.joinpath("GIT_STATUS.txt").write_text(
        subprocess.check_output(["git", "status", "--short"], cwd=REPO, text=True), encoding="utf-8"
    )
    _write_reproduction_scripts()


def validate_staging() -> None:
    required = [
        "00_README", "01_SCIENCE", "02_LITERATURE", "03_MATHEMATICS",
        "04_METHOD", "05_PLATFORM", "06_SOURCE_ENV", "07_TESTS",
        "08_DEVELOPMENT_SEARCH", "09_VALIDATION", "10_FINAL",
        "11_RAW_RESULTS", "12_SUMMARY_TABLES", "13_FIGURES",
        "14_FAILURES", "15_PAPER_DRAFT", "16_REPRODUCIBILITY",
        "17_GIT_MANIFEST", "18_FINAL_STATUS",
    ]
    missing = [name for name in required if not (STAGING / name).is_dir()]
    if missing:
        raise RuntimeError(f"missing required directories: {missing}")
    status = json.loads((STAGING / "18_FINAL_STATUS/FINAL_STATUS.json").read_text("utf-8"))
    if status["final_status"] != "DIRECTION5_TERMINATED_WITH_DECISIVE_NEGATIVE_EVIDENCE":
        raise RuntimeError("unexpected terminal result")
    if status["final_seeds_consumed"] is not False:
        raise RuntimeError("final seed audit is inconsistent")
    paper = (STAGING / "15_PAPER_DRAFT/MANUSCRIPT.md").read_text("utf-8")
    if "[PREDICTED]" in paper or "TO BE FILLED" in paper:
        raise RuntimeError("manuscript contains predicted-result placeholders")
    if not list((STAGING / "11_RAW_RESULTS/M2/cycle_parts").glob("*.parquet")):
        raise RuntimeError("raw control-cycle trajectories are missing")


def write_manifest() -> None:
    target = STAGING / "17_GIT_MANIFEST/MANIFEST.csv"
    rows = []
    for path in sorted(STAGING.rglob("*")):
        if not path.is_file() or path == target:
            continue
        rows.append(
            {"path": path.relative_to(STAGING).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)}
        )
    with target.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("path", "bytes", "sha256"))
        writer.writeheader()
        writer.writerows(rows)


def build_zip() -> None:
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(STAGING.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(STAGING).as_posix())
    if ZIP_PATH.stat().st_size >= 512 * 1024 * 1024:
        raise RuntimeError("review package exceeds 512 MiB")


def fresh_replay() -> None:
    FRESH.mkdir(parents=True)
    with zipfile.ZipFile(ZIP_PATH) as archive:
        archive.extractall(FRESH)
        bad = archive.testzip()
        if bad is not None:
            raise RuntimeError(f"ZIP CRC failure: {bad}")
    subprocess.run([sys.executable, "16_REPRODUCIBILITY/verify_manifest.py"], cwd=FRESH, check=True)
    subprocess.run([sys.executable, "16_REPRODUCIBILITY/reproduce_minimal.py"], cwd=FRESH, check=True)


def main() -> None:
    populate()
    validate_staging()
    write_manifest()
    build_zip()
    fresh_replay()
    sha = digest(ZIP_PATH)
    ZIP_PATH.with_suffix(ZIP_PATH.suffix + ".sha256").write_text(
        f"{sha}  {ZIP_PATH.name}\n", encoding="utf-8"
    )
    audit = {
        "zip_absolute_path": str(ZIP_PATH.resolve()),
        "bytes": ZIP_PATH.stat().st_size,
        "megabytes": ZIP_PATH.stat().st_size / 1_000_000.0,
        "mebibytes": ZIP_PATH.stat().st_size / (1024.0 * 1024.0),
        "sha256": sha,
        "fresh_extract_manifest": "PASS",
        "fresh_extract_minimal_replay": "PASS",
    }
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "FINAL_PACKAGE_AUDIT.json").write_text(
        json.dumps(audit, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
