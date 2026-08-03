"""Registered lexicographic restoration boundary."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RestorationPolicy:
    relax_performance_envelope: bool = True
    relax_settling_target: bool = True
    relax_sg_power: bool = False
    relax_bess_power: bool = False
    relax_ramp: bool = False
    relax_energy: bool = False
    relax_delay_causality: bool = False
    relax_physical_capability: bool = False
    relax_safety_boundary: bool = False

    def physical_constraints_never_relaxed(self) -> bool:
        return not any(
            (
                self.relax_sg_power,
                self.relax_bess_power,
                self.relax_ramp,
                self.relax_energy,
                self.relax_delay_causality,
                self.relax_physical_capability,
                self.relax_safety_boundary,
            )
        )
