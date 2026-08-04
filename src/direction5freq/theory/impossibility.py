"""Constructive indistinguishable-world same-instant impossibility witness."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class SameInstantImpossibilityWitness:
    public_history_identical: bool
    causal_actions_identical: bool
    command_pu: np.ndarray
    retained_world_power_bound_pu: np.ndarray
    collapsed_world_power_bound_pu: np.ndarray
    retained_world_executable: bool
    collapsed_world_executable: bool
    impossibility_established: bool
    theorem_scope: str


def construct_same_instant_impossibility_witness(
    command_pu: np.ndarray,
    retained_world_power_bound_pu: np.ndarray,
    collapsed_world_power_bound_pu: np.ndarray,
) -> SameInstantImpossibilityWitness:
    """Return the two-world witness for an arbitrary unannounced collapse.

    Both worlds expose the same public history through the decision instant, so
    a deterministic causal policy issues the same action.  The witness is
    established when that action is executable in the retained world but not
    in the collapsed world.  Randomized policies have the same limitation after
    conditioning on their public random seed.
    """

    command = np.abs(np.asarray(command_pu, dtype=float))
    retained = np.asarray(retained_world_power_bound_pu, dtype=float)
    collapsed = np.asarray(collapsed_world_power_bound_pu, dtype=float)
    if command.shape != (2,) or retained.shape != (2,) or collapsed.shape != (2,):
        raise ValueError("impossibility witness uses two-area power vectors")
    retained_executable = bool(np.all(command <= retained + 1e-12))
    collapsed_executable = bool(np.all(command <= collapsed + 1e-12))
    established = retained_executable and not collapsed_executable
    return SameInstantImpossibilityWitness(
        public_history_identical=True,
        causal_actions_identical=True,
        command_pu=command,
        retained_world_power_bound_pu=retained,
        collapsed_world_power_bound_pu=collapsed,
        retained_world_executable=retained_executable,
        collapsed_world_executable=collapsed_executable,
        impossibility_established=established,
        theorem_scope="ARBITRARY_UNANNOUNCED_CAPABILITY_COLLAPSE_BELOW_KNOWN_FLOOR",
    )


__all__ = [
    "SameInstantImpossibilityWitness",
    "construct_same_instant_impossibility_witness",
]
