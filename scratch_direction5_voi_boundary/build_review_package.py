"""Build the single Direction5 VOI-boundary review package."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts_direction5_voi_boundary"
STAGE = Path(tempfile.gettempdir()) / "d5vb_review_stage"
ZIP = ROOT / "DIRECTION5_VOI_BOUNDARY_SINGLE_REVIEW_PACKAGE.zip"


def copy(source: Path, relative: str) -> None:
    target = STAGE / relative
    if source.is_dir():
        shutil.copytree(
            source, target,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "*.egg-info"),
        )
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def write(relative: str, text: str) -> None:
    target = STAGE / relative; target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    status_path = ROOT / "results_boundary/final/FINAL_STATUS.json"
    status = json.loads(status_path.read_text("utf-8"))
    if status["final_status"] != "PAPER_READY_NO_PROBE_BOUNDARY":
        raise RuntimeError("refusing to package an unfinished or inconsistent result")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    if STAGE.exists():
        if STAGE.resolve().parent != Path(tempfile.gettempdir()).resolve():
            raise RuntimeError("unsafe stage path")
        shutil.rmtree(STAGE)
    STAGE.mkdir()

    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    git_status = subprocess.check_output(
        ["git", "status", "--short"], cwd=ROOT, text=True, encoding="utf-8"
    )
    readme = f"""# DIRECTION5 VOI boundary single review package

Final status: **{status['final_status']}**

This package contains the complete source snapshot, registered formulation,
all 1,920 retained boundary points, independent nonlinear Plant-A and native
ANDES Plant-B results, six genuine 3,600 s normal profiles, failures, final
paper draft, and minimal replay utilities.

Scientific conclusion: the registered positive safe-probe value region is
empty. The selected probe is NONE and the selective controller is exactly the
same contract MPC in the zero region. The theorem and evidence are conditional
on the declared finite capability/probe/controller domain; they do not prove a
universal impossibility result.

Scientific commit: `{commit}`

From a fresh extraction root run:

