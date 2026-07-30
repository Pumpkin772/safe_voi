"""Control-relevant regime and passive-identifiability audit utilities."""

from __future__ import annotations

from dataclasses import dataclass
import itertools
import math
from typing import Sequence

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.stats import chi2

from d5freq.models.two_area_plant_b import (
    PlantBParameters,
    PlantBStateIndex,
    TwoAreaPlantB,
    UpperCommand,
)


FloatArray = NDArray[np.float64]
VISIBLE_INDICES = np.asarray((0, 3, 6, 8, 12, 1, 4), dtype=np.int64)
VISIBLE_SCALE = np.asarray((0.02, 0.02, 0.02, 0.08, 0.08, 0.05, 0.05))


@dataclass(frozen=True, slots=True)
class ControlDistanceWeights:
    prediction: float = 0.50
    action: float = 0.30
    capability: float = 0.20
    merge_threshold: float = 0.05

    def __post_init__(self) -> None:
        values = np.asarray(
            (self.prediction, self.action, self.capability, self.merge_threshold),
            dtype=np.float64,
        )
        if not np.isfinite(values).all() or np.any(values <= 0.0):
            raise ValueError("control-distance weights and threshold must be positive")
        if not math.isclose(float(np.sum(values[:3])), 1.0, abs_tol=1.0e-12):
            raise ValueError("control-distance component weights must sum to one")


def visible_output(trajectory: ArrayLike) -> FloatArray:
    values = np.asarray(trajectory, dtype=np.float64)
    if values.ndim == 1 and values.shape == (15,):
        return values[VISIBLE_INDICES]
    if values.ndim == 2 and values.shape[0] == 15:
        return values[VISIBLE_INDICES, :]
    raise ValueError("trajectory must have shape (15,) or (15, n)")


def rollout_expected_block(
    params: PlantBParameters,
    *,
    state: ArrayLike,
    action: ArrayLike,
    load_pu: ArrayLike,
    regime_pair: Sequence[str],
    past_ibr_commands_pu: ArrayLike | None = None,
    integration_step_s: float = 0.10,
) -> FloatArray:
    """Roll out one command block using expected packet delivery."""

    model = TwoAreaPlantB(params)
    current = model.validate_state(state).copy()
    command_values = np.asarray(action, dtype=np.float64)
    load = np.asarray(load_pu, dtype=np.float64)
    pair = tuple(str(value) for value in regime_pair)
    past = (
        np.zeros((2, 2), dtype=np.float64)
        if past_ibr_commands_pu is None
        else np.asarray(past_ibr_commands_pu, dtype=np.float64)
    )
    if command_values.shape != (4,) or load.shape != (2,) or past.shape != (2, 2):
        raise ValueError("invalid block rollout shapes")
    if len(pair) != 2 or any(value not in params.regimes for value in pair):
        raise ValueError("invalid block rollout regime pair")
    steps = round(params.upper_control_period_s / integration_step_s)
    trajectory = np.empty((15, steps + 1), dtype=np.float64)
    trajectory[:, 0] = current
    command = UpperCommand(
        sg_pu=(float(command_values[0]), float(command_values[1])),
        ibr_pu=(float(command_values[2]), float(command_values[3])),
    )
    for substep in range(steps):
        delivered: list[float] = []
        for area in (0, 1):
            regime = params.regimes[pair[area]]
            source_time = substep * integration_step_s - regime.command_delay_s
            source_block = math.floor(
                (source_time + 1.0e-12) / params.upper_control_period_s
            )
            if source_block >= 0:
                value = command_values[2 + area]
            else:
                value = past[area, max(0, min(1, source_block + 2))]
            delivered.append((1.0 - regime.dropout_probability) * float(value))
        current = model.step(
            current,
            command=command,
            delayed_ibr_command_pu=delivered,
            load_disturbance_pu=load,
            regimes=(params.regimes[pair[0]], params.regimes[pair[1]]),
            step_s=integration_step_s,
        )
        trajectory[:, substep + 1] = current
    return trajectory


def registered_candidate_actions(
    params: PlantBParameters,
    load_area_1_pu: float,
) -> tuple[FloatArray, ...]:
    reserve = params.sg_capability.reserve_up_pu[0]
    rating = params.bess[0].rating_pu
    sg_values = tuple(sorted({0.0, min(max(load_area_1_pu, 0.0), reserve), reserve}))
    ibr_values = tuple(
        sorted({0.0, min(max(load_area_1_pu, 0.0), 0.5 * rating), min(max(load_area_1_pu, 0.0), rating)})
    )
    return tuple(
        np.asarray((sg, 0.0, ibr, 0.0), dtype=np.float64)
        for sg, ibr in itertools.product(sg_values, ibr_values)
    )


