"""Generate deterministic unlabeled identification trajectories.

The public tree contains only opaque trajectory IDs and the five whitelisted
sample columns.  Hidden mode names and generation seeds are written under the
separate ``private/`` evaluation tree.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from d5freq.data import (
    SplitCounts,
    generate_identification_dataset,
    generation_config_from_base_config,
    write_identification_dataset,
)
from d5freq.models.hidden_mode_ibr import IBRModeParams
from d5freq.utils.config import load_yaml
from d5freq.utils.hashing import sha256_file


def _known_modes(path: Path) -> dict[str, IBRModeParams]:
    config = load_yaml(path)
    if config.get("schema_version") != 1:
        raise ValueError("known-mode config must use schema_version 1")
    if config.get("truth_access") != "simulator_and_evaluation_only":
        raise ValueError("known-mode truth must be simulator/evaluation-only")
    values = config.get("known_modes")
    if not isinstance(values, dict) or not values:
        raise ValueError("known-mode config contains no known_modes mapping")
    return {
        str(name): IBRModeParams.from_mapping(str(name), fields)
        for name, fields in values.items()
    }


def _validate_global_safety(base_config: dict[str, object], config: object) -> None:
    # Attribute access is kept local so this CLI remains a thin adapter around
    # the validated library dataclass.
    command = base_config["ibr_command"]  # type: ignore[index]
    grid = base_config["grid"]  # type: ignore[index]
    command_limit = max(
        abs(float(command["u_min_pu"])),  # type: ignore[index]
        abs(float(command["u_max_pu"])),  # type: ignore[index]
    )
    if config.command_abs_limit_pu > command_limit:  # type: ignore[attr-defined]
        raise ValueError("identification command limit exceeds the global IBR bound")
    if config.command_rate_limit_pu_per_s > float(  # type: ignore[attr-defined]
        command["ramp_pu_per_s"]  # type: ignore[index]
    ):
        raise ValueError("identification command rate exceeds the global IBR bound")
    if config.frequency_abs_limit_hz > float(  # type: ignore[attr-defined]
        grid["freq_limit_hz"]  # type: ignore[index]
    ):
        raise ValueError("identification frequency limit exceeds the grid safety bound")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/base.yaml"))
    parser.add_argument(
        "--modes-config", type=Path, default=Path("configs/modes_known.yaml")
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/identification_data"),
    )
    parser.add_argument("--trajectories-per-mode", type=int)
    parser.add_argument("--duration-s", type=float)
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Generate four 30-second paired trajectories per mode, one per split.",
    )
    args = parser.parse_args()

    base_path = args.config.resolve()
    modes_path = args.modes_config.resolve()
    base_config = load_yaml(base_path)
    if base_config.get("schema_version") != 1:
        raise ValueError("base config must use schema_version 1")
    if args.smoke and (
        args.trajectories_per_mode is not None or args.duration_s is not None
    ):
        raise ValueError("--smoke cannot be combined with explicit size overrides")
    if args.smoke:
        count_override = 4
        duration_override = 30.0
        split_override = SplitCounts(1, 1, 1, 1)
    else:
        count_override = args.trajectories_per_mode
        duration_override = args.duration_s
        split_override = None
    generation_config = generation_config_from_base_config(
        base_config,
        trajectories_per_mode=count_override,
        trajectory_duration_s=duration_override,
        split_counts_per_mode=split_override,
    )
    _validate_global_safety(base_config, generation_config)
    modes = _known_modes(modes_path)
    result = generate_identification_dataset(modes, generation_config)
    written = write_identification_dataset(
        result,
        args.output_dir,
        source_hashes={
            "base_config": sha256_file(base_path),
            "known_modes_config": sha256_file(modes_path),
            "generation_script": sha256_file(Path(__file__)),
        },
    )
    print(
        json.dumps(
            {
                "dataset_sha256": written.dataset_sha256,
                "output_directory": str(written.output_directory),
                "private_metadata_sha256": written.private_metadata_sha256,
                "public_manifest_sha256": written.public_manifest_sha256,
                "trajectory_count": written.trajectory_count,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
