"""Freeze and correct the Phase-I evidence without changing the algorithm."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pandas as pd


REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from direction5freq.evaluation.corrected_statistics import (
    corrected_metric_summary,
    paired_failure_rows,
    paired_failure_table,
    solver_denominator_audit,
)


PHASE_I = REPO / "results_phase_i/I6"
RAW = REPO / "results_final/R0"
FORENSIC = REPO / "research_outputs_final/00_FORENSIC"
TABLES = REPO / "research_outputs_final/11_SUMMARY_TABLES/R0"
FAILURES = REPO / "research_outputs_final/13_FAILURES/R0"
PROGRESS = REPO / "progress_final"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def main() -> None:
    for directory in (RAW, FORENSIC, TABLES, FAILURES, PROGRESS):
        directory.mkdir(parents=True, exist_ok=True)
    episodes_path = PHASE_I / "VALIDATION_EPISODES.parquet"
    normal_path = PHASE_I / "NORMAL1H_EPISODES.parquet"
    cycles_path = PHASE_I / "VALIDATION_CYCLES.parquet"
    episodes = pd.read_parquet(episodes_path)
    normal = pd.read_parquet(normal_path)
    cycles = pd.read_parquet(cycles_path)

    failure_rows = paired_failure_rows(episodes, "dcsv_mpc", "fixed_allocation_pi")
    failure_table = paired_failure_table(failure_rows)
    summaries, bootstrap, pair_rows = corrected_metric_summary(
        failure_rows,
        "dcsv_mpc",
        "fixed_allocation_pi",
        resamples=5000,
    )
    denominator = solver_denominator_audit(
        episodes, normal, cycles, proposed="dcsv_mpc"
    )
    pair_rows.to_parquet(RAW / "CORRECTED_PAIRED_STATISTICS.parquet", index=False)
    failure_rows.to_parquet(RAW / "PAIRED_SCENARIO_STATUS.parquet", index=False)
    failure_table.to_csv(TABLES / "PAIRED_FAILURE_TABLE.csv", index=False)
    summaries.to_csv(TABLES / "AGGREGATE_MEAN_IMPROVEMENTS.csv", index=False)
    bootstrap.to_csv(TABLES / "HIERARCHICAL_BOOTSTRAP.csv", index=False)
    denominator.to_csv(TABLES / "SOLVER_DENOMINATOR_AUDIT.csv", index=False)

    anomaly = normal[normal.frequency_peak_hz > 1.0].copy()
    normal_table = normal[[
        "scenario_id", "method", "frequency_peak_hz", "ace_iae_pu_s",
        "tie_rms_pu", "terminal_recovery", "hard_violation",
        "fallback_calls", "p99_solve_time_s", "real_normal1h_provenance",
    ]]
    normal_table.to_csv(TABLES / "NORMAL1H_PHASE_I_AUDIT.csv", index=False)
    omitted = int(denominator.loc[
        denominator.quantity.eq("omitted_backup_actions_in_phase_i_denominator"), "count"
    ].iloc[0])
    attempts = int(denominator.attempted_decision_denominator.iloc[0])
    raw_attempts = int(denominator.raw_solver_invocation_denominator.iloc[0])
    unresolved_fraction = float(denominator.unresolved_fraction_of_attempted_decisions.iloc[0])
    fallback_fraction = float(denominator.fallback_fraction_of_attempted_decisions.iloc[0])

    primary = summaries[summaries.primary_metric].copy()
    primary_lines = "\n".join(
        f"| {row.metric} | {row.scenario_balanced_proposed_mean:.6g} | "
        f"{row.scenario_balanced_baseline_mean:.6g} | "
        f"{100 * row.aggregate_mean_relative_improvement:.2f}% |"
        for row in primary.itertuples()
    )
    write_text(FORENSIC / "PHASE_I_CORRECTION.md", f"""
# Phase I correction and retraction

## Corrected verdict

The Phase-I terminal claim is withdrawn as decisive scientific evidence.  The
frozen run remains evidence about the tested prototype, but its method-level
termination was driven by an unstable primary statistic, omission of the
contract-only rolling MPC comparator, a heuristic deliverability estimator, and
an incomplete solver denominator.

