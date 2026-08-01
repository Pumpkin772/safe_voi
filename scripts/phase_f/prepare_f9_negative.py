"""Prepare honest F6--F8 not-evaluated records and Phase-F final analysis."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[2]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    progress_dir = REPO / "progress_phase_f"
    final = REPO / "research_outputs_phase_f" / "final"
    literature = REPO / "research_outputs_phase_f" / "02_LITERATURE"
    paper = REPO / "research_outputs_phase_f" / "13_PAPER"
    figures = REPO / "figures_phase_f" / "F5"
    result_f9 = REPO / "results_phase_f" / "F9"
    for directory in (progress_dir, final, literature, paper, figures, result_f9):
        directory.mkdir(parents=True, exist_ok=True)

    for stage, gate, reason in (
        ("F6", "G6_VALIDATION", "G5 failed before development/validation comparison"),
        ("F7", "G7_FINAL_LOCK_AND_G8_EVIDENCE", "final seeds prohibited after G5 stop"),
        ("F8", "PAPER_EVIDENCE", "no final experiment; only negative analysis is prepared"),
    ):
        write_json(
            progress_dir / f"{stage}.json",
            {
                "schema": "direction1.phase_f.progress.v1",
                "stage": stage,
                "gate": gate,
                "gate_status": "NOT_EVALUATED",
                "gate_passed": None,
                "reason": reason,
                "episodes_run": 0,
                "final_seeds_consumed": False,
                "not_evaluated_is_not_failure": True,
                "next_stage": "F9_NEGATIVE_PACKAGE",
            },
        )

    phase_e_literature = REPO / "research_outputs_phase_e" / "02_LITERATURE"
    for name in (
        "LITERATURE_MATRIX.csv",
        "REFERENCES.bib",
        "SEARCH_PROTOCOL.md",
        "SEARCH_LOG.csv",
        "METADATA_VERIFICATION.json",
    ):
        shutil.copy2(phase_e_literature / name, literature / name)
    matrix = pd.read_csv(phase_e_literature / "LITERATURE_MATRIX.csv")
    focus = matrix[
        matrix.title.str.contains(
            "tube|robust|feasibility|predictive load frequency|multi-area",
            case=False,
            regex=True,
        )
        & matrix.formal_peer_reviewed_or_standard.astype(bool)
    ].copy()
    focus.to_csv(literature / "FOCUSED_LITERATURE_MATRIX.csv", index=False)
    (literature / "PHASE_F_SEARCH_LOG.md").write_text(
        """# Phase-F focused literature log

Phase F retains the DOI/publisher-verified Phase-E corpus frozen on 2026-07-31
and filters formal records for robust/tube MPC, feasibility, and multi-area load
frequency control.  No arXiv-only record supports the core claim.  Because G5
stopped the method before validation/final experiments, Phase F makes no new
positive novelty claim that would justify post-hoc literature expansion.
""",
        encoding="utf-8",
    )
    (literature / "INNOVATION_COMPARISON.md").write_text(
        """# CDSR-MPC innovation comparison and negative boundary

Formal neighboring work covers multi-area load-frequency MPC, tube-based LFC,
robust adaptive MPC, and safe learning MPC.  The implemented combination of a
contract capability floor, explicit delay vertices, common robust control,
transactional action commit, performance-only restoration, and SG terminal
backup is narrower than those broad categories.

