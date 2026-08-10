"""Read-only causal trigger audit for a completed M1 working run."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    rows = []
    for path in sorted((args.run_dir / "cycle_parts").glob("*__accr_mpc.parquet")):
        cycle = pd.read_parquet(path)
        worthwhile = cycle[cycle.voi_worthwhile]
        if worthwhile.empty:
            continue
        row = worthwhile.iloc[0]
        rows.append({
            "scenario_id": row.scenario_id,
            "trigger_time_s": row.time_s,
            "decision_relevance_pu": row.decision_relevance_pu,
            "oracle_gap_proxy": row.oracle_gap_proxy,
            "estimated_net_voi": row.estimated_net_voi,
            "ace_l1_pu": abs(row.ace0_pu) + abs(row.ace1_pu),
            "tie_abs_pu": abs(row.tie_pu),
            "frequency_max_hz": max(abs(row.frequency0_hz), abs(row.frequency1_hz)),
            "bess_command_l1_pu": abs(row.command_bess0_pu) + abs(row.command_bess1_pu),
            "bess_tracking_error_l1_pu": (
                abs(row.command_bess0_pu - row.actual_bess0_pu)
                + abs(row.command_bess1_pu - row.actual_bess1_pu)
            ),
        })
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
