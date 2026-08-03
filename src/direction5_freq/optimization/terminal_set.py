"""Load-translated SG terminal-policy RPI/RCI support calculation."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.linalg import solve_discrete_are

from direction1freq.models.delay_augmented_prediction import exact_fractional_delay_vertex
from direction1freq.models.plant_a_v2 import TwoAreaPlantAV2


@dataclass(frozen=True, slots=True)
class SustainableTerminalCertificate:
    plant: str
    period_s: float
    closed_loop_matrix: np.ndarray
    feedback_gain: np.ndarray
    disturbance_radius: np.ndarray
    generator_matrix: np.ndarray
    coordinate_support: np.ndarray
    frequency_support_hz: np.ndarray
    ace_support_pu: np.ndarray
    tie_support_pu: float
    valve_support_pu: np.ndarray
    mechanical_support_pu: np.ndarray
    command_support_pu: np.ndarray
    spectral_radius: float
    tail_generator_inf: float
    iterations: int
    stable: bool
    invariant: bool
    admissible: bool
    terminal_radius_compatible: bool


def terminal_feedback_gain(period_s: float) -> np.ndarray:
    vertex = exact_fractional_delay_vertex(period_s, 0.20)
    current = vertex.b_current[:, [0, 2]]
    previous = vertex.b_previous[:, [0, 2]]
    augmented_a = np.block(
        [[vertex.ad, previous], [np.zeros((2, 11))]]
    )
    augmented_b = np.vstack([current, np.eye(2)])
    q = np.diag([2e4, 2e4, 1e4, 50, 50, 200, 200, 20, 20, 5, 5])
    r = 3.0 * np.eye(2)
    p = solve_discrete_are(augmented_a, augmented_b, q, r)
    return np.linalg.solve(
        r + augmented_b.T @ p @ augmented_b,
        augmented_b.T @ p @ augmented_a,
    )


def _reachable_generators(
    matrix: np.ndarray,
    disturbance_radius: np.ndarray,
    tolerance: float = 1e-12,
    maximum_iterations: int = 4000,
) -> tuple[np.ndarray, tuple[np.ndarray, ...], float]:
    power = np.eye(matrix.shape[0])
    support = np.zeros(matrix.shape[0])
    generators = []
    tail = float("inf")
    for _ in range(maximum_iterations):
        generator = power @ np.diag(disturbance_radius)
        generators.append(generator)
        support += np.sum(np.abs(generator), axis=1)
        power = matrix @ power
        tail = float(np.max(np.abs(power @ np.diag(disturbance_radius))))
        if tail <= tolerance:
            break
    return support, tuple(generators), tail


def _support(row: np.ndarray, generators: tuple[np.ndarray, ...]) -> float:
    vector = np.asarray(row, dtype=float).reshape(1, -1)
    return float(sum(np.sum(np.abs(vector @ generator)) for generator in generators))


def compute_sustainable_terminal_set(
    plant: str,
    period_s: float,
    state_disturbance_radius: np.ndarray,
    terminal_radius: np.ndarray,
    *,
    minimum_sg_margin_pu: float = 0.025,
) -> SustainableTerminalCertificate:
    """Compute the minimal fixed-policy RPI zonotope support.

    The terminal policy commands SG only. Consequently the uncertain BESS
    delay vertices induce the same augmented closed-loop matrix; BESS execution
    uncertainty is already represented in the registered local disturbance.
    """

    vertex = exact_fractional_delay_vertex(float(period_s), 0.20)
    gain = terminal_feedback_gain(float(period_s))
    augmented_a = np.block(
        [[vertex.ad, vertex.b_previous[:, [0, 2]]], [np.zeros((2, 11))]]
    )
    augmented_b = np.vstack([vertex.b_current[:, [0, 2]], np.eye(2)])
    closed = augmented_a - augmented_b @ gain
    disturbance = np.r_[np.asarray(state_disturbance_radius, dtype=float), np.zeros(2)]
    coordinate, generators, tail = _reachable_generators(closed, disturbance)
    nominal_frequency = 50.0 if str(plant) == "A" else 60.0
    model = TwoAreaPlantAV2()
    _a, _b, c_ace, _e = model.linear_continuous_model_separate()
    identity = np.eye(11)
    frequency = np.array(
        [_support(nominal_frequency * identity[index], generators) for index in (0, 1)]
    )
    ace = np.array(
        [_support(np.r_[c_ace[index], np.zeros(2)], generators) for index in (0, 1)]
    )
    tie = _support(identity[2], generators)
    valve = np.array([_support(identity[index], generators) for index in (3, 4)])
    mechanical = np.array([_support(identity[index], generators) for index in (5, 6)])
    command = np.array([_support(gain[index], generators) for index in (0, 1)])
    spectral = float(np.max(np.abs(np.linalg.eigvals(closed))))
    stable = spectral < 1.0
    invariant = bool(stable and tail <= 1e-10)
    terminal_compatible = bool(
        np.all(coordinate[:9] <= np.asarray(terminal_radius) + 1e-12)
    )
    # The recursive initial domain is the subset whose load-dependent
    # equilibrium retains at least this margin to SG/valve bounds. H4 used a
    # wider empirical terminal neighborhood; H6 deliberately restricts the
    # theorem domain instead of inflating or deleting the local disturbance.
    admissible = bool(
        np.max(frequency) <= 0.30
        and np.max(ace) <= 0.15
        and tie <= 0.08
        and np.max(valve) <= minimum_sg_margin_pu
        and np.max(mechanical) <= minimum_sg_margin_pu
        and np.max(command) <= minimum_sg_margin_pu
    )
    return SustainableTerminalCertificate(
        str(plant),
        float(period_s),
        closed,
        gain,
        disturbance,
        np.concatenate(generators, axis=1),
        coordinate,
        frequency,
        ace,
        tie,
        valve,
        mechanical,
        command,
        spectral,
        tail,
        len(generators),
        stable,
        invariant,
        admissible,
        terminal_compatible,
    )
