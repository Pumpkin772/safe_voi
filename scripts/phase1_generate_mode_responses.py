"""Generate reproducible hidden-mode command-step response evidence."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from d5freq.models.hidden_mode_ibr import (
    CommandHistory,
    IBRModeParams,
    IBRState,
    resolve_delay_s,
    step_ibr_rk4,
)
from d5freq.utils.config import load_yaml
from d5freq.utils.hashing import sha256_file


def simulate_mode_response(
    params: IBRModeParams,
    *,
    command_pu: float,
    duration_s: float,
    integration_step_s: float,
) -> list[dict[str, float | str]]:
    """Simulate one truth mode at zero frequency deviation."""

    step_count_float = duration_s / integration_step_s
    step_count = round(step_count_float)
    if step_count < 1 or abs(step_count_float - step_count) > 1.0e-10:
        raise ValueError("duration_s must be an integer multiple of integration_step_s")
    history = CommandHistory(initial_value_pu=0.0)
    history.record(0.0, command_pu)
    state = IBRState()
    rows: list[dict[str, float | str]] = [
        {
            "mode": params.name,
            "time_s": 0.0,
            "u_ibr_pu": command_pu,
            "q_pu": state.q_pu,
            "p_ibr_pu": state.p_ibr_pu,
        }
    ]
    for index in range(step_count):
        time_s = index * integration_step_s
        delayed_command = history.delayed_value(
            time_s,
            resolve_delay_s(params, time_s),
        )
        state = step_ibr_rk4(
            state,
            delayed_command,
            0.0,
            params,
            integration_step_s,
        )
        rows.append(
            {
                "mode": params.name,
                "time_s": (index + 1) * integration_step_s,
                "u_ibr_pu": command_pu,
                "q_pu": state.q_pu,
                "p_ibr_pu": state.p_ibr_pu,
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-config", type=Path, default=Path("configs/base.yaml"))
    parser.add_argument(
        "--modes-config", type=Path, default=Path("configs/modes_known.yaml")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/phase1"))
    parser.add_argument("--command-pu", type=float, default=0.04)
    parser.add_argument("--duration-s", type=float, default=10.0)
    args = parser.parse_args()

    base_config = load_yaml(args.base_config)
    modes_config = load_yaml(args.modes_config)
    integration_step_s = float(base_config["grid"]["integration_step_s"])
    modes = {
        name: IBRModeParams.from_mapping(name, values)
        for name, values in modes_config["known_modes"].items()
    }
    rows = [
        row
        for params in modes.values()
        for row in simulate_mode_response(
            params,
            command_pu=args.command_pu,
            duration_s=args.duration_s,
            integration_step_s=integration_step_s,
        )
    ]

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "known_mode_step_responses.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=("mode", "time_s", "u_ibr_pu", "q_pu", "p_ibr_pu"),
        )
        writer.writeheader()
        writer.writerows(rows)

    figure, axis = plt.subplots(figsize=(7.0, 4.2), constrained_layout=True)
    for name in modes:
        selected = [row for row in rows if row["mode"] == name]
        axis.plot(
            [float(row["time_s"]) for row in selected],
            [float(row["p_ibr_pu"]) for row in selected],
            label=name,
            linewidth=1.8,
        )
    axis.axhline(args.command_pu, color="black", linestyle="--", linewidth=1.0)
    axis.set_xlabel("Time (s)")
    axis.set_ylabel("IBR active-power increment (pu)")
    axis.set_title("Hidden-mode IBR command-step responses")
    axis.grid(True, alpha=0.25)
    axis.legend()
    figure.savefig(output_dir / "known_mode_step_responses.png", dpi=180)
    plt.close(figure)

    metadata = {
        "schema_version": 1,
        "command_pu": args.command_pu,
        "duration_s": args.duration_s,
        "integration_step_s": integration_step_s,
        "base_config_sha256": sha256_file(args.base_config),
        "modes_config_sha256": sha256_file(args.modes_config),
        "modes": list(modes),
        "csv_sha256": sha256_file(csv_path),
    }
    (output_dir / "known_mode_step_responses_metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

