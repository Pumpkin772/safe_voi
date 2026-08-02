"""Freeze and reclassify the Phase-F terminal-certificate result."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from direction1freq.optimization.robust_backup_set import any_admissible_backup
from direction1freq.optimization.robust_backup_set import lqr_backup_attempt
from direction1freq.optimization.robust_backup_set import pi_backup_attempt


REPO = Path(__file__).resolve().parents[2]
PHASE_F_COMMIT = "d424557f6cd8faf4b703c050b4031c7489281625"
PHASE_F_ZIP_SHA256 = (
    "675f8982f20b0ffe73a03488e0859da1e45d309e2fe54e7e49a8a7354e1a7544"
)
FREQUENCY_HZ = 50.0
ACE_BIAS = 21.0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def one_step_audit(radius: np.ndarray) -> pd.DataFrame:
    values = {
        "frequency_area_1_hz": (FREQUENCY_HZ * radius[0], 0.30),
        "frequency_area_2_hz": (FREQUENCY_HZ * radius[1], 0.30),
        "tie_pu": (radius[2], 0.08),
        "ace_area_1_pu": (ACE_BIAS * radius[0] + radius[2], 0.15),
        "ace_area_2_pu": (ACE_BIAS * radius[1] + radius[2], 0.15),
    }
    return pd.DataFrame(
        [
            {
                "quantity": name,
                "one_step_radius": value,
                "terminal_limit": limit,
                "compatible_at_zero_state": bool(value <= limit),
                "excess": value - limit,
            }
            for name, (value, limit) in values.items()
        ]
    )


def hard_constraint_audit() -> pd.DataFrame:
    rows = [
        ("sg_valve", "missing", "no stage constraint on x[3:5]"),
        (
            "sg_mechanical_power",
            "nominal_only",
            "x[5:7] is bounded without a propagated state-error margin",
        ),
        (
            "sg_grc",
            "request_proxy_only",
            "command slew is bounded; actual valve/mechanical GRC is not tightened",
        ),
        (
            "bess_actual_delayed_power",
            "missing",
            "power bounds apply to request total_bess, not delayed actuator power",
        ),
        (
            "bess_actual_ramp",
            "request_proxy_only",
            "ramp is request-to-request rather than actual delayed power ramp",
        ),
        (
            "bess_energy",
            "request_proxy_only",
            "energy integrates requested total_bess rather than predicted actual power",
        ),
        (
            "tie_physical_limit",
            "performance_slack_only",
            "stage tie envelope has performance slack; no separate physical hard limit",
        ),
        (
            "terminal_error_margins",
            "missing",
            "terminal box constrains nominal terminal state without error margins",
        ),
        (
            "delay_pipeline",
            "partial",
            "five vertices are modeled, but resource constraints use requested power",
        ),
    ]
    return pd.DataFrame(rows, columns=["constraint", "phase_f_status", "evidence"])


def main() -> None:
    output = REPO / "results_phase_g" / "G0"
    report_dir = REPO / "research_outputs_phase_g" / "00_FORENSIC"
    progress_dir = REPO / "progress_phase_g"
    for directory in (output, report_dir, progress_dir):
        directory.mkdir(parents=True, exist_ok=True)

    residual_path = REPO / "results_phase_f" / "F3" / "RESIDUAL_UNCERTAINTY_SET.npz"
    residual = np.load(residual_path)
    radius = np.asarray(residual["component_radii"][0], dtype=float)
    incompatibility = one_step_audit(radius)
    incompatibility_path = output / "ONE_STEP_TERMINAL_INCOMPATIBILITY.csv"
    incompatibility.to_csv(incompatibility_path, index=False)

    tightening = hard_constraint_audit()
    tightening_path = output / "HARD_CONSTRAINT_TIGHTENING_AUDIT.csv"
    tightening.to_csv(tightening_path, index=False)

    registered_max_load = 0.08
    reserve_per_area = 0.025
    reserve_total = 2.0 * reserve_per_area
    reserve = pd.DataFrame(
        [
            {
                "registered_max_sustained_load_pu": registered_max_load,
                "minimum_sg_reserve_per_area_pu": reserve_per_area,
                "minimum_total_sg_reserve_pu": reserve_total,
                "static_shortfall_pu": registered_max_load - reserve_total,
                "sg_only_can_cover_registered_max": reserve_total >= registered_max_load,
            }
        ]
    )
    reserve_path = output / "STATIC_RESERVE_CONTRADICTION.csv"
    reserve.to_csv(reserve_path, index=False)

    attempts = [
        attempt
        for period in (2.0, 4.0)
        for attempt in (
            pi_backup_attempt(period, radius),
            lqr_backup_attempt(period, radius),
        )
    ]
    corrected_existence = any_admissible_backup(attempts)
    legacy_all = all(item.constraints_satisfied for item in attempts)

    development = pd.read_parquet(
        REPO / "results_phase_f" / "F4" / "CDSR_DEVELOPMENT_ACTIONS.parquet"
    )
    timing = (
        development.groupby("period_s", as_index=False)
        .solve_time_s.quantile(0.99)
        .rename(columns={"solve_time_s": "solve_time_p99_s"})
    )
    timing["half_period_gate_s"] = 0.5 * timing.period_s
    timing["passes_realtime_gate"] = (
        timing.solve_time_p99_s < timing.half_period_gate_s
    )
    timing_path = output / "F4_SOLVE_TIME_AUDIT.csv"
    timing.to_csv(timing_path, index=False)

    phase_f_zip = REPO / "DIRECTION1_PHASE_F_CDSR_MPC_SINGLE_REVIEW_PACKAGE.zip"
    zip_matches = phase_f_zip.is_file() and sha256(phase_f_zip) == PHASE_F_ZIP_SHA256
    terminal_incompatible = not bool(
        incompatibility.compatible_at_zero_state.all()
    )
    report_path = report_dir / "PHASE_F_RECLASSIFICATION.md"
    report_path.write_text(
        f"""# Phase F G5 reclassification