```text
PHASE_I_TERMINATION: WITHDRAWN
CORRECTED_INTERPRETATION: PROTOTYPE_FAILED_REGISTERED_GATES_UNDER_DEFECTIVE_ATTRIBUTION
FINAL_DIRECTION5_DECISION: PENDING_R1_TO_R5
```

No Phase-I episode, warning, threshold, or raw result was changed.  This R0
analysis reads only the frozen Phase-I evidence.

## Scenario-balanced both-success aggregates

| metric | Phase-I DCSV | fixed-allocation PI | aggregate improvement |
|---|---:|---:|---:|
{primary_lines}

The diagnostic mean of episode-wise relative ratios is retained in the CSV for
forensic reproduction only and is explicitly not a primary metric.

## Corrected solver denominator

- attempted optimization decisions: {attempts};
- inferred raw solver invocations: {raw_attempts};
- fallback outcomes omitted by the old success-only denominator: {omitted};
- unresolved mathematical-infeasibility fraction of attempted decisions:
  {unresolved_fraction:.6%};
- fallback fraction of attempted decisions: {fallback_fraction:.6%}.

Thus correcting the denominator does not rescue the Phase-I prototype's solver
Gate; it only makes the failure rate auditable.

## Missing comparator and attribution

`RollingContractMPC` existed in Phase I but was not included in I6.  Because the
online envelope altered only an objective weight, I6 could not attribute any
observed difference to a contract-safe online-capability contribution.  R0 does
not impute the missing comparator result.
""")

    anomaly_lines = "\n".join(
        f"- `{row.scenario_id}` / `{row.method}`: peak "
        f"{row.frequency_peak_hz:.6f} Hz, terminal recovery={row.terminal_recovery}."
        for row in anomaly.itertuples()
    ) or "- No >1 Hz anomaly found."
    write_text(FAILURES / "NORMAL1H_STABILITY_DIAGNOSIS.md", f"""
# Phase-I normal1h stability diagnosis

## Observed anomaly

{anomaly_lines}

The anomaly is shared by DCSV and fixed-allocation PI on `I6-N-02`, despite the
registered synthetic profile having no exceptional amplitude.  The PI
implementation integrates ACE before clipping and has no conditional
integration or back-calculation, so integral windup is a confirmed code defect.
The DCSV trace also repeatedly reaches the contract command limits.  The saved
normal episode parts contain command, actual BESS power, SoC, domain and solver
status, but omit frequency, ACE, SG valve/mechanical power and slow-reserve
states.  Consequently the exact divergence onset cannot be reconstructed from
the frozen trace and must not be over-attributed to a single component.

## Gate defect

Phase I checked only that six rows per method existed and that a provenance
string was non-null.  It did not enforce a normal-frequency quality threshold.
Moreover the profile is a seeded AR(1)+sinusoid synthetic trace, not a public
measured load record; the field name `real_normal1h_provenance` described real
simulation duration, not real-world data provenance.

## Required R2/R5 repair

1. anti-windup PI and explicit saturation diagnostics;
2. full frequency/ACE/tie/SG/BESS/slow-reserve normal trajectories;
3. a registered frequency-quality Gate;
4. public measured data when obtainable, otherwise an explicit `synthetic`
   label;
5. no normal-profile claim from a non-null string alone.
""")

    input_hashes = {
        str(path.relative_to(REPO)).replace("\\", "/"): sha256(path)
        for path in (episodes_path, normal_path, cycles_path)
    }
    progress = {
        "schema": "direction5.final_repair.progress.v1",
        "stage": "R0",
        "status": "PASS",
        "gate": "PHASE_I_EVIDENCE_AUDITABLE_AND_CORRECTED",
        "phase_i_terminal_claim_withdrawn": True,
        "algorithm_changed": False,
        "input_hashes": input_hashes,
        "episode_method_rows": int(len(episodes)),
        "normal1h_method_rows": int(len(normal)),
        "attempted_optimization_decisions": attempts,
        "inferred_raw_solver_invocations": raw_attempts,
        "omitted_backup_actions_in_old_denominator": omitted,
        "normal1h_anomalous_method_rows": int(len(anomaly)),
        "failures_preserved": True,
        "next_stage": "R1",
    }
    (PROGRESS / "R0.json").write_text(json.dumps(progress, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(progress, indent=2))


if __name__ == "__main__":
    main()

