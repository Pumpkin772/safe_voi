"""Monte Carlo calibration of window-level dynamic capability evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.stats import beta, chi2

from direction5freq.voi_positive_region import (
    DynamicCapabilityCandidate,
    DynamicEvidenceConfig,
    simulate_candidate_response,
    whitened_residual_score,
)


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = (
    ROOT
    / "research_outputs_direction5_safe_voi_positive_region_rebuild"
    / "R2_TARGET_DISTRIBUTION"
    / "DYNAMIC_EVIDENCE_MONTE_CARLO.json"
)


def candidates() -> tuple[DynamicCapabilityCandidate, ...]:
    return tuple(
        DynamicCapabilityCandidate(
            f"P{power:.3f}_R{ramp:.3f}_D{delay:.1f}",
            power,
            ramp,
            delay,
        )
        for power in (0.045, 0.068)
        for ramp in (0.025, 0.039)
        for delay in (0.2, 1.5)
    )


def ar1_noise(
    rng: np.random.Generator,
    trials: int,
    samples: int,
    sigma: float,
    rho: float,
) -> np.ndarray:
    innovation = rng.normal(0.0, sigma, (trials, samples))
    result = np.empty_like(innovation)
    result[:, 0] = innovation[:, 0]
    scale = np.sqrt(1.0 - rho * rho)
    for index in range(1, samples):
        result[:, index] = rho * result[:, index - 1] + scale * innovation[:, index]
    return result


def upper_binomial_bound(events: int, trials: int, confidence: float = 0.95) -> float:
    if events == trials:
        return 1.0
    return float(beta.ppf(confidence, events + 1, trials - events))


def evaluate(arguments: argparse.Namespace) -> dict[str, object]:
    config = DynamicEvidenceConfig(
        maximum_windows=2,
        familywise_false_optimism=0.01,
        deterministic_residual_bound_pu=arguments.residual_bound,
    )
    grid = candidates()
    times = np.arange(0.0, 15.0 + 1e-10, config.sample_period_s)
    issued = np.full_like(times, 0.045)
    issued[(times >= 3.0) & (times < 11.0)] = arguments.command
    frequency = np.zeros_like(times)
    mask = times >= 3.0 + config.settling_exclusion_s - 1e-10
    predicted = np.asarray([
        simulate_candidate_response(times, issued, frequency, 0.0, item, config)[mask]
        for item in grid
    ])
    scored_samples = int(np.sum(mask))
    window_alpha = config.familywise_false_optimism / config.maximum_windows
    radius = float(chi2.ppf(1.0 - window_alpha, scored_samples))
    low = np.asarray([item.power_pu <= config.contract_power_pu + 1e-10 for item in grid])
    rng = np.random.default_rng(arguments.seed)
    rows = []
    for truth_index, truth in enumerate(grid):
        false_or_true_positive = 0
        for start in range(0, arguments.trials, arguments.batch_size):
            count = min(arguments.batch_size, arguments.trials - start)
            noise = ar1_noise(
                rng,
                count,
                scored_samples,
                config.measurement_noise_std_pu,
                config.ar1_correlation,
            )
            discrepancy = rng.uniform(
                -config.deterministic_residual_bound_pu,
                config.deterministic_residual_bound_pu,
                (count, scored_samples),
            )
            observed = predicted[truth_index][None, :] + noise + discrepancy
            residual = observed[:, None, :] - predicted[None, :, :]
            score = whitened_residual_score(residual, config)
            retained = score <= np.min(score, axis=1, keepdims=True) + radius
            high_only = ~np.any(retained[:, low], axis=1)
            false_or_true_positive += int(np.sum(high_only))
        rate = false_or_true_positive / arguments.trials
        rows.append({
            "truth_candidate_id": truth.candidate_id,
            "truth_power_pu": truth.power_pu,
            "truth_ramp_pu_per_s": truth.ramp_pu_per_s,
            "truth_delay_s": truth.delay_s,
            "high_power_decisions": false_or_true_positive,
            "trials": arguments.trials,
            "high_power_decision_rate": rate,
            "one_sided_95_upper": upper_binomial_bound(
                false_or_true_positive, arguments.trials
            ),
        })
    low_rows = [row for row in rows if row["truth_power_pu"] <= 0.045 + 1e-10]
    high_rows = [row for row in rows if row["truth_power_pu"] > 0.045 + 1e-10]
    return {
        "evidence": "window_level_dynamic_candidate_likelihood_set",
        "command_pu": arguments.command,
        "active_duration_s": 8.0,
        "post_action_response_s": config.post_action_response_s,
        "settling_exclusion_s": config.settling_exclusion_s,
        "raw_sample_period_s": config.sample_period_s,
        "scored_samples": scored_samples,
        "ar1_correlation": config.ar1_correlation,
        "measurement_noise_std_pu": config.measurement_noise_std_pu,
        "deterministic_residual_bound_pu": config.deterministic_residual_bound_pu,
        "familywise_false_optimism": config.familywise_false_optimism,
        "maximum_windows": config.maximum_windows,
        "window_alpha": window_alpha,
        "likelihood_radius": radius,
        "maximum_low_truth_false_optimism_rate": max(
            float(row["high_power_decision_rate"]) for row in low_rows
        ),
        "maximum_low_truth_one_sided_95_upper": max(
            float(row["one_sided_95_upper"]) for row in low_rows
        ),
        "minimum_high_truth_detection_rate": min(
            float(row["high_power_decision_rate"]) for row in high_rows
        ),
        "candidate_results": rows,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--trials", type=int, default=50000)
    result.add_argument("--batch-size", type=int, default=1000)
    result.add_argument("--seed", type=int, default=80731)
    result.add_argument("--command", type=float, default=0.050)
    result.add_argument("--residual-bound", type=float, default=0.0005)
    return result


if __name__ == "__main__":
    summary = evaluate(parser().parse_args())
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
