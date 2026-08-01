"""Recomputable SG-only robust-backup reachable-set calculations."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.linalg import solve_discrete_are

from direction1freq.controllers.ace_pi_aw import (
    delayed_sampled_closed_loop_matrix,
    design_stable_pi,
)
from direction1freq.models.delay_augmented_prediction import (
    exact_fractional_delay_vertex,
)
from direction1freq.models.plant_a_v2 import TwoAreaPlantAV2


@dataclass(frozen=True, slots=True)
class BackupSetAttempt:
    design: str
    period_s: float
    closed_loop_matrix: np.ndarray
    command_gain: np.ndarray
    disturbance_radius: np.ndarray
    coordinate_support: np.ndarray
    frequency_support_hz: np.ndarray
    ace_support_pu: np.ndarray
    tie_support_pu: float
    sg_mechanical_support_pu: np.ndarray
    sg_command_support_pu: np.ndarray
    spectral_radius: float
    tail_generator_inf: float
    iterations: int
    constraints_satisfied: bool


def reachable_zonotope_support(
    closed_loop: np.ndarray,
    disturbance_radius: np.ndarray,
    *,
    tolerance: float = 1e-12,
    maximum_iterations: int = 2000,
) -> tuple[np.ndarray, list[np.ndarray], float]:
    """Return support of sum A^i diag(w) and retained generators."""

    matrix = np.asarray(closed_loop, dtype=float)
    radius = np.asarray(disturbance_radius, dtype=float)
    power = np.eye(matrix.shape[0])
    generators: list[np.ndarray] = []
    support = np.zeros(matrix.shape[0])
    tail = float("inf")
    for _iteration in range(maximum_iterations):
        generator = power @ np.diag(radius)
        generators.append(generator)
        support += np.sum(np.abs(generator), axis=1)
        power = matrix @ power
        tail = float(np.max(np.abs(power @ np.diag(radius))))
        if tail <= tolerance:
            break
    return support, generators, tail


def linear_support(row: np.ndarray, generators: list[np.ndarray]) -> float:
    vector = np.asarray(row, dtype=float).reshape(1, -1)
    return float(sum(np.sum(np.abs(vector @ generator)) for generator in generators))


def _evaluate_attempt(
    design: str,
    period_s: float,
    closed_loop: np.ndarray,
    command_gain: np.ndarray,
    disturbance_radius: np.ndarray,
) -> BackupSetAttempt:
    support, generators, tail = reachable_zonotope_support(
        closed_loop, disturbance_radius
    )
    plant = TwoAreaPlantAV2()
    _a, _b, c_ace, _e = plant.linear_continuous_model_separate()
    frequency = np.array(
        [
            linear_support(
                np.eye(len(support))[area] * 50.0,
                generators,
            )
            for area in range(2)
        ]
    )
    ace = np.array(
        [
            linear_support(
                np.r_[c_ace[area], np.zeros(len(support) - 9)], generators
            )
            for area in range(2)
        ]
    )
    tie = linear_support(
        np.r_[np.array([0.0, 0.0, 1.0]), np.zeros(len(support) - 3)],
        generators,
    )
    mechanical = np.array(
        [
            linear_support(
                np.r_[np.eye(9)[5 + area], np.zeros(len(support) - 9)],
                generators,
            )
            for area in range(2)
        ]
    )
    command = np.array(
        [linear_support(command_gain[area], generators) for area in range(2)]
    )
    passed = bool(
        np.max(frequency) <= 0.30
        and np.max(ace) <= 0.15
        and tie <= 0.08
        and np.max(mechanical) <= 0.10
        and np.max(command) <= 0.025
        and tail <= 1e-10
    )
    return BackupSetAttempt(
        design,
        float(period_s),
        closed_loop,
        command_gain,
        disturbance_radius,
        support,
        frequency,
        ace,
        tie,
        mechanical,
        command,
        float(np.max(np.abs(np.linalg.eigvals(closed_loop)))),
        tail,
        len(generators),
        passed,
    )


def pi_backup_attempt(
    period_s: float, plant_state_disturbance_radius: np.ndarray
) -> BackupSetAttempt:
    plant = TwoAreaPlantAV2()
    kp, ki, _ = design_stable_pi(plant, period_s, sg_fraction=1.0)
    closed = delayed_sampled_closed_loop_matrix(
        plant, period_s, kp, ki, sg_fraction=1.0
    )
    _a, _b, c_ace, _e = plant.linear_continuous_model_separate()
    command_gain = np.zeros((2, closed.shape[0]))
    command_gain[:, :9] = -kp * c_ace
    command_gain[:, 9:11] = np.eye(2)
    disturbance = np.r_[
        np.asarray(plant_state_disturbance_radius, dtype=float), np.zeros(4)
    ]
    return _evaluate_attempt(
        "stable_ace_pi", period_s, closed, command_gain, disturbance
    )


def lqr_backup_attempt(
    period_s: float, plant_state_disturbance_radius: np.ndarray
) -> BackupSetAttempt:
    vertex = exact_fractional_delay_vertex(period_s, 0.2)
    sg_current = vertex.b_current[:, [0, 2]]
    sg_previous = vertex.b_previous[:, [0, 2]]
    n, m = 9, 2
    augmented_a = np.block(
        [
            [vertex.ad, sg_previous],
            [np.zeros((m, n + m))],
        ]
    )
    augmented_b = np.vstack([sg_current, np.eye(m)])
    q = np.diag([1e4, 1e4, 1e4, 10, 10, 100, 100, 1, 1, 1, 1])
    r = np.eye(m)
    p = solve_discrete_are(augmented_a, augmented_b, q, r)
    gain = np.linalg.solve(
        r + augmented_b.T @ p @ augmented_b,
        augmented_b.T @ p @ augmented_a,
    )
    closed = augmented_a - augmented_b @ gain
    disturbance = np.r_[
        np.asarray(plant_state_disturbance_radius, dtype=float), np.zeros(2)
    ]
    return _evaluate_attempt(
        "sg_state_feedback_lqr", period_s, closed, -gain, disturbance
    )
