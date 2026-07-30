"""Fit and validate development-only O1 truth-regime identified models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from d5freq.evaluation.phase_b2_identified_mpc import (
    IdentifiedRegimeModel,
    exact_block_transition,
    fit_identified_regime_model,
    save_identified_model,
)
from d5freq.evaluation.phase_b2_plant import load_plant_b_parameters
from d5freq.models.two_area_plant_b import TwoAreaPlantB


KNOWN_REGIMES = (
    "nominal_available",
    "headroom_or_current_limited",
    "energy_limited",
    "communication_degraded",
    "service_disabled",
    "recovery",
)
SG_LEVELS = ("adequate", "scarce", "critical")
HORIZONS = (1, 5, 10, 20)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--samples", type=int, default=400)
    return parser.parse_args()


def _validate_recursive_prediction(
    params: object,
    model: IdentifiedRegimeModel,
    *,
    seeds: range,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    augmented_state_matrix, augmented_action, augmented_load, augmented_offset = (
        model.augmented_matrices()
    )
    for seed in seeds:
        rng = np.random.default_rng(seed)
        physical_model = TwoAreaPlantB(params)
        initial_soc = 0.14 if model.regime_pair[0] == "energy_limited" else 0.50
        exact_state = physical_model.initial_state(soc=(initial_soc, initial_soc))
        exact_state[[0, 3]] = rng.uniform(-0.01, 0.01, size=2)
        exact_state[6] = rng.uniform(-0.005, 0.005)
        past = rng.uniform(-0.01, 0.01, size=(2, 2))
        identified_state = np.concatenate(
            (exact_state.copy(), past.reshape(-1, order="F"))
        )
        errors_by_horizon: dict[int, np.ndarray] = {}
        for step in range(1, max(HORIZONS) + 1):
            load = np.asarray(
                (
                    0.04 + 0.005 * np.sin(0.4 * step + 0.01 * seed),
                    0.01 * np.cos(0.3 * step + 0.02 * seed),
                )
            )
            action = np.asarray(
                (
                    np.clip(load[0] * 0.55, -0.08, 0.08),
                    np.clip(load[1] * 0.55, -0.08, 0.08),
                    np.clip(load[0] * 0.45 + 0.005 * rng.normal(), -0.08, 0.08),
                    np.clip(load[1] * 0.45 + 0.005 * rng.normal(), -0.08, 0.08),
                )
            )
            exact_state = exact_block_transition(
                params,
                state=exact_state,
                action=action,
                load_pu=load,
                regime_pair=model.regime_pair,
                past_ibr_commands_pu=past,
            )
            identified_state = (
                augmented_state_matrix @ identified_state
                + augmented_action @ action
                + augmented_load @ load
                + augmented_offset
            )
            past = np.column_stack((past[:, 1], action[2:]))
            if step in HORIZONS:
                errors_by_horizon[step] = identified_state[:15] - exact_state
        for horizon, error in errors_by_horizon.items():
            rows.append(
                {
                    "plant_id": "Plant_B",
                    "sg_level": "pending",
                    "regime": model.regime_pair[0],
                    "method": "O1_truth_regime_identified_linear_MPC",
                    "seed": seed,
                    "horizon_steps": horizon,
                    "horizon_seconds": 2.0 * horizon,
                    "metric": "all_physical_states",
                    "rmse": float(np.sqrt(np.mean(error**2))),
                    "q95_abs_error": float(np.quantile(np.abs(error), 0.95)),
                    "max_abs_error": float(np.max(np.abs(error))),
                }
            )
    return rows


def main() -> None:
    args = parse_args()
    repository = args.repository.resolve()
    config = repository / "configs" / "phase_b2_plant_b.yaml"
    artifact_root = repository / "artifacts_phase_b2" / "identified_models"
    result_root = repository / "results_phase_b2" / "oracle_validation"
    artifact_root.mkdir(parents=True, exist_ok=True)
    result_root.mkdir(parents=True, exist_ok=True)
    manifest_models: dict[str, dict[str, object]] = {}
    prediction_rows: list[dict[str, object]] = []
    for sg_number, sg_level in enumerate(SG_LEVELS):
        params = load_plant_b_parameters(config, sg_level=sg_level)
        for regime_number, regime_id in enumerate(KNOWN_REGIMES):
            seed = 700 + 20 * sg_number + regime_number
            model = fit_identified_regime_model(
                params,
                regime_pair=(regime_id, regime_id),
                sample_count=args.samples,
                development_seed=seed,
            )
            destination = artifact_root / sg_level / f"{regime_id}.npz"
            save_identified_model(model, destination)
            key = f"{sg_level}:{regime_id}"
            manifest_models[key] = {
                "path": destination.relative_to(repository).as_posix(),
                "regime_pair": list(model.regime_pair),
                "fit_sample_count": model.fit_sample_count,
                "validation_rmse": model.validation_rmse,
                "validation_q95_abs_error": model.validation_q95_abs_error,
                "validation_max_abs_error": model.validation_max_abs_error,
                "ridge_alpha": model.ridge_alpha,
                "development_seed": model.development_seed,
            }
            rows = _validate_recursive_prediction(
                params,
                model,
                seeds=range(800, 805),
            )
            for row in rows:
                row["sg_level"] = sg_level
            prediction_rows.extend(rows)
            print(
                f"fitted {key}: one-step validation RMSE={model.validation_rmse:.6g}",
                flush=True,
            )
    prediction = pd.DataFrame(prediction_rows)
    prediction.to_csv(result_root / "prediction_error.csv", index=False)
    summary = (
        prediction.groupby(
            ["plant_id", "sg_level", "regime", "method", "horizon_steps", "horizon_seconds", "metric"],
            as_index=False,
        )
        .agg(
            rmse=("rmse", "mean"),
            q95_abs_error=("q95_abs_error", "mean"),
            max_abs_error=("max_abs_error", "max"),
            seed_count=("seed", "nunique"),
        )
    )
    summary.to_csv(result_root / "prediction_error_summary.csv", index=False)
    manifest = {
        "schema_version": "d5freq.phase_b2.identified_models.v1",
        "development_only_fit": True,
        "fit_seed_range": [700, 745],
        "validation_seed_range": [800, 804],
        "structural_ood_model_available": False,
        "models": manifest_models,
    }
    (artifact_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(manifest_models)} identified models", flush=True)


if __name__ == "__main__":
    main()