def block_quality_cost(
    params: PlantBParameters,
    trajectory: FloatArray,
    action: FloatArray,
    *,
    integration_step_s: float = 0.10,
) -> float:
    frequency = trajectory[[0, 3], :-1]
    tie = trajectory[6, :-1]
    ace_1 = params.areas[0].ace_bias_pu_per_hz * frequency[0] + tie
    ace_2 = params.areas[1].ace_bias_pu_per_hz * frequency[1] - tie
    return float(
        integration_step_s
        * (
            200.0 * np.sum(np.abs(frequency))
            + 100.0 * np.sum(np.abs(ace_1))
            + 100.0 * np.sum(np.abs(ace_2))
        )
        + 5.0 * np.sum(action[:2] ** 2)
        + 8.0 * np.sum(action[2:] ** 2)
    )


def candidate_set_minimizer(
    params: PlantBParameters,
    *,
    state: ArrayLike,
    assumed_regime: str,
    load_pu: tuple[float, float],
    past_ibr_commands_pu: ArrayLike | None = None,
) -> tuple[FloatArray, float]:
    """Return the best registered finite action; no global claim is made."""

    best_action: FloatArray | None = None
    best_cost = math.inf
    for action in registered_candidate_actions(params, load_pu[0]):
        trajectory = rollout_expected_block(
            params,
            state=state,
            action=action,
            load_pu=load_pu,
            regime_pair=(assumed_regime, assumed_regime),
            past_ibr_commands_pu=past_ibr_commands_pu,
        )
        cost = block_quality_cost(params, trajectory, action)
        if cost < best_cost:
            best_cost = cost
            best_action = action
    assert best_action is not None
    return best_action, best_cost


def control_relevant_distance_rows(
    params: PlantBParameters,
    regime_ids: Sequence[str],
    *,
    weights: ControlDistanceWeights | None = None,
) -> list[dict[str, object]]:
    resolved = ControlDistanceWeights() if weights is None else weights
    model = TwoAreaPlantB(params)
    state = model.initial_state()
    probes = (
        (np.asarray((0.0, 0.0, 0.0, 0.0)), (0.0, 0.0)),
        (np.asarray((0.03, 0.0, 0.04, 0.0)), (0.04, 0.0)),
        (np.asarray((0.0, 0.03, 0.0, 0.04)), (0.0, 0.04)),
        (np.asarray((-0.03, 0.0, -0.04, 0.0)), (-0.04, 0.0)),
    )
    signatures: dict[str, FloatArray] = {}
    actions: dict[str, FloatArray] = {}
    capability: dict[str, FloatArray] = {}
    for regime_id in regime_ids:
        signature_parts: list[FloatArray] = []
        for action, load in probes:
            trajectory = rollout_expected_block(
                params,
                state=state,
                action=action,
                load_pu=load,
                regime_pair=(regime_id, regime_id),
            )
            signature_parts.append(
                (visible_output(trajectory) / VISIBLE_SCALE[:, None]).reshape(-1)
            )
        signatures[regime_id] = np.concatenate(signature_parts)
        action_rows = []
        for load in ((0.04, 0.0), (0.06, 0.0)):
            action_rows.append(
                candidate_set_minimizer(
                    params,
                    state=state,
                    assumed_regime=regime_id,
                    load_pu=load,
                )[0]
            )
        actions[regime_id] = np.concatenate(action_rows) / np.tile(
            np.asarray((0.05, 0.05, 0.08, 0.08)), 2
        )
        up_down = []
        for area in (0, 1):
            up_down.extend(
                model.headroom(
                    state, area=area, regime=params.regimes[regime_id]
                )
            )
        capability[regime_id] = np.asarray(up_down) / 0.08
    rows: list[dict[str, object]] = []
    for regime_a, regime_b in itertools.combinations(regime_ids, 2):
        prediction_raw = float(
            np.mean((signatures[regime_a] - signatures[regime_b]) ** 2)
        )
        action_raw = float(np.mean((actions[regime_a] - actions[regime_b]) ** 2))
        capability_raw = float(
            np.max(np.abs(capability[regime_a] - capability[regime_b])) ** 2
        )
        d_prediction = 1.0 - math.exp(-prediction_raw)
        d_action = 1.0 - math.exp(-action_raw)
        d_capability = 1.0 - math.exp(-capability_raw)
        d_control = (
            resolved.prediction * d_prediction
            + resolved.action * d_action
            + resolved.capability * d_capability
        )
        rows.append(
            {
                "regime_a": regime_a,
                "regime_b": regime_b,
                "d_pred": d_prediction,
                "d_act": d_action,
                "d_cap": d_capability,
                "d_ctrl": d_control,
                "merge_threshold": resolved.merge_threshold,
                "merge_decision": d_control < resolved.merge_threshold,
                "action_metric": "registered_candidate_set_minimizer_not_global_optimum",
            }
        )
    return rows


