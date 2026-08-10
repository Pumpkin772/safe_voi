"""Run A2 passive capability-set validation on new validation seeds."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from scipy.stats import beta
import yaml


REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from direction5freq.accr.capability_identification import PassiveCapabilityIdentifier, interval_contains_truth
from direction5freq.models.capability_contract import BESSParameters, BESSState, CapabilityRealization, step_bess


def lower_confidence(successes: int, samples: int) -> float:
    return 0.0 if successes == 0 else float(beta.ppf(0.05, successes, samples - successes + 1))


def episode(seed: int, excited: bool, lock: dict) -> dict:
    rng = np.random.default_rng(np.random.SeedSequence([20260810, 202, int(seed)]))
    power = float(rng.uniform(*lock["power_truth_range_pu"]))
    ramp = float(rng.uniform(*lock["ramp_truth_range_pu_per_s"]))
    delay = float(rng.uniform(*lock["delay_truth_range_s"]))
    truth = CapabilityRealization(
        lower_power_pu=(-power, -0.95 * power),
        upper_power_pu=(power, 0.95 * power),
        ramp_down_pu_per_s=(ramp, 0.95 * ramp),
        ramp_up_pu_per_s=(ramp, 0.95 * ramp),
        delay_s=(delay, min(delay + 0.05, 1.45)),
    )
    parameters = BESSParameters()
    dt_s = float(lock["identification_dt_s"])
    state = BESSState.equilibrium(parameters, dt_s)
    identifier = PassiveCapabilityIdentifier(
        parameters.contract,
        dt_s,
        window_s=float(lock["window_s"]),
        residual_bound_pu=float(lock["residual_bound_pu"]),
    )
    snapshot = None
    steps = int(round(float(lock["identification_horizon_s"]) / dt_s))
    for step in range(steps + 1):
        time_s = step * dt_s
        if excited:
            block = int(time_s // 4.0)
            command = np.array((0.095 if block % 2 == 0 else -0.095,
                                -0.090 if block % 2 == 0 else 0.090))
        else:
            command = np.array((0.004 * np.sin(0.20 * time_s),
                                -0.003 * np.sin(0.17 * time_s)))
        state, _ = step_bess(state, np.zeros(2), command, parameters, truth, dt_s)
        measured = state.power_pu + rng.uniform(
            -float(lock["measurement_noise_bound_pu"]),
            float(lock["measurement_noise_bound_pu"]),
            size=2,
        )
        snapshot = identifier.update(time_s, command, measured)
    assert snapshot is not None
    interval = snapshot.interval_set
    power_covered, ramp_covered, delay_covered = interval_contains_truth(
        interval,
        positive_power_pu=np.asarray(truth.upper_power_pu),
        negative_power_pu=-np.asarray(truth.lower_power_pu),
        ramp_up_pu_per_s=np.asarray(truth.ramp_up_pu_per_s),
        ramp_down_pu_per_s=np.asarray(truth.ramp_down_pu_per_s),
        delay_s=np.asarray(truth.delay_s),
    )
    false_optimism = bool(
        np.any(interval.upper_power_capability_interval_pu[:, 0] > np.asarray(truth.upper_power_pu))
        or np.any(interval.lower_power_capability_interval_pu[:, 0] > -np.asarray(truth.lower_power_pu))
        or np.any(interval.ramp_up_capability_interval_pu_per_s[:, 0] > np.asarray(truth.ramp_up_pu_per_s))
        or np.any(interval.ramp_down_capability_interval_pu_per_s[:, 0] > np.asarray(truth.ramp_down_pu_per_s))
    )
    grid = snapshot.candidate_set
    grid_nonempty = bool(not grid.feasible_set_empty.any())
    return {
        "episode_id": f"A2-V-{seed}", "seed": seed, "split": "validation",
        "excited": excited, "true_power0_pu": power, "true_ramp0_pu_per_s": ramp,
        "true_delay0_s": delay, "power_covered": power_covered,
        "ramp_covered": ramp_covered, "delay_covered": delay_covered,
        "all_dimensions_covered": power_covered and ramp_covered and delay_covered,
        "false_optimism": false_optimism,
        "excitation_sufficient": bool(interval.excitation_sufficient.all()),
        "delay_width0_s": float(np.ptp(interval.delay_interval_s[0])),
        "power_width0_pu": float(np.ptp(interval.upper_power_capability_interval_pu[0])),
        "delay_candidate_count0": int(interval.delay_candidate_count[0]),
        "grid_model_count": int(grid.feasible_delay_mask.sum()),
        "grid_nonempty": grid_nonempty,
        "grid_change_reset_seen": bool(grid.change_reset.any()),
        "samples": interval.samples,
    }


def abrupt_reset_audit(lock: dict) -> dict:
    parameters = BESSParameters()
    identifier = PassiveCapabilityIdentifier(parameters.contract, 0.25, window_s=8.0)
    reset_seen = False
    snapshot = None
    for index in range(16):
        command = np.array((0.08, -0.08))
        actual = np.array((0.06, -0.06)) if index < 10 else np.array((-0.06, 0.06))
        snapshot = identifier.update(index * 0.25, command, actual)
        reset_seen |= bool(snapshot.candidate_set.change_reset.any())
    return {
        "case": "ABRUPT_INCOMPATIBLE_COMMAND_TO_ACTUAL_TRANSITION",
        "reset_seen": reset_seen,
        "post_reset_interval_samples": int(snapshot.interval_set.samples),
        "truth_read_by_identifier": False,
    }


def main() -> None:
    lock = yaml.safe_load((REPO / "configs/direction5_accr/a2_identification_lock.yaml").read_text("utf-8"))
    if not lock["registered_before_execution"]:
        raise RuntimeError("A2 is not locked")
    excited_range = range(lock["excited_validation_seeds"][0], lock["excited_validation_seeds"][1] + 1)
    passive_range = range(lock["no_excitation_validation_seeds"][0], lock["no_excitation_validation_seeds"][1] + 1)
    rows = [episode(seed, True, lock) for seed in excited_range]
    rows += [episode(seed, False, lock) for seed in passive_range]
    episodes = pd.DataFrame(rows)
    excited = episodes[episodes.excited]
    no_excitation = episodes[~episodes.excited]
    metrics = []
    for metric in ("power_covered", "ramp_covered", "delay_covered", "all_dimensions_covered"):
        successes = int(excited[metric].sum())
        metrics.append({
            "metric": metric, "samples": len(excited), "successes": successes,
            "empirical_rate": successes / len(excited),
            "one_sided_95_confidence_lower": lower_confidence(successes, len(excited)),
            "plant": "physical_BESS_command_to_actual", "period_s": lock["identification_dt_s"],
            "horizon_s": lock["identification_horizon_s"],
        })
    false_count = int(excited.false_optimism.sum())
    false_rate = false_count / len(excited)
    metrics.append({
        "metric": "false_optimism", "samples": len(excited), "successes": false_count,
        "empirical_rate": false_rate, "one_sided_95_confidence_lower": np.nan,
        "plant": "physical_BESS_command_to_actual", "period_s": lock["identification_dt_s"],
        "horizon_s": lock["identification_horizon_s"],
    })
    coverage = pd.DataFrame(metrics)
    reset = abrupt_reset_audit(lock)
    gates = {
        "power_containment_at_least_95_percent": bool(excited.power_covered.mean() >= lock["gates"]["containment_min"]),
        "ramp_containment_at_least_95_percent": bool(excited.ramp_covered.mean() >= lock["gates"]["containment_min"]),
        "delay_containment_at_least_95_percent": bool(excited.delay_covered.mean() >= lock["gates"]["containment_min"]),
        "false_optimism_at_most_1_percent": bool(false_rate <= lock["gates"]["false_optimism_max"]),
        "finite_candidate_grid_nonempty": bool(excited.grid_nonempty.all()),
        "no_excitation_does_not_claim_excitation": bool(not no_excitation.excitation_sufficient.any()),
        "no_excitation_delay_set_remains_wide": bool(no_excitation.delay_width0_s.ge(lock["gates"]["no_excitation_delay_width_min_s"]).all()),
        "no_excitation_power_set_remains_wide": bool(no_excitation.power_width0_pu.ge(lock["gates"]["no_excitation_power_width_min_pu"]).all()),
        "abrupt_change_reset_works": bool(reset["reset_seen"]),
        "passive_baseline_does_not_falsely_certify_surplus": bool(not no_excitation.excitation_sufficient.any()),
    }
    output = REPO / "results_accr/A2"
    output.mkdir(parents=True, exist_ok=True)
    episodes.to_csv(output / "A2_IDENTIFICATION_EPISODES.csv", index=False)
    coverage.to_csv(output / "A2_COVERAGE_SUMMARY.csv", index=False)
    (output / "A2_ABRUPT_RESET_AUDIT.json").write_text(json.dumps(reset, indent=2) + "\n", "utf-8")
    summary = {
        "schema": "direction5.accr.a2.v1", "stage": "A2",
        "status": "PASS" if all(gates.values()) else "FAIL",
        "selected_observer": "CONSTRAINED_MHE_ACTUAL_BESS_POI",
        "selected_capability_estimator": "FINITE_AB_DELAY_GRID_PLUS_INTERVAL_MHE",
        "validation_episodes": len(episodes), "excited_episodes": len(excited),
        "no_excitation_episodes": len(no_excitation),
        "power_coverage": float(excited.power_covered.mean()),
        "ramp_coverage": float(excited.ramp_covered.mean()),
        "delay_coverage": float(excited.delay_covered.mean()),
        "false_optimism": false_rate, "gates": gates,
        "repairs_used": 0, "final_seeds_consumed": False,
        "next_stage": "A3" if all(gates.values()) else "A2_REPAIR_1",
    }
    (output / "A2_SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n", "utf-8")
    print(json.dumps(summary, indent=2))
    raise SystemExit(0 if summary["status"] == "PASS" else 2)


if __name__ == "__main__":
    main()

