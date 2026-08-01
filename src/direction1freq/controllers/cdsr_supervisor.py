"""Terminal and fallback supervisor for CDSR-MPC."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from direction1freq.controllers.backup_safe_controller import SGBackupSafeController
from direction1freq.models.plant_a_v2 import PublicObservationV2, TwoAreaPlantAV2
from direction1freq.optimization.terminal_backup import SGTerminalBackupSet


@dataclass(frozen=True, slots=True)
class SupervisorDecision:
    accepted_proposal: bool
    terminal_reject: bool
    backup_used: bool
    reason: str


class CDSRFeasibilitySupervisor:
    def __init__(self, period_s: float, reserve_pu: float = 0.10) -> None:
        self.backup = SGBackupSafeController(period_s, reserve_pu)
        self.terminal_set = SGTerminalBackupSet()

    def reset(self) -> None:
        self.backup.reset()

    def terminal_contains_all(
        self, predicted_states: np.ndarray, c_ace: np.ndarray
    ) -> bool:
        if predicted_states.ndim != 3 or not np.all(np.isfinite(predicted_states)):
            return False
        return all(
            self.terminal_set.contains(state[:, -1], c_ace)
            for state in predicted_states
        )

    def select(
        self,
        candidate_action: np.ndarray,
        *,
        solver_accepted: bool,
        predicted_states: np.ndarray,
        c_ace: np.ndarray,
        hard_constraint_residual: float,
        observation: PublicObservationV2,
        sg_reserve_pu: float,
    ) -> tuple[np.ndarray, SupervisorDecision]:
        terminal_ok = bool(
            solver_accepted and self.terminal_contains_all(predicted_states, c_ace)
        )
        residual_ok = bool(
            np.isfinite(hard_constraint_residual)
            and hard_constraint_residual <= 1e-5
        )
        accepted = bool(solver_accepted and terminal_ok and residual_ok)
        if accepted:
            return np.asarray(candidate_action, dtype=float).copy(), SupervisorDecision(
                True, False, False, "accepted"
            )
        action = self.backup.update(observation)
        action[[0, 2]] = np.clip(action[[0, 2]], -sg_reserve_pu, sg_reserve_pu)
        action[[1, 3]] = 0.0
        terminal_reject = bool(solver_accepted and not terminal_ok)
        reason = (
            "terminal_reject"
            if terminal_reject
            else (
                "constraint_residual_reject"
                if solver_accepted and not residual_ok
                else "solver_or_restoration_failure"
            )
        )
        return action, SupervisorDecision(False, terminal_reject, True, reason)