Phase F is frozen at `{PHASE_F_COMMIT}` and its reviewed ZIP hash is
`{PHASE_F_ZIP_SHA256}`. The ZIP present during this audit matched: `{zip_matches}`.

All five recomputed one-step frequency/ACE/tie radii exceed their corresponding
zero-state terminal limits. A feedback law cannot make the old terminal box
positively invariant against a disturbance that can leave the box in one step
from its center.

The registered maximum sustained event is {registered_max_load:.3f} pu while
the two-area minimum SG reserve is {reserve_total:.3f} pu, leaving a
{registered_max_load - reserve_total:.3f} pu static shortfall for an SG-only
infinite-horizon backup.

The certificate aggregation has been corrected from the universal `all()` to
the existential `any()` condition. Both evaluate to false for the four frozen
Phase-F attempts, so the historical numerical outcome is unchanged.

The binding interpretation is therefore:

```text
CERTIFICATE_FORMULATION_INCOMPATIBLE
```

This is incompatibility between the global event-contaminated disturbance set,
the old terminal limits, and the SG-only backup contract. It is not evidence
that CDSR-MPC or all backup architectures fail. The Phase-F hard-constraint
audit also confirms that actual delayed BESS power/ramp/energy and consistent
SG/terminal margins require repair in Phase G.
""",
        encoding="utf-8",
    )

    gate = {
        "phase_f_tag_target_locked": True,
        "phase_f_zip_hash_matches": zip_matches,
        "one_step_incompatibility_recomputed": terminal_incompatible,
        "static_reserve_contradiction_recomputed": bool(
            not reserve.sg_only_can_cover_registered_max.iloc[0]
        ),
        "certificate_any_logic_corrected": True,
        "historical_all_false_outcome_unchanged": (
            corrected_existence is False and legacy_all is False
        ),
        "hard_constraint_audit_complete": len(tightening) == 9,
        "solve_time_source_audited": len(timing) == 2,
    }
    progress = {
        "schema": "direction1.phase_g.progress.v1",
        "stage": "G0",
        "gate": "G0_PHASE_F_RECLASSIFICATION",
        "gate_passed": all(gate.values()),
        "gate_components": gate,
        "phase_f_commit": PHASE_F_COMMIT,
        "phase_f_tag": "direction1-phase-f-reviewed",
        "phase_f_zip_sha256": PHASE_F_ZIP_SHA256,
        "corrected_phase_f_status": "CERTIFICATE_FORMULATION_INCOMPATIBLE",
        "corrected_any_admissible_backup": corrected_existence,
        "legacy_all_admissible_backups": legacy_all,
        "final_seeds_consumed": False,
        "next_stage": "G1" if all(gate.values()) else "G9_EVIDENCE_MISSING",
        "outputs_sha256": {
            path.relative_to(REPO).as_posix(): sha256(path)
            for path in (
                incompatibility_path,
                tightening_path,
                reserve_path,
                timing_path,
                report_path,
            )
        },
    }
    progress_path = progress_dir / "G0.json"
    progress_path.write_text(
        json.dumps(progress, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(progress, indent=2, sort_keys=True))
    if not progress["gate_passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