Phase F does **not** claim a completed new robust-safe method: its calibrated
error set made both tested SG backup reachable sets inadmissible.  The valid
contribution is therefore the failure diagnosis, formulation, and recomputable
certificate boundary.  Failure of two backups is not evidence that all robust
MPC or all SG backups are impossible.
""",
        encoding="utf-8",
    )

    gates = pd.DataFrame(
        [
            ("G0", "F0 forensic", "PASS", "Phase E frozen; bug and replay defect reproduced"),
            ("G1", "corrected science", "PASS", "H1 supported with failure-aware legacy validation"),
            ("G2", "transaction and solver", "PASS", "9180 cycles; zero history mismatch"),
            ("G3", "model set", "PASS", "validation residual coverage >=95%"),
            ("G4", "CDSR implementation", "PASS", "true rolling common-sequence QP"),
            ("G5", "certificate", "FAIL", "no admissible nonempty backup set for either tested design"),
            ("G6", "validation", "NOT_EVALUATED", "stopped by G5; no Gate imputation"),
            ("G7", "final lock", "NOT_EVALUATED", "final seeds not consumed"),
            ("G8", "final evidence", "NOT_EVALUATED", "known/OOD not run"),
            ("G9", "review package", "PENDING", "set by package verifier only"),
        ],
        columns=["gate", "stage", "status", "evidence"],
    )
    gates.to_csv(result_f9 / "ALL_GATES.csv", index=False)
    hypotheses = pd.DataFrame(
        [
            ("H1", "SUPPORTED", "4 mechanisms and 3 SG tensions after success-first correction"),
            ("H2", "TESTED_PASSIVE_ESTIMATORS_NOT_SUPPORTED_UNDER_REGISTERED_EXCITATION", "limited Phase-E evidence"),
            ("H3", "TESTED_ACTIVE_PROBE_NOT_SAFE", "limited to registered tested probe"),
            ("H4", "NOT_EVALUATED", "G5 certificate stop before comparative validation"),
            ("H5", "NOT_SUPPORTED_FULL_REGISTERED_SET", "finite-horizon only; no recursive/switching certificate"),
        ],
        columns=["hypothesis", "status", "evidence"],
    )
    hypotheses.to_csv(result_f9 / "HYPOTHESES_STATUS.csv", index=False)

    f2 = json.loads((progress_dir / "F2.json").read_text())
    f4 = json.loads((progress_dir / "F4.json").read_text())
    f5 = json.loads((progress_dir / "F5.json").read_text())
    failure_ledger = pd.DataFrame(
        [
            ("F0", "legacy_evidence", "Phase-E 1.846% bucket lacks mathematical/numerical taxonomy", "resolved prospectively; old claim withdrawn", True),
            ("F2", "method_prototype", "358 delay backup cycles and max consecutive backup 7 in transactional replay", "retained; not a final CDSR result", False),
            ("F3", "scenario_code", "attempt 1 initialized energy mechanism outside accessible service window", "fixed manifest physical inconsistency; log retained", True),
            ("F3", "model_set", "five-vertex delay interpolation matrix error reaches 0.2914", "explicit state remainder added; no exact-hull claim", False),
            ("F4", "computation", f"development solve-time p99 {f4['tests']['solve_time_p99_s']:.3f}s", "not repaired because G5 stopped before G6", False),
            ("F5", "certificate", "both tested stable SG backup reachable sets violate registered limits", "fatal scientific stop; no threshold relaxation", False),
        ],
        columns=["stage", "class", "failure", "disposition", "resolved"],
    )
    failure_ledger.to_csv(result_f9 / "FAILURE_LEDGER.csv", index=False)

    certificate_attempts = pd.read_csv(
        REPO / "results_phase_f" / "F5" / "F5_BACKUP_SET_ATTEMPTS.csv"
    )
    labels = [f"{row.design}\n{row.period_s:g}s" for row in certificate_attempts.itertuples()]
    metrics = [
        ("frequency_support_max_hz", "frequency_limit_hz", "Frequency [Hz]"),
        ("tie_support_pu", "tie_limit_pu", "Tie-line [pu]"),
        ("sg_mechanical_support_max_pu", "sg_mechanical_limit_pu", "SG mechanical [pu]"),
        ("sg_command_support_max_pu", "minimum_registered_sg_reserve_pu", "SG command [pu]"),
    ]
    figure_source = []
    fig, axes = plt.subplots(2, 2, figsize=(10, 7))
    for axis, (value, limit, title) in zip(axes.ravel(), metrics):
        normalized = certificate_attempts[value] / certificate_attempts[limit]
        axis.bar(labels, normalized, color="#b64b4b")
        axis.axhline(1.0, color="black", linestyle="--", linewidth=1)
        axis.set_title(title)
        axis.set_ylabel("support / registered limit")
        axis.tick_params(axis="x", labelrotation=25)
        for row, ratio in zip(certificate_attempts.itertuples(), normalized):
            figure_source.append(
                {
                    "design": row.design,
                    "period_s": row.period_s,
                    "metric": value,
                    "support_to_limit": ratio,
                }
            )
    fig.suptitle("F5 robust SG-backup certificate failure (all failures retained)")
    fig.tight_layout()
    for suffix in ("svg", "pdf"):
        fig.savefig(figures / f"f5_certificate_failure.{suffix}")
    fig.savefig(figures / "f5_certificate_failure.png", dpi=600)
    plt.close(fig)
    pd.DataFrame(figure_source).to_csv(figures / "f5_certificate_failure_source.csv", index=False)

    claim_evidence = pd.DataFrame(
        [
            ("Phase-E failure was implementation/certificate incomplete", "F0 action mismatch and legacy taxonomy", "SUPPORTED"),
            ("H1 materiality survives correction", "F1 failure-aware table", "SUPPORTED"),
            ("CDSR is a true rolling robust finite-horizon optimizer", "F4 source/tests", "SUPPORTED_IMPLEMENTATION"),
            ("registered-set finite-horizon constraints", "F4 residual checks and F5 formulation certificate", "SUPPORTED_CONDITIONAL_ON_ACCEPTED_SOLUTION"),
            ("recursive feasibility", "F5 backup certificate", "UNSUPPORTED"),
            ("robust switching safety", "F5 backup certificate", "UNSUPPORTED"),
            ("known/OOD superiority", "G6/G8", "NOT_EVALUATED"),
        ],
        columns=["claim", "evidence", "status"],
    )
    claim_evidence.to_csv(final / "CLAIM_EVIDENCE_MATRIX.csv", index=False)

    final_status = {
        "schema": "direction1.phase_f.final_status.v1",
        "project": "DIRECTION1",
        "method": "CDSR-MPC",
        "final_research_status": "NO_NONEMPTY_ROBUST_BACKUP_SET",
        "interpretation_scope": "two tested SG backup designs under the locked registered error set",
        "best_deployable_baseline": "fixed_allocation_pi",
        "gates": dict(zip(gates.gate, gates.status)),
        "hypotheses": dict(zip(hypotheses.hypothesis, hypotheses.status)),
        "known_results": "NOT_EVALUATED",
        "ood_results": "NOT_EVALUATED",
        "plant_a_status": "F0-F5 development/model/certificate evidence completed",
        "plant_b_status": "PHASE_F_NOT_EVALUATED_AFTER_G5_STOP; frozen Phase-E platform retained",
        "solver_statistics": {
            "f2_control_cycles": f2["tests"]["control_cycles"],
            "f2_transactional_replay_backup_fraction": f2["tests"]["transactional_replay_backup_fraction"],
            "f2_maximum_consecutive_backup": f2["tests"]["maximum_consecutive_backup"],
            "f4_development_solver_accepted_fraction": f4["tests"]["solver_accepted_fraction"],
            "f4_development_restoration_fraction": f4["tests"]["restoration_fraction"],
            "f4_development_backup_fraction": f4["tests"]["backup_fraction"],
            "f4_development_solve_time_p99_s": f4["tests"]["solve_time_p99_s"],
            "forced_restoration_and_backup_paths": "both verified separately",
        },
        "certificate_status": f5["certificate_status"],
        "recursive_feasibility_certified": False,
        "robust_switching_safety_certified": False,
        "final_seeds_consumed": False,
        "final_seeds_used_for_tuning": False,
        "failures_deleted": False,
        "not_evaluated_imputed_as_failure": False,
        "most_severe_limitation": "no admissible robust SG terminal backup set for either tested design; comparative CDSR validation and Plant-B known/OOD evidence are therefore absent",
        "next_step_boundary": "STOP_FOR_REVIEW; do not develop another controller without review",
    }
    write_json(final / "FINAL_STATUS.json", final_status)
    (final / "FINAL_RESULTS_INTERPRETATION.md").write_text(
        """# Final Phase-F results interpretation

