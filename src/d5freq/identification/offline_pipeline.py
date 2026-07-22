"""Reproducible, information-isolated offline mode-discovery orchestration.

The entry point in this module accepts only public training and validation
trajectories.  Its outputs retain native GMM component identifiers and are
fully determined by those public signals plus versioned numerical settings.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import logging
import math
from numbers import Integral, Real
from pathlib import Path
from typing import Any

import joblib
import matplotlib

matplotlib.use("Agg", force=True)

import matplotlib.pyplot as plt
import numpy as np
from numpy.typing import ArrayLike, NDArray
import pandas as pd
from sklearn.decomposition import PCA

from d5freq.identification.arx import (
    build_arx_regression,
    fit_arx_ridge,
    fit_arx_ridge_from_regression,
    validate_arx_multistep,
)
from d5freq.identification.mode_discovery import (
    ARXFitterAPI,
    EpisodeAssignmentResult,
    ModeDiscoveryConfig,
    ModeDiscoveryResult,
    ModeValidationMetrics,
    UnlabeledTrajectory,
    assign_episodes_with_frozen_discovery,
    discover_unlabeled_modes,
    evaluate_assigned_validation_episodes,
)
from d5freq.identification.model_library import (
    ModeLibrary,
    discovery_metadata_from_selection,
    mode_library_from_discovery,
)
from d5freq.models.grid_frequency import GridFrequencyModel, GridParams
from d5freq.utils.hashing import sha256_file


LOGGER = logging.getLogger(__name__)

FloatArray = NDArray[np.float64]

ARX_PARAMETER_NAMES: tuple[str, ...] = (
    "a1",
    "a2",
    "b0",
    "b1",
    "c0",
    "c1",
    "intercept",
)
REQUIRED_LABEL_FREE_ARTIFACTS: tuple[str, ...] = (
    "mode_library.json",
    "scaler.json",
    "gmm.pkl",
    "bic_table.csv",
    "episode_features.parquet",
    "cluster_assignments.csv",
    "mode_model_metrics.csv",
    "multi_step_error_quantiles.csv",
    "distinguishability_matrix.csv",
    "bic_curve.png",
    "parameter_embedding.png",
)


def _finite_real(value: object, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


def _positive_integer(value: object, name: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise TypeError(f"{name} must be an integer")
    normalized = int(value)
    if normalized < 1:
        raise ValueError(f"{name} must be positive")
    return normalized


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    return value


@dataclass(frozen=True, slots=True)
class OfflinePipelineConfig:
    """Fully materialized numerical settings for the offline pipeline."""

    grid_params: GridParams
    discovery: ModeDiscoveryConfig
    multi_step_horizon: int
    switch_epsilon: float

    def __post_init__(self) -> None:
        if not isinstance(self.grid_params, GridParams):
            raise TypeError("grid_params must be GridParams")
        if not isinstance(self.discovery, ModeDiscoveryConfig):
            raise TypeError("discovery must be ModeDiscoveryConfig")
        object.__setattr__(
            self,
            "multi_step_horizon",
            _positive_integer(self.multi_step_horizon, "multi_step_horizon"),
        )
        epsilon = _finite_real(self.switch_epsilon, "switch_epsilon")
        if not 0.0 <= epsilon <= 1.0:
            raise ValueError("switch_epsilon must lie in [0, 1]")
        object.__setattr__(self, "switch_epsilon", epsilon)

    @property
    def sample_time_s(self) -> float:
        return self.grid_params.control_period_s

    @property
    def f0_hz(self) -> float:
        return self.grid_params.f0_hz


def offline_pipeline_config_from_base_config(
    base_config: Mapping[str, Any],
) -> OfflinePipelineConfig:
    """Construct strict Phase-3 settings from ``configs/base.yaml`` data."""

    base = _mapping(base_config, "base_config")
    if base.get("schema_version") != 1:
        raise ValueError("base_config schema_version must equal 1")
    project = _mapping(base.get("project"), "project")
    grid = _mapping(base.get("grid"), "grid")
    identification = _mapping(base.get("identification"), "identification")
    belief = _mapping(base.get("belief"), "belief")
    expected_orders = {
        "arx_order_y": 2,
        "arx_order_u": 2,
        "arx_order_f": 2,
    }
    for name, expected in expected_orders.items():
        if identification.get(name) != expected:
            raise ValueError(f"{name} must equal {expected} for the Phase-3 main chain")

    grid_params = GridParams(
        f0_hz=float(grid["f0_hz"]),
        M_s=float(grid["M_s"]),
        D_pu=float(grid["D_pu"]),
        T_t_s=float(grid["T_t_s"]),
        T_g_s=float(grid["T_g_s"]),
        R_pu=float(grid["R_pu"]),
        control_period_s=float(grid["control_period_s"]),
        integration_step_s=float(grid["integration_step_s"]),
    )
    discovery = ModeDiscoveryConfig(
        ridge_lambda=float(identification["ridge_lambda"]),
        variance_epsilon=float(identification["feature_variance_epsilon"]),
        residual_variance_floor=float(identification["residual_variance_floor"]),
        k_min=int(identification["gmm_k_min"]),
        k_max=int(identification["gmm_k_max"]),
        covariance_type=str(identification["gmm_covariance_type"]),
        n_init=int(identification["gmm_restarts"]),
        random_seed=int(project["seed"]),
        max_iter=int(identification["gmm_max_iter"]),
        reg_covar=float(identification["gmm_reg_covar"]),
        lower_power_quantile=float(identification["lower_power_quantile"]),
        upper_power_quantile=float(identification["upper_power_quantile"]),
        directional_rate_quantile=float(
            identification["directional_rate_quantile"]
        ),
    )
    switch_epsilon = _finite_real(belief["switch_epsilon"], "switch_epsilon")
    if not 0.0 <= switch_epsilon <= 1.0:
        raise ValueError("belief.switch_epsilon must lie in [0, 1]")
    return OfflinePipelineConfig(
        grid_params=grid_params,
        discovery=discovery,
        multi_step_horizon=int(identification["multi_step_horizon"]),
        switch_epsilon=switch_epsilon,
    )


@dataclass(frozen=True, slots=True)
class LabelFreeDiscoveryRun:
    """In-memory results plus the immutable model-library digest."""

    output_directory: Path
    discovery: ModeDiscoveryResult
    validation_assignment: EpisodeAssignmentResult
    validation_metrics: tuple[ModeValidationMetrics, ...]
    mode_library: ModeLibrary
    model_library_sha256: str
    frequency_error_hz_by_component: Mapping[int, FloatArray]
    rocof_error_hz_per_s_by_component: Mapping[int, FloatArray]
    distinguishability: FloatArray


def default_arx_fitter_api() -> ARXFitterAPI:
    """Return the fixed equation-(76)/(77)/(83) ARX implementation."""

    return ARXFitterAPI(
        build_regression=build_arx_regression,
        fit_trajectory=fit_arx_ridge,
        fit_from_regression=fit_arx_ridge_from_regression,
    )


def propagate_grid_frequency_errors(
    power_prediction_errors_pu: ArrayLike,
    *,
    grid_model: GridFrequencyModel,
) -> FloatArray:
    """Propagate IBR power errors through ``e_x+=A_d e_x+E_d e_p``.

    Rows are independent rolling origins and columns are prediction leads.  The
    returned values are frequency-deviation errors in hertz.
    """

    if not isinstance(grid_model, GridFrequencyModel):
        raise TypeError("grid_model must be GridFrequencyModel")
    raw = np.asarray(power_prediction_errors_pu)
    if np.iscomplexobj(raw):
        raise TypeError("power_prediction_errors_pu must be real-valued")
    errors = np.asarray(raw, dtype=np.float64)
    if errors.ndim != 2 or errors.shape[0] == 0 or errors.shape[1] == 0:
        raise ValueError("power_prediction_errors_pu must be a non-empty matrix")
    if not np.all(np.isfinite(errors)):
        raise ValueError("power_prediction_errors_pu must contain finite values")

    A_d, _, E_d, _ = grid_model.discrete_matrices()
    state_error = np.zeros((errors.shape[0], A_d.shape[0]), dtype=np.float64)
    frequency_error_hz = np.empty_like(errors)
    for lead in range(errors.shape[1]):
        state_error = state_error @ A_d.T + errors[:, [lead]] * E_d[:, 0]
        frequency_error_hz[:, lead] = (
            grid_model.params.f0_hz * state_error[:, 0]
        )
    if not np.all(np.isfinite(frequency_error_hz)):
        raise FloatingPointError("grid frequency-error propagation became non-finite")
    return frequency_error_hz


def frequency_errors_to_rocof_errors(
    frequency_prediction_errors_hz: ArrayLike,
    *,
    sample_time_s: float,
) -> FloatArray:
    """Convert frequency-error paths to leadwise RoCoF errors in Hz/s."""

    sample_time = _finite_real(sample_time_s, "sample_time_s")
    if sample_time <= 0.0:
        raise ValueError("sample_time_s must be strictly positive")
    raw = np.asarray(frequency_prediction_errors_hz)
    if np.iscomplexobj(raw):
        raise TypeError("frequency_prediction_errors_hz must be real-valued")
    frequency = np.asarray(raw, dtype=np.float64)
    if frequency.ndim != 2 or frequency.shape[0] == 0 or frequency.shape[1] == 0:
        raise ValueError("frequency_prediction_errors_hz must be a non-empty matrix")
    if not np.all(np.isfinite(frequency)):
        raise ValueError("frequency_prediction_errors_hz must contain finite values")
    initial_zero = np.zeros((frequency.shape[0], 1), dtype=np.float64)
    return np.diff(np.hstack((initial_zero, frequency)), axis=1) / sample_time


def _pairwise_distinguishability_matrix(
    theta_by_component: ArrayLike,
    residual_variances: ArrayLike,
    common_regression_vectors: ArrayLike,
) -> FloatArray:
    """Evaluate equations (38)--(39) on one common public validation set."""

    theta = np.asarray(theta_by_component, dtype=np.float64)
    variances = np.asarray(residual_variances, dtype=np.float64)
    phi = np.asarray(common_regression_vectors, dtype=np.float64)
    if theta.ndim != 2 or theta.shape[0] == 0 or theta.shape[1] != 7:
        raise ValueError("theta_by_component must have shape (K, 7)")
    if variances.shape != (theta.shape[0],) or np.any(variances <= 0.0):
        raise ValueError("residual_variances must be positive with shape (K,)")
    if phi.ndim != 2 or phi.shape[0] == 0 or phi.shape[1] != 7:
        raise ValueError("common_regression_vectors must have shape (N, 7)")
    if not (
        np.all(np.isfinite(theta))
        and np.all(np.isfinite(variances))
        and np.all(np.isfinite(phi))
    ):
        raise ValueError("distinguishability inputs must be finite")
    information = np.zeros((theta.shape[0], theta.shape[0]), dtype=np.float64)
    for first in range(theta.shape[0]):
        for second in range(first + 1, theta.shape[0]):
            differences = phi @ (theta[first] - theta[second])
            value = float(
                np.dot(differences, differences)
                / (variances[first] + variances[second])
            )
            information[first, second] = value
            information[second, first] = value
    return information


def _ensure_unique_disjoint_ids(
    training: Sequence[UnlabeledTrajectory],
    validation: Sequence[UnlabeledTrajectory],
) -> None:
    if not training or not validation:
        raise ValueError("non-empty public training and validation sets are required")
    training_ids = [str(item.trajectory_id) for item in training]
    validation_ids = [str(item.trajectory_id) for item in validation]
    if len(set(training_ids)) != len(training_ids):
        raise ValueError("training trajectory IDs must be unique")
    if len(set(validation_ids)) != len(validation_ids):
        raise ValueError("validation trajectory IDs must be unique")
    overlap = set(training_ids).intersection(validation_ids)
    if overlap:
        raise ValueError("training and validation trajectories must be disjoint")


def _prepare_empty_output_directory(output_directory: str | Path) -> Path:
    output = Path(output_directory).expanduser().resolve()
    if output.exists() and not output.is_dir():
        raise NotADirectoryError(output)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    return output


def _write_json(payload: object, path: Path) -> None:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    )
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(serialized + "\n", encoding="utf-8", newline="\n")
    temporary.replace(path)


def _validation_error_blocks(
    validation: Sequence[UnlabeledTrajectory],
    assignment: EpisodeAssignmentResult,
    discovery: ModeDiscoveryResult,
    *,
    horizon: int,
) -> dict[int, FloatArray]:
    blocks: dict[int, list[FloatArray]] = {
        model.component_id: [] for model in discovery.mode_models
    }
    model_by_component = {
        model.component_id: model for model in discovery.mode_models
    }
    for trajectory, component_id in zip(
        validation, assignment.component_ids.tolist(), strict=True
    ):
        model = model_by_component[int(component_id)]
        scored = validate_arx_multistep(
            model.theta,
            trajectory.p_ibr_pu,
            trajectory.u_ibr_pu,
            trajectory.omega_pu,
            horizon=horizon,
        )
        blocks[int(component_id)].append(np.asarray(scored.errors, dtype=np.float64))
    missing = [component for component, values in blocks.items() if not values]
    if missing:
        raise ValueError(
            "validation assignments leave discovered components without independent "
            f"multi-step evidence: {missing}"
        )
    return {component: np.vstack(values) for component, values in blocks.items()}


def _episode_feature_frame(
    discovery: ModeDiscoveryResult,
    validation_assignment: EpisodeAssignmentResult,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    def append_rows(
        split: str,
        fits: Sequence[object],
        standardized: FloatArray,
        components: NDArray[np.int64],
        probabilities: FloatArray,
    ) -> None:
        for row_index, (fit, component) in enumerate(
            zip(fits, components.tolist(), strict=True)
        ):
            raw_feature = np.asarray(getattr(fit, "raw_feature"), dtype=np.float64)
            row: dict[str, object] = {
                "trajectory_id": str(getattr(fit, "trajectory_id")),
                "dataset_split": split,
                "component_id": int(component),
                "condition_number": float(getattr(fit, "condition_number")),
                "residual_variance": float(getattr(fit, "residual_variance")),
            }
            for index, name in enumerate(ARX_PARAMETER_NAMES):
                row[f"theta_{name}"] = float(raw_feature[index])
            row["log_residual_variance"] = float(raw_feature[-1])
            for index, value in enumerate(standardized[row_index]):
                row[f"standardized_feature_{index}"] = float(value)
            for index, probability in enumerate(probabilities[row_index]):
                row[f"component_probability_{index}"] = float(probability)
            rows.append(row)

    train_probabilities = np.asarray(
        discovery.mixture.model.predict_proba(discovery.standardized_features),
        dtype=np.float64,
    )
    append_rows(
        "train",
        discovery.episode_fits,
        discovery.standardized_features,
        discovery.mixture.labels,
        train_probabilities,
    )
    append_rows(
        "validation",
        validation_assignment.episode_fits,
        validation_assignment.standardized_features,
        validation_assignment.component_ids,
        validation_assignment.component_probabilities,
    )
    return pd.DataFrame(rows)


def _assignment_frame(features: pd.DataFrame, component_count: int) -> pd.DataFrame:
    columns = ["trajectory_id", "dataset_split", "component_id"] + [
        f"component_probability_{index}" for index in range(component_count)
    ]
    return features.loc[:, columns].copy()


def _bic_frame(discovery: ModeDiscoveryResult) -> pd.DataFrame:
    selected = discovery.mixture.selected_k
    rows = []
    for candidate in discovery.mixture.candidate_scores:
        rows.append(
            {
                "component_count": candidate.component_count,
                "bic": "" if candidate.bic is None else candidate.bic,
                "delta_bic": "" if candidate.delta_bic is None else candidate.delta_bic,
                "converged": candidate.converged,
                "iterations": candidate.iterations,
                "failure_reason": candidate.failure_reason or "",
                "selected": candidate.component_count == selected,
            }
        )
    return pd.DataFrame(rows)


def _mode_metrics_frame(
    discovery: ModeDiscoveryResult,
    validation_metrics: Sequence[ModeValidationMetrics],
) -> pd.DataFrame:
    validation_by_component = {
        metric.component_id: metric for metric in validation_metrics
    }
    selected_score = next(
        score
        for score in discovery.mixture.candidate_scores
        if score.component_count == discovery.mixture.selected_k
    )
    rows: list[dict[str, object]] = []
    for model in discovery.mode_models:
        validation = validation_by_component[model.component_id]
        gmm_center = discovery.mixture.component_centers[model.component_id]
        row: dict[str, object] = {
            "component_id": model.component_id,
            "residual_variance": model.residual_variance,
            "regression_condition_number": model.condition_number,
            "training_episode_count": model.training_episode_count,
            "training_sample_count": model.training_sample_count,
            "validation_episode_count": validation.validation_episode_count,
            "validation_prediction_origin_count": validation.prediction_origin_count,
            "power_bound_coverage": validation.power_bound_coverage,
            "directional_rate_bound_coverage": validation.directional_rate_bound_coverage,
            "p_output_min_pu": model.capability.p_output_min_pu,
            "p_output_max_pu": model.capability.p_output_max_pu,
            "ramp_down_pu_per_s": model.capability.ramp_down_pu_per_s,
            "ramp_up_pu_per_s": model.capability.ramp_up_pu_per_s,
            "gmm_selected_k": discovery.mixture.selected_k,
            "gmm_selected_converged": selected_score.converged,
            "gmm_silhouette": (
                "" if discovery.mixture.silhouette is None else discovery.mixture.silhouette
            ),
        }
        for name, value in zip(ARX_PARAMETER_NAMES, model.theta, strict=True):
            row[f"theta_{name}"] = float(value)
        for index, value in enumerate(gmm_center):
            row[f"gmm_standardized_center_{index}"] = float(value)
        rows.append(row)
    return pd.DataFrame(rows)


def _multistep_frame(
    validation_metrics: Sequence[ModeValidationMetrics],
    frequency_errors: Mapping[int, FloatArray],
    rocof_errors: Mapping[int, FloatArray],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for metric in validation_metrics:
        frequency = np.asarray(
            frequency_errors[metric.component_id], dtype=np.float64
        )
        frequency_absolute = np.abs(frequency)
        rocof = np.asarray(rocof_errors[metric.component_id], dtype=np.float64)
        rocof_absolute = np.abs(rocof)
        for lead in range(metric.rmse_by_lead.size):
            rows.append(
                {
                    "component_id": metric.component_id,
                    "lead_step": lead + 1,
                    "power_error_rmse_pu": float(metric.rmse_by_lead[lead]),
                    "power_error_mae_pu": float(metric.mae_by_lead[lead]),
                    "power_abs_error_quantile_95_pu": float(
                        metric.abs_error_quantile_95_by_lead[lead]
                    ),
                    "frequency_error_rmse_hz": float(
                        np.sqrt(np.mean(np.square(frequency[:, lead])))
                    ),
                    "frequency_error_mae_hz": float(
                        np.mean(frequency_absolute[:, lead])
                    ),
                    "frequency_abs_error_quantile_95_hz": float(
                        np.quantile(frequency_absolute[:, lead], 0.95)
                    ),
                    "rocof_error_rmse_hz_per_s": float(
                        np.sqrt(np.mean(np.square(rocof[:, lead])))
                    ),
                    "rocof_error_mae_hz_per_s": float(
                        np.mean(rocof_absolute[:, lead])
                    ),
                    "rocof_abs_error_quantile_95_hz_per_s": float(
                        np.quantile(rocof_absolute[:, lead], 0.95)
                    ),
                    "prediction_origin_count": metric.prediction_origin_count,
                }
            )
    return pd.DataFrame(rows)


def _distinguishability_frame(information: FloatArray) -> pd.DataFrame:
    component_count = information.shape[0]
    frame = pd.DataFrame(
        information,
        columns=[f"component_{index}" for index in range(component_count)],
    )
    frame.insert(0, "component_id", np.arange(component_count, dtype=int))
    return frame


def _save_bic_curve(bic_frame: pd.DataFrame, path: Path) -> None:
    successful = bic_frame.copy()
    successful["bic"] = pd.to_numeric(successful["bic"], errors="coerce")
    successful = successful.dropna(subset=["bic"])
    if successful.empty:
        raise RuntimeError("cannot plot a BIC curve without successful candidates")
    figure, axis = plt.subplots(figsize=(6.4, 4.2), constrained_layout=True)
    x = successful["component_count"].to_numpy(dtype=int)
    y = successful["bic"].to_numpy(dtype=float)
    axis.plot(x, y, marker="o", linewidth=1.6)
    selected = successful.loc[successful["selected"]]
    axis.scatter(
        selected["component_count"].to_numpy(dtype=int),
        selected["bic"].to_numpy(dtype=float),
        marker="*",
        s=130,
        label="BIC selection",
        zorder=3,
    )
    axis.set_xlabel("GMM component count K")
    axis.set_ylabel("BIC")
    axis.set_title("Training-only GMM model selection")
    axis.grid(alpha=0.25)
    axis.legend()
    figure.savefig(path, dpi=180)
    plt.close(figure)


def _save_parameter_embedding(feature_frame: pd.DataFrame, path: Path) -> None:
    """Use PCA exclusively for a plot regenerated from the saved feature table."""

    training = feature_frame.loc[feature_frame["dataset_split"] == "train"]
    feature_columns = [f"standardized_feature_{index}" for index in range(8)]
    features = training.loc[:, feature_columns].to_numpy(dtype=np.float64)
    labels = training["component_id"].to_numpy(dtype=np.int64)
    if features.shape[0] < 2:
        embedded = np.column_stack((features[:, 0], np.zeros(features.shape[0])))
        variance_text = "PCA unavailable for one episode"
    else:
        pca = PCA(n_components=2, svd_solver="full")
        embedded = pca.fit_transform(features)
        variance_text = (
            f"explained variance: {100.0 * pca.explained_variance_ratio_[0]:.1f}% + "
            f"{100.0 * pca.explained_variance_ratio_[1]:.1f}%"
        )
    figure, axis = plt.subplots(figsize=(6.4, 5.0), constrained_layout=True)
    scatter = axis.scatter(
        embedded[:, 0],
        embedded[:, 1],
        c=labels,
        cmap="tab10",
        s=36,
        alpha=0.85,
    )
    axis.set_xlabel("PCA coordinate 1 (plot only)")
    axis.set_ylabel("PCA coordinate 2 (plot only)")
    axis.set_title(f"Training ARX feature embedding\n{variance_text}")
    axis.grid(alpha=0.2)
    figure.colorbar(scatter, ax=axis, label="discovered component")
    figure.savefig(path, dpi=180)
    plt.close(figure)


def run_label_free_mode_discovery(
    training_trajectories: Sequence[UnlabeledTrajectory],
    validation_trajectories: Sequence[UnlabeledTrajectory],
    *,
    config: OfflinePipelineConfig,
    output_directory: str | Path,
    arx: ARXFitterAPI | None = None,
) -> LabelFreeDiscoveryRun:
    """Fit, validate, and persist a public-signal-only discovery result."""

    if not isinstance(config, OfflinePipelineConfig):
        raise TypeError("config must be OfflinePipelineConfig")
    training = tuple(training_trajectories)
    validation = tuple(validation_trajectories)
    _ensure_unique_disjoint_ids(training, validation)
    fitter = default_arx_fitter_api() if arx is None else arx

    discovery = discover_unlabeled_modes(
        training,
        sample_time_s=config.sample_time_s,
        arx=fitter,
        config=config.discovery,
    )
    component_count = discovery.mixture.selected_k
    if component_count > 1 and config.switch_epsilon > 1.0 / (component_count - 1):
        raise ValueError(
            "switch_epsilon is too large for the BIC-selected component count"
        )
    stay_probability = (
        1.0
        if component_count == 1
        else 1.0 - (component_count - 1) * config.switch_epsilon
    )
    validation_assignment = assign_episodes_with_frozen_discovery(
        validation,
        arx=fitter,
        feature_scaler=discovery.feature_scaler,
        mixture=discovery.mixture.model,
        ridge_lambda=config.discovery.ridge_lambda,
        variance_epsilon=config.discovery.variance_epsilon,
    )
    output = _prepare_empty_output_directory(output_directory)
    _write_json(discovery.feature_scaler.to_dict(), output / "scaler.json")
    joblib.dump(discovery.mixture.model, output / "gmm.pkl", compress=3)
    bic_frame = _bic_frame(discovery)
    feature_frame = _episode_feature_frame(discovery, validation_assignment)
    assignment_frame = _assignment_frame(feature_frame, component_count)
    bic_frame.to_csv(output / "bic_table.csv", index=False)
    feature_frame.to_parquet(
        output / "episode_features.parquet",
        index=False,
        engine="pyarrow",
        compression="zstd",
    )
    assignment_frame.to_csv(output / "cluster_assignments.csv", index=False)
    _save_bic_curve(
        pd.read_csv(output / "bic_table.csv"), output / "bic_curve.png"
    )
    _save_parameter_embedding(
        pd.read_parquet(output / "episode_features.parquet", engine="pyarrow"),
        output / "parameter_embedding.png",
    )
    selected_score = next(
        score
        for score in discovery.mixture.candidate_scores
        if score.component_count == component_count
    )
    try:
        validation_metrics = evaluate_assigned_validation_episodes(
            validation,
            validation_assignment.component_ids,
            discovery.mode_models,
            sample_time_s=config.sample_time_s,
            horizon=config.multi_step_horizon,
            validate_trajectory=validate_arx_multistep,
        )
        error_blocks = _validation_error_blocks(
            validation,
            validation_assignment,
            discovery,
            horizon=config.multi_step_horizon,
        )
    except (TypeError, ValueError, FloatingPointError) as exc:
        validation_sizes = np.bincount(
            validation_assignment.component_ids,
            minlength=component_count,
        )
        _write_json(
            {
                "schema_version": 1,
                "stage": "independent_component_validation",
                "status": "failed",
                "failure_type": type(exc).__name__,
                "failure_message": str(exc),
                "selected_k": component_count,
                "hit_candidate_k_max": component_count == config.discovery.k_max,
                "validation_cluster_sizes": validation_sizes.tolist(),
                "empty_validation_components": np.flatnonzero(
                    validation_sizes == 0
                ).tolist(),
                "model_library_persisted": False,
                "fallback_component_count_used": False,
            },
            output / "discovery_failure.json",
        )
        raise RuntimeError(
            "independent validation failed; public BIC/features/assignments were "
            "persisted and no alternate component count was substituted"
        ) from exc
    grid_model = GridFrequencyModel(config.grid_params)
    frequency_errors = {
        component: propagate_grid_frequency_errors(errors, grid_model=grid_model)
        for component, errors in error_blocks.items()
    }
    rocof_errors = {
        component: frequency_errors_to_rocof_errors(
            errors,
            sample_time_s=config.sample_time_s,
        )
        for component, errors in frequency_errors.items()
    }

    common_validation_phi = np.vstack(
        [fit.regression_matrix for fit in validation_assignment.episode_fits]
    )
    distinguishability = _pairwise_distinguishability_matrix(
        np.vstack([model.theta for model in discovery.mode_models]),
        np.asarray(
            [model.residual_variance for model in discovery.mode_models],
            dtype=np.float64,
        ),
        common_validation_phi,
    )
    power_quantiles = {
        metric.component_id: metric.error_quantiles_for_library
        for metric in validation_metrics
    }
    frequency_quantiles = {
        component: {
            lead: float(value)
            for lead, value in enumerate(
                np.quantile(np.abs(errors), 0.95, axis=0), start=1
            )
        }
        for component, errors in frequency_errors.items()
    }
    rocof_quantiles = {
        component: {
            lead: float(value)
            for lead, value in enumerate(
                np.quantile(np.abs(errors), 0.95, axis=0), start=1
            )
        }
        for component, errors in rocof_errors.items()
    }
    metadata = discovery_metadata_from_selection(
        discovery.mixture,
        random_seed=config.discovery.random_seed,
    )
    library = mode_library_from_discovery(
        discovery.mode_models,
        feature_scaler=discovery.feature_scaler,
        discovery_metadata=metadata,
        multi_step_power_error_quantiles_pu=power_quantiles,
        multi_step_frequency_error_quantiles_hz=frequency_quantiles,
        multi_step_rocof_error_quantiles_hz_per_s=rocof_quantiles,
        stay_probability=stay_probability,
    )

    library_path = output / "mode_library.json"
    library.save_json(library_path)
    library_digest = sha256_file(library_path)
    mode_metrics = _mode_metrics_frame(discovery, validation_metrics)
    multistep = _multistep_frame(
        validation_metrics, frequency_errors, rocof_errors
    )
    distinguishability_frame = _distinguishability_frame(distinguishability)
    mode_metrics.to_csv(output / "mode_model_metrics.csv", index=False)
    multistep.to_csv(output / "multi_step_error_quantiles.csv", index=False)
    distinguishability_frame.to_csv(
        output / "distinguishability_matrix.csv", index=False
    )
    _write_json(
        {
            "schema_version": 1,
            "information_boundary": "public_train_and_validation_only",
            "training_episode_count": len(training),
            "validation_episode_count": len(validation),
            "selected_k": discovery.mixture.selected_k,
            "selected_by": "minimum_training_bic",
            "selected_gmm_converged": selected_score.converged,
            "silhouette": discovery.mixture.silhouette,
            "hit_candidate_k_max": (
                discovery.mixture.selected_k == config.discovery.k_max
            ),
            "model_library_sha256": library_digest,
            "switch_epsilon": config.switch_epsilon,
            "derived_stay_probability": stay_probability,
            "multi_step_horizon": config.multi_step_horizon,
            "pca_role": "parameter_embedding_plot_only",
            "mode_library_quantile_units": {
                "multi_step_power_error_quantiles_pu": "pu",
                "multi_step_frequency_error_quantiles_hz": "Hz",
                "multi_step_rocof_error_quantiles_hz_per_s": "Hz/s",
            },
            "gmm_numerical_configuration": {
                "candidate_k_min": config.discovery.k_min,
                "candidate_k_max": config.discovery.k_max,
                "covariance_type": config.discovery.covariance_type,
                "n_init": config.discovery.n_init,
                "max_iter": config.discovery.max_iter,
                "reg_covar": config.discovery.reg_covar,
                "random_seed": config.discovery.random_seed,
            },
            "gmm_configuration_provenance": (
                "versioned public-signal configuration; no external reference "
                "labels, reference-K override, or score-driven hyperparameter search"
            ),
        },
        output / "label_free_summary.json",
    )
    if not selected_score.converged:
        LOGGER.error(
            "BIC-selected GMM did not converge; persisted audit marks it explicitly"
        )
    missing = [name for name in REQUIRED_LABEL_FREE_ARTIFACTS if not (output / name).is_file()]
    if missing:
        raise RuntimeError(f"label-free artifact write is incomplete: {missing}")
    return LabelFreeDiscoveryRun(
        output_directory=output,
        discovery=discovery,
        validation_assignment=validation_assignment,
        validation_metrics=tuple(validation_metrics),
        mode_library=library,
        model_library_sha256=library_digest,
        frequency_error_hz_by_component=frequency_errors,
        rocof_error_hz_per_s_by_component=rocof_errors,
        distinguishability=distinguishability,
    )


__all__ = [
    "ARX_PARAMETER_NAMES",
    "LabelFreeDiscoveryRun",
    "OfflinePipelineConfig",
    "REQUIRED_LABEL_FREE_ARTIFACTS",
    "default_arx_fitter_api",
    "frequency_errors_to_rocof_errors",
    "offline_pipeline_config_from_base_config",
    "propagate_grid_frequency_errors",
    "run_label_free_mode_discovery",
]