def critical_window(
    params: PlantBParameters,
    *,
    actual_regime: str,
    load_pu: tuple[float, float] = (0.06, 0.0),
    episode_s: float = 30.0,
    frequency_threshold: float = 0.020,
    control_cost_threshold: float = 0.050,
    safety_frequency_threshold: float = 0.20,
) -> dict[str, object]:
    model = TwoAreaPlantB(params)
    initial_soc = 0.14 if actual_regime == "energy_limited" else 0.50
    exact_state = model.initial_state(soc=(initial_soc, initial_soc))
    wrong_state = exact_state.copy()
    exact_past = np.zeros((2, 2), dtype=np.float64)
    wrong_past = np.zeros((2, 2), dtype=np.float64)
    cumulative_exact_iae = 0.0
    cumulative_wrong_iae = 0.0
    cumulative_exact_control = 0.0
    cumulative_wrong_control = 0.0
    critical_time = math.nan
    cause = "right_censored"
    steps_per_block = round(params.upper_control_period_s / 0.10)
    blocks = round(episode_s / params.upper_control_period_s)
    elapsed = 0.0
    for _ in range(blocks):
        exact_action, _ = candidate_set_minimizer(
            params,
            state=exact_state,
            assumed_regime=actual_regime,
            load_pu=load_pu,
            past_ibr_commands_pu=exact_past,
        )
        wrong_action, _ = candidate_set_minimizer(
            params,
            state=wrong_state,
            assumed_regime="nominal_available",
            load_pu=load_pu,
            past_ibr_commands_pu=wrong_past,
        )
        exact_trajectory = rollout_expected_block(
            params,
            state=exact_state,
            action=exact_action,
            load_pu=load_pu,
            regime_pair=(actual_regime, actual_regime),
            past_ibr_commands_pu=exact_past,
        )
        wrong_trajectory = rollout_expected_block(
            params,
            state=wrong_state,
            action=wrong_action,
            load_pu=load_pu,
            regime_pair=(actual_regime, actual_regime),
            past_ibr_commands_pu=wrong_past,
        )
        exact_control_rate = 5.0 * np.sum(exact_action[:2] ** 2) + 8.0 * np.sum(
            exact_action[2:] ** 2
        )
        wrong_control_rate = 5.0 * np.sum(wrong_action[:2] ** 2) + 8.0 * np.sum(
            wrong_action[2:] ** 2
        )
        for substep in range(1, steps_per_block + 1):
            cumulative_exact_iae += 0.10 * float(
                np.sum(np.abs(exact_trajectory[[0, 3], substep]))
            )
            cumulative_wrong_iae += 0.10 * float(
                np.sum(np.abs(wrong_trajectory[[0, 3], substep]))
            )
            cumulative_exact_control += 0.10 * exact_control_rate
            cumulative_wrong_control += 0.10 * wrong_control_rate
            elapsed += 0.10
            frequency_gap = cumulative_wrong_iae - cumulative_exact_iae
            cost_gap = abs(cumulative_wrong_control - cumulative_exact_control)
            exact_safe = (
                np.max(np.abs(exact_trajectory[[0, 3], substep]))
                <= safety_frequency_threshold
            )
            wrong_safe = (
                np.max(np.abs(wrong_trajectory[[0, 3], substep]))
                <= safety_frequency_threshold
            )
            if math.isnan(critical_time):
                if exact_safe != wrong_safe:
                    critical_time, cause = elapsed, "safety_difference"
                elif frequency_gap >= frequency_threshold:
                    critical_time, cause = elapsed, "frequency_iae_difference"
                elif cost_gap >= control_cost_threshold:
                    critical_time, cause = elapsed, "control_cost_difference"
        exact_state = exact_trajectory[:, -1]
        wrong_state = wrong_trajectory[:, -1]
        exact_past = np.column_stack((exact_past[:, 1], exact_action[2:]))
        wrong_past = np.column_stack((wrong_past[:, 1], wrong_action[2:]))
    return {
        "event": f"nominal_to_{actual_regime}",
        "scenario": "coincident_regime_and_load",
        "Tcritical_s": critical_time,
        "right_censored": math.isnan(critical_time),
        "threshold_cause": cause,
        "final_frequency_iae_gap": cumulative_wrong_iae - cumulative_exact_iae,
        "final_control_cost_abs_gap": abs(
            cumulative_wrong_control - cumulative_exact_control
        ),
    }


