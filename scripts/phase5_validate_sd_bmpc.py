"""Generate the auditable native-K6/Np20 Phase-5 validation artifact set."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from d5freq.evaluation.phase5_validation import run_phase5_validation


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the frozen K6/Np20 SD-BMPC template, strict solver policy, "
            "controller state machine, and runtime information boundary."
        )
    )
    parser.add_argument("--base-config", type=Path, default=Path("configs/base.yaml"))
    parser.add_argument("--mpc-config", type=Path, default=Path("configs/mpc.yaml"))
    parser.add_argument(
        "--mode-library",
        type=Path,
        default=Path("artifacts/mode_discovery/mode_library.json"),
    )
    parser.add_argument(
        "--ood-calibration",
        type=Path,
        default=Path("artifacts/online_diagnosis/ood_calibration_artifact.json"),
    )
    parser.add_argument(
        "--ood-selection",
        type=Path,
        default=Path("artifacts/online_diagnosis/ood_hysteresis_selection.json"),
    )
    parser.add_argument(
        "--known-modes-simulator-only",
        type=Path,
        default=Path("configs/modes_known.yaml"),
        help="Simulator-private truth config; it is never passed to the controller.",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("artifacts/sd_bmpc")
    )
    parser.add_argument("--repeat-count", type=int, default=5)
    parser.add_argument("--singleton-component-id", type=int, default=3)
    parser.add_argument("--controller-smoke-steps", type=int, default=8)
    parser.add_argument("--controller-smoke-seed", type=int, default=20260722)
    parser.add_argument(
        "--no-controller-smoke",
        action="store_true",
        help="Generate optimization evidence only; canonical runs include the smoke test.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = run_phase5_validation(
        base_config_path=args.base_config,
        mpc_config_path=args.mpc_config,
        mode_library_path=args.mode_library,
        ood_calibration_path=args.ood_calibration,
        ood_selection_path=args.ood_selection,
        known_modes_config_path=args.known_modes_simulator_only,
        output_directory=args.output_dir,
        repeat_count=args.repeat_count,
        singleton_component_id=args.singleton_component_id,
        controller_smoke_steps=args.controller_smoke_steps,
        controller_smoke_seed=args.controller_smoke_seed,
        run_controller_smoke=not args.no_controller_smoke,
    )
    print(
        json.dumps(
            {
                "output_directory": str(result.output_directory),
                "summary_sha256": result.summary_sha256,
                "solver_log_sha256": result.solver_log_sha256,
                "runtime_smoke_log_sha256": result.runtime_smoke_log_sha256,
                "artifact_manifest_sha256": result.artifact_manifest_sha256,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
