"""Screen preregistered MPC weights for positive nonlinear Oracle value."""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from pathlib import Path
import sys
import traceback
from types import SimpleNamespace

import numpy as np
import pandas as pd
import yaml


REPO = Path(__file__).resolve().parents[1]
for path in (REPO / "src", REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import direction5freq.accr.validation as validation
from direction5freq.models.capability_contract import CapabilityContract
from scratch_direction5.run_m1_search import make_manifest
from direction5freq.controllers.voi_accr_mpc import weighted_contract_mpc_class


WEIGHTS = [
    ("WREF", 30.0, 0.0, 12.0, 0.085, 0.050),
    ("W00", 30.0, 5.0, 12.0, 0.040, 0.030),
    ("W01", 35.0, 10.0, 15.0, 0.040, 0.060),
    ("W02", 35.0, 10.0, 15.0, 0.040, 0.100),
    ("W03", 35.0, 10.0, 15.0, 0.010, 0.060),
    ("W04", 35.0, 10.0, 15.0, 0.010, 0.100),
    ("W05", 35.0, 10.0, 15.0, 0.001, 0.060),
]


def bound_class(values):
    _, ace, tie, frequency, bess, sg = values
    weighted = weighted_contract_mpc_class(
        ace_weight=ace, tie_weight=tie, frequency_weight=frequency,
        bess_effort_weight=bess, sg_effort_weight=sg,
    )

    class BoundRolling(weighted):
        def __init__(self, period_s, horizon_steps, parameters, **kwargs):
            super().__init__(period_s, 3, parameters)
            self.registered_contract = parameters.bess.contract

        def propose(self, inputs):
            power = np.maximum(
                np.asarray(inputs.deliverability_set.performance_power_pu),
                np.asarray(self.registered_contract.upper_power_pu),
            )
            ramp = np.maximum(
                np.asarray(inputs.deliverability_set.performance_ramp_pu_per_s),
                np.asarray(self.registered_contract.ramp_up_pu_per_s),
            )
            is_contract = bool(
                np.allclose(power, self.registered_contract.upper_power_pu)
                and np.allclose(ramp, self.registered_contract.ramp_up_pu_per_s)
            )
            delay = (
                np.asarray(self.registered_contract.maximum_delay_s)
                if is_contract
                else np.asarray(inputs.deliverability_set.delay_interval_s[:, 1])
            )
            self.contract = CapabilityContract(
                lower_power_pu=tuple(-float(value) for value in power),
                upper_power_pu=tuple(float(value) for value in power),
                ramp_down_pu_per_s=tuple(float(value) for value in ramp),
                ramp_up_pu_per_s=tuple(float(value) for value in ramp),
                maximum_delay_s=tuple(float(value) for value in delay),
            )
            raw = super().propose(inputs)
            diagnostics = asdict(raw.diagnostics)
            diagnostics["attempted_optimization_calls"] = 2 if (
                raw.diagnostics.restoration_used or raw.diagnostics.fallback_used
            ) else 1
            raw = replace(raw, diagnostics=SimpleNamespace(**diagnostics))
            guaranteed = np.clip(
                raw.proposed_action_pu[[1, 3]],
                self.registered_contract.lower_power_pu,
                self.registered_contract.upper_power_pu,
            )
            fields = {name: getattr(raw, name) for name in raw.__dataclass_fields__}
            return SimpleNamespace(
                **fields,
                guaranteed_bess_command_pu=guaranteed,
                surplus_bess_command_pu=raw.proposed_action_pu[[1, 3]] - guaranteed,
                shared_current_action_verified=True,
                surplus_loss_branch_verified=False,
            )

        def commit(self, action, actual, guaranteed=None):
            super().commit(action, actual)

    return BoundRolling


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=0)
    parser.add_argument("--scenario-limit", type=int, default=0)
    parser.add_argument("--run-label", default="WSCREEN_V2")
    args = parser.parse_args()
    if not args.run_label.replace("-", "").replace("_", "").isalnum():
        raise ValueError("run-label must contain only letters, digits, hyphens, or underscores")
    output = REPO / "research_outputs_working/M1/weight_screen_runs" / args.run_label
    output.mkdir(parents=True, exist_ok=True)
    manifest = make_manifest().iloc[[0, 2, 4, 6]].copy()
    if args.scenario_limit > 0:
        manifest = manifest.head(args.scenario_limit).copy()
    lock = yaml.safe_load(
        (REPO / "configs/direction5_accr/a6_validation_lock.yaml").read_text("utf-8")
    )
    lock["horizon_steps"] = 3
    original = validation.DCSVContractRecourseMPC
    episode_rows = []
    screen_rows = []
    try:
        chosen = WEIGHTS[args.start :]
        if args.count > 0:
            chosen = chosen[: args.count]
        for values in chosen:
            weight_id, ace, tie, frequency, bess, sg = values
            validation.DCSVContractRecourseMPC = bound_class(values)
            current = []
            for scenario in manifest.to_dict("records"):
                for method in (
                    "contract_only_recourse_mpc",
                    "perfect_capability_recourse_oracle",
                ):
                    result = validation.simulate_plant_a_episode(
                        scenario, method, lock, 0.0,
                        cycle_output_path=(
                            output / "cycles" / f"{weight_id}__{scenario['scenario_id']}__contract.parquet"
                            if method == "contract_only_recourse_mpc" else None
                        ),
                    )
                    result["weight_id"] = weight_id
                    current.append(result); episode_rows.append(result)
            episodes = pd.DataFrame(current)
            pivot = episodes.pivot(index="scenario_id", columns="method")
            contract = "contract_only_recourse_mpc"
            oracle = "perfect_capability_recourse_oracle"
            ace_gap = (
                pivot.ace_iae_pu_s[contract] - pivot.ace_iae_pu_s[oracle]
            ) / pivot.ace_iae_pu_s[contract]
            tie_gap = (
                pivot.tie_iae_pu_s[contract] - pivot.tie_iae_pu_s[oracle]
            ) / pivot.tie_iae_pu_s[contract]
            max_bess = []
            for scenario_id in manifest.scenario_id:
                cycle = pd.read_parquet(output / "cycles" / f"{weight_id}__{scenario_id}__contract.parquet")
                max_bess.append(float(cycle[["command_bess0_pu", "command_bess1_pu"]].abs().to_numpy().max()))
            row = {
                "weight_id": weight_id, "ace_weight": ace, "tie_weight": tie,
                "frequency_weight": frequency, "bess_effort_weight": bess,
                "sg_effort_weight": sg,
                "mean_oracle_ace_gap": float(ace_gap.mean()),
                "mean_oracle_tie_gap": float(tie_gap.mean()),
                "positive_oracle_scenarios": int(((ace_gap > 0.01) | (tie_gap > 0.01)).sum()),
                "mean_contract_max_bess_pu": float(np.mean(max_bess)),
                "hard_violations": int(episodes.hard_violation.sum()),
                "fallback_calls": int(episodes.fallback_calls.sum()),
            }
            screen_rows.append(row)
            pd.DataFrame(screen_rows).to_csv(output / "WEIGHT_SCREEN.csv", index=False)
            pd.DataFrame(episode_rows).to_csv(
                output / "WEIGHT_SCREEN_EPISODES_CHECKPOINT.csv", index=False
            )
            print(row, flush=True)
    finally:
        validation.DCSVContractRecourseMPC = original
    pd.DataFrame(episode_rows).to_csv(output / "WEIGHT_SCREEN_EPISODES.csv", index=False)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        error_path = REPO / "research_outputs_working/M1/M1_WEIGHT_SCREEN_ERROR.log"
        error_path.parent.mkdir(parents=True, exist_ok=True)
        error_path.write_text(traceback.format_exc(), encoding="utf-8")
        raise
