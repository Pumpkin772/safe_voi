"""Registered two-branch recourse topology for DCSV-CR-MPC."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RecourseBranch:
    name: str
    surplus_delivery_fraction: float
    extra_surplus_delay_s: float
    future_sg_recourse: bool
    future_reserve_recourse: bool


@dataclass(frozen=True, slots=True)
class RecourseTree:
    branches: tuple[RecourseBranch, ...]
    shared_action_steps: int = 1

    @classmethod
    def registered(cls, maximum_contract_delay_s: float) -> "RecourseTree":
        return cls((
            RecourseBranch(
                name="DELIVERED",
                surplus_delivery_fraction=1.0,
                extra_surplus_delay_s=0.0,
                future_sg_recourse=True,
                future_reserve_recourse=True,
            ),
            RecourseBranch(
                name="SURPLUS_LOSS",
                surplus_delivery_fraction=0.0,
                extra_surplus_delay_s=float(maximum_contract_delay_s),
                future_sg_recourse=True,
                future_reserve_recourse=True,
            ),
        ))

    def validate(self) -> None:
        if self.shared_action_steps != 1:
            raise ValueError("the registered tree shares exactly the current action")
        names = {branch.name for branch in self.branches}
        if names != {"DELIVERED", "SURPLUS_LOSS"}:
            raise ValueError("registered recourse tree requires delivered and surplus-loss branches")
        loss = next(branch for branch in self.branches if branch.name == "SURPLUS_LOSS")
        if loss.surplus_delivery_fraction != 0.0:
            raise ValueError("the hard loss branch cannot assume surplus delivery")


__all__ = ["RecourseBranch", "RecourseTree"]
