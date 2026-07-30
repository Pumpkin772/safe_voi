"""Controller-visible conventional baseline for the Phase-B2 two-area plant."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from d5freq.models.two_area_plant_b import PlantBObservation, SGCapability, UpperCommand


@dataclass(frozen=True, slots=True)
class ConventionalPIConfig:
    """Fixed supplementary ACE PI settings selected on development cases only."""

    proportional_gain: float = 0.60
    integral_gain_per_s: float = 0.040
    anti_windup_gain_per_s: float = 0.10

    def __post_init__(self) -> None:
        for name in (
            "proportional_gain",
            "integral_gain_per_s",
            "anti_windup_gain_per_s",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
            object.__setattr__(self, name, value)


class ConventionalACEPIController:
    """O0: SG-only PI on measured ACE with reserve-aware anti-windup."""

    evaluation_label = "O0_conventional_ACE_PI"
    uses_true_regime = False
    uses_true_internal_state = False
    uses_future_load = False
    uses_future_regime = False

    def __init__(
        self,
        capability: SGCapability,
        *,
        control_period_s: float,
        config: ConventionalPIConfig | None = None,
    ) -> None:
        self.capability = capability
        self.control_period_s = float(control_period_s)
        if not math.isfinite(self.control_period_s) or self.control_period_s <= 0.0:
            raise ValueError("control_period_s must be finite and positive")
        self.config = ConventionalPIConfig() if config is None else config
        self._integral = np.zeros(2, dtype=np.float64)

    def reset(self) -> None:
        self._integral.fill(0.0)

    @property
    def integral_state(self) -> tuple[float, float]:
        return float(self._integral[0]), float(self._integral[1])

    def command(self, observation: PlantBObservation) -> UpperCommand:
        ace = np.asarray(observation.ace_pu, dtype=np.float64)
        unconstrained = -(
            self.config.proportional_gain * ace
            + self.config.integral_gain_per_s * self._integral
        )
        lower = -np.asarray(self.capability.reserve_down_pu, dtype=np.float64)
        upper = np.asarray(self.capability.reserve_up_pu, dtype=np.float64)
        constrained = np.clip(unconstrained, lower, upper)
        tracking_error = constrained - unconstrained
        self._integral += self.control_period_s * (
            ace
            - self.config.anti_windup_gain_per_s
            * tracking_error
            / max(self.config.integral_gain_per_s, 1.0e-12)
        )
        return UpperCommand(
            sg_pu=(float(constrained[0]), float(constrained[1])),
            ibr_pu=(0.0, 0.0),
        )


__all__ = ["ConventionalACEPIController", "ConventionalPIConfig"]
