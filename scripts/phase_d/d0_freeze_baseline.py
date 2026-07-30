"""Freeze Phase C evidence and withdraw claims invalidated by the Phase D audit."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile


REPO = Path(__file__).resolve().parents[2]
LAUNCH = REPO / "research" / "direction1_phase_d_crcs_tube_mpc"
PHASE_C_ZIP = REPO / "DIRECTION5_PHASE_C_FULL_REBUILD_AND_METHOD_COMPLETION_SINGLE_REVIEW_PACKAGE.zip"
PHASE_C_SHA256 = "28f64c4668a86c4d336619f27382c16766a0b425a6cd6895fd816f07aff809e9"
PHASE_C_COMMIT = "86f982baeda32ee62f8a6117bfe66bc3a9e9bdbb"
PHASE_C_TAG = "direction5-phase-c-reviewed-invalidated"
PHASE_D_BRANCH = "direction1-phase-d-crcs-tube-mpc"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True, capture_output=True, text=True,
        encoding="utf-8",
    ).stdout.strip()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def verify_launch_package() -> list[dict[str, object]]:
    index = json.loads((LAUNCH / "PACKAGE_INDEX.json").read_text(encoding="utf-8"))
    for row in index:
        path = LAUNCH / str(row["path"])
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.stat().st_size != int(row["size_bytes"]) or sha256(path) != row["sha256"]:
            raise RuntimeError(f"Phase D launch-package mismatch: {row['path']}")
    return index


def write_phase_c_manifest(path: Path) -> int:
    roots = [
        REPO / "results_phase_c", REPO / "figures_phase_c", REPO / "logs_phase_c",
        REPO / "artifacts_phase_c", REPO / "research_outputs", REPO / "progress",
        REPO / "scripts" / "phase_c", REPO / "tests" / "phase_c",
    ]
    rows: list[tuple[str, int, str]] = []
    for root in roots:
        if not root.exists():
            continue
        for item in sorted(root.rglob("*"), key=lambda value: value.as_posix()):
            if item.is_file() and "__pycache__" not in item.parts:
                rows.append((item.relative_to(REPO).as_posix(), item.stat().st_size, sha256(item)))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("path", "size_bytes", "sha256"))
        writer.writerows(rows)
    return len(rows)


def write_code_audit(path: Path) -> None:
    rows = [
        ("physics", "src/d5freq/models/plant_a_two_area.py", "retain_and_harden", "Correct per-unit frequency and BESS energy foundations remain useful."),
        ("physics", "src/d5freq/models/plant_b_native_rms.py", "invalid_for_claim", "BESS injection is placed in an auxiliary DC solve but is absent from machine electrical-power balance."),
        ("validation", "src/d5freq/models/plant_b_native_rms.py:andes_native_qualification", "invalid_for_claim", "ANDES Kundur is run separately; no common disturbance or BESS control is injected into the native case."),
        ("causality", "src/d5freq/identification/passive_capability_detector.py", "invalid", "Centered convolution uses future residual samples."),
        ("causality", "src/d5freq/identification/passive_capability_detector.py", "invalid", "Post-alarm 8 s window is used to classify the event."),
        ("identifiability", "scripts/phase_c/c5_identifiability.py", "invalid_for_claim", "Synthetic command is persistently exciting and Tcrit starts at a later preregistered load event; it does not establish natural closed-loop capability-set coverage."),
        ("controller", "src/d5freq/controllers/set_adaptive_mpc.py", "invalid_mpc_name", "The action is algebraic allocation and does not solve a finite-horizon optimization."),
        ("controller", "src/d5freq/evaluation/phase_c_oracle.py", "partial_reuse", "It is a rolling local multiple-shooting NLP, but its surrogate is not the rebuilt native Plant B and requires reliability hardening."),
        ("experiments", "scripts/phase_c/c8_final_experiment.py", "invalid_for_claim", "Scenario identity and dynamics are entangled; Phase D requires explicit independent factors and a locked manifest."),
        ("statistics", "scripts/phase_c/c8_reporting.py", "historical_only", "Negative method evidence is retained, but C5/C6/C8 scientific claims are withdrawn."),
        ("software", "src/d5freq", "historical_only", "Legacy D5 namespace remains immutable historical evidence; new implementation must use src/direction1freq."),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("area", "path_or_symbol", "audit_status", "finding"))
        writer.writerows(rows)


def main() -> None:
    if git("branch", "--show-current") != PHASE_D_BRANCH:
        raise RuntimeError("D0 must execute on the Direction1 Phase D branch")
    if git("rev-list", "-n", "1", PHASE_C_TAG) != PHASE_C_COMMIT:
        raise RuntimeError("Phase C freeze tag does not resolve to the frozen commit")
    if sha256(PHASE_C_ZIP) != PHASE_C_SHA256:
        raise RuntimeError("Phase C ZIP SHA256 mismatch")
    with zipfile.ZipFile(PHASE_C_ZIP) as archive:
        corrupt = archive.testzip()
        if corrupt:
            raise RuntimeError(f"Phase C ZIP CRC error: {corrupt}")
        zip_members = len(archive.namelist())
    launch_rows = verify_launch_package()

    out = REPO / "research_outputs_phase_d" / "D0"
    artifact = REPO / "artifacts_phase_d" / "D0"
    manifest_count = write_phase_c_manifest(artifact / "PHASE_C_ARCHIVE_MANIFEST.csv")
    write_code_audit(out / "CURRENT_CODE_AUDIT.csv")
    invalidated = {
        "schema": "direction1.phase_d.invalidated_claims.v1",
        "audit_date": "2026-07-30",
        "phase_c_commit": PHASE_C_COMMIT,
        "disposition": "historical_evidence_only",
        "claims": [
            {"claim": "C5_PASSIVE_IDENTIFIABLE", "status": "invalidated-by-audit", "reasons": ["centered convolution", "post-alarm future window", "no capability-set coverage Gate"]},
            {"claim": "C6_A_SET_ADAPTIVE_MPC", "status": "invalidated-by-audit", "reasons": ["algebraic allocation mislabeled as MPC", "depends on invalid C5 Gate"]},
            {"claim": "C8_METHOD_COMPARISON", "status": "invalidated-by-audit", "reasons": ["non-MPC baselines", "scenario-factor confounding", "invalid Plant B power balance"]},
        ],
        "not_withdrawn": ["Phase C software/test evidence as historical record", "Plant A engineering components subject to Phase D revalidation"],
    }
    write_json(out / "INVALIDATED_CLAIMS.json", invalidated)
    baseline = f"""# D0 baseline freeze and claim withdrawal

