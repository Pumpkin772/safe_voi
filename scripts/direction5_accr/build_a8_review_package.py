"""Build and fresh-extract replay the final Direction5 ACCR review package."""

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
ARTIFACTS = REPO / "artifacts_accr"
STAGING = ARTIFACTS / "final_review_package"
FRESH = ARTIFACTS / "fresh_extract_check"
ZIP_PATH = REPO / "DIRECTION5_ACCR_MPC_SINGLE_REVIEW_PACKAGE.zip"


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
            source, target, dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", ".pytest_cache", "*.egg-info",
                "*CHECKPOINT*", "*.lic",
            ),
        )
    else:
        shutil.copy2(source, target)


def _assert_artifact_target(path: Path) -> None:
    resolved = path.resolve()
    root = ARTIFACTS.resolve()
    if root not in resolved.parents:
        raise RuntimeError(f"refusing broad artifact deletion: {resolved}")


def populate() -> None:
    for target in (STAGING, FRESH):
        _assert_artifact_target(target)
        if target.exists():
            shutil.rmtree(target)
    STAGING.mkdir(parents=True)
    readme = STAGING / "00_README/README_FIRST.md"
    readme.parent.mkdir(parents=True)
    readme.write_text("""# Direction5 ACCR-MPC single review package

This archive contains the complete A0--A8 evidence path. Read `19_FINAL_STATUS/FINAL_STATUS.json` first. Historical DCSV-CR negative evidence is frozen and not overwritten. Run the two scripts in `17_REPRODUCIBILITY` from this extracted root.
""", encoding="utf-8")
    mappings = (
        (REPO / "research_outputs_accr/00_AUDIT", STAGING / "01_AUDIT/00_PLATFORM_AUDIT"),
        (REPO / "research_outputs_accr/01_AUDIT", STAGING / "01_AUDIT/01_SCIENCE_AUDIT"),
        (REPO / "research/direction5_accr_mpc_one_goal", STAGING / "02_SCIENCE/governing_goal"),
        (REPO / "research_outputs_accr/02_LITERATURE", STAGING / "03_LITERATURE"),
        (REPO / "research_outputs_accr/03_MODEL", STAGING / "04_MODEL"),
        (REPO / "research_outputs_accr/04_IDENTIFICATION", STAGING / "05_IDENTIFICATION"),
        (REPO / "research_outputs_accr/05_PROBING", STAGING / "06_PROBE_DESIGN"),
        (REPO / "research_outputs_accr/06_METHOD", STAGING / "07_METHOD"),
        (REPO / "research_outputs_accr/07_THEORY", STAGING / "08_THEORY"),
        (REPO / "src/direction5freq", STAGING / "09_SOURCE_ENV/src/direction5freq"),
        (REPO / "scripts/direction5_accr", STAGING / "09_SOURCE_ENV/scripts/direction5_accr"),
        (REPO / "configs/direction5_accr", STAGING / "09_SOURCE_ENV/configs/direction5_accr"),
        (REPO / "research_outputs_accr/02_LITERATURE/A1_FORMAL_LITERATURE_REGISTRY.csv", STAGING / "09_SOURCE_ENV/research_outputs_accr/02_LITERATURE/A1_FORMAL_LITERATURE_REGISTRY.csv"),
        (REPO / "environment.yml", STAGING / "09_SOURCE_ENV/environment.yml"),
        (REPO / "pyproject.toml", STAGING / "09_SOURCE_ENV/pyproject.toml"),
        (REPO / "tests/direction5_accr", STAGING / "10_TESTS/tests/direction5_accr"),
        (REPO / "results_accr/A6/development/A6_DEVELOPMENT_MANIFEST.csv", STAGING / "11_EXPERIMENT_DESIGN/A6_DEVELOPMENT_MANIFEST.csv"),
        (REPO / "results_accr/A6/validation/A6_PLANT_A_MANIFEST.csv", STAGING / "11_EXPERIMENT_DESIGN/A6_PLANT_A_MANIFEST.csv"),
        (REPO / "results_accr/A6/validation/A6_PLANT_B_MANIFEST.csv", STAGING / "11_EXPERIMENT_DESIGN/A6_PLANT_B_MANIFEST.csv"),
        (REPO / "results_accr/A6/validation/A6_NORMAL1H_MANIFEST.csv", STAGING / "11_EXPERIMENT_DESIGN/A6_NORMAL1H_MANIFEST.csv"),
        (REPO / "results_accr/A7/A7_FINAL_MANIFEST.csv", STAGING / "11_EXPERIMENT_DESIGN/A7_FINAL_MANIFEST.csv"),
        (REPO / "results_accr", STAGING / "12_RAW_RESULTS/results_accr"),
        (REPO / "results_accr/final", STAGING / "13_SUMMARY_TABLES"),
        (REPO / "research_outputs_accr/09_FIGURES", STAGING / "14_FIGURES"),
        (REPO / "research_outputs_accr/11_FAILURES", STAGING / "15_FAILURES"),
        (REPO / "logs_accr", STAGING / "15_FAILURES/logs_accr"),
        (REPO / "research_outputs_accr/10_PAPER", STAGING / "16_PAPER_DRAFT"),
        (REPO / "results_accr/final/FINAL_STATUS.json", STAGING / "19_FINAL_STATUS/FINAL_STATUS.json"),
        (REPO / "results_accr/final/ALL_GATES.csv", STAGING / "19_FINAL_STATUS/ALL_GATES.csv"),
        (REPO / "results_accr/final/HYPOTHESES_H1_H6.csv", STAGING / "19_FINAL_STATUS/HYPOTHESES_H1_H6.csv"),
    )
    for source, target in mappings:
        copy_path(source, target)

    git_dir = STAGING / "18_GIT_MANIFEST"
    git_dir.mkdir(parents=True, exist_ok=True)
    git_dir.joinpath("GIT_COMMIT.txt").write_text(
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True), encoding="utf-8"
    )
    git_dir.joinpath("GIT_STATUS.txt").write_text(
        subprocess.check_output(["git", "status", "--short"], cwd=REPO, text=True), encoding="utf-8"
    )

    reproduce = STAGING / "17_REPRODUCIBILITY"
    reproduce.mkdir(parents=True, exist_ok=True)
    reproduce.joinpath("verify_manifest.py").write_text("""from pathlib import Path
import csv, hashlib

root = Path(__file__).resolve().parents[1]
manifest = root / '18_GIT_MANIFEST/MANIFEST.csv'
rows = list(csv.DictReader(manifest.open(encoding='utf-8', newline='')))
for row in rows:
    path = root / row['path']
    assert path.is_file(), row['path']
    assert path.stat().st_size == int(row['bytes']), row['path']
    assert hashlib.sha256(path.read_bytes()).hexdigest() == row['sha256'], row['path']
print(f'MANIFEST_OK files={len(rows)}')
""", encoding="utf-8")
    reproduce.joinpath("reproduce_minimal.py").write_text("""from pathlib import Path
import json
import pandas as pd

root = Path(__file__).resolve().parents[1]
status = json.loads((root / '19_FINAL_STATUS/FINAL_STATUS.json').read_text('utf-8'))
allowed = {'PAPER_READY_WITH_BOUNDED_CLAIMS', 'DIRECTION5_TERMINATED_WITH_DECISIVE_NEGATIVE_EVIDENCE'}
assert status['final_status'] in allowed
gates = pd.read_csv(root / '19_FINAL_STATUS/ALL_GATES.csv')
assert set(f'A{i}' for i in range(9)).issubset(set(gates.stage))
certificate = json.loads((root / '08_THEORY/CERTIFICATE_STATUS.json').read_text('utf-8'))
assert certificate['global_recursive_safety_claimed'] is False
print(status['final_status'])
print('MINIMAL_REPLAY_OK')
""", encoding="utf-8")


