"""Compact scientific audit computations evaluated inside Phase-B1 episodes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray

from d5freq.identification.arx import open_loop_arx_rollout, predict_arx_next
from d5freq.identification.model_library import ModeLibrary
from d5freq.models.grid_frequency import GRID_STATE_SIZE, GridFrequencyModel, GridStateIndex
from d5freq.models.hidden_mode_ibr import IBRModeParams, resolve_delay_s


FloatArray = NDArray[np.float64]
AUDIT_SCHEMA_VERSION = "d5freq.phase_b1.compact_episode_audits.v1"


def information_gramian(regressors: ArrayLike) -> tuple[FloatArray, float, float]:
    values = np.asarray(regressors, dtype=float)
    if values.ndim != 2 or values.shape[0] == 0 or values.shape[1] == 0:
        raise ValueError("regressors must be a non-empty matrix")
    if not np.all(np.isfinite(values)):
        raise ValueError("regressors must be finite")
    gramian = values.T @ values
    eigenvalues = np.linalg.eigvalsh(gramian)
    minimum = max(0.0, float(eigenvalues[0]))
    maximum = max(0.0, float(eigenvalues[-1]))
    condition = math.inf if minimum == 0.0 else maximum / minimum
    return gramian, minimum, condition


def gaussian_jsd(
    mean_a: float,
    variance_a: float,
    mean_b: float,
    variance_b: float,
    *,
    grid_size: int = 201,
) -> float:
    """Numerically integrate Jensen-Shannon divergence for two 1-D Gaussians."""

    if grid_size < 51 or grid_size % 2 == 0:
        raise ValueError("grid_size must be an odd integer of at least 51")
    if variance_a <= 0.0 or variance_b <= 0.0:
        raise ValueError("Gaussian variances must be positive")
    std_a = math.sqrt(variance_a)
    std_b = math.sqrt(variance_b)
    lower = min(mean_a - 8.0 * std_a, mean_b - 8.0 * std_b)
    upper = max(mean_a + 8.0 * std_a, mean_b + 8.0 * std_b)
    grid = np.linspace(lower, upper, grid_size)
    p = np.exp(-0.5 * np.square((grid - mean_a) / std_a)) / (
        math.sqrt(2.0 * math.pi) * std_a
    )
    q = np.exp(-0.5 * np.square((grid - mean_b) / std_b)) / (
        math.sqrt(2.0 * math.pi) * std_b
    )
    mixture = 0.5 * (p + q)
    tiny = np.finfo(float).tiny
    integrand = 0.5 * (
        p * np.log(np.maximum(p, tiny) / np.maximum(mixture, tiny))
        + q * np.log(np.maximum(q, tiny) / np.maximum(mixture, tiny))
    )
    value = float(np.trapezoid(integrand, grid))
    return min(math.log(2.0), max(0.0, value))


def _truth_at_control_samples(data: object) -> dict[str, Any]:
    measurements = tuple(getattr(data, "measurements"))
    actions = tuple(getattr(data, "actions"))
    truth_points = tuple(getattr(data, "truth_points_eval_only"))
    if len(measurements) < 3 or len(actions) + 1 != len(measurements):
        raise ValueError("episode lacks a complete control-rate trajectory")
    by_time: dict[float, Mapping[str, Any]] = {}
    for point in truth_points:
        by_time[round(float(point["time_s"]), 10)] = point
    selected: list[Mapping[str, Any]] = []
    for measurement in measurements:
        try:
            selected.append(by_time[round(float(measurement.time_s), 10)])
        except KeyError as exc:
            raise ValueError("truth trace lacks a controller sample time") from exc
    last_action = actions[-1]
    u_sg = np.asarray(
        [action.u_sg_pu for action in actions] + [last_action.u_sg_pu], dtype=float
    )
    u_ibr = np.asarray(
        [action.u_ibr_pu for action in actions] + [last_action.u_ibr_pu], dtype=float
    )
    return {
        "time": np.asarray([point["time_s"] for point in selected], dtype=float),
        "omega": np.asarray([point["omega_true_pu"] for point in selected], dtype=float),
        "p_mech": np.asarray([point["p_mech_true_pu"] for point in selected], dtype=float),
        "p_ibr": np.asarray([point["p_ibr_true_pu"] for point in selected], dtype=float),
        "load": np.asarray([point["load_disturbance_pu"] for point in selected], dtype=float),
        "rocof": np.asarray([point["rocof_true_hz_per_s"] for point in selected], dtype=float),
        "mode": np.asarray([str(point["true_mode_eval_only"]) for point in selected], dtype=object),
        "u_sg": u_sg,
        "u_ibr": u_ibr,
        "measurements": measurements,
    }


def _summarize_errors(
    values: Sequence[float],
    *,
    base: Mapping[str, Any],
) -> dict[str, Any]:
    array = np.asarray(values, dtype=float)
    if array.size == 0:
        return {
            **base,
            "sample_count": 0,
            "rmse": None,
            "mae": None,
            "q95_abs_error": None,
            "max_abs_error": None,
        }
    return {
        **base,
        "sample_count": int(array.size),
        "rmse": float(np.sqrt(np.mean(np.square(array)))),
        "mae": float(np.mean(np.abs(array))),
        "q95_abs_error": float(np.quantile(np.abs(array), 0.95)),
        "max_abs_error": float(np.max(np.abs(array))),
    }


def exact_vs_arx_episode_rows(
    data: object,
    *,
    grid_model: GridFrequencyModel,
    arx_models_by_true_mode_eval_only: Mapping[str, object],
    mode_params_eval_only: Mapping[str, IBRModeParams],
    sg_level: str,
    horizons: Sequence[int] = (1, 5, 10, 20),
) -> list[dict[str, Any]]:
    """Return power/frequency/RoCoF rolling-origin errors by true mode."""

    samples = _truth_at_control_samples(data)
    p = samples["p_ibr"]
    u_ibr = samples["u_ibr"]
    u_sg = samples["u_sg"]
    omega = samples["omega"]
    p_mech = samples["p_mech"]
    load = samples["load"]
    rocof = samples["rocof"]
    modes = samples["mode"]
    dt = grid_model.params.control_period_s
    p_mech_derivative = np.gradient(p_mech, dt)
    p_valve = p_mech + grid_model.params.T_t_s * p_mech_derivative
    A_d, B_d, E_d, _ = grid_model.discrete_matrices()
    errors: dict[tuple[str, int, str, str], list[float]] = {}
    availability: dict[str, bool] = {}
    for mode in sorted(set(str(value) for value in modes)):
        availability[mode] = mode in arx_models_by_true_mode_eval_only
    for horizon in tuple(int(value) for value in horizons):
        for origin in range(1, len(p) - horizon):
            mode = str(modes[origin])
            if not np.all(modes[origin : origin + horizon + 1] == mode):
                continue
            model = arx_models_by_true_mode_eval_only.get(mode)
            if model is None:
                continue
            params = mode_params_eval_only[mode]
            window = slice(origin, origin + horizon + 1)
            power_window = p[window]
            rate_window = np.diff(power_window) / dt
            saturation_active = bool(
                np.any(power_window >= params.p_max_pos_pu - 5.0e-4)
                or np.any(power_window <= -params.p_max_neg_pu + 5.0e-4)
            )
            rate_active = bool(
                np.any(rate_window >= 0.95 * params.ramp_up_pu_per_s)
                or np.any(rate_window <= -0.95 * params.ramp_down_pu_per_s)
            )
            deadband_active = False
            delayed_command_differs = False
            for index in range(origin, origin + horizon + 1):
                query = samples["time"][index] - resolve_delay_s(
                    params, samples["time"][index]
                )
                prior = int(
                    max(
                        0,
                        np.searchsorted(samples["time"], query, side="right") - 1,
                    )
                )
                delayed_command = u_ibr[prior]
                deadband_active |= abs(delayed_command) <= params.deadband_pu
                delayed_command_differs |= (
                    abs(delayed_command - u_ibr[index]) > 1.0e-12
                )
            constraint_regime = (
                "active"
                if saturation_active
                or rate_active
                or deadband_active
                or delayed_command_differs
                else "inactive"
            )
            predicted_power = open_loop_arx_rollout(
                getattr(model, "theta"),
                p_k=p[origin],
                p_k_minus_1=p[origin - 1],
                u_k_minus_1=u_ibr[origin - 1],
                omega_k_minus_1=omega[origin - 1],
                future_u_ibr_pu=u_ibr[origin : origin + horizon],
                future_omega_pu=omega[origin : origin + horizon],
            )
            power_error = float(p[origin + horizon] - predicted_power[-1])
            state = np.array(
                [
                    omega[origin],
                    p_mech[origin],
                    p_valve[origin],
                    0.0,
                    load[origin],
                ],
                dtype=float,
            )
            prior_frequency = grid_model.params.f0_hz * state[GridStateIndex.OMEGA_PU]
            predicted_rocof = 0.0
            for lead in range(horizon):
                state = (
                    A_d @ state
                    + B_d[:, 0] * u_sg[origin + lead]
                    + E_d[:, 0] * predicted_power[lead]
                )
                current_frequency = (
                    grid_model.params.f0_hz * state[GridStateIndex.OMEGA_PU]
                )
                predicted_rocof = (current_frequency - prior_frequency) / dt
                prior_frequency = current_frequency
            actual_frequency = grid_model.params.f0_hz * omega[origin + horizon]
            frequency_error = float(actual_frequency - prior_frequency)
            rocof_error = float(rocof[origin + horizon] - predicted_rocof)
            for regime in ("all", constraint_regime):
                errors.setdefault((mode, horizon, "ibr_power_pu", regime), []).append(
                    power_error
                )
                errors.setdefault((mode, horizon, "frequency_hz", regime), []).append(
                    frequency_error
                )
                errors.setdefault((mode, horizon, "rocof_hz_per_s", regime), []).append(
                    rocof_error
                )
    rows: list[dict[str, Any]] = []
    identity = getattr(data, "identity")
    for mode in sorted(availability):
        if not availability[mode]:
            for horizon in horizons:
                for metric in ("ibr_power_pu", "frequency_hz", "rocof_hz_per_s"):
                    for regime in ("all", "active", "inactive"):
                        rows.append(
                            _summarize_errors(
                                (),
                                base={
                                    "schema_version": AUDIT_SCHEMA_VERSION,
                                    "run_id": identity.run_id,
                                    "scenario_id": identity.scenario_id,
                                    "seed": identity.seed,
                                    "sg_level": sg_level,
                                    "true_mode": mode,
                                    "horizon_steps": int(horizon),
                                    "metric": metric,
                                    "constraint_regime": regime,
                                    "arx_available": False,
                                },
                            )
                        )
            continue
        for horizon in horizons:
            for metric in ("ibr_power_pu", "frequency_hz", "rocof_hz_per_s"):
                for regime in ("all", "active", "inactive"):
                    rows.append(
                        _summarize_errors(
                            errors.get((mode, int(horizon), metric, regime), ()),
                            base={
                                "schema_version": AUDIT_SCHEMA_VERSION,
                                "run_id": identity.run_id,
                                "scenario_id": identity.scenario_id,
                                "seed": identity.seed,
                                "sg_level": sg_level,
                                "true_mode": mode,
                                "horizon_steps": int(horizon),
                                "metric": metric,
                                "constraint_regime": regime,
                                "arx_available": True,
                            },
                        )
                    )
    return rows


def constraint_activation_episode_rows(
    data: object,
    *,
    mode_params_eval_only: Mapping[str, IBRModeParams],
    sg_level: str,
) -> list[dict[str, Any]]:
    samples = _truth_at_control_samples(data)
    rows: list[dict[str, Any]] = []
    identity = getattr(data, "identity")
    time = samples["time"]
    dt = float(np.median(np.diff(time)))
    for mode in sorted(set(str(value) for value in samples["mode"])):
        params = mode_params_eval_only[mode]
        indices = np.flatnonzero(samples["mode"] == mode)
        if not indices.size:
            continue
        power = samples["p_ibr"][indices]
        rate = np.gradient(samples["p_ibr"], dt)[indices]
        delayed_diff: list[bool] = []
        deadband_active: list[bool] = []
        for index in indices:
            query = time[index] - resolve_delay_s(params, time[index])
            prior = int(max(0, np.searchsorted(time, query, side="right") - 1))
            delayed = samples["u_ibr"][prior]
            delayed_diff.append(abs(delayed - samples["u_ibr"][index]) > 1.0e-12)
            deadband_active.append(abs(delayed) <= params.deadband_pu)
        rows.append(
            {
                "schema_version": AUDIT_SCHEMA_VERSION,
                "run_id": identity.run_id,
                "scenario_id": identity.scenario_id,
                "seed": identity.seed,
                "sg_level": sg_level,
                "true_mode": mode,
                "sample_count": int(indices.size),
                "positive_saturation_fraction": float(
                    np.mean(power >= params.p_max_pos_pu - 5.0e-4)
                ),
                "negative_saturation_fraction": float(
                    np.mean(power <= -params.p_max_neg_pu + 5.0e-4)
                ),
                "ramp_up_activation_fraction": float(
                    np.mean(rate >= 0.95 * params.ramp_up_pu_per_s)
                ),
                "ramp_down_activation_fraction": float(
                    np.mean(rate <= -0.95 * params.ramp_down_pu_per_s)
                ),
                "deadband_activation_fraction": float(np.mean(deadband_active)),
                "delayed_command_differs_fraction": float(np.mean(delayed_diff)),
                "fixed_or_mean_delay_s": float(
                    np.mean([resolve_delay_s(params, value) for value in time[indices]])
                ),
            }
        )
    return rows


def _semantic_log_likelihoods(
    samples: Mapping[str, Any],
    library: ModeLibrary,
    component_to_semantic_eval_only: Mapping[int, str],
    measurement_variance_pu2: float,
) -> tuple[list[str], FloatArray, FloatArray]:
    semantics = sorted(set(component_to_semantic_eval_only.values()))
    semantic_index = {name: index for index, name in enumerate(semantics)}
    count = len(samples["p_ibr"]) - 2
    log_likelihood = np.full((count, len(semantics)), -math.inf, dtype=float)
    predictions = np.zeros((count, len(library.models)), dtype=float)
    component_ll = np.zeros_like(predictions)
    for row, k in enumerate(range(1, len(samples["p_ibr"]) - 1)):
        for model in library.models:
            prediction = predict_arx_next(
                model.theta,
                p_k=samples["p_ibr"][k],
                p_k_minus_1=samples["p_ibr"][k - 1],
                u_k=samples["u_ibr"][k],
                u_k_minus_1=samples["u_ibr"][k - 1],
                omega_k=samples["omega"][k],
                omega_k_minus_1=samples["omega"][k - 1],
            )
            variance = model.residual_variance + measurement_variance_pu2
            residual = samples["p_ibr"][k + 1] - prediction
            predictions[row, model.component_id] = prediction
            component_ll[row, model.component_id] = -0.5 * (
                math.log(2.0 * math.pi * variance) + residual * residual / variance
            )
        for semantic in semantics:
            components = [
                component
                for component, label in component_to_semantic_eval_only.items()
                if label == semantic
            ]
            values = component_ll[row, components]
            maximum = float(np.max(values))
            log_likelihood[row, semantic_index[semantic]] = (
                maximum + math.log(float(np.mean(np.exp(values - maximum))))
            )
    return semantics, log_likelihood, predictions


def passive_identifiability_episode_rows(
    data: object,
    *,
    bayes_candidate_library_eval_only: ModeLibrary,
    bayes_component_to_semantic_eval_only: Mapping[int, str],
    diagnostic_component_to_semantic_eval_only: Mapping[int, str],
    sg_level: str,
    windows_s: Sequence[float] = (2.0, 5.0, 10.0, 20.0),
    eigenvalue_threshold: float = 1.0e-8,
    condition_threshold: float = 1.0e10,
    likelihood_margin_threshold: float = 2.0,
    measurement_variance_pu2: float = 4.0e-8,
    gramian_time_bin_s: float = 5.0,
) -> dict[str, list[dict[str, Any]]]:
    samples = _truth_at_control_samples(data)
    identity = getattr(data, "identity")
    scenario = getattr(data, "scenario")
    dt = float(np.median(np.diff(samples["time"])))
    regressors = np.column_stack(
        (
            samples["p_ibr"][1:-1],
            samples["p_ibr"][:-2],
            samples["u_ibr"][1:-1],
            samples["u_ibr"][:-2],
            samples["omega"][1:-1],
            samples["omega"][:-2],
            np.ones(len(samples["p_ibr"]) - 2),
        )
    )
    semantics, log_likelihood, predictions = _semantic_log_likelihoods(
        samples,
        bayes_candidate_library_eval_only,
        bayes_component_to_semantic_eval_only,
        measurement_variance_pu2,
    )
    semantic_index = {name: index for index, name in enumerate(semantics)}
    information_rows: list[dict[str, Any]] = []
    for window_s in windows_s:
        length = max(1, int(round(float(window_s) / dt)))
        minimum_eigenvalues: list[float] = []
        conditions: list[float] = []
        for end in range(length, len(regressors) + 1):
            _, minimum, condition = information_gramian(regressors[end - length : end])
            minimum_eigenvalues.append(minimum)
            conditions.append(condition)
        eigen = np.asarray(minimum_eigenvalues, dtype=float)
        condition = np.asarray(conditions, dtype=float)
        insufficient = (eigen < eigenvalue_threshold) | (condition > condition_threshold)
        end_times = samples["time"][2:][length - 1 :]
        if len(end_times) != len(eigen):
            raise RuntimeError("Gramian end times and rolling windows are misaligned")
        bin_indices = np.floor(end_times / float(gramian_time_bin_s)).astype(int)
        for bin_index in sorted(set(bin_indices.tolist())):
            selected = bin_indices == bin_index
            eigen_bin = eigen[selected]
            condition_bin = condition[selected]
            insufficient_bin = insufficient[selected]
            finite_condition = condition_bin[np.isfinite(condition_bin)]
            information_rows.append(
                {
                "schema_version": AUDIT_SCHEMA_VERSION,
                "run_id": identity.run_id,
                "scenario_id": identity.scenario_id,
                "seed": identity.seed,
                "sg_level": sg_level,
                "window_s": float(window_s),
                "time_bin_start_s": float(bin_index * gramian_time_bin_s),
                "time_bin_end_s": float((bin_index + 1) * gramian_time_bin_s),
                "window_count": int(eigen_bin.size),
                "min_eigenvalue_min": float(np.min(eigen_bin)),
                "min_eigenvalue_median": float(np.median(eigen_bin)),
                "condition_median_finite": (
                    None if not finite_condition.size else float(np.median(finite_condition))
                ),
                "condition_q95_finite": (
                    None
                    if not finite_condition.size
                    else float(np.quantile(finite_condition, 0.95))
                ),
                "singular_gramian_ratio": (
                    float(np.mean(~np.isfinite(condition_bin)))
                ),
                "information_insufficient_ratio": (
                    float(np.mean(insufficient_bin))
                ),
                }
            )

    pairwise_rows: list[dict[str, Any]] = []
    delay_rows: list[dict[str, Any]] = []
    records = tuple(getattr(data, "controller_records", ()))
    semantic_beliefs: list[dict[str, float]] = []
    for record in records:
        belief: dict[str, float] = {name: 0.0 for name in semantics}
        for component, semantic in diagnostic_component_to_semantic_eval_only.items():
            key = f"belief_{component}"
            if key in record:
                belief.setdefault(semantic, 0.0)
                belief[semantic] += float(record[key])
        semantic_beliefs.append(belief)

    for switch in getattr(scenario.mode_schedule, "switches", ()):
        target = str(switch.mode)
        prior = str(scenario.mode_schedule.mode_at(np.nextafter(switch.time_s, 0.0)))
        start = int(round(switch.time_s / dt))
        detected_index: int | None = None
        for index in range(start, max(start, len(semantic_beliefs) - 2)):
            if all(
                semantic_beliefs[index + offset].get(target, 0.0) >= 0.8
                for offset in range(3)
            ):
                detected_index = index + 2
                break
        common_delay = {
                "schema_version": AUDIT_SCHEMA_VERSION,
                "run_id": identity.run_id,
                "scenario_id": identity.scenario_id,
                "seed": identity.seed,
                "sg_level": sg_level,
                "switch_time_s": float(switch.time_s),
                "from_mode": prior,
                "to_mode": target,
                "candidate_set_contains_truth": target in semantic_index,
        }
        delay_rows.append(
            {
                **common_delay,
                "classifier": "current_native_diagnostic",
                "detection_delay_s": (
                    None if detected_index is None else detected_index * dt - switch.time_s
                ),
                "detection_censored": detected_index is None,
                "censoring_time_s": (
                    max(0.0, samples["time"][-1] - switch.time_s)
                    if detected_index is None
                    else None
                ),
            }
        )
        bayes_detected_index: int | None = None
        if target in semantic_index:
            target_index = semantic_index[target]
            ll_start = max(0, start - 1)
            running = np.cumsum(log_likelihood[ll_start:], axis=0)
            shifted = running - np.max(running, axis=1, keepdims=True)
            posterior_sequence = np.exp(shifted)
            posterior_sequence /= np.sum(posterior_sequence, axis=1, keepdims=True)
            for offset in range(max(0, len(posterior_sequence) - 2)):
                if np.all(posterior_sequence[offset : offset + 3, target_index] >= 0.8):
                    bayes_detected_index = ll_start + offset + 2
                    break
        delay_rows.append(
            {
                **common_delay,
                "classifier": "evaluation_only_bayes_correct_candidates",
                "detection_delay_s": (
                    None
                    if bayes_detected_index is None
                    else bayes_detected_index * dt - switch.time_s
                ),
                "detection_censored": bayes_detected_index is None,
                "censoring_time_s": (
                    max(0.0, samples["time"][-1] - switch.time_s)
                    if bayes_detected_index is None
                    else None
                ),
            }
        )
        ll_start = max(0, start - 1)
        for window_s in windows_s:
            length = int(round(float(window_s) / dt))
            stop = min(log_likelihood.shape[0], ll_start + length)
            if stop <= ll_start or target not in semantic_index:
                continue
            summed = np.sum(log_likelihood[ll_start:stop], axis=0)
            target_index = semantic_index[target]
            alternatives = [index for index in range(len(semantics)) if index != target_index]
            margin = float(summed[target_index] - np.max(summed[alternatives]))
            shifted = summed - np.max(summed)
            posterior = np.exp(shifted) / np.sum(np.exp(shifted))
            best_alternative = alternatives[int(np.argmax(summed[alternatives]))]
            components_target = [
                component
                for component, semantic in bayes_component_to_semantic_eval_only.items()
                if semantic == target
            ]
            components_alt = [
                component
                for component, semantic in bayes_component_to_semantic_eval_only.items()
                if semantic == semantics[best_alternative]
            ]
            jsd_values: list[float] = []
            for row in range(ll_start, stop):
                comp_target = max(components_target, key=lambda c: -abs(predictions[row, c] - samples["p_ibr"][row + 2]))
                comp_alt = max(components_alt, key=lambda c: -abs(predictions[row, c] - samples["p_ibr"][row + 2]))
                model_target = bayes_candidate_library_eval_only.models[comp_target]
                model_alt = bayes_candidate_library_eval_only.models[comp_alt]
                jsd_values.append(
                    gaussian_jsd(
                        predictions[row, comp_target],
                        model_target.residual_variance + measurement_variance_pu2,
                        predictions[row, comp_alt],
                        model_alt.residual_variance + measurement_variance_pu2,
                        grid_size=101,
                    )
                )
            pairwise_rows.append(
                {
                    "schema_version": AUDIT_SCHEMA_VERSION,
                    "run_id": identity.run_id,
                    "scenario_id": identity.scenario_id,
                    "seed": identity.seed,
                    "sg_level": sg_level,
                    "switch_time_s": float(switch.time_s),
                    "true_mode": target,
                    "hardest_alternative": semantics[best_alternative],
                    "window_s": float(window_s),
                    "predictive_log_likelihood_margin": margin,
                    "mean_pairwise_jsd": float(np.mean(jsd_values)),
                    "posterior_true_mode": float(posterior[target_index]),
                    "bayes_correct": int(np.argmax(posterior)) == target_index,
                    "likelihood_information_insufficient": margin < likelihood_margin_threshold,
                }
            )

    source_rows: list[dict[str, Any]] = []
    event_times = sorted(
        set(float(event.start_time_s) for event in scenario.disturbance.events)
        | set(float(switch.time_s) for switch in scenario.mode_schedule.switches)
    )
    load_times = {float(event.start_time_s) for event in scenario.disturbance.events}
    mode_times = {float(switch.time_s) for switch in scenario.mode_schedule.switches}
    for event_time in event_times:
        source = (
            "coincident"
            if event_time in load_times and event_time in mode_times
            else ("load_only" if event_time in load_times else "mode_only")
        )
        start = int(round(event_time / dt))
        pre_mode = str(scenario.mode_schedule.mode_at(np.nextafter(event_time, 0.0)))
        true_after = str(scenario.mode_schedule.mode_at(event_time))
        map_sequence = [
            max(row, key=row.get) if row else "unavailable"
            for row in semantic_beliefs[start : min(len(semantic_beliefs), start + int(20.0 / dt))]
        ]
        declared_change = any(
            all(value != pre_mode for value in map_sequence[index : index + 3])
            for index in range(max(0, len(map_sequence) - 2))
        )
        target_detected = any(
            all(value == true_after for value in map_sequence[index : index + 3])
            for index in range(max(0, len(map_sequence) - 2))
        )
        common_source = {
                "schema_version": AUDIT_SCHEMA_VERSION,
                "run_id": identity.run_id,
                "scenario_id": identity.scenario_id,
                "seed": identity.seed,
                "sg_level": sg_level,
                "event_time_s": event_time,
                "true_source": source,
                "pre_mode": pre_mode,
                "true_mode_after": true_after,
                "candidate_set_contains_truth": true_after in semantic_index,
        }
        source_rows.append(
            {
                **common_source,
                "classifier": "current_native_diagnostic",
                "diagnostic_declared_mode_change": declared_change,
                "target_mode_detected_within_20s": target_detected,
                "false_mode_alarm_under_load": source == "load_only" and declared_change,
                "missed_mode_change": source in {"mode_only", "coincident"} and not target_detected,
            }
        )
        bayes_map_sequence: list[str] = []
        ll_start = max(0, start - 1)
        ll_stop = min(log_likelihood.shape[0], ll_start + int(20.0 / dt))
        if ll_stop > ll_start:
            running = np.cumsum(log_likelihood[ll_start:ll_stop], axis=0)
            bayes_map_sequence = [semantics[int(np.argmax(row))] for row in running]
        bayes_declared_change = any(
            all(value != pre_mode for value in bayes_map_sequence[index : index + 3])
            for index in range(max(0, len(bayes_map_sequence) - 2))
        )
        bayes_target_detected = any(
            all(value == true_after for value in bayes_map_sequence[index : index + 3])
            for index in range(max(0, len(bayes_map_sequence) - 2))
        )
        source_rows.append(
            {
                **common_source,
                "classifier": "evaluation_only_bayes_correct_candidates",
                "diagnostic_declared_mode_change": bayes_declared_change,
                "target_mode_detected_within_20s": bayes_target_detected,
                "false_mode_alarm_under_load": (
                    source == "load_only" and bayes_declared_change
                ),
                "missed_mode_change": (
                    source in {"mode_only", "coincident"} and not bayes_target_detected
                ),
            }
        )
    return {
        "information_gramian": information_rows,
        "pairwise_separation": pairwise_rows,
        "identifiability_delay": delay_rows,
        "source_confusion": source_rows,
    }


__all__ = [
    "AUDIT_SCHEMA_VERSION",
    "constraint_activation_episode_rows",
    "exact_vs_arx_episode_rows",
    "gaussian_jsd",
    "information_gramian",
    "passive_identifiability_episode_rows",
]
