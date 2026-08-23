"""Test causal probing when the contract command approaches its power floor."""

from __future__ import annotations

from itertools import combinations
import json
from pathlib import Path
import sys

import numpy as np
from scipy.stats import norm


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scratch_direction5_voi_boundary"))

import voi_boundary_engine as frozen  # noqa: E402
from direction5freq.voi_positive_region import trajectory_metrics  # noqa: E402


def realized_cost(
    point: frozen.BoundaryPoint,
    solution: frozen.PolicySolution,
    model: frozen.CapabilityModel,
    scales: frozen.ObjectiveScales,
    previous_sg: np.ndarray | None = None,
    previous_bess: np.ndarray | None = None,
) -> float:
    prior_sg = np.zeros(2) if previous_sg is None else previous_sg.copy()
    prior_bess = np.zeros(2) if previous_bess is None else previous_bess.copy()
    states = solution.states[model.model_id]
    total = 0.0
    for step in range(solution.sg_command.shape[1]):
        sg = solution.sg_command[:, step]
        bess = solution.bess_command[:, step]
        total += frozen._numeric_stage_cost(
            states[:, step + 1], sg, bess, prior_sg, prior_bess,
            scales, point.period_s, point.nominal_frequency_hz,
        )
        prior_sg = sg
        prior_bess = bess
    total += 2.0 * frozen._numeric_stage_cost(
        states[:, -1], solution.sg_command[:, -1], solution.bess_command[:, -1],
        solution.sg_command[:, -1], solution.bess_command[:, -1],
        scales, point.period_s, point.nominal_frequency_hz,
    )
    return float(total)


def grid_metrics(
    point: frozen.BoundaryPoint,
    solution: frozen.PolicySolution,
    model: frozen.CapabilityModel,
    previous_sg: np.ndarray | None = None,
    previous_bess: np.ndarray | None = None,
):
    return trajectory_metrics(
        solution.states[model.model_id][:, 1:],
        solution.sg_command,
        solution.bess_command,
        period_s=point.period_s,
        nominal_frequency_hz=point.nominal_frequency_hz,
        previous_sg_command=previous_sg,
        previous_bess_command=previous_bess,
    )


