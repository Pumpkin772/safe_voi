"""Generate deterministic adaptive points around the nonzero-VPI boundary."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import qmc

from voi_boundary_engine import BoundaryPoint


ROOT = Path(__file__).resolve().parents[1]


def generate(source: pd.DataFrame, count: int, seed: int) -> list[BoundaryPoint]:
    substantive = source.loc[source.perfect_information_value.gt(1e-6)].copy()
    if substantive.empty:
        substantive = source.nlargest(24, "perfect_information_value")
    sampler = qmc.LatinHypercube(d=7, seed=seed)
    draws = sampler.random(count)
    rng = np.random.default_rng(seed)
    anchors = substantive.iloc[rng.integers(0, len(substantive), size=count)]
    scales = np.array((0.012, 0.010, 0.010, 0.30, 0.00035, 0.10, 0.010))
    lower = np.array((0.015, 0.0, 0.0, 0.0, 0.0005, 0.30, 0.0))
    upper = np.array((0.075, 0.035, 0.035, 1.3, 0.0020, 0.70, 0.04))
    names = (
        "load_magnitude_pu", "power_spread_pu", "ramp_spread_pu_per_s",
        "delay_spread_s", "noise_std_pu", "soc", "tie_loading_pu",
    )
    points = []
    for index, (_, anchor), draw in zip(range(count), anchors.iterrows(), draws):
        center = np.array([float(anchor[name]) for name in names])
        values = np.clip(center + (2.0 * draw - 1.0) * scales, lower, upper)
        points.append(BoundaryPoint(
            point_id=f"B1_ADAPT_{index:04d}", period_s=float(anchor.period_s),
            sg_tension=str(anchor.sg_tension), objective=str(anchor.objective),
            **{name: float(value) for name, value in zip(names, values)},
        ))
    return points


def main() -> None:
    arguments = argparse.ArgumentParser()
    arguments.add_argument("--source", type=Path, default=ROOT / "research_outputs_boundary/B1_TIGHT_MAP/BOUNDARY_MAP.csv")
    arguments.add_argument("--output", type=Path, default=ROOT / "research_outputs_boundary/B1_ADAPTIVE_MANIFEST.csv")
    arguments.add_argument("--count", type=int, default=1024)
    arguments.add_argument("--seed", type=int, default=7011)
    args = arguments.parse_args()
    points = generate(pd.read_csv(args.source), args.count, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(points[0].__dataclass_fields__))
        writer.writeheader()
        for point in points:
            writer.writerow({name: getattr(point, name) for name in point.__dataclass_fields__})
    print(args.output)


if __name__ == "__main__":
    main()

