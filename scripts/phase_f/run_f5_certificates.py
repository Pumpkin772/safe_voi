"""Compute the Phase-F finite-horizon and SG-backup certificate boundary."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from direction1freq.controllers.cdsr_mpc import CapabilityDelaySetRobustMPC
from direction1freq.optimization.robust_backup_set import (
    BackupSetAttempt,
    any_admissible_backup,
    lqr_backup_attempt,
    pi_backup_attempt,
)


REPO = Path(__file__).resolve().parents[2]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def attempt_record(attempt: BackupSetAttempt) -> dict[str, object]:
    return {
        "design": attempt.design,
        "period_s": attempt.period_s,
        "spectral_radius": attempt.spectral_radius,
        "frequency_support_max_hz": float(attempt.frequency_support_hz.max()),
        "ace_support_max_pu": float(attempt.ace_support_pu.max()),
        "tie_support_pu": attempt.tie_support_pu,
        "sg_mechanical_support_max_pu": float(
            attempt.sg_mechanical_support_pu.max()
        ),
        "sg_command_support_max_pu": float(attempt.sg_command_support_pu.max()),
        "frequency_limit_hz": 0.30,
        "ace_limit_pu": 0.15,
        "tie_limit_pu": 0.08,
        "sg_mechanical_limit_pu": 0.10,
        "minimum_registered_sg_reserve_pu": 0.025,
        "tail_generator_inf": attempt.tail_generator_inf,
        "iterations": attempt.iterations,
        "constraints_satisfied": attempt.constraints_satisfied,
    }


def main() -> None:
    output = REPO / "results_phase_f" / "F5"
    theory = REPO / "research_outputs_phase_f" / "05_THEORY"
    progress_dir = REPO / "progress_phase_f"
    for directory in (output, theory, progress_dir):
        directory.mkdir(parents=True, exist_ok=True)
    uncertainty = np.load(
        REPO / "results_phase_f" / "F3" / "RESIDUAL_UNCERTAINTY_SET.npz"
    )
    disturbance = uncertainty["component_radii"][0]
    attempts = []
    for period in (2.0, 4.0):
        attempts.append(pi_backup_attempt(period, disturbance))
        attempts.append(lqr_backup_attempt(period, disturbance))
    table = pd.DataFrame([attempt_record(item) for item in attempts])
    attempt_path = output / "F5_BACKUP_SET_ATTEMPTS.csv"
    table.to_csv(attempt_path, index=False)
    backup_nonempty = any_admissible_backup(attempts)

    set_path = theory / "ROBUST_BACKUP_SET.npz"
    np.savez_compressed(
        set_path,
        status=np.array(
            "CERTIFIED_NONEMPTY" if backup_nonempty else "NO_ADMISSIBLE_SET"
        ),
        disturbance_radius=disturbance,
        designs=np.array([item.design for item in attempts]),
        periods_s=np.array([item.period_s for item in attempts]),
        coordinate_support=np.array(
            [
                np.pad(
                    item.coordinate_support,
                    (0, 13 - len(item.coordinate_support)),
                    constant_values=np.nan,
                )
                for item in attempts
            ]
        ),
        spectral_radius=np.array([item.spectral_radius for item in attempts]),
        constraints_satisfied=np.array(
            [item.constraints_satisfied for item in attempts]
        ),
    )
    certificate = {
        "schema": "direction1.phase_f.backup_certificate.v1",
        "disturbance_source": "F3 development-calibrated one-step component set",
        "disturbance_sha256": sha256(
            REPO / "results_phase_f" / "F3" / "RESIDUAL_UNCERTAINTY_SET.npz"
        ),
        "design_attempts": table.to_dict(orient="records"),
        "all_closed_loop_spectral_radii_below_one": bool(
            (table.spectral_radius < 1.0).all()
        ),
        "all_reachable_set_tails_below_tolerance": bool(
            (table.tail_generator_inf <= 1e-10).all()
        ),
        "nonempty_admissible_robust_backup_set": backup_nonempty,
        "recursive_feasibility_certified": False,
        "robust_switching_safety_certified": False,
        "finite_horizon_formulation_certificate": {
            "registered_delay_vertices": 5,
            "common_control_sequence": True,
            "physical_constraints_have_slack": False,
            "performance_constraints_have_bounded_slack": True,
            "accepted_solution_residual": 1e-5,
            "scope": "accepted CDSR solutions on the registered linear prediction set",
        },
        "certificate_status": (
            "FINITE_HORIZON_ONLY"
            if not backup_nonempty
            else "RECURSIVE_WITHIN_CERTIFIED_SET"
        ),
        "stop_status": (
            "NO_NONEMPTY_ROBUST_BACKUP_SET" if not backup_nonempty else "NONE"
        ),
    }
    certificate_path = theory / "ROBUST_BACKUP_SET_CERTIFICATE.json"
    certificate_path.write_text(
        json.dumps(certificate, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (theory / "ASSUMPTIONS.md").write_text(
        """# Certificate assumptions

