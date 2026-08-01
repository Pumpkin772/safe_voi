"""Exact fractional-period ZOH delay vertices and command-history augmentation."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import cont2discrete

from direction1freq.models.plant_a_v2 import TwoAreaPlantAV2


@dataclass(frozen=True, slots=True)
class DelayAugmentedVertex:
    period_s: float
    bess_delay_s: float
    sg_delay_s: float
    ad: np.ndarray
    b_current: np.ndarray
    b_previous: np.ndarray
    ed: np.ndarray
    a_augmented: np.ndarray
    b_augmented: np.ndarray
    e_augmented: np.ndarray


def _zoh_input_column(
    a: np.ndarray, column: np.ndarray, duration_s: float
) -> np.ndarray:
    c = np.zeros((1, a.shape[0]))
    d = np.zeros((1, 1))
    _ad, bd, *_ = cont2discrete((a, column, c, d), duration_s, method="zoh")
    return np.asarray(bd)


def exact_fractional_delay_vertex(
    period_s: float,
    bess_delay_s: float,
    *,
    sg_delay_s: float = 0.2,
    plant: TwoAreaPlantAV2 | None = None,
) -> DelayAugmentedVertex:
    """Build z=[x,u_previous,E] with SG delay fixed and BESS delay uncertain."""

    period = float(period_s)
    if not 0.0 <= bess_delay_s < period:
        raise ValueError("BESS delay must lie in [0, period)")
    if not 0.0 <= sg_delay_s < period:
        raise ValueError("SG delay must lie in [0, period)")
    model = TwoAreaPlantAV2() if plant is None else plant
    a, b, _c_ace, e = model.linear_continuous_model_separate()
    combined = np.column_stack((b, e))
    c = np.zeros((1, a.shape[0]))
    d = np.zeros((1, combined.shape[1]))
    ad, full, *_ = cont2discrete((a, combined, c, d), period, method="zoh")
    bd = np.asarray(full[:, : b.shape[1]])
    ed = np.asarray(full[:, b.shape[1] :])
    current = np.zeros_like(bd)
    for column in range(b.shape[1]):
        delay = bess_delay_s if column in (1, 3) else sg_delay_s
        current[:, [column]] = _zoh_input_column(
            a, b[:, [column]], period - delay
        )
    previous = bd - current
    n, m, energy_dimension = a.shape[0], b.shape[1], 2
    a_augmented = np.block(
        [
            [np.asarray(ad), previous, np.zeros((n, energy_dimension))],
            [np.zeros((m, n)), np.zeros((m, m)), np.zeros((m, energy_dimension))],
            [np.zeros((energy_dimension, n + m)), np.eye(energy_dimension)],
        ]
    )
    b_augmented = np.vstack(
        [current, np.eye(m), np.zeros((energy_dimension, m))]
    )
    e_augmented = np.vstack(
        [ed, np.zeros((m + energy_dimension, ed.shape[1]))]
    )
    return DelayAugmentedVertex(
        period,
        float(bess_delay_s),
        float(sg_delay_s),
        np.asarray(ad),
        current,
        previous,
        ed,
        a_augmented,
        b_augmented,
        e_augmented,
    )


def build_registered_delay_vertices(
    period_s: float, delays_s: tuple[float, ...]
) -> tuple[DelayAugmentedVertex, ...]:
    return tuple(
        exact_fractional_delay_vertex(period_s, delay) for delay in delays_s
    )


def dense_linear_hull_remainder(
    period_s: float,
    delays_s: tuple[float, ...],
    *,
    power_bound_pu: float,
    dense_points: int = 361,
) -> tuple[np.ndarray, list[dict[str, float]]]:
    """Compute a componentwise outer bound for between-vertex delay curvature."""

    delays = np.asarray(delays_s, dtype=float)
    vertices = build_registered_delay_vertices(period_s, delays_s)
    state_bound = np.zeros(vertices[0].ad.shape[0])
    rows: list[dict[str, float]] = []
    for delay in np.linspace(delays[0], delays[-1], dense_points):
        left = min(max(int(np.searchsorted(delays, delay, side="right") - 1), 0), len(delays) - 2)
        alpha = (delay - delays[left]) / (delays[left + 1] - delays[left])
        current_hull = (
            (1.0 - alpha) * vertices[left].b_current
            + alpha * vertices[left + 1].b_current
        )
        previous_hull = (
            (1.0 - alpha) * vertices[left].b_previous
            + alpha * vertices[left + 1].b_previous
        )
        exact = exact_fractional_delay_vertex(period_s, float(delay))
        # SG columns are identical at every vertex; only BESS columns enter the
        # continuum remainder.  Current and previous commands are both bounded.
        error_current = exact.b_current[:, [1, 3]] - current_hull[:, [1, 3]]
        error_previous = exact.b_previous[:, [1, 3]] - previous_hull[:, [1, 3]]
        component_bound = power_bound_pu * (
            np.sum(np.abs(error_current), axis=1)
            + np.sum(np.abs(error_previous), axis=1)
        )
        state_bound = np.maximum(state_bound, component_bound)
        rows.append(
            {
                "period_s": float(period_s),
                "delay_s": float(delay),
                "left_vertex_s": float(delays[left]),
                "right_vertex_s": float(delays[left + 1]),
                "matrix_inf_error": float(
                    max(
                        np.max(np.abs(error_current)),
                        np.max(np.abs(error_previous)),
                    )
                ),
                "bounded_state_error_inf": float(np.max(component_bound)),
            }
        )
    return state_bound, rows

