"""Test excitation that is aligned with the current regulation need.

The contract-safe SG command is left unchanged.  A short BESS surplus request
is issued only when the robust contract command is already close to the public
power floor.  Non-delivery therefore retains the contract trajectory, whereas
delivery helps the current load event and reveals headroom.
"""

from __future__ import annotations

from dataclasses import replace
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


def main() -> None:
    point = frozen.BoundaryPoint(
        "R1_CONTROL_ALIGNED_POWER_PROBE",
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
    steps = 6
    baseline = frozen.solve_policy(
        point,
        models,
        horizon_steps=steps,
        initial_grid_state=frozen.initial_state(point),
        scales=scales,
    )
    passive_probe = frozen.Probe(
        "passive", 24.0, 0.0, "passive", 0, 1, (0.0,) * steps
    )
    passive = frozen._fixed_prefix(point, models, baseline, passive_probe, scales)
    passive_metrics = {
        model.model_id: trajectory_metrics(
            passive.states[model.model_id][:, 1:],
            passive.sg_command,
            passive.bess_command,
            period_s=point.period_s,
            nominal_frequency_hz=point.nominal_frequency_hz,
        )
        for model in models
    }
    sigma = float(np.hypot(point.noise_std_pu, 2.5e-4 / np.sqrt(3.0)))
    rows = []
    classification_target_sigma = float(-2.0 * norm.ppf(0.01))
    for amplitude in (0.0020, 0.0025, 0.0030, 0.0035, 0.0040, 0.0045):
        sequence = np.asarray((0.0, 0.0, amplitude, amplitude, 0.0, 0.0))
        # _fixed_prefix normally subtracts q from SG.  Pre-adding q to its
        # reference leaves the applied SG command exactly at the contract-safe
        # baseline while still adding q to BESS.
        reference_sg = baseline.sg_command.copy()
        reference_sg[0] += sequence
        reference = replace(baseline, sg_command=reference_sg)
        probe = frozen.Probe(
            f"control_aligned_24s_{amplitude:.4f}",
            24.0,
            amplitude,
            "control_aligned_surplus",
            0,
            1,
            tuple(float(value) for value in sequence),
        )
        prefix = frozen._fixed_prefix(point, models, reference, probe, scales)
        if not prefix.safe:
            rows.append({"amplitude_pu": amplitude, "safe": False, "reason": prefix.reason})
            continue
        centers = np.asarray([
            prefix.bess_power[model.model_id][:, 1:].T.ravel()
            for model in models
        ])
        distances = np.asarray([
            np.linalg.norm(centers[left] - centers[right]) / sigma
            for left, right in combinations(range(len(models)), 2)
        ])
        nonzero = distances[distances > 1e-10]
        minimum_distance = float(nonzero.min()) if len(nonzero) else 0.0
        probe_metrics = {
            model.model_id: trajectory_metrics(
                prefix.states[model.model_id][:, 1:],
                prefix.sg_command,
                prefix.bess_command,
                period_s=point.period_s,
                nominal_frequency_hz=point.nominal_frequency_hz,
            )
            for model in models
        }
        low_power = min(model.power_pu for model in models)
        low_delta = []
        high_delta = []
        for model in models:
            delta = (
                probe_metrics[model.model_id].grid_service_cost
                - passive_metrics[model.model_id].grid_service_cost
            )
            (low_delta if np.isclose(model.power_pu, low_power) else high_delta).append(delta)
        repeats_for_one_percent = (
            int(np.ceil((classification_target_sigma / minimum_distance) ** 2))
            if minimum_distance > 0.0 else None
        )
        mean_grid_change = float(np.mean(low_delta + high_delta))
        rows.append({
            "amplitude_pu": amplitude,
            "safe": True,
            "unique_response_centers": len(np.unique(np.round(centers, 12), axis=0)),
            "minimum_nonzero_pairwise_separation_sigma": minimum_distance,
            "nearest_pair_equal_prior_error": (
                float(norm.cdf(-0.5 * minimum_distance)) if minimum_distance else 0.5
            ),
            "independent_windows_for_one_percent_error": repeats_for_one_percent,
            "grid_cost_change_until_one_percent_error": (
                None if repeats_for_one_percent is None
                else repeats_for_one_percent * mean_grid_change
            ),
            "low_power_grid_cost_change_mean": float(np.mean(low_delta)),
            "high_power_grid_cost_change_mean": float(np.mean(high_delta)),
            "worst_grid_cost_change": float(max(low_delta + high_delta)),
            "best_grid_cost_change": float(min(low_delta + high_delta)),
            "incremental_sg_command_mileage_pu": (
                probe_metrics[models[0].model_id].sg_command_mileage_pu
                - passive_metrics[models[0].model_id].sg_command_mileage_pu
            ),
            "incremental_bess_command_mileage_pu": (
                probe_metrics[models[0].model_id].bess_command_mileage_pu
                - passive_metrics[models[0].model_id].bess_command_mileage_pu
            ),
            "maximum_frequency_peak_hz": float(max(
                metric.frequency_peak_hz for metric in probe_metrics.values()
            )),
        })
    print(json.dumps({
        "point_id": point.point_id,
        "baseline_bess_commands_pu": np.round(baseline.bess_command, 6).tolist(),
        "rows": rows,
    }, indent=2))


if __name__ == "__main__":
    main()