def main() -> None:
    point = frozen.BoundaryPoint(
        "R1_BINDING_POWER_RAMP_PROBE",
        4.0,
        "medium",
        0.070091,
        0.022973,
        0.014259,
        0.0,
        0.001755,
        0.684096,
        0.011833,
        "resource_economy",
    )
    models = frozen.candidate_models(point)
    scales = frozen.objective_scales(point.objective)
    horizon_steps = 6
    baseline = frozen.solve_policy(
        point,
        models,
        horizon_steps=horizon_steps,
        initial_grid_state=frozen.initial_state(point),
        scales=scales,
    )
    baseline_expected = float(np.mean([
        realized_cost(point, baseline, model, scales) for model in models
    ]))
    baseline_grid_cost = np.asarray([
        grid_metrics(point, baseline, model).grid_service_cost for model in models
    ])
    singleton_costs = []
    for model in models:
        singleton = frozen.solve_policy(
            point,
            (model,),
            horizon_steps=horizon_steps,
            initial_grid_state=frozen.initial_state(point),
            scales=scales,
        )
        singleton_costs.append(singleton.objective)
    expected_perfect_information_value = float(
        baseline_expected - np.mean(singleton_costs)
    )
    sigma = float(np.hypot(point.noise_std_pu, 2.5e-4 / np.sqrt(3.0)))
    zero_probe = frozen.Probe(
        "passive", 24.0, 0.0, "passive", 0, 1, (0.0,) * horizon_steps,
    )
    zero_prefix = frozen._fixed_prefix(point, models, baseline, zero_probe, scales)
    zero_prefix_expected = float(np.mean(list(zero_prefix.prefix_cost.values())))
    zero_grid_metrics = [
        trajectory_metrics(
            zero_prefix.states[model.model_id][:, 1:],
            zero_prefix.sg_command,
            zero_prefix.bess_command,
            period_s=point.period_s,
            nominal_frequency_hz=point.nominal_frequency_hz,
        )
        for model in models
    ]
    rows = []
    for amplitude in (0.0, 0.0025, 0.0050, 0.0075, 0.0100):
        sequence = (0.0, 0.0, amplitude, amplitude, -amplitude, -amplitude)
        probe = frozen.Probe(
            f"binding_24s_{amplitude:.4f}", 24.0, amplitude,
            "delayed_biphasic", 0, 1, sequence,
        )
        prefix = frozen._fixed_prefix(point, models, baseline, probe, scales)
        if not prefix.safe:
            rows.append({"amplitude_pu": amplitude, "safe": False, "reason": prefix.reason})
            continue
        centers = np.asarray([
            prefix.bess_power[model.model_id][:, 1:].T.ravel() for model in models
        ])
        pair_distance = {
            (left, right): float(np.linalg.norm(centers[left] - centers[right]) / sigma)
            for left, right in combinations(range(len(models)), 2)
        }
        distances = np.asarray(list(pair_distance.values()))
        nonzero = distances[distances > 1e-10]
        unique_centers = len(np.unique(np.round(centers, 12), axis=0))
        minimum_distance = float(nonzero.min()) if len(nonzero) else 0.0
        pairwise_error_bound = float(norm.cdf(-0.5 * minimum_distance)) if minimum_distance else 0.5

        # Merge hypotheses that cannot be separated with a union-bound error
        # below one percent.  This is conservative for development screening.
        threshold = float(-2.0 * norm.ppf(0.01 / max(1, len(models) - 1)))
        parents = list(range(len(models)))

        def find(index: int) -> int:
            while parents[index] != index:
                parents[index] = parents[parents[index]]
                index = parents[index]
            return index

        def union(left: int, right: int) -> None:
            left_root = find(left)
            right_root = find(right)
            if left_root != right_root:
                parents[right_root] = left_root

        for (left, right), distance in pair_distance.items():
            if distance < threshold:
                union(left, right)
        groups: dict[int, list[int]] = {}
        for index in range(len(models)):
            groups.setdefault(find(index), []).append(index)

        grouped_event_costs = []
        grouped_grid_cost = np.zeros(len(models))
        failures = 0
        for indices in groups.values():
            candidates = tuple(models[index] for index in indices)
            group_policy = frozen.solve_policy(
                point,
                candidates,
                horizon_steps=horizon_steps,
                initial_grid_state=frozen.initial_state(point),
                scales=scales,
            )
            failures += int(not np.isfinite(group_policy.objective))
            for index in indices:
                grouped_event_costs.append(
                    realized_cost(point, group_policy, models[index], scales)
                )
                grouped_grid_cost[index] = grid_metrics(
                    point, group_policy, models[index]
                ).grid_service_cost
        grouped_event_value = float(
            baseline_expected - np.mean(grouped_event_costs)
        )
        acquisition_cost = float(
            np.mean(list(prefix.prefix_cost.values())) - zero_prefix_expected
        )
        probe_grid_metrics = [
            trajectory_metrics(
                prefix.states[model.model_id][:, 1:],
                prefix.sg_command,
                prefix.bess_command,
                period_s=point.period_s,
                nominal_frequency_hz=point.nominal_frequency_hz,
            )
            for model in models
        ]
        grid_acquisition_by_model = np.asarray([
            probe_metric.grid_service_cost - passive_metric.grid_service_cost
            for probe_metric, passive_metric in zip(
                probe_grid_metrics, zero_grid_metrics, strict=True
            )
        ])
        grid_event_benefit_by_model = baseline_grid_cost - grouped_grid_cost
        low_power = min(model.power_pu for model in models)
        high_indices = np.asarray([
            index for index, model in enumerate(models)
            if model.power_pu > low_power + 1e-12
        ], dtype=int)
        low_indices = np.asarray([
            index for index, model in enumerate(models)
            if model.power_pu <= low_power + 1e-12
        ], dtype=int)

        def prior_boundary(event_count: int) -> dict[str, float | None]:
            net = event_count * grid_event_benefit_by_model - grid_acquisition_by_model
            low = float(np.mean(net[low_indices]))
            high = float(np.mean(net[high_indices]))
            if high <= low:
                threshold_prior = None
            else:
                threshold_prior = float(np.clip(-low / (high - low), 0.0, 1.0))
            return {
                "low_power_mean_net": low,
                "high_power_mean_net": high,
                "break_even_high_power_prior": threshold_prior,
                "minimum_capability_net": float(np.min(net)),
            }

        rows.append({
            "amplitude_pu": amplitude,
            "safe": True,
            "unique_response_centers": unique_centers,
            "minimum_nonzero_pairwise_separation_sigma": minimum_distance,
            "nearest_pair_equal_prior_error": pairwise_error_bound,
            "one_percent_union_bound_separation_sigma": threshold,
            "confident_posterior_groups": len(groups),
            "maximum_confident_group_size": max(map(len, groups.values())),
            "expected_group_value_per_future_event": grouped_event_value,
            "probe_acquisition_cost": acquisition_cost,
            "lifetime_net_value_3_events": 3.0 * grouped_event_value - acquisition_cost,
            "lifetime_net_value_5_events": 5.0 * grouped_event_value - acquisition_cost,
            "lifetime_net_value_8_events": 8.0 * grouped_event_value - acquisition_cost,
            "grid_service_acquisition_cost_mean": float(np.mean(grid_acquisition_by_model)),
            "grid_service_acquisition_cost_range": [
                float(np.min(grid_acquisition_by_model)),
                float(np.max(grid_acquisition_by_model)),
            ],
            "grid_service_event_benefit_mean": float(np.mean(grid_event_benefit_by_model)),
            "grid_service_event_benefit_range": [
                float(np.min(grid_event_benefit_by_model)),
                float(np.max(grid_event_benefit_by_model)),
            ],
            "grid_prior_boundary_3_events": prior_boundary(3),
            "grid_prior_boundary_5_events": prior_boundary(5),
            "grid_prior_boundary_8_events": prior_boundary(8),
            "incremental_sg_command_mileage_pu": float(
                probe_grid_metrics[0].sg_command_mileage_pu
                - zero_grid_metrics[0].sg_command_mileage_pu
            ),
            "incremental_bess_command_mileage_pu": float(
                probe_grid_metrics[0].bess_command_mileage_pu
                - zero_grid_metrics[0].bess_command_mileage_pu
            ),
            "maximum_probe_frequency_peak_hz": float(max(
                metric.frequency_peak_hz for metric in probe_grid_metrics
            )),
            "solver_failures": failures,
        })
    print(json.dumps({
        "point_id": point.point_id,
        "baseline_expected_cost": baseline_expected,
        "expected_perfect_information_value_per_event": expected_perfect_information_value,
        "baseline_bess_commands_pu": np.round(baseline.bess_command, 6).tolist(),
        "rows": rows,
    }, indent=2))


if __name__ == "__main__":
    main()
