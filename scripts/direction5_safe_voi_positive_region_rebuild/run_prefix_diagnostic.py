"""Measure the acquisition cost of smaller probes on the frozen top-VPI point.

This is a development diagnostic, not the successor value formulation.  It
reuses the frozen linear boundary model only to determine whether the old
no-probe result was dominated by probe safety, probe cost, or information value.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scratch_direction5_voi_boundary"))

from voi_boundary_engine import (  # noqa: E402
    BoundaryPoint,
    Probe,
    candidate_models,
    evaluate_probe,
    evaluate_probe_upper,
    initial_state,
    objective_scales,
    solve_policy,
)

from direction5freq.voi_positive_region import registered_probe_library  # noqa: E402


def main() -> None:
    point = BoundaryPoint(
        point_id="R1_TOP_VPI_PREFIX_DIAGNOSTIC",
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
    models = candidate_models(point)
    scales = objective_scales(point.objective)
    horizon_steps = 12
    baseline = solve_policy(
        point,
        models,
        horizon_steps=horizon_steps,
        initial_grid_state=initial_state(point),
        scales=scales,
    )
    selected = [
        item
        for item in registered_probe_library(point.period_s)
        if item.shape == "biphasic"
        and item.physical_duration_s in {4.0, 8.0}
        and item.amplitude_pu in {0.0005, 0.0010, 0.0015, 0.0025}
    ]
    rows = []
    for item in selected:
        probe = Probe(
            probe_id=item.probe_id,
            duration_s=item.physical_duration_s,
            amplitude_pu=item.amplitude_pu,
            shape=item.shape,
            area=0,
            sign=1,
            sequence_pu=item.sequence_pu,
        )
        value = evaluate_probe_upper(
            point,
            models,
            baseline,
            probe,
            horizon_steps=horizon_steps,
            scales=scales,
        )
        row = {
            "probe_id": probe.probe_id,
            "safe": value.safe,
            "reason": value.reason,
            "upper_value": value.upper_value,
            "mean_posterior_reduction": value.mean_posterior_reduction,
            "maximum_posterior_size": value.maximum_posterior_size,
            "solver_failures": value.solver_failures,
        }
        if value.safe and value.upper_value > 0.0:
            exact = evaluate_probe(
                point,
                models,
                baseline,
                probe,
                horizon_steps=horizon_steps,
                scales=scales,
            )
            row.update(
                exact_value=exact.exact_value,
                probe_counterfactual_cost=exact.probe_counterfactual_cost,
                exact_reason=exact.reason,
                exact_solver_failures=exact.solver_failures,
            )
        rows.append(row)
    print(json.dumps({
        "point_id": point.point_id,
        "baseline_cost": baseline.objective,
        "probes": rows,
    }, indent=2))


if __name__ == "__main__":
    main()
