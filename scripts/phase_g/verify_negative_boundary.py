"""Recompute the Phase-G local incompatibility certificate without CVXPY."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve()
ROOT = HERE.parents[1] if (HERE.parents[1] / "05_THEORY").is_dir() else HERE.parents[2]


def main() -> None:
    data = np.load(
        ROOT / "05_THEORY" / "LOCAL_TERMINAL_INCOMPATIBILITY_CERTIFICATE.npz"
    )
    certificate = json.loads(
        (ROOT / "05_THEORY" / "LOCAL_TERMINAL_INCOMPATIBILITY_CERTIFICATE.json").read_text()
    )
    maximum_load_effect = np.max(data["load_state_effect_by_period_vertex"], axis=0)
    effective = data["model_observer_radius"] + maximum_load_effect
    assert np.allclose(maximum_load_effect, data["maximum_load_state_effect"])
    assert np.allclose(effective, data["effective_state_radius"])
    frequency = 50.0 * effective[:2]
    tie = effective[2]
    ace = np.array([21.0 * effective[0] + tie, 21.0 * effective[1] + tie])
    incompatible = np.r_[frequency > 0.30, tie > 0.08, ace > 0.15]
    assert incompatible.all()
    assert certificate["status"] == "LOCAL_TERMINAL_MODEL_NOT_CERTIFIABLE"
    print(
        json.dumps(
            {
                "status": certificate["status"],
                "frequency_hz": frequency.tolist(),
                "tie_pu": float(tie),
                "ace_pu": ace.tolist(),
                "all_incompatible": bool(incompatible.all()),
                "cvxpy_used": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
