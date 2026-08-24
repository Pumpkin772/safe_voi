"""Development Monte Carlo for the sequential one-sided power certificate."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.stats import norm


def simulate(
    true_delivery_pu: float,
    correlation: float,
    total_alpha: float,
    trials: int = 100_000,
) -> dict[str, float]:
    rng = np.random.default_rng(8120)
    samples = 20
    noise_std = 0.001
    innovations = rng.normal(
        0.0, noise_std * np.sqrt(1.0 - correlation ** 2),
        size=(trials, samples),
    )
    noise = np.empty_like(innovations)
    noise[:, 0] = rng.normal(0.0, noise_std, size=trials)
    for index in range(1, samples):
        noise[:, index] = correlation * noise[:, index - 1] + innovations[:, index]
    # Use the adverse edge of the retained deterministic residual bound.
    observed = true_delivery_pu + 0.00025 + noise
    certified = np.zeros(trials, dtype=bool)
    certification_sample = np.zeros(trials, dtype=int)
    z_value = float(norm.ppf(1.0 - total_alpha / samples))
    for count in range(2, samples + 1):
        effective = count * (1.0 - correlation) / (1.0 + correlation)
        threshold = 0.045 + 0.00025 + z_value * noise_std / np.sqrt(effective)
        new = (~certified) & (observed[:, :count].mean(axis=1) > threshold)
        certification_sample[new] = count
        certified |= new
    detected_samples = certification_sample[certified]
    return {
        "true_delivery_pu": true_delivery_pu,
        "window_correlation": correlation,
        "total_alpha": total_alpha,
        "certification_rate": float(certified.mean()),
        "median_certification_samples": (
            float(np.median(detected_samples)) if len(detected_samples) else float("nan")
        ),
        "p95_certification_samples": (
            float(np.quantile(detected_samples, 0.95)) if len(detected_samples) else float("nan")
        ),
    }


def main() -> None:
    result = {
        "trials_per_branch": 100_000,
        "alpha_correlation_sensitivity": [
            {
                "total_alpha": total_alpha,
                "correlation": correlation,
                "low_branch": simulate(0.045, correlation, total_alpha),
                "high_branch_0_048": simulate(0.048, correlation, total_alpha),
            }
            for total_alpha in (0.01, 0.02, 0.03, 0.04, 0.05)
            for correlation in (0.0, 0.2, 0.4)
        ],
        "high_branch_0_050_at_alpha_0_01_correlation_0_2": simulate(
            0.050, 0.2, 0.01
        ),
    }
    root = Path(__file__).resolve().parents[2]
    destination = (
        root
        / "research_outputs_direction5_safe_voi_positive_region_rebuild"
        / "R1_CERTIFICATE_MONTE_CARLO.json"
    )
    destination.write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
