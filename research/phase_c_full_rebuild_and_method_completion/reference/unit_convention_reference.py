"""Reference utilities for the Phase-C unit convention.

These functions are not a replacement for the final plant implementation. They
exist to prevent the Hz / per-unit frequency scaling error found in Phase B2.
"""
from __future__ import annotations


def hz_to_pu_frequency(delta_f_hz: float, f0_hz: float) -> float:
    if f0_hz <= 0:
        raise ValueError("f0_hz must be positive")
    return delta_f_hz / f0_hz


def pu_frequency_to_hz(omega_pu: float, f0_hz: float) -> float:
    if f0_hz <= 0:
        raise ValueError("f0_hz must be positive")
    return omega_pu * f0_hz


def initial_rocof_hz_per_s(
    delta_p_pu: float,
    inertia_H_s: float,
    f0_hz: float,
) -> float:
    """Initial RoCoF for 2H*domega/dt = -delta_p, before controls act."""
    if inertia_H_s <= 0 or f0_hz <= 0:
        raise ValueError("H and f0 must be positive")
    return -f0_hz * delta_p_pu / (2.0 * inertia_H_s)


def energy_next_mwh(
    energy_mwh: float,
    power_mw: float,
    dt_s: float,
    eta_charge: float,
    eta_discharge: float,
) -> float:
    """Positive power is discharge to the grid; negative is charge."""
    if not (0 < eta_charge <= 1 and 0 < eta_discharge <= 1):
        raise ValueError("efficiencies must lie in (0,1]")
    if dt_s < 0:
        raise ValueError("dt_s must be nonnegative")
    if power_mw >= 0:
        delta = power_mw / eta_discharge * dt_s / 3600.0
    else:
        delta = power_mw * eta_charge * dt_s / 3600.0
    return energy_mwh - delta


def discharge_power_from_energy_limit_mw(
    energy_mwh: float,
    energy_min_mwh: float,
    dt_s: float,
    eta_discharge: float,
) -> float:
    if dt_s <= 0:
        raise ValueError("dt_s must be positive")
    return max(0.0, 3600.0 * eta_discharge * (energy_mwh - energy_min_mwh) / dt_s)
