"""Audit whether the one-step state-error box already exceeds terminal limits."""
from __future__ import annotations
import numpy as np

F0_HZ = 50.0
BETA = 21.0
TERMINAL = {"frequency_hz": 0.30, "ace_pu": 0.15, "tie_pu": 0.08}


def audit(radius: np.ndarray) -> dict[str, float | bool]:
    r = np.asarray(radius, dtype=float)
    freq_1 = F0_HZ * r[0]
    freq_2 = F0_HZ * r[1]
    tie = r[2]
    ace_1 = BETA * r[0] + r[2]
    ace_2 = BETA * r[1] + r[2]
    return {
        "frequency_1_hz": freq_1,
        "frequency_2_hz": freq_2,
        "tie_pu": tie,
        "ace_1_pu": ace_1,
        "ace_2_pu": ace_2,
        "zero_state_one_step_compatible": bool(
            freq_1 <= TERMINAL["frequency_hz"]
            and freq_2 <= TERMINAL["frequency_hz"]
            and tie <= TERMINAL["tie_pu"]
            and ace_1 <= TERMINAL["ace_pu"]
            and ace_2 <= TERMINAL["ace_pu"]
        ),
    }


if __name__ == "__main__":
    radius = np.array([
        0.00799565, 0.00709626, 0.10434633, 0.06645182,
        0.05858623, 0.06308563, 0.03916844, 0.01753620, 0.02027096,
    ])
    print(audit(radius))
