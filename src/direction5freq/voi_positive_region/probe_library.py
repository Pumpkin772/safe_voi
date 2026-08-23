"""Physical-duration-normalized allocation-neutral probes."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ProbeDesign:
    probe_id: str
    period_s: float
    physical_duration_s: float
    amplitude_pu: float
    shape: str
    sequence_pu: tuple[float, ...]
    mode: str = "allocation_neutral"

    def __post_init__(self) -> None:
        sequence = np.asarray(self.sequence_pu, dtype=float)
        if len(sequence) < 2:
            raise ValueError("a nonzero zero-integral probe needs at least two samples")
        if self.mode == "allocation_neutral":
            if abs(float(sequence.sum()) * self.period_s) > 1e-12:
                raise ValueError("allocation-neutral probe has nonzero integral")
        elif self.mode == "control_aligned_surplus":
            if np.any(sequence < 0.0) or not np.any(sequence > 0.0):
                raise ValueError("control-aligned surplus must be nonnegative and nonzero")
        else:
            raise ValueError("unknown probe mode")
        if np.max(np.abs(sequence)) > self.amplitude_pu + 1e-12:
            raise ValueError("probe exceeds registered amplitude")
        if abs(len(sequence) * self.period_s - self.physical_duration_s) > 1e-12:
            raise ValueError("sequence duration does not match physical duration")


def _shape(samples: int, name: str) -> np.ndarray:
    if samples < 2:
        raise ValueError("physical duration is shorter than two control samples")
    if name == "biphasic":
        raw = np.r_[np.ones(samples // 2), -np.ones(samples - samples // 2)]
    elif name == "ternary":
        raw = np.resize(np.asarray((1.0, 0.0, -1.0)), samples)
    elif name == "short_prbs":
        raw = np.resize(np.asarray((1.0, -1.0, -1.0, 1.0)), samples)
    else:
        raise ValueError(f"unknown probe shape {name}")
    raw -= raw.mean()
    maximum = float(np.max(np.abs(raw)))
    if maximum <= 0.0:
        raise ValueError("probe shape collapsed to zero")
    return raw / maximum


def registered_probe_library(
    period_s: float,
    durations_s: tuple[float, ...] = (4.0, 8.0, 12.0),
    amplitudes_pu: tuple[float, ...] = (0.0005, 0.0010, 0.0015, 0.0025, 0.0035, 0.0050),
    shapes: tuple[str, ...] = ("biphasic", "ternary", "short_prbs"),
) -> list[ProbeDesign]:
    if period_s not in {2.0, 4.0}:
        raise ValueError("registered period must be 2 or 4 s")
    probes: list[ProbeDesign] = []
    for duration_s in durations_s:
        samples_float = duration_s / period_s
        samples = int(round(samples_float))
        if abs(samples - samples_float) > 1e-12 or samples < 2:
            continue
        for amplitude in amplitudes_pu:
            for name in shapes:
                unit = _shape(samples, name)
                sequence = tuple(float(value * amplitude) for value in unit)
                probes.append(ProbeDesign(
                    probe_id=(
                        f"{name}_{duration_s:g}s_{amplitude:.4f}pu_{period_s:g}s"
                    ),
                    period_s=period_s,
                    physical_duration_s=duration_s,
                    amplitude_pu=amplitude,
                    shape=name,
                    sequence_pu=sequence,
                ))
    return probes


def registered_control_aligned_library(
    period_s: float,
    durations_s: tuple[float, ...] = (12.0, 24.0),
    amplitudes_pu: tuple[float, ...] = (0.0020, 0.0025, 0.0030, 0.0035, 0.0040),
) -> list[ProbeDesign]:
    """Surplus requests used only under a causal binding-regulation trigger."""

    probes: list[ProbeDesign] = []
    for duration_s in durations_s:
        samples = int(round(duration_s / period_s))
        if samples < 2 or not np.isclose(samples * period_s, duration_s):
            continue
        active_samples = max(1, samples // 3)
        start = max(0, (samples - active_samples) // 2)
        for amplitude in amplitudes_pu:
            sequence = np.zeros(samples)
            sequence[start:start + active_samples] = amplitude
            probes.append(ProbeDesign(
                probe_id=f"control_aligned_{duration_s:g}s_{amplitude:.4f}pu_{period_s:g}s",
                period_s=period_s,
                physical_duration_s=duration_s,
                amplitude_pu=amplitude,
                shape="surplus_plateau",
                sequence_pu=tuple(float(value) for value in sequence),
                mode="control_aligned_surplus",
            ))
    return probes