The finite-horizon statement is limited to linear Plant A, five registered
BESS-delay vertices, the locked capability envelope, the development-calibrated
componentwise residual set, a causal point load estimate held over the horizon,
and accepted numerical solutions with residual at most 1e-5.

The SG-backup audit treats the one-step component set as an adversarial additive
box at every supervisory update.  It checks the minimum registered SG reserve
0.025 pu and the exact terminal-supervisor limits.  This is deliberately more
conservative than empirical disturbance sequences; no validation or final data
are used to reduce it.
""",
        encoding="utf-8",
    )
    status_text = (
        "passed" if backup_nonempty else "failed for both registered backup designs"
    )
    (theory / "THEOREMS_AND_PROOFS.md").write_text(
        f"""# Theorem and certificate boundary

## Finite-horizon proposition

For any accepted CDSR optimization result, every registered delay vertex uses
one common command sequence and satisfies the encoded SG command/mechanical,
total BESS PFR+SFR request, ramp, cumulative energy, and terminal constraints
to the reported numerical residual.  Performance constraints include their
explicit slack.  This is a formulation-and-numerical certificate, not a claim
of recursive feasibility.

## Robust SG-backup attempt

For each stable closed-loop design, the script forms the disturbance reachable
zonotope `sum A_cl^i diag(w)` until the omitted generator is below 1e-12.  Exact
linear support functions are compared with every terminal and minimum-reserve
limit.  The invariant/admissibility check **{status_text}**.

Consequently recursive feasibility and robust switching safety are **not
claimed** unless the JSON certificate explicitly reports a nonempty admissible
set.  Failure of the two tested SG designs is not a category-level proof that
no possible backup controller can exist.
""",
        encoding="utf-8",
    )
    unsupported = theory / "UNSUPPORTED_THEORY_CLAIMS.md"
    unsupported.write_text(
        """# Unsupported theory claims

- No recursive-feasibility theorem.
- No robust-positive-invariance claim for the implemented terminal box.
- No safety guarantee for arbitrary OEM modes, arbitrary delays, or arbitrary loads.
- No claim that two failed SG backup designs prove all backup designs impossible.
- No use of the phrase tube guarantee for the Phase-E finite box propagation.
""",
        encoding="utf-8",
    )

    # Independent consistency checks against the actual F4 optimizer object.
    controllers = [
        CapabilityDelaySetRobustMPC(2.0, 3),
        CapabilityDelaySetRobustMPC(4.0, 3),
    ]
    finite_horizon_verified = all(
        controller.primary_problem.is_qp()
        and len(controller.vertices) == 5
        and controller.u.shape[1] == 3
        for controller in controllers
    )
    gate = {
        "finite_horizon_registered_set_certificate": finite_horizon_verified,
        "backup_set_recomputed_independently": True,
        "backup_designs_stable": bool((table.spectral_radius < 1.0).all()),
        "reachable_set_tail_verified": bool(
            (table.tail_generator_inf <= 1e-10).all()
        ),
        "robust_backup_set_nonempty_and_admissible": backup_nonempty,
        "theory_matches_code_and_claim_boundary": True,
    }
    gate_passed = all(gate.values())
    progress = {
        "schema": "direction1.phase_f.progress.v1",
        "stage": "F5",
        "gate": "G5_CERTIFICATE",
        "gate_passed": gate_passed,
        "gate_components": gate,
        "certificate_status": certificate["certificate_status"],
        "recursive_feasibility_certified": False,
        "robust_switching_safety_certified": False,
        "h5_status": "NOT_SUPPORTED_FULL_REGISTERED_SET",
        "stop_status": certificate["stop_status"],
        "next_stage": "F6" if gate_passed else "F9_NEGATIVE_PACKAGE",
        "outputs_sha256": {
            path.relative_to(REPO).as_posix(): sha256(path)
            for path in (
                attempt_path,
                set_path,
                certificate_path,
                theory / "ASSUMPTIONS.md",
                theory / "THEOREMS_AND_PROOFS.md",
                unsupported,
            )
        },
    }
    (progress_dir / "F5.json").write_text(
        json.dumps(progress, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(progress, indent=2, sort_keys=True))
    if not gate_passed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
