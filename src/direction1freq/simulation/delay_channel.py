"""One causal delay implementation shared by every Phase-E plant entrypoint."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np


@dataclass(frozen=True, slots=True)
class DelayChannelState:
    """Immutable ring-buffer state.

    Columns are ordered oldest to newest.  Zero prehistory is explicit, so a
    command issued at time zero cannot appear before the requested delay.
    """

    history: np.ndarray


class CausalDelayChannel:
    def __init__(self, channels: int, dt_s: float, maximum_delay_s: float) -> None:
        if channels <= 0 or dt_s <= 0 or maximum_delay_s < 0:
            raise ValueError("invalid delay-channel dimensions")
        self.channels = int(channels)
        self.dt_s = float(dt_s)
        self.maximum_delay_s = float(maximum_delay_s)
        self.history_length = int(math.ceil(maximum_delay_s / dt_s)) + 2

    def equilibrium(self, initial: np.ndarray | None = None) -> DelayChannelState:
        value = np.zeros(self.channels) if initial is None else np.asarray(initial, dtype=float)
        if value.shape != (self.channels,):
            raise ValueError("initial delay value has the wrong shape")
        return DelayChannelState(np.repeat(value[:, None], self.history_length, axis=1))

    def step(
        self, state: DelayChannelState, issued: np.ndarray, delay_s: np.ndarray | float,
    ) -> tuple[DelayChannelState, np.ndarray]:
        command = np.asarray(issued, dtype=float)
        delays = np.broadcast_to(np.asarray(delay_s, dtype=float), (self.channels,))
        if command.shape != (self.channels,):
            raise ValueError("issued command has the wrong shape")
        if state.history.shape != (self.channels, self.history_length):
            raise ValueError("delay state does not match channel configuration")
        if np.any(delays < -1e-12) or np.any(delays > self.maximum_delay_s + 1e-12):
            raise ValueError("delay outside preregistered channel range")

        history = np.roll(state.history, -1, axis=1)
        history[:, -1] = command
        delay_steps = np.rint(delays / self.dt_s).astype(int)
        delay_steps = np.clip(delay_steps, 0, self.history_length - 1)
        delivered = np.array([history[index, -1 - delay_steps[index]] for index in range(self.channels)])
        return DelayChannelState(history), delivered