```text
python 19_REPRODUCIBILITY/verify_manifest.py
python 19_REPRODUCIBILITY/reproduce_minimal.py
python 19_REPRODUCIBILITY/reproduce_all.py
```
"""
    write("00_README/README.md", readme)
    copy(ROOT / "research_outputs_boundary/00_FROZEN_HEURISTIC_RESULT.md", "01_AUDIT/00_FROZEN_HEURISTIC_RESULT.md")
    copy(ROOT / "research_outputs_boundary/B1_MILESTONE.md", "01_AUDIT/B1_MILESTONE.md")
    copy(ROOT / "research_outputs_boundary/B2_VALIDATION_RESULT.md", "01_AUDIT/B2_VALIDATION_RESULT.md")
    copy(ROOT / "research_outputs_boundary/B3_POST_LOCK_CODE_CORRECTION.md", "01_AUDIT/B3_POST_LOCK_CODE_CORRECTION.md")
    copy(ROOT / "results_boundary/final/FINAL_STATUS.json", "02_SCIENCE/FINAL_STATUS.json")
    copy(ROOT / "research_outputs_boundary/01_LITERATURE_POSITION.md", "03_LITERATURE/LITERATURE_POSITION.md")
    copy(ROOT / "research_outputs_boundary/B0_FORMULATION_AND_THEOREM.md", "04_MATHEMATICS/FORMULATION_AND_NO_PROBE_THEOREM.md")
    copy(ROOT / "research/direction5_voi_boundary_final/02_COMPLETE_MATHEMATICAL_DERIVATION.md", "04_MATHEMATICS/REGISTERED_DERIVATION.md")
    copy(ROOT / "scratch_direction5_voi_boundary/voi_boundary_engine.py", "05_BOUNDARY_ENGINE/voi_boundary_engine.py")
    copy(ROOT / "scratch_direction5_voi_boundary/selective_boundary_policy.py", "06_METHOD/selective_boundary_policy.py")
    copy(ROOT / "scratch_direction5_voi_boundary/rolling_boundary_controller.py", "06_METHOD/rolling_boundary_controller.py")
    copy(ROOT / "results_boundary/final/THEORY_SCOPE.md", "07_THEORY/THEORY_SCOPE.md")

    copy(ROOT / "scratch_direction5_voi_boundary", "08_SOURCE_ENV/scratch_direction5_voi_boundary")
    copy(ROOT / "src/direction5freq", "08_SOURCE_ENV/src/direction5freq")
    copy(ROOT / "research/direction5_voi_boundary_final", "08_SOURCE_ENV/research/direction5_voi_boundary_final")
    copy(ROOT / "environment.yml", "08_SOURCE_ENV/environment.yml")
    copy(ROOT / "pyproject.toml", "08_SOURCE_ENV/pyproject.toml")
    copy(ROOT / "scratch_direction5_voi_boundary/test_boundary_engine.py", "09_TESTS/test_boundary_engine.py")
    copy(ROOT / "results_boundary/final/TEST_RESULTS.txt", "09_TESTS/TEST_RESULTS.txt")
    copy(ROOT / "scratch_direction5_voi_boundary/boundary_study_lock.yaml", "10_DESIGN_SPACE/boundary_study_lock.yaml")
    copy(ROOT / "research_outputs_boundary/B1_ADAPTIVE_MANIFEST.csv", "10_DESIGN_SPACE/B1_ADAPTIVE_MANIFEST.csv")

    write("11_DEVELOPMENT/README.md", "Development evidence is preserved without deletion in 14_RAW_RESULTS/B1_* and summarized in 15_SUMMARY_TABLES.\n")
    write("12_VALIDATION/README.md", "Independent validation evidence is in 14_RAW_RESULTS/B2_* and 15_SUMMARY_TABLES.\n")
    write("13_FINAL_OR_CONFIRMATION/README.md", "One-shot final boundary and normal1h evidence is in 14_RAW_RESULTS/B3_* and 15_SUMMARY_TABLES.\n")
    copy(ROOT / "research_outputs_boundary", "14_RAW_RESULTS/research_outputs_boundary")
    copy(ROOT / "results_boundary/final", "15_SUMMARY_TABLES/results_boundary_final")
    copy(ROOT / "research_outputs_boundary/B1_FINAL_MAP/BOUNDARY_MAP.png", "16_FIGURES/BOUNDARY_MAP.png")
    copy(ROOT / "results_boundary/final/FAILURE_LEDGER.csv", "17_FAILURES/FAILURE_LEDGER.csv")
    copy(ROOT / "results_boundary/final/MANUSCRIPT.md", "18_PAPER_DRAFT/MANUSCRIPT.md")

    verify = '''from __future__ import annotations
import csv, hashlib
from pathlib import Path
root = Path(__file__).resolve().parents[1]
manifest = root / "20_GIT_MANIFEST/MANIFEST.csv"
failures = []
with manifest.open(newline="", encoding="utf-8") as stream:
    for row in csv.DictReader(stream):
        path = root / row["path"]
        if not path.is_file():
            failures.append(f"missing:{row['path']}")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if path.stat().st_size != int(row["bytes"]) or digest != row["sha256"]:
            failures.append(f"mismatch:{row['path']}")
if failures:
    raise SystemExit("manifest verification failed: " + ", ".join(failures[:20]))
print(f"manifest verified: {sum(1 for _ in csv.DictReader(manifest.open(encoding='utf-8')))} files")
'''
    reproduce = '''from __future__ import annotations
import csv, json
from pathlib import Path
root = Path(__file__).resolve().parents[1]
status = json.loads((root / "21_FINAL_STATUS/FINAL_STATUS.json").read_text(encoding="utf-8"))
assert status["final_status"] == "PAPER_READY_NO_PROBE_BOUNDARY"
assert status["positive_value_region_points"] == 0
assert status["zero_value_region_points"] == 1920
assert status["selected_probe"] == "NONE"
assert status["plant_b"]["all_native_andes_converged"] is True
assert status["normal1h"]["profiles"] >= 6
assert status["solver"]["solver_failure_calls"] == 0
print(json.dumps({
    "final_status": status["final_status"],
    "zero_value_region_points": status["zero_value_region_points"],
    "selected_probe": status["selected_probe"],
    "plant_a_scenarios": status["plant_a"]["scenarios"],
    "native_plant_b_scenarios": status["plant_b"]["scenarios"],
    "normal1h_profiles": status["normal1h"]["profiles"],
}, indent=2, sort_keys=True))
'''
    write("19_REPRODUCIBILITY/verify_manifest.py", verify)
    write("19_REPRODUCIBILITY/reproduce_minimal.py", reproduce)
    recompute = '''from __future__ import annotations
import json, sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
source = root / "08_SOURCE_ENV/scratch_direction5_voi_boundary"
sys.path.insert(0, str(source))
sys.path.insert(0, str(root / "08_SOURCE_ENV/src"))
from voi_boundary_engine import BoundaryPoint, evaluate_boundary_point
point = BoundaryPoint(
    point_id="minimal_replay", period_s=4.0, sg_tension="medium",
    load_magnitude_pu=0.045, power_spread_pu=0.020,
    ramp_spread_pu_per_s=0.020, delay_spread_s=0.8,
    noise_std_pu=0.001, soc=0.5, tie_loading_pu=0.02,
    objective="balanced",
)
result = evaluate_boundary_point(
    point, physical_horizon_s=24.0, exact_probe_limit=0,
)
print(json.dumps(result.summary(), indent=2, sort_keys=True))
'''
    write("19_REPRODUCIBILITY/recompute_small_boundary.py", recompute)
    recompute_validation = '''from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
root = Path(__file__).resolve().parents[1]
raw = root / "14_RAW_RESULTS/research_outputs_boundary"
plant_a = pd.concat([
    pd.read_csv(raw / "B2_VALIDATION_1_PLANT_A/EPISODES.csv"),
    pd.read_csv(raw / "B2_VALIDATION_2_PLANT_A/EPISODES.csv"),
], ignore_index=True)
plant_b = pd.read_csv(raw / "B2_NATIVE_PLANT_B/EPISODES.csv")
selected_a = plant_a.loc[plant_a.method.eq("selective_voi_accr_mpc")]
selected_b = plant_b.loc[plant_b.method.eq("selective_voi_accr_mpc")]
combined = pd.concat([selected_a, selected_b], ignore_index=True)
summary = {
    "plant_a_scenarios": int(len(selected_a)),
    "plant_a_physical_successes": int(selected_a.physical_success.astype(bool).sum()),
    "native_plant_b_scenarios": int(len(selected_b)),
    "native_plant_b_physical_successes": int(selected_b.physical_success.astype(bool).sum()),
    "optimization_calls": int(combined.optimization_attempts.sum()),
    "solver_failures": int(combined.solver_failure_calls.sum()),
    "fallbacks": int(combined.fallback_calls.sum()),
    "probe_triggers": int(combined.probe_triggers.sum()),
    "maximum_contract_action_difference_pu": float(
        combined.contract_action_max_abs_difference_pu.max()
    ),
}
assert summary == {
    "plant_a_scenarios": 40,
    "plant_a_physical_successes": 40,
    "native_plant_b_scenarios": 12,
    "native_plant_b_physical_successes": 12,
    "optimization_calls": 5902,
    "solver_failures": 0,
    "fallbacks": 0,
    "probe_triggers": 0,
    "maximum_contract_action_difference_pu": 0.0,
}
print(json.dumps(summary, indent=2, sort_keys=True))
'''
    write("19_REPRODUCIBILITY/recompute_validation_summary.py", recompute_validation)
    reproduce_all = '''from __future__ import annotations
import os
from pathlib import Path
import subprocess
import sys
root = Path(__file__).resolve().parents[1]
for script in (
    "verify_manifest.py",
    "reproduce_minimal.py",
    "recompute_small_boundary.py",
    "recompute_validation_summary.py",
):
    subprocess.run(
        [sys.executable, str(root / "19_REPRODUCIBILITY" / script)],
        cwd=root, check=True,
    )
environment = dict(os.environ)
source = root / "08_SOURCE_ENV"
environment["PYTHONPATH"] = os.pathsep.join((
    str(source / "scratch_direction5_voi_boundary"),
    str(source / "src"),
))
subprocess.run(
    [sys.executable, "-m", "pytest", "09_TESTS/test_boundary_engine.py", "-q"],
    cwd=root, env=environment, check=True,
)
print("REPRODUCE_ALL_OK")
'''
    write("19_REPRODUCIBILITY/reproduce_all.py", reproduce_all)
    write("20_GIT_MANIFEST/GIT_COMMIT.txt", commit + "\n")
    write("20_GIT_MANIFEST/GIT_STATUS.txt", git_status)
    copy(ROOT / "results_boundary/final/FINAL_STATUS.json", "21_FINAL_STATUS/FINAL_STATUS.json")

    manifest_path = STAGE / "20_GIT_MANIFEST/MANIFEST.csv"
    files = sorted(
        path for path in STAGE.rglob("*")
        if path.is_file() and path != manifest_path
    )
    with manifest_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=("path", "bytes", "sha256"))
        writer.writeheader()
        for path in files:
            writer.writerow({
                "path": path.relative_to(STAGE).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            })

    if ZIP.exists():
        ZIP.unlink()
    with zipfile.ZipFile(ZIP, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(item for item in STAGE.rglob("*") if item.is_file()):
            archive.write(path, path.relative_to(STAGE).as_posix())
    zip_hash = sha256(ZIP)
    ZIP.with_suffix(ZIP.suffix + ".sha256").write_text(
        f"{zip_hash}  {ZIP.name}\n", encoding="ascii"
    )
    result = {
        "zip": str(ZIP.resolve()), "bytes": ZIP.stat().st_size,
        "mb": ZIP.stat().st_size / 1_000_000.0, "sha256": zip_hash,
        "commit": commit,
    }
    (ARTIFACTS / "PACKAGE_RESULT.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
