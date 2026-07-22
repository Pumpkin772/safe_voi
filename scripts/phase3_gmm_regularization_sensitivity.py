"""Read-only numerical audit of GMM covariance regularization in Phase 3.

The audit rebuilds the fixed eight-dimensional local-ARX feature matrix from
the public training split, fits one training-only scaler, and repeats the BIC
search on a prescribed covariance-regularization grid.  Its selections are
diagnostic within each grid point and are never operational model choices.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import csv
from dataclasses import dataclass
import hashlib
import json
import math
from numbers import Integral, Real
from pathlib import Path
import warnings

import numpy as np
from numpy.typing import NDArray
from sklearn.exceptions import ConvergenceWarning

from d5freq.data import load_public_identification_data
from d5freq.identification.arx import (
    build_arx_regression,
    fit_arx_ridge,
    fit_arx_ridge_from_regression,
)
from d5freq.identification.mode_discovery import (
    ARXFitterAPI,
    FEATURE_DIMENSION,
    FeatureStandardizer,
    GMMSelectionError,
    ModeDiscoveryConfig,
    UnlabeledTrajectory,
    fit_local_episode_models,
    select_gmm_by_bic,
)
from d5freq.utils.config import load_yaml


FloatArray = NDArray[np.float64]

REGULARIZATION_GRID: tuple[float, ...] = (1.0e-5, 1.0e-4, 1.0e-3, 1.0e-2)
CSV_FILENAME = "gmm_regularization_bic.csv"
SUMMARY_FILENAME = "gmm_regularization_summary.json"
CSV_COLUMNS: tuple[str, ...] = (
    "reg_covar",
    "K",
    "bic",
    "delta_bic",
    "converged",
    "selected_for_that_reg",
)


@dataclass(frozen=True, slots=True)
class SensitivityAuditResult:
    """Paths written by a completed diagnostic audit."""

    output_directory: Path
    bic_table_path: Path
    summary_path: Path


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    return value


def _real(value: object, name: str, *, strictly_positive: bool) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    if strictly_positive and normalized <= 0.0:
        raise ValueError(f"{name} must be strictly positive")
    if not strictly_positive and normalized < 0.0:
        raise ValueError(f"{name} must be non-negative")
    return normalized


def _integer(value: object, name: str, *, minimum: int) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise TypeError(f"{name} must be an integer")
    normalized = int(value)
    if normalized < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return normalized


def _settings_from_base_config(
    base_config: Mapping[str, object],
) -> ModeDiscoveryConfig:
    base = _mapping(base_config, "base_config")
    if base.get("schema_version") != 1:
        raise ValueError("base_config schema_version must equal 1")
    project = _mapping(base.get("project"), "project")
    identification = _mapping(base.get("identification"), "identification")
    for key in ("arx_order_y", "arx_order_u", "arx_order_f"):
        if identification.get(key) != 2:
            raise ValueError(f"{key} must equal 2 for the fixed 8D feature")

    return ModeDiscoveryConfig(
        ridge_lambda=_real(
            identification.get("ridge_lambda"),
            "identification.ridge_lambda",
            strictly_positive=False,
        ),
        variance_epsilon=_real(
            identification.get("feature_variance_epsilon"),
            "identification.feature_variance_epsilon",
            strictly_positive=True,
        ),
        residual_variance_floor=_real(
            identification.get("residual_variance_floor"),
            "identification.residual_variance_floor",
            strictly_positive=True,
        ),
        k_min=_integer(
            identification.get("gmm_k_min"),
            "identification.gmm_k_min",
            minimum=1,
        ),
        k_max=_integer(
            identification.get("gmm_k_max"),
            "identification.gmm_k_max",
            minimum=1,
        ),
        covariance_type=str(identification.get("gmm_covariance_type")),
        n_init=_integer(
            identification.get("gmm_restarts"),
            "identification.gmm_restarts",
            minimum=2,
        ),
        random_seed=_integer(project.get("seed"), "project.seed", minimum=0),
        max_iter=_integer(
            identification.get("gmm_max_iter"),
            "identification.gmm_max_iter",
            minimum=1,
        ),
        reg_covar=_real(
            identification.get("gmm_reg_covar"),
            "identification.gmm_reg_covar",
            strictly_positive=True,
        ),
    )


def _arx_fitter() -> ARXFitterAPI:
    return ARXFitterAPI(
        build_regression=build_arx_regression,
        fit_trajectory=fit_arx_ridge,
        fit_from_regression=fit_arx_ridge_from_regression,
    )


def _prepare_new_or_empty_directory(output_directory: str | Path) -> Path:
    raw = Path(output_directory).expanduser()
    if raw.is_symlink():
        raise ValueError("output directory must not be a symbolic link")
    output = raw.resolve()
    if output.exists():
        if not output.is_dir():
            raise NotADirectoryError(output)
        if any(output.iterdir()):
            raise FileExistsError(f"output directory is not empty: {output}")
    else:
        output.mkdir(parents=True, exist_ok=False)
    return output


def _matrix_sha256(values: FloatArray) -> str:
    contiguous = np.ascontiguousarray(values, dtype="<f8")
    digest = hashlib.sha256()
    digest.update(json.dumps(list(contiguous.shape), separators=(",", ":")).encode())
    digest.update(b"\0")
    digest.update(contiguous.tobytes(order="C"))
    return digest.hexdigest()


def _write_csv(rows: Sequence[Mapping[str, object]], path: Path) -> None:
    if path.exists():
        raise FileExistsError(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    if temporary.exists():
        raise FileExistsError(temporary)
    with temporary.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS, extrasaction="raise")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    temporary.replace(path)


def _write_json(payload: object, path: Path) -> None:
    if path.exists():
        raise FileExistsError(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    if temporary.exists():
        raise FileExistsError(temporary)
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    )
    temporary.write_text(serialized + "\n", encoding="utf-8", newline="\n")
    temporary.replace(path)


def run_sensitivity_audit(
    training_trajectories: Sequence[UnlabeledTrajectory],
    base_config: Mapping[str, object],
    output_directory: str | Path,
) -> SensitivityAuditResult:
    """Run the fixed regularization grid on freshly rebuilt training features."""

    settings = _settings_from_base_config(base_config)
    if len(training_trajectories) == 0:
        raise ValueError("the public training split must not be empty")

    local_fits = fit_local_episode_models(
        training_trajectories,
        arx=_arx_fitter(),
        ridge_lambda=settings.ridge_lambda,
        variance_epsilon=settings.variance_epsilon,
    )
    raw_features = np.vstack([fit.raw_feature for fit in local_fits])
    if raw_features.shape != (len(training_trajectories), FEATURE_DIMENSION):
        raise RuntimeError("local ARX features do not have the fixed 8D shape")
    scaler = FeatureStandardizer.fit(raw_features)
    standardized_features = scaler.transform(raw_features)

    rows: list[dict[str, object]] = []
    selections: list[dict[str, object]] = []
    for regularizer in REGULARIZATION_GRID:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", ConvergenceWarning)
                warnings.filterwarnings(
                    "ignore",
                    message="Could not find the number of physical cores",
                    category=UserWarning,
                    module=r"joblib\.externals\.loky\.backend\.context",
                )
                result = select_gmm_by_bic(
                    standardized_features,
                    k_min=settings.k_min,
                    k_max=settings.k_max,
                    covariance_type=settings.covariance_type,
                    n_init=settings.n_init,
                    random_seed=settings.random_seed,
                    max_iter=settings.max_iter,
                    reg_covar=regularizer,
                )
            scores = result.candidate_scores
            selected_k: int | None = result.selected_k
        except GMMSelectionError as error:
            scores = error.candidate_scores
            selected_k = None

        selections.append(
            {
                "reg_covar": regularizer,
                "selected_k_within_setting": selected_k,
            }
        )
        for score in scores:
            rows.append(
                {
                    "reg_covar": format(regularizer, ".17g"),
                    "K": score.component_count,
                    "bic": "" if score.bic is None else format(score.bic, ".17g"),
                    "delta_bic": (
                        ""
                        if score.delta_bic is None
                        else format(score.delta_bic, ".17g")
                    ),
                    "converged": str(score.converged).lower(),
                    "selected_for_that_reg": str(
                        selected_k == score.component_count
                    ).lower(),
                }
            )

    output = _prepare_new_or_empty_directory(output_directory)
    bic_path = output / CSV_FILENAME
    summary_path = output / SUMMARY_FILENAME
    _write_csv(rows, bic_path)
    _write_json(
        {
            "schema_version": 1,
            "audit": "phase3_gmm_regularization_sensitivity",
            "scope": "diagnostic_only",
            "authoritative_model_selection": False,
            "source_split": "train",
            "training_episode_count": len(training_trajectories),
            "feature_dimension": FEATURE_DIMENSION,
            "feature_construction": "seven_arx_parameters_plus_log_residual_variance",
            "scaler_fit_scope": "training_features_only",
            "scaler": scaler.to_dict(),
            "standardized_training_features_sha256": _matrix_sha256(
                standardized_features
            ),
            "regularization_grid": list(REGULARIZATION_GRID),
            "base_reg_covar": settings.reg_covar,
            "fixed_gmm_settings": {
                "k_min": settings.k_min,
                "k_max": settings.k_max,
                "covariance_type": settings.covariance_type,
                "n_init": settings.n_init,
                "random_seed": settings.random_seed,
                "max_iter": settings.max_iter,
            },
            "fixed_arx_settings": {
                "ridge_lambda": settings.ridge_lambda,
                "variance_epsilon": settings.variance_epsilon,
            },
            "within_setting_selections": selections,
            "bic_table": CSV_FILENAME,
        },
        summary_path,
    )
    return SensitivityAuditResult(
        output_directory=output,
        bic_table_path=bic_path,
        summary_path=summary_path,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the diagnostic Phase-3 GMM regularization audit."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/base.yaml"),
        help="base YAML configuration",
    )
    parser.add_argument(
        "--public-dir",
        type=Path,
        default=Path("artifacts/identification_data/public"),
        help="authenticated public identification-data directory",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/mode_discovery_sensitivity"),
        help="new or empty audit-output directory",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    base_config = load_yaml(arguments.config)
    training = load_public_identification_data(
        arguments.public_dir,
        split="train",
        verify_hashes=True,
    )
    result = run_sensitivity_audit(training, base_config, arguments.output_dir)
    print(result.summary_path.read_text(encoding="utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