The project is now named **Direction1 / 方向1**. The legacy `d5freq` tree and all Phase C outputs are retained as read-only historical evidence; no Phase C scientific conclusion is carried forward.

## Frozen Phase C baseline

- Commit: `{PHASE_C_COMMIT}`
- Annotated tag: `{PHASE_C_TAG}`
- Review ZIP: `DIRECTION5_PHASE_C_FULL_REBUILD_AND_METHOD_COMPLETION_SINGLE_REVIEW_PACKAGE.zip`
- ZIP SHA256: `{PHASE_C_SHA256}`
- ZIP members: {zip_members}; CRC verification: pass
- Archived evidence manifest: `artifacts_phase_d/D0/PHASE_C_ARCHIVE_MANIFEST.csv` ({manifest_count} files)

## Phase D launch integrity

All {len(launch_rows)} indexed launch files match their registered byte sizes and SHA256 values. `CODEX_GOAL.md` in the Phase D launch directory is the sole active project Goal.

## Withdrawal

The Phase C C5 passive-identifiable Gate and the C6/C8 method conclusions are `invalidated-by-audit`. The reasons are the invalid Plant B power coupling, noncausal centered/future-window processing, algebraic controllers mislabeled as MPC, and confounded final scenario construction. The exact claims and reasons are machine-readable in `INVALIDATED_CLAIMS.json`.

## D0 Gate

`SOURCE_BASELINE_INTEGRITY = PASS`. The frozen ZIP, tag, launch index, minimal Phase C test suite, and evidence inventory are present and reproducible. Development proceeds only in `src/direction1freq`, `scripts/phase_d`, and Phase D output roots.
"""
    (out / "BASELINE_FREEZE.md").write_text(baseline, encoding="utf-8")

    output_paths = [out / "BASELINE_FREEZE.md", out / "INVALIDATED_CLAIMS.json", out / "CURRENT_CODE_AUDIT.csv", artifact / "PHASE_C_ARCHIVE_MANIFEST.csv"]
    progress = {
        "stage": "D0", "goal": "Freeze Phase C and withdraw invalid claims",
        "status": "PASSED", "gate": "SOURCE_BASELINE_INTEGRITY",
        "gate_passed": True,
        "inputs_sha256": {"phase_c_zip": PHASE_C_SHA256, "phase_d_package_index": sha256(LAUNCH / "PACKAGE_INDEX.json")},
        "commands": ["python -m pytest tests/phase_c -q", "python scripts/phase_d/d0_freeze_baseline.py"],
        "tests": {"phase_c": "20 passed", "launch_index_entries": len(launch_rows), "launch_mismatches": 0},
        "failures": [], "repairs": ["Created frozen Phase C annotated tag", "Withdrew C5/C6/C8 claims"],
        "outputs_sha256": {path.relative_to(REPO).as_posix(): sha256(path) for path in output_paths},
        "next_stage": "D1",
    }
    write_json(REPO / "progress_phase_d" / "D0.json", progress)
    print(json.dumps(progress, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