def passive_detection_rows(
    params: PlantBParameters,
    *,
    actual_regime: str,
    critical_time_s: float,
    seeds: Sequence[int] = (800, 801, 802, 803, 804),
    noise_multipliers: Sequence[float] = (0.5, 1.0, 2.0),
    episode_s: float = 20.0,
    load_pu: tuple[float, float] = (0.06, 0.0),
) -> tuple[list[dict[str, object]], dict[str, object]]:
    model = TwoAreaPlantB(params)
    initial_soc = 0.14 if actual_regime == "energy_limited" else 0.50
    actual_state = model.initial_state(soc=(initial_soc, initial_soc))
    nominal_state = actual_state.copy()
    action = np.asarray(
        (
            min(load_pu[0], params.sg_capability.reserve_up_pu[0]),
            0.0,
            0.0,
            0.0,
        )
    )
    steps = round(episode_s / 0.10)
    actual_visible = np.empty((7, steps + 1), dtype=np.float64)
    nominal_visible = np.empty((7, steps + 1), dtype=np.float64)
    actual_visible[:, 0] = visible_output(actual_state)
    nominal_visible[:, 0] = visible_output(nominal_state)
    column = 1
    for _ in range(round(episode_s / params.upper_control_period_s)):
        actual_block = rollout_expected_block(
            params,
            state=actual_state,
            action=action,
            load_pu=load_pu,
            regime_pair=(actual_regime, actual_regime),
        )
        nominal_block = rollout_expected_block(
            params,
            state=nominal_state,
            action=action,
            load_pu=load_pu,
            regime_pair=("nominal_available", "nominal_available"),
        )
        actual_visible[:, column : column + 20] = visible_output(actual_block[:, 1:])
        nominal_visible[:, column : column + 20] = visible_output(nominal_block[:, 1:])
        actual_state = actual_block[:, -1]
        nominal_state = nominal_block[:, -1]
        column += 20
    base_sigma = np.asarray((0.001, 0.001, 0.001, 0.001, 0.001, 0.001, 0.001))
    rows: list[dict[str, object]] = []
    deterministic_residual = actual_visible - nominal_visible
    gramian = float(np.sum((deterministic_residual[:, 1:] / base_sigma[:, None]) ** 2))
    window = 20
    threshold = float(chi2.ppf(0.99, df=7 * window))
    for noise_multiplier in noise_multipliers:
        sigma = base_sigma * float(noise_multiplier)
        for seed in seeds:
            rng = np.random.default_rng(seed + 1000 * int(10 * noise_multiplier))
            residual = deterministic_residual + rng.normal(
                0.0, sigma[:, None], size=deterministic_residual.shape
            )
            detected_at = math.nan
            for end in range(window, steps + 1):
                nis = float(
                    np.sum((residual[:, end - window + 1 : end + 1] / sigma[:, None]) ** 2)
                )
                if nis > threshold:
                    detected_at = 0.10 * end
                    break
            censored = math.isnan(detected_at)
            rows.append(
                {
                    "event": f"nominal_to_{actual_regime}",
                    "seed": seed,
                    "sg_level": "scarce",
                    "noise_multiplier": noise_multiplier,
                    "detection_delay_s": detected_at,
                    "censored": censored,
                    "Tcritical_s": critical_time_s,
                    "detected_before_critical": bool(
                        not censored
                        and not math.isnan(critical_time_s)
                        and detected_at <= critical_time_s
                    ),
                    "source_confusion": "not_evaluated_in_best_case_same_load_detector",
                    "information_gramian": gramian,
                    "detector_scope": "best_case_same_load_counterfactual",
                }
            )
    summary = {
        "event": f"nominal_to_{actual_regime}",
        "information_gramian": gramian,
        "pairwise_predictive_divergence": float(
            np.mean((deterministic_residual / VISIBLE_SCALE[:, None]) ** 2)
        ),
        "threshold": threshold,
    }
    return rows, summary


__all__ = [
    "ControlDistanceWeights",
    "block_quality_cost",
    "candidate_set_minimizer",
    "control_relevant_distance_rows",
    "critical_window",
    "passive_detection_rows",
    "registered_candidate_actions",
    "rollout_expected_block",
    "visible_output",
]
