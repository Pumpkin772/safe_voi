"""Deterministic, paired, safety-constrained identification excitations."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from numpy.typing import NDArray

from d5freq.utils.hashing import sha256_json
from d5freq.utils.seeds import make_rng

from .schemas import (
    EXCITATION_FAMILIES,
    ExcitationSignals,
    IdentificationGenerationConfig,
)


FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class ExcitationSafetyAudit:
    """Pre-simulation audit of the externally imposed ZOH signals."""

    max_abs_command_pu: float
    max_abs_command_step_pu: float
    max_abs_command_rate_pu_per_s: float
    max_abs_frequency_hz: float
    command_std_pu: float
    frequency_std_hz: float
    amplitude_safe: bool
    rate_safe: bool
    frequency_safe: bool
    command_excitation_sufficient: bool
    frequency_excitation_sufficient: bool

    @property
    def passed(self) -> bool:
        return all(
            (
                self.amplitude_safe,
                self.rate_safe,
                self.frequency_safe,
                self.command_excitation_sufficient,
                self.frequency_excitation_sufficient,
            )
        )


def _normalize_to_peak(values: FloatArray, peak: float) -> FloatArray:
    centered = np.asarray(values, dtype=np.float64) - float(values[0])
    maximum = float(np.max(np.abs(centered)))
    if maximum <= np.finfo(float).eps:
        raise ValueError("excitation construction produced a constant signal")
    return centered * (peak / maximum)


def _slew_project(
    target: FloatArray,
    *,
    absolute_limit: float,
    maximum_step: float,
) -> FloatArray:
    """Project a target sequence onto amplitude and one-step slew bounds."""

    if maximum_step <= 0.0 or absolute_limit <= 0.0:
        raise ValueError("slew projection limits must be positive")
    projected = np.empty_like(target, dtype=np.float64)
    projected[0] = 0.0
    for index in range(1, len(target)):
        bounded_target = float(np.clip(target[index], -absolute_limit, absolute_limit))
        projected[index] = np.clip(
            bounded_target,
            projected[index - 1] - maximum_step,
            projected[index - 1] + maximum_step,
        )
    return np.clip(projected, -absolute_limit, absolute_limit)


def _prbs_target(
    sample_count: int, rng: np.random.Generator, amplitude: float
) -> FloatArray:
    target = np.zeros(sample_count, dtype=np.float64)
    maximum_dwell = max(2, min(10, sample_count // 12))
    index = 1
    previous_sign = -1.0 if float(rng.random()) < 0.5 else 1.0
    while index < sample_count:
        # Force a sign change most of the time while retaining a genuine PRBS
        # family rather than a deterministic square wave.
        sign = -previous_sign if float(rng.random()) < 0.8 else previous_sign
        dwell = int(rng.integers(1, maximum_dwell + 1))
        target[index : min(sample_count, index + dwell)] = sign * amplitude
        previous_sign = sign
        index += dwell
    return target


def _band_limited_target(
    sample_count: int, rng: np.random.Generator, amplitude: float
) -> FloatArray:
    innovations = rng.normal(0.0, 1.0, size=sample_count)
    filtered = np.zeros(sample_count, dtype=np.float64)
    coefficient = 0.82
    for index in range(1, sample_count):
        filtered[index] = (
            coefficient * filtered[index - 1]
            + (1.0 - coefficient) * innovations[index]
        )
    return _normalize_to_peak(filtered, amplitude)


def _multisine_target(
    sample_count: int, rng: np.random.Generator, amplitude: float
) -> FloatArray:
    phase = np.linspace(0.0, 2.0 * math.pi, sample_count, dtype=np.float64)
    cycles = np.array([1.0, 2.0, 3.0, 5.0], dtype=np.float64)
    phases = rng.uniform(0.0, 2.0 * math.pi, size=len(cycles))
    weights = np.array([1.0, 0.75, 0.5, 0.3], dtype=np.float64)
    signal = np.sum(
        weights[:, None]
        * np.sin(cycles[:, None] * phase[None, :] + phases[:, None]),
        axis=0,
    )
    return _normalize_to_peak(signal, amplitude)


def _step_target(
    sample_count: int, rng: np.random.Generator, amplitude: float
) -> FloatArray:
    target = np.zeros(sample_count, dtype=np.float64)
    levels = amplitude * np.array([-1.0, -0.45, 0.45, 1.0], dtype=np.float64)
    dwell = max(1, sample_count // 10)
    index = 1
    while index < sample_count:
        order = rng.permutation(len(levels))
        for level_index in order:
            if index >= sample_count:
                break
            stop = min(sample_count, index + dwell)
            target[index:stop] = levels[int(level_index)]
            index = stop
    return target


def _frequency_waveform_hz(
    sample_count: int,
    rng: np.random.Generator,
    frequency_abs_limit_hz: float,
) -> FloatArray:
    """Generate an independent smooth multisine-plus-random frequency test."""

    phase = np.linspace(0.0, 2.0 * math.pi, sample_count, dtype=np.float64)
    phases = rng.uniform(0.0, 2.0 * math.pi, size=3)
    multisine = (
        np.sin(1.0 * phase + phases[0])
        + 0.55 * np.sin(2.5 * phase + phases[1])
        + 0.30 * np.sin(4.0 * phase + phases[2])
    )
    innovations = rng.normal(0.0, 1.0, size=sample_count)
    colored = np.zeros(sample_count, dtype=np.float64)
    for index in range(1, sample_count):
        colored[index] = 0.90 * colored[index - 1] + 0.10 * innovations[index]
    combined = multisine + 0.30 * colored
    return _normalize_to_peak(combined, 0.92 * frequency_abs_limit_hz)


def generate_safe_excitation(
    config: IdentificationGenerationConfig,
    *,
    family: str,
    seed: int,
) -> ExcitationSignals:
    """Generate one deterministic command/frequency pair at the control period.

    The returned samples define right-continuous ZOH signals.  The command is
    projected onto both equation-level identification safety constraints,
    ``|u_b| <= u_id,max`` and ``|Delta u_b| <= r_id,max T_s``.
    """

    if not isinstance(config, IdentificationGenerationConfig):
        raise TypeError("config must be an IdentificationGenerationConfig")
    if family not in EXCITATION_FAMILIES:
        raise ValueError(f"unknown excitation family: {family!r}")
    rng = make_rng(seed)
    sample_count = config.sample_count
    command_peak = 0.92 * config.command_abs_limit_pu
    builders = {
        "prbs": _prbs_target,
        "band_limited": _band_limited_target,
        "multisine": _multisine_target,
        "steps": _step_target,
    }
    target = builders[family](sample_count, rng, command_peak)
    command = _slew_project(
        target,
        absolute_limit=config.command_abs_limit_pu,
        maximum_step=(
            config.command_rate_limit_pu_per_s * config.control_period_s
        ),
    )
    frequency_hz = _frequency_waveform_hz(
        sample_count,
        rng,
        config.frequency_abs_limit_hz,
    )
    time = np.arange(sample_count, dtype=np.float64) * config.control_period_s
    signals = ExcitationSignals(
        family=family,
        time_s=time,
        u_ibr_pu=command,
        omega_pu=frequency_hz / config.f0_hz,
    )
    audit = audit_safe_excitation(signals, config)
    if not audit.passed:
        raise RuntimeError(
            f"generated {family} excitation failed its safety/quality audit: {audit}"
        )
    return signals


def audit_safe_excitation(
    signals: ExcitationSignals,
    config: IdentificationGenerationConfig,
    *,
    tolerance: float = 1.0e-12,
) -> ExcitationSafetyAudit:
    """Audit command magnitude/rate, frequency magnitude, and signal spread."""

    if not isinstance(signals, ExcitationSignals):
        raise TypeError("signals must be an ExcitationSignals instance")
    if not isinstance(config, IdentificationGenerationConfig):
        raise TypeError("config must be an IdentificationGenerationConfig")
    if tolerance < 0.0 or not math.isfinite(tolerance):
        raise ValueError("tolerance must be finite and non-negative")
    dt = np.diff(signals.time_s)
    if not np.allclose(
        dt, config.control_period_s, rtol=0.0, atol=max(tolerance, 1.0e-12)
    ):
        raise ValueError("excitation samples are not on the configured control period")
    command_steps = np.diff(signals.u_ibr_pu)
    max_abs_command = float(np.max(np.abs(signals.u_ibr_pu)))
    max_abs_step = float(np.max(np.abs(command_steps)))
    max_abs_rate = float(np.max(np.abs(command_steps / dt)))
    frequency_hz = config.f0_hz * signals.omega_pu
    max_abs_frequency = float(np.max(np.abs(frequency_hz)))
    command_std = float(np.std(signals.u_ibr_pu))
    frequency_std = float(np.std(frequency_hz))
    return ExcitationSafetyAudit(
        max_abs_command_pu=max_abs_command,
        max_abs_command_step_pu=max_abs_step,
        max_abs_command_rate_pu_per_s=max_abs_rate,
        max_abs_frequency_hz=max_abs_frequency,
        command_std_pu=command_std,
        frequency_std_hz=frequency_std,
        amplitude_safe=max_abs_command <= config.command_abs_limit_pu + tolerance,
        rate_safe=(
            max_abs_rate <= config.command_rate_limit_pu_per_s + tolerance
        ),
        frequency_safe=(
            max_abs_frequency <= config.frequency_abs_limit_hz + tolerance
        ),
        command_excitation_sufficient=(
            command_std + tolerance >= config.minimum_command_std_pu
        ),
        frequency_excitation_sufficient=(
            frequency_std + tolerance >= config.minimum_frequency_std_hz
        ),
    )


def excitation_sha256(signals: ExcitationSignals) -> str:
    """Hash the logical excitation, independent of any file format."""

    if not isinstance(signals, ExcitationSignals):
        raise TypeError("signals must be an ExcitationSignals instance")
    return sha256_json(
        {
            "family": signals.family,
            "time_s": signals.time_s,
            "u_ibr_pu": signals.u_ibr_pu,
            "omega_pu": signals.omega_pu,
        }
    )


__all__ = [
    "ExcitationSafetyAudit",
    "audit_safe_excitation",
    "excitation_sha256",
    "generate_safe_excitation",
]
