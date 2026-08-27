"""Map where the retained capability set changes the causal MPC action."""

from __future__ import annotations

import csv
from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
SCRATCH = ROOT / "scratch_direction5_voi_boundary"
OUTPUT = (
    ROOT / "research_outputs_direction5_safe_voi_positive_region_rebuild"
    / "R3_MEAN_REVERTING_DEVELOPMENT" / "MPC_DECISION_RELEVANCE_MAP.csv"
)
sys.path.insert(0, str(SCRATCH))

from voi_boundary_engine import (  # noqa: E402
    BoundaryPoint, candidate_models, objective_scales, solve_policy,
)


def main() -> None:
    rows: list[dict[str, float | str]] = []
    loads = np.linspace(0.0, 0.070, 15)
    for period_s in (2.0, 4.0):
        for horizon_s in (24.0, 32.0):
            for objective in (
                "grid_service", "sg_conserving_4", "sg_conserving_16",
                "sg_conserving_64",
            ):
                for load_pu in loads:
                    point = BoundaryPoint(
                        "DECISION_RELEVANCE", period_s, "medium", float(load_pu),
                        0.023, 0.014, 1.30, 0.0015, 0.50, 0.0, objective,
                    )
                    models = candidate_models(point)
                    high_models = tuple(
                        model for model in models if model.power_pu > 0.045 + 1e-8
                    )
                    arguments = dict(
                        horizon_steps=int(round(horizon_s / period_s)),
                        initial_grid_state=np.zeros(7),
                        initial_bess_power=np.zeros(2),
                        previous_sg_command=np.zeros(2),
                        previous_bess_command=np.zeros(2),
                        load_forecast_pu=np.full(2, load_pu),
                        scales=objective_scales(objective),
                    )
                    contract = solve_policy(point, models, **arguments)
                    high = solve_policy(point, high_models, **arguments)
                    difference = float("nan")
                    if contract.bess_command.size and high.bess_command.size:
                        difference = float(np.max(np.abs(
                            contract.bess_command[:, 0] - high.bess_command[:, 0]
                        )))
                    rows.append({
                        "period_s": period_s,
                        "horizon_s": horizon_s,
                        "objective": objective,
                        "relative_sg_penalty": (
                            objective_scales(objective).bess_move_pu
                            / objective_scales(objective).sg_move_pu
                        ) ** 2,
                        "load_pu": float(load_pu),
                        "contract_status": contract.status,
                        "high_status": high.status,
                        "first_bess_action_difference_pu": difference,
                        "contract_first_bess_pu": (
                            float(np.max(np.abs(contract.bess_command[:, 0])))
                            if contract.bess_command.size else float("nan")
                        ),
                        "high_first_bess_pu": (
                            float(np.max(np.abs(high.bess_command[:, 0])))
                            if high.bess_command.size else float("nan")
                        ),
                    })
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    for objective in sorted({str(row["objective"]) for row in rows}):
        selected = [row for row in rows if row["objective"] == objective]
        relevant = [
            row for row in selected
            if float(row["first_bess_action_difference_pu"]) > 1e-4
        ]
        threshold = min((float(row["load_pu"]) for row in relevant), default=np.nan)
        maximum = max(
            float(row["first_bess_action_difference_pu"]) for row in selected
        )
        print(
            f"{objective}: decision_relevance_threshold={threshold:.3f} pu, "
            f"maximum_first_action_difference={maximum:.6f} pu"
        )


if __name__ == "__main__":
    main()
