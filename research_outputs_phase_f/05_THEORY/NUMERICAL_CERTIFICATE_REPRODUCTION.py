"""Independently recompute the Phase-F SG-backup certificate outcome."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from direction1freq.optimization.robust_backup_set import (
    any_admissible_backup,
    lqr_backup_attempt,
    pi_backup_attempt,
)


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    uncertainty = np.load(
        root / "results_phase_f" / "F3" / "RESIDUAL_UNCERTAINTY_SET.npz"
    )
    disturbance = uncertainty["component_radii"][0]
    attempts = [
        function(period, disturbance)
        for period in (2.0, 4.0)
        for function in (pi_backup_attempt, lqr_backup_attempt)
    ]
    recomputed_nonempty = any_admissible_backup(attempts)
    certificate = json.loads(
        (root / "research_outputs_phase_f" / "05_THEORY" / "ROBUST_BACKUP_SET_CERTIFICATE.json").read_text()
    )
    assert recomputed_nonempty == certificate["nonempty_admissible_robust_backup_set"]
    assert all(item.spectral_radius < 1.0 for item in attempts)
    assert all(item.tail_generator_inf <= 1e-10 for item in attempts)
    print(
        json.dumps(
            {
                "recomputed_nonempty": recomputed_nonempty,
                "certificate_status": certificate["certificate_status"],
                "attempts": [
                    {
                        "design": item.design,
                        "period_s": item.period_s,
                        "constraints_satisfied": item.constraints_satisfied,
                    }
                    for item in attempts
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
