"""Freeze and independently invalidate the Phase D H2 scientific Gate."""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
GOVERNANCE = ROOT / "research" / "direction1_phase_e_science_recovery_and_capability_control"
FORENSIC = ROOT / "research_outputs_phase_e" / "forensic"
LOGS = ROOT / "logs_phase_e" / "E0"
PROGRESS = ROOT / "progress_phase_e" / "E0.json"
PHASE_D_ZIP = ROOT / "DIRECTION1_PHASE_D_CRCS_TUBE_MPC_SINGLE_REVIEW_PACKAGE.zip"
EXPECTED_ZIP_SHA = "ed471534e162d5748cb8d735d9ca1f017ac6ad2c7ab9c125c6351e6ef658ebc6"
PHASE_D_COMMIT = "11f0379e0e7bd9b1ddf97be8d88b7f918bbb52e9"
REVISED_STATUS = "PHASE_D_GATE_INVALIDATED_BY_CLOSED_LOOP_AND_EVALUATION_DEFECTS"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, encoding="utf-8").strip()


def flatten(payload: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(payload, dict):
        result: dict[str, Any] = {}
        for key, value in payload.items():
            result.update(flatten(value, f"{prefix}.{key}" if prefix else str(key)))
        return result
    return {prefix: payload}


def run_independent_audit() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    FORENSIC.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    output = FORENSIC / "INDEPENDENT_AUDIT_RESULTS.json"
    reference = GOVERNANCE / "reference" / "independent_audit_reproduction.py"
    completed = subprocess.run(
        [sys.executable, str(reference), "--source-root", str(ROOT), "--output", str(output)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    (LOGS / "independent_audit_stdout.log").write_text(completed.stdout, encoding="utf-8")
    (LOGS / "independent_audit_stderr.log").write_text(completed.stderr, encoding="utf-8")
    actual = json.loads(output.read_text(encoding="utf-8"))
    expected = json.loads((GOVERNANCE / "reference" / "independent_audit_expected_output.json").read_text(encoding="utf-8"))
    actual_flat = flatten(actual)
    expected_flat = flatten(expected)
    rows: list[dict[str, Any]] = []
    for key in sorted(set(actual_flat) | set(expected_flat)):
        a = actual_flat.get(key, "<missing>")
        e = expected_flat.get(key, "<missing>")
        if isinstance(a, (int, float)) and not isinstance(a, bool) and isinstance(e, (int, float)) and not isinstance(e, bool):
            absolute_error = abs(float(a) - float(e))
            match = absolute_error <= 1e-10
        else:
            absolute_error = ""
            match = a == e
        rows.append({"field": key, "expected": e, "actual": a, "absolute_error": absolute_error, "match": match})
    with (FORENSIC / "INDEPENDENT_AUDIT_COMPARISON.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["field", "expected", "actual", "absolute_error", "match"])
        writer.writeheader()
        writer.writerows(rows)
    if not all(row["match"] for row in rows):
        raise AssertionError("independent Phase D reproduction differs from registered expected output")
    return actual, rows


def verify_phase_d_package() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if sha256(PHASE_D_ZIP) != EXPECTED_ZIP_SHA:
        raise AssertionError("Phase D review ZIP SHA256 mismatch")
    evidence_rows: list[dict[str, Any]] = []
    with zipfile.ZipFile(PHASE_D_ZIP) as archive:
        if archive.testzip() is not None:
            raise AssertionError("Phase D ZIP CRC failure")
        manifest_bytes = archive.read("13_GIT_AND_MANIFEST/FILE_MANIFEST.csv")
        manifest = list(csv.DictReader(manifest_bytes.decode("utf-8").splitlines()))
        for row in manifest:
            content = archive.read(row["path"])
            actual_hash = sha256_bytes(content)
            match = len(content) == int(row["bytes"]) and actual_hash == row["sha256"]
            evidence_rows.append(
                {
                    "evidence_source": PHASE_D_ZIP.name,
                    "member_path": row["path"],
                    "bytes": len(content),
                    "declared_sha256": row["sha256"],
                    "actual_sha256": actual_hash,
                    "hash_match": match,
                    "retention": "read_only_phase_d_archive",
                }
            )
        git_state = json.loads(archive.read("13_GIT_AND_MANIFEST/GIT_STATE.json"))
        member_count = len(archive.namelist())
    if len(evidence_rows) != 240 or not all(row["hash_match"] for row in evidence_rows):
        raise AssertionError("Phase D file manifest is incomplete or has bad hashes")
    with (FORENSIC / "PHASE_D_EVIDENCE_INDEX.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(evidence_rows[0]))
        writer.writeheader()
        writer.writerows(evidence_rows)
    return evidence_rows, {"member_count": member_count, "managed_records": len(evidence_rows), "git_state": git_state}


def governance_inventory() -> list[dict[str, Any]]:
    rows = []
    for path in sorted(GOVERNANCE.rglob("*")):
        if path.is_file():
            rows.append({"path": path.relative_to(GOVERNANCE).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)})
    with (FORENSIC / "PHASE_E_GOVERNANCE_INVENTORY.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["path", "bytes", "sha256"])
        writer.writeheader()
        writer.writerows(rows)
    if len(rows) != 20:
        raise AssertionError(f"expected 20 Phase E governance files, found {len(rows)}")
    return rows


def main() -> int:
    FORENSIC.mkdir(parents=True, exist_ok=True)
    package_rows, package = verify_phase_d_package()
    audit, comparison = run_independent_audit()
    governance = governance_inventory()

    tag_commit = git("rev-list", "-n", "1", "direction1-phase-d-negative-reviewed")
    branch = git("branch", "--show-current")
    if tag_commit != PHASE_D_COMMIT or branch != "direction1-phase-e-science-recovery":
        raise AssertionError({"tag_commit": tag_commit, "branch": branch})

    source = (ROOT / "scripts" / "phase_d" / "d3_capability_gate.py").read_text(encoding="utf-8")
    source_findings = {
        "update_time_alarm_only": "if estimate.alarm:" in source and "update_time = time_s" in source,
        "control_loss_deficit_area": "deficit_area >= 0.015" in source,
        "all_failed_selects_last_allowed_candidate": "selected = ESTIMATOR_CANDIDATES[min(2, len(repair_records) - 1)]" in source,
    }
    if not all(source_findings.values()):
        raise AssertionError(source_findings)

    invalidation = {
        "schema": "direction1.phase_e.e0.invalidation.v1",
        "phase_d_original_status": "PASSIVE_CAPABILITY_SET_NOT_SUPPORTED",
        "phase_d_revised_status": REVISED_STATUS,
        "general_passive_impossibility_supported": False,
        "phase_d_h2_scientific_gate_valid": False,
        "decisive_defects": [
            "registered nominal PI closed loop self-excites and saturates",
            "delay candidate-set update is omitted by alarm-only update-time scoring",
            "deficit-area time is not a matched physical/counterfactual control-loss time",
            "all-failed candidate logic selects the last rather than a Pareto/minimum-violation candidate",
            "H2 was evaluated before H1 materiality",
        ],
        "phase_d_zip_sha256": EXPECTED_ZIP_SHA,
        "phase_d_commit": PHASE_D_COMMIT,
        "phase_d_tag": "direction1-phase-d-negative-reviewed",
        "source_findings": source_findings,
    }
    write_json(FORENSIC / "PHASE_D_INVALIDATED_CLAIMS.json", invalidation)

    report = f"""# Phase D invalidation and Phase E recovery baseline

## Decision

The Phase D status `PASSIVE_CAPABILITY_SET_NOT_SUPPORTED` is withdrawn as a scientific conclusion and retained only as the outcome of the old protocol. The binding replacement is:

`{REVISED_STATUS}`

## Frozen evidence

- ZIP SHA256: `{EXPECTED_ZIP_SHA}`
- Git commit: `{PHASE_D_COMMIT}`
- Frozen tag: `direction1-phase-d-negative-reviewed`
- ZIP members: {package['member_count']}
- Manifest-managed files: {package['managed_records']}/240, all hashes matched
- Governance files read and hashed: {len(governance)}/20

No Phase D CSV, Parquet, JSON, source or figure was overwritten. The evidence index points into the read-only ZIP.

## Independently reproduced decisive defects

- Tiny `1e-6 pu` initial frequency perturbation under the registered PI reached {audit['tiny_initial_perturbation_registered_pi']['max_abs_frequency_hz']:.6f} Hz and ended at {audit['tiny_initial_perturbation_registered_pi']['terminal_max_abs_frequency_hz']:.6f} Hz after 200 s.
- The registered PI raised background-load maximum frequency deviation from {audit['background_no_sfr']['max_abs_frequency_hz']:.6f} Hz without SFR to {audit['background_registered_pi']['max_abs_frequency_hz']:.6f} Hz.
- Delay truth changed at 45.0 s; the candidate set changed at {audit['delay_update_replay']['first_delay_candidate_set_change_s']:.1f} s and became the correct singleton at {audit['delay_update_replay']['first_correct_singleton_delay_set_s']:.1f} s, while no alarm/update time was recorded.
- The old deficit-area loss time was {audit['delay_update_replay']['phase_d_deficit_area_loss_time_s']:.1f} s; it is not a frequency/ACE/tie/constraint or matched-Oracle loss definition.
- Static source audit confirms the all-failed path selected the final allowed candidate instead of a preregistered Pareto/minimum-violation candidate.

All fields in the independent reproduction matched the registered expected output to `1e-10` absolute tolerance or exact categorical equality.

## Consequence

Phase E must first establish stable 2/4 s nominal control and physical Plant A/B, then qualify a rolling current-capability Oracle and test H1 before any passive/active identification conclusion. Phase D remains immutable historical evidence, not paper support for passive impossibility.
"""
    (FORENSIC / "PHASE_D_INVALIDATION_REPORT.md").write_text(report, encoding="utf-8")

    outputs = sorted(path for path in FORENSIC.rglob("*") if path.is_file())
    progress = {
        "stage": "E0",
        "status": "PASSED",
        "goal": "Freeze Phase D and reproduce the defects that invalidate its H2 scientific Gate",
        "inputs_sha256": {
            "phase_d_zip": EXPECTED_ZIP_SHA,
            "phase_e_goal": sha256(GOVERNANCE / "CODEX_GOAL.md"),
            "independent_audit_reference": sha256(GOVERNANCE / "reference" / "independent_audit_reproduction.py"),
        },
        "commands": [
            "python research/direction1_phase_e_science_recovery_and_capability_control/reference/independent_audit_reproduction.py --source-root .",
            "python -m scripts.phase_e.run_e0_forensic",
            "python -m pytest tests/phase_e/test_e0_forensic.py -q",
        ],
        "tests": {
            "phase_d_zip_sha256_match": True,
            "phase_d_zip_crc": "PASS",
            "phase_d_manifest_records": len(package_rows),
            "phase_d_manifest_bad_hashes": 0,
            "independent_audit_fields": len(comparison),
            "independent_audit_mismatches": 0,
            "source_findings": source_findings,
            "phase_d_tag_commit": tag_commit,
            "phase_e_branch": branch,
        },
        "gate": {"name": "G0_BASELINE", "passed": True, "decision": REVISED_STATUS},
        "failures": [],
        "repairs": ["withdrew invalid Phase D H2 generalization; no Phase D evidence modified"],
        "outputs_sha256": {path.relative_to(ROOT).as_posix(): sha256(path) for path in outputs},
        "next_stage": "E1",
    }
    write_json(PROGRESS, progress)
    print(json.dumps({"gate": "G0_BASELINE", "passed": True, "revised_status": REVISED_STATUS}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
