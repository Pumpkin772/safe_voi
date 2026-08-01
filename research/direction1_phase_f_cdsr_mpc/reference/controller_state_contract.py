"""Reference contract: proposal must not mutate applied-action history."""

from __future__ import annotations
from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class Proposal:
    candidate_action: np.ndarray
    solved: bool
    terminal_ok: bool
    status: str


class TransactionalControllerReference:
    def __init__(self, action_dimension: int = 4) -> None:
        self.previous_applied_action = np.zeros(action_dimension)

    def propose(self, candidate: np.ndarray, solved: bool, terminal_ok: bool) -> Proposal:
        before = self.previous_applied_action.copy()
        proposal = Proposal(np.asarray(candidate, dtype=float).copy(), solved, terminal_ok, "reference")
        assert np.array_equal(before, self.previous_applied_action), "propose mutated physical history"
        return proposal

    def select(self, proposal: Proposal, fallback: np.ndarray) -> np.ndarray:
        if proposal.solved and proposal.terminal_ok:
            return proposal.candidate_action.copy()
        return np.asarray(fallback, dtype=float).copy()

    def commit_applied_action(self, applied: np.ndarray) -> None:
        self.previous_applied_action = np.asarray(applied, dtype=float).copy()
