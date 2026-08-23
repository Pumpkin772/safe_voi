"""Compare predecessor worst-case VoI with the new expected operating value."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scratch_direction5_voi_boundary"))

import voi_boundary_engine as frozen  # noqa: E402


def realized_cost(
    point: frozen.BoundaryPoint,
    solution: frozen.PolicySolution,
    model: frozen.CapabilityModel,
    scales: frozen.ObjectiveScales,
) -> float:
    states = solution.states[model.model_id]
    total = 0.0
    previous_sg = np.zeros(2)
    previous_bess = np.zeros(2)
    for step in range(solution.sg_command.shape[1]):
        sg = solution.sg_command[:, step]
        bess = solution.bess_command[:, step]
        total += frozen._numeric_stage_cost(
            states[:, step + 1],
            sg,
            bess,
            previous_sg,
            previous_bess,
            scales,
            point.period_s,
            point.nominal_frequency_hz,
        )
        previous_sg = sg
        previous_bess = bess
    total += 2.0 * frozen._numeric_stage_cost(
        states[:, -1],
        solution.sg_command[:, -1],
        solution.bess_command[:, -1],
        solution.sg_command[:, -1],
        solution.bess_command[:, -1],
        scales,
        point.period_s,
        point.nominal_frequency_hz,
    )
    return float(total)


def evaluate(point: frozen.BoundaryPoint) -> dict[str, object]:
    models = frozen.candidate_models(point)
    scales = frozen.objective_scales(point.objective)
    steps = int(round(24.0 / point.period_s))
    robust = frozen.solve_policy(
        point,
        models,
        horizon_steps=steps,
        initial_grid_state=frozen.initial_state(point),
        scales=scales,
    )
    robust_realized = [realized_cost(point, robust, model, scales) for model in models]
    singleton_costs = []
    for model in models:
        solution = frozen.solve_policy(
            point,
            (model,),
            horizon_steps=steps,
            initial_grid_state=frozen.initial_state(point),
            scales=scales,
        )
        singleton_costs.append(solution.objective)
    return {
        "point_id": point.point_id,
        "candidate_count": len(models),
        "robust_worst_cost": robust.objective,
        "robust_expected_realized_cost": float(np.mean(robust_realized)),
        "perfect_information_worst_cost": float(np.max(singleton_costs)),
        "perfect_information_expected_cost": float(np.mean(singleton_costs)),
        "predecessor_worst_case_vpi": float(robust.objective - np.max(singleton_costs)),
        "registered_uniform_expected_vpi": float(
            np.mean(robust_realized) - np.mean(singleton_costs)
        ),
        "robust_bess_command_max_abs_pu": float(np.max(np.abs(robust.bess_command))),
        "robust_bess_first_four_commands_pu": np.round(
            robust.bess_command[:, :4], 6
        ).tolist(),
        "robust_realized_cost_range": [float(np.min(robust_realized)), float(np.max(robust_realized))],
        "singleton_cost_range": [float(np.min(singleton_costs)), float(np.max(singleton_costs))],
    }


def main() -> None:
    points = (
        frozen.BoundaryPoint(
            "delay_material",
            2.0,
            "medium",
            0.015,
            0.020674,
            0.027353,
            1.095263,
            0.001410,
            0.382124,
            0.037153,
            "regional_responsibility",
        ),
        frozen.BoundaryPoint(
            "power_ramp_only",
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
        ),
    )
    print(json.dumps([evaluate(point) for point in points], indent=2))


if __name__ == "__main__":
    main()