def validate_staging() -> None:
    required = [f"{index:02d}_{name}" for index, name in enumerate((
        "README", "AUDIT", "SCIENCE", "LITERATURE", "MODEL",
        "IDENTIFICATION", "PROBE_DESIGN", "METHOD", "THEORY",
        "SOURCE_ENV", "TESTS", "EXPERIMENT_DESIGN", "RAW_RESULTS",
        "SUMMARY_TABLES", "FIGURES", "FAILURES", "PAPER_DRAFT",
        "REPRODUCIBILITY", "GIT_MANIFEST", "FINAL_STATUS",
    ))]
    missing = [name for name in required if not (STAGING / name).is_dir()]
    if missing:
        raise RuntimeError(f"missing required review-package directories: {missing}")
    manuscript = STAGING / "16_PAPER_DRAFT/MANUSCRIPT.md"
    text = manuscript.read_text("utf-8")
    if "[PREDICTED]" in text or "TO BE FILLED" in text:
        raise RuntimeError("paper still contains predicted-result placeholders")
    if not (STAGING / "11_EXPERIMENT_DESIGN/A7_FINAL_MANIFEST.csv").is_file():
        raise RuntimeError("final seed manifest is missing")
    raw = STAGING / "12_RAW_RESULTS/results_accr/A6"
    development_rows = sum(1 for _ in (raw / "development/A6_DEVELOPMENT_EPISODES.csv").open("r", encoding="utf-8")) - 1
    validation_rows = sum(1 for _ in (raw / "validation/A6_ALL_EPISODES.csv").open("r", encoding="utf-8")) - 1
    normal_rows = sum(1 for _ in (raw / "validation/A6_NORMAL1H_EPISODES.csv").open("r", encoding="utf-8")) - 1
    development_cycles = len(list((raw / "development/cycle_parts").glob("*.parquet")))
    validation_cycles = len(list((raw / "validation/cycle_parts").glob("*.parquet")))
    if development_cycles != development_rows:
        raise RuntimeError("A6 development cycle count does not match episode rows")
    if validation_cycles != validation_rows + normal_rows:
        raise RuntimeError("A6 validation cycle count does not match episode plus normal rows")


def manifest() -> None:
    target = STAGING / "18_GIT_MANIFEST/MANIFEST.csv"
    rows = []
    for path in sorted(STAGING.rglob("*")):
        if not path.is_file() or path == target:
            continue
        rows.append({
            "path": path.relative_to(STAGING).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": digest(path),
        })
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
    subprocess.run([sys.executable, "17_REPRODUCIBILITY/verify_manifest.py"], cwd=FRESH, check=True)
    subprocess.run([sys.executable, "17_REPRODUCIBILITY/reproduce_minimal.py"], cwd=FRESH, check=True)


def main() -> None:
    populate()
    validate_staging()
    manifest()
    build_zip()
    fresh_replay()
    sha = digest(ZIP_PATH)
    ZIP_PATH.with_suffix(ZIP_PATH.suffix + ".sha256").write_text(f"{sha}  {ZIP_PATH.name}\n", encoding="utf-8")
    audit = {
        "zip_absolute_path": str(ZIP_PATH.resolve()),
        "bytes": ZIP_PATH.stat().st_size,
        "megabytes": ZIP_PATH.stat().st_size / 1_000_000.0,
        "sha256": sha,
        "fresh_extract_manifest": "PASS",
        "fresh_extract_minimal_replay": "PASS",
    }
    (ARTIFACTS / "FINAL_PACKAGE_AUDIT.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
