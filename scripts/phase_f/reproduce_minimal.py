"""Review-root-aware replay of the binding Phase-F negative certificate."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "06_SOURCE" / "src"
sys.path.insert(0, str(SOURCE))

from direction1freq.optimization.robust_backup_set import (  # noqa: E402
    any_admissible_backup,
    lqr_backup_attempt,
    pi_backup_attempt,
)


def main() -> None:
    status = json.loads((ROOT / "17_FINAL_STATUS" / "FINAL_STATUS.json").read_text())
    gates = pd.read_csv(ROOT / "17_FINAL_STATUS" / "ALL_GATES.csv")
    certificate = json.loads(
        (ROOT / "05_THEORY" / "ROBUST_BACKUP_SET_CERTIFICATE.json").read_text()
    )
    uncertainty = np.load(
        ROOT
        / "10_RAW_RESULTS"
        / "results_phase_f"
        / "F3"
        / "RESIDUAL_UNCERTAINTY_SET.npz"
    )
    disturbance = uncertainty["component_radii"][0]
    attempts = [
        function(period, disturbance)
        for period in (2.0, 4.0)
        for function in (pi_backup_attempt, lqr_backup_attempt)
    ]
    recomputed_nonempty = any_admissible_backup(attempts)
    assert status["final_research_status"] == "NO_NONEMPTY_ROBUST_BACKUP_SET"
    assert status["final_seeds_consumed"] is False
    assert status["known_results"] == "NOT_EVALUATED"
    assert status["ood_results"] == "NOT_EVALUATED"
    assert gates.set_index("gate").loc["G5", "status"] == "FAIL"
    assert gates.set_index("gate").loc["G6", "status"] == "NOT_EVALUATED"
    assert gates.set_index("gate").loc["G9", "status"] == "PASS"
    assert recomputed_nonempty is False
    assert recomputed_nonempty == certificate["nonempty_admissible_robust_backup_set"]
    print(
        json.dumps(
            {
                "final_status": status["final_research_status"],
                "certificate_status": certificate["certificate_status"],
                "recomputed_backup_set_nonempty": recomputed_nonempty,
                "final_seeds_consumed": status["final_seeds_consumed"],
                "known": status["known_results"],
                "ood": status["ood_results"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
