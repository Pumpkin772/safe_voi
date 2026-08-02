from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from direction1freq.optimization.robust_backup_set import any_admissible_backup
from scripts.phase_g.run_g0_forensic import one_step_audit


def test_backup_existence_is_existential() -> None:
    failed = SimpleNamespace(constraints_satisfied=False)
    passed = SimpleNamespace(constraints_satisfied=True)
    assert any_admissible_backup([failed, passed])
    assert not any_admissible_backup([failed, failed])


def test_phase_f_one_step_set_exceeds_every_audited_terminal_limit() -> None:
    radius = np.array(
        [
            0.00799565,
            0.00709626,
            0.10434633,
            0.06645182,
            0.05858623,
            0.06308563,
            0.03916844,
            0.01753620,
            0.02027096,
        ]
    )
    audit = one_step_audit(radius)
    assert not audit.compatible_at_zero_state.any()
