"""Simulator-private piecewise-constant hidden-mode schedules."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import math


def _mode_name(value: str, field_name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


@dataclass(frozen=True, slots=True, order=True)
class ModeSwitch:
    """Select ``mode`` beginning exactly at ``time_s``."""

    time_s: float
    mode: str

    def __post_init__(self) -> None:
        time = float(self.time_s)
        if not math.isfinite(time) or time <= 0.0:
            raise ValueError("mode-switch time_s must be finite and positive")
        object.__setattr__(self, "time_s", time)
        object.__setattr__(self, "mode", _mode_name(self.mode, "mode"))


@dataclass(frozen=True, slots=True)
class PiecewiseConstantModeSchedule:
    """An initial hidden mode followed by strictly ordered switches."""

    initial_mode: str
    switches: tuple[ModeSwitch, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "initial_mode", _mode_name(self.initial_mode, "initial_mode")
        )
        switches = tuple(self.switches)
        times = tuple(switch.time_s for switch in switches)
        if any(right <= left for left, right in zip(times, times[1:])):
            raise ValueError("mode switches must have strictly increasing times")
        object.__setattr__(self, "switches", switches)

    @classmethod
    def from_pairs(
        cls,
        initial_mode: str,
        switches: tuple[tuple[float, str], ...] | list[tuple[float, str]],
    ) -> "PiecewiseConstantModeSchedule":
        return cls(
            initial_mode,
            tuple(ModeSwitch(time_s, mode) for time_s, mode in switches),
        )

    def mode_at(self, time_s: float) -> str:
        time = float(time_s)
        if not math.isfinite(time) or time < 0.0:
            raise ValueError("time_s must be finite and non-negative")
        times = tuple(switch.time_s for switch in self.switches)
        index = bisect_right(times, time)
        if index == 0:
            return self.initial_mode
        return self.switches[index - 1].mode

    def switch_times_between(self, start_time_s: float, end_time_s: float) -> tuple[float, ...]:
        """Return switch instants in the half-open interval ``(start, end]``."""

        start = float(start_time_s)
        end = float(end_time_s)
        if not math.isfinite(start) or not math.isfinite(end) or start < 0.0:
            raise ValueError("schedule interval must be finite and start non-negative")
        if end < start:
            raise ValueError("end_time_s must not precede start_time_s")
        return tuple(
            switch.time_s for switch in self.switches if start < switch.time_s <= end
        )

    @property
    def modes(self) -> tuple[str, ...]:
        """Return unique configured names in first-appearance order."""

        return tuple(dict.fromkeys((self.initial_mode, *(s.mode for s in self.switches))))


ModeSchedule = PiecewiseConstantModeSchedule


__all__ = ["ModeSchedule", "ModeSwitch", "PiecewiseConstantModeSchedule"]