Phase F corrected the evidence and implemented the requested CDSR-MPC, but it
did not complete a publishable positive method result.  G5 failed before G6:
the locked uncertainty set produces SG-only reachable sets outside terminal,
mechanical-power, and minimum-reserve limits for both tested stable backups.

Thus only a conditional registered-set finite-horizon constraint statement is
supported.  Recursive feasibility, robust switching safety, Plant-A/B
comparative superiority, known performance, and OOD performance are not
supported or not evaluated.  No final seed was consumed and no failure was
deleted.
""",
        encoding="utf-8",
    )
    (final / "NEXT_STEP_BOUNDARY.md").write_text(
        """# Next-step boundary

Stop for external review.  A future phase may reconsider the terminal error
set, backup controller, or performance/contract assumptions only as a new
preregistered design.  It must not reinterpret this package as evidence that
all SG backups or all robust MPC methods are impossible.
""",
        encoding="utf-8",
    )
    (final / "SUPPORTED_AND_UNSUPPORTED_CLAIMS.md").write_text(
        """# Supported and unsupported claims

Supported: corrected H1 materiality; limited H2/H3 negative evidence;
transactional action semantics; complete solver taxonomy; physical capability
source audit; five-vertex common-control CDSR formulation; finite-horizon hard
constraint encoding conditional on an accepted solution; recomputable negative
backup certificate.

Unsupported: recursive feasibility; robust switching safety; exact continuum
delay hull; universal passive/active impossibility; method superiority;
Plant-B Phase-F performance; known/OOD performance.
""",
        encoding="utf-8",
    )

    for name, content in {
        "PAPER_ROUTE.md": "# Paper route\n\nNegative/incomplete method result. Do not submit as a positive CDSR paper without a new preregistered recovery phase.\n",
        "CONTRIBUTIONS.md": "# Contributions\n\nEvidence correction, transactional MPC infrastructure, explicit capability/delay/energy formulation, and a recomputable certificate failure boundary.\n",
        "RESULTS_NARRATIVE.md": "# Results narrative\n\nF0-F4 passed implementation and model gates. F5 failed because stable SG backup reachable sets violate the locked limits. F6-F8 are not evaluated.\n",
        "REVIEWER_RISK_REGISTER.md": "# Reviewer risk register\n\nHighest risks: no Plant-B Phase-F comparison, no known/OOD data, solver p99 above the intended real-time target in F4, conservative component error set, and no recursive certificate.\n",
        "SUPPORTED_AND_UNSUPPORTED_CLAIMS.md": (final / "SUPPORTED_AND_UNSUPPORTED_CLAIMS.md").read_text(encoding="utf-8"),
    }.items():
        (paper / name).write_text(content, encoding="utf-8")

    print(json.dumps(final_status, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

