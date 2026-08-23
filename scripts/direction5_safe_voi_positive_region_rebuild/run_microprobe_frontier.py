"""Development frontier for the narrow safe micro-probe region.

The calculation reuses the frozen linear prediction model to isolate one
scientific mechanism: a two-sample allocation-neutral probe identifies the
delay group, after which the remaining MPC is still robust to power and ramp.
Safety is checked over all eight capability vertices.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
from scipy.stats import norm


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scratch_direction5_voi_boundary"))

import voi_boundary_engine as frozen  # noqa: E402


def point() -> frozen.BoundaryPoint:
    return frozen.BoundaryPoint(
        point_id="R1_MICROPROBE_FRONTIER",
        period_s=2.0,
        sg_tension="medium",
        load_magnitude_pu=0.015,
        power_spread_pu=0.020674,
        ramp_spread_pu_per_s=0.027353,
        delay_spread_s=1.095263,
        noise_std_pu=0.001410,
        soc=0.382124,
        tie_loading_pu=0.037153,
        objective="regional_responsibility",
    )


def delay_group_value(
    item: frozen.BoundaryPoint,
    models: tuple[frozen.CapabilityModel, ...],
    baseline: frozen.PolicySolution,
    prefix: frozen.FixedPrefix,
    probe: frozen.Probe,
    scales: frozen.ObjectiveScales,
    horizon_steps: int,
) -> tuple[float, int]:
    remaining = horizon_steps - len(probe.sequence_pu)
    worst = -float("inf")
    failures = 0
    for truth in models:
        posterior = tuple(
            candidate
            for candidate in models
            if np.isclose(candidate.delay_s, truth.delay_s)
        )
        recourse = frozen.solve_policy(
            item,
            posterior,
            horizon_steps=remaining,
            initial_grid_state=prefix.states[truth.model_id][:, -1],
            initial_bess_power=prefix.bess_power[truth.model_id][:, -1],
            previous_sg_command=prefix.sg_command[:, -1],
            previous_bess_command=prefix.bess_command[:, -1],
            initial_energy_mwh=prefix.energy_mwh[truth.model_id][:, -1],
            scales=scales,
        )
        failures += int(not np.isfinite(recourse.objective))
        worst = max(
            worst,
            prefix.prefix_cost[truth.model_id] + recourse.objective,
        )
    return float(baseline.objective - worst), failures


def main() -> None:
    item = point()
    models = frozen.candidate_models(item)
    scales = frozen.objective_scales(item.objective)
    horizon_steps = 12
    baseline = frozen.solve_policy(
        item,
        models,
        horizon_steps=horizon_steps,
        initial_grid_state=frozen.initial_state(item),
        scales=scales,
    )
    sigma = float(np.hypot(item.noise_std_pu, 2.5e-4 / np.sqrt(3.0)))
    rows = []
    for amplitude in (0.0, 0.00050, 0.00052, 0.00055, 0.00058, 0.00062):
        probe = frozen.Probe(
            probe_id=f"delay_micro_4s_{amplitude:.5f}",
            duration_s=4.0,
            amplitude_pu=amplitude,
            shape="biphasic",
            area=0,
            sign=1,
            sequence_pu=(amplitude, -amplitude),
        )
        prefix = frozen._fixed_prefix(item, models, baseline, probe, scales)
        if not prefix.safe:
            rows.append({"amplitude_pu": amplitude, "safe": False, "reason": prefix.reason})
            continue
        delay_centers = []
        for delay in sorted({candidate.delay_s for candidate in models}):
            traces = [
                prefix.bess_power[candidate.model_id][:, 1:].T.ravel()
                for candidate in models
                if np.isclose(candidate.delay_s, delay)
            ]
            delay_centers.append(np.mean(traces, axis=0))
        separation_sigma = float(
            np.linalg.norm(delay_centers[0] - delay_centers[1]) / sigma
        )
        equal_prior_classification_error = float(norm.cdf(-0.5 * separation_sigma))
        upper = frozen.evaluate_probe_upper(
            item,
            models,
            baseline,
            probe,
            horizon_steps=horizon_steps,
            scales=scales,
        )
        grouped_value, grouped_failures = delay_group_value(
            item,
            models,
            baseline,
            prefix,
            probe,
            scales,
            horizon_steps,
        )
        rows.append({
            "amplitude_pu": amplitude,
            "probe_kind": "passive_contract_trace" if amplitude == 0.0 else "active_microprobe",
            "safe": True,
            "delay_separation_sigma": separation_sigma,
            "equal_prior_delay_error": equal_prior_classification_error,
            "perfect_posterior_upper_value": upper.upper_value,
            "perfect_delay_group_value": grouped_value,
            "posterior_group_size": len(models) // 2,
            "solver_failures": upper.solver_failures + grouped_failures,
        })
    print(json.dumps({
        "point_id": item.point_id,
        "baseline_cost": baseline.objective,
        "rows": rows,
    }, indent=2))


if __name__ == "__main__":
    main()
