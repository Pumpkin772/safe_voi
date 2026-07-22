"""Reproducible Phase-4 online-diagnosis and OOD evaluation pipeline.

The module enforces a hard information barrier between runtime diagnostics and
evaluation truth.  Public trajectories are authenticated before use.  Runtime
records are persisted and hashed before the private identification metadata or
the Phase-3 train-label alignment is opened.  The resulting truth join and the
many-to-one mapping from six native components to four reference classes are
therefore evaluation-only artifacts and can never influence the filter.

OOD hysteresis is selected with leave-one-trajectory-out cross-validation on
known-mode calibration trajectories only.  Held-out OOD trajectories are
generated and evaluated only after the selected thresholds are frozen.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import csv
import itertools
import json
import math
from pathlib import Path
import subprocess
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray
import pandas as pd

from d5freq.data import (
    ExcitationSignals,
    IdentificationTrajectory,
    PrivateTrajectoryMetadata,
    load_public_identification_data,
)
from d5freq.estimation.mode_belief_filter import (
    build_online_arx_regressor,
    build_sticky_transition_matrix,
)
from d5freq.estimation.online_diagnostic import OnlineModeDiagnostic
from d5freq.estimation.ood_detector import (
    OODCalibrationArtifact,
    OODDetectorConfig,
    OODHysteresisStateMachine,
    OODState,
    calibration_scores_from_residuals,
)
from d5freq.evaluation.online_diagnostic_metrics import (
    evaluate_false_alarms,
    evaluate_mode_probabilities,
    evaluate_ood_detection,
    evaluate_switch_detection,
)
from d5freq.evaluation.online_diagnosis_scenarios import (
    EvaluationTruthTimeline,
    simulate_scheduled_ibr_trajectory,
)
from d5freq.identification.model_library import ModeLibrary
from d5freq.interfaces import Measurement
from d5freq.models.hidden_mode_ibr import IBRModeParams
from d5freq.simulation.mode_schedules import PiecewiseConstantModeSchedule
from d5freq.utils.config import config_sha256, load_yaml, save_yaml
from d5freq.utils.environment import collect_environment_info
from d5freq.utils.hashing import (
    file_sha256_manifest,
    sha256_file,
    sha256_json,
)


FloatArray = NDArray[np.float64]
PHASE4_SCHEMA_VERSION = "d5freq.phase4.v1"
RUNTIME_LOG_SCHEMA_VERSION = "d5freq.runtime_diagnostic.v1"
PHASE4_GENERATED_SCENARIOS: tuple[tuple[str, int, str | None], ...] = (
    ("nominal_to_sluggish", 0, "sluggish"),
    ("nominal_to_unavailable", 1, "unavailable"),
    ("load_step_no_mode", 2, None),
    ("noise_change_no_mode", 3, None),
    ("ood_asymmetric_limit", 0, "asymmetric_limit"),
    ("ood_time_varying_delay", 1, "time_varying_delay"),
)
PHASE4_SOURCE_PATHS: tuple[str, ...] = (
    "scripts/03_calibrate_ood.py",
    "src/d5freq/evaluation/phase4_pipeline.py",
    "src/d5freq/evaluation/online_diagnostic_metrics.py",
    "src/d5freq/evaluation/online_diagnosis_scenarios.py",
    "src/d5freq/estimation/mode_belief_filter.py",
    "src/d5freq/estimation/ood_detector.py",
    "src/d5freq/estimation/online_diagnostic.py",
    "src/d5freq/identification/model_library.py",
    "src/d5freq/identification/arx.py",
    "src/d5freq/data/generate_identification_data.py",
    "src/d5freq/data/schemas.py",
    "src/d5freq/interfaces.py",
    "src/d5freq/models/hidden_mode_ibr.py",
    "src/d5freq/simulation/integrators.py",
    "src/d5freq/simulation/mode_schedules.py",
    "src/d5freq/utils/config.py",
    "src/d5freq/utils/environment.py",
    "src/d5freq/utils/hashing.py",
    "src/d5freq/utils/seeds.py",
)


def _strict_json(path: Path) -> Any:
    """Load UTF-8 JSON while rejecting duplicate keys and non-finite values."""

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r} in {path}")
            result[key] = value
        return result

    def reject_constant(token: str) -> None:
        raise ValueError(f"non-finite JSON token {token!r} in {path}")

    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=unique_object,
        parse_constant=reject_constant,
    )


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def _portable_path(path: Path, repository_root: Path, raw_value: str | Path) -> str:
    """Prefer a repository-relative path, otherwise retain the literal CLI input."""

    try:
        return path.resolve().relative_to(repository_root.resolve()).as_posix()
    except ValueError:
        return Path(raw_value).as_posix()


def phase4_source_hashes(repository_root: str | Path) -> dict[str, str]:
    """Hash every in-repository source that materially produces Phase-4 output."""

    root = Path(repository_root).expanduser().resolve()
    hashes: dict[str, str] = {}
    for relative in PHASE4_SOURCE_PATHS:
        source = root / Path(relative)
        if not source.is_file() or source.is_symlink():
            raise FileNotFoundError(f"Phase-4 source must be a regular file: {source}")
        hashes[relative] = sha256_file(source)
    return hashes


def _git_provenance(repository_root: Path) -> dict[str, object]:
    def run_git(*arguments: str) -> str:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10.0,
        )
        return completed.stdout.strip()

    try:
        commit = run_git("rev-parse", "HEAD")
        status = run_git("status", "--porcelain=v1", "--untracked-files=all")
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("Phase-4 run requires readable Git provenance") from exc
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise ValueError("git rev-parse returned an invalid commit digest")
    changed_paths = tuple(
        sorted(
            line[3:].replace("\\", "/")
            for line in status.splitlines()
            if len(line) >= 4
        )
    )
    return {
        "commit": commit,
        "worktree_dirty": bool(status),
        "changed_path_count": len(changed_paths),
        "changed_paths": list(changed_paths),
    }


def _reproducibility_provenance(
    repository_root: Path,
    settings: "Phase4Settings",
) -> dict[str, object]:
    scenario_seeds = {
        scenario: settings.master_seed + 40_000 + ordinal
        for ordinal, (scenario, _, _) in enumerate(PHASE4_GENERATED_SCENARIOS)
    }
    environment = collect_environment_info(
        extra={
            "project_environment": "topo_sfr",
            "phase": 4,
            "solver_use": "version_capture_only_no_optimization_in_phase4",
        }
    )
    return {
        "schema_version": PHASE4_SCHEMA_VERSION,
        "git": _git_provenance(repository_root),
        "environment": environment,
        "randomness": {
            "master_seed": settings.master_seed,
            "numpy_bit_generator": "PCG64",
            "generated_scenario_measurement_seeds": scenario_seeds,
            "hysteresis_selection": "deterministic_no_rng",
            "public_test_trajectories": "frozen_authenticated_inputs",
        },
        "source_sha256": phase4_source_hashes(repository_root),
    }


def _finite_positive(value: object, name: str) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise TypeError(f"{name} must be a real number")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= 0.0:
        raise ValueError(f"{name} must be finite and positive")
    return normalized


def _finite_real(value: object, name: str) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise TypeError(f"{name} must be a real number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


def _finite_nonnegative(value: object, name: str) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise TypeError(f"{name} must be a real number")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0.0:
        raise ValueError(f"{name} must be finite and non-negative")
    return normalized


def _positive_integer(value: object, name: str) -> int:
    if isinstance(value, (bool, np.bool_)) or int(value) != value:
        raise TypeError(f"{name} must be an integer")
    normalized = int(value)
    if normalized <= 0:
        raise ValueError(f"{name} must be positive")
    return normalized


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    if not all(isinstance(key, str) for key in value):
        raise TypeError(f"{name} keys must be strings")
    return dict(value)


def _number_sequence(
    value: object,
    name: str,
    *,
    positive: bool,
) -> tuple[float, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(f"{name} must be a sequence")
    validator = _finite_positive if positive else _finite_nonnegative
    normalized = tuple(validator(item, name) for item in value)
    if not normalized or len(set(normalized)) != len(normalized):
        raise ValueError(f"{name} must be non-empty and contain no duplicates")
    return normalized


def _integer_sequence(value: object, name: str) -> tuple[int, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(f"{name} must be a sequence")
    normalized = tuple(_positive_integer(item, name) for item in value)
    if not normalized or len(set(normalized)) != len(normalized):
        raise ValueError(f"{name} must be non-empty and contain no duplicates")
    return normalized


@dataclass(frozen=True, slots=True)
class Phase4Settings:
    """Validated Phase-4 settings resolved from ``configs/base.yaml``."""

    master_seed: int
    control_period_s: float
    integration_step_s: float
    measurement_noise_std_pu: float
    epsilon_switch: float
    epsilon_sensitivity: tuple[float, ...]
    belief_floor: float
    variance_floor_pu2: float
    belief_detection_threshold: float
    belief_detection_hold_steps: int
    false_alarm_hold_steps: int
    default_ood_config: OODDetectorConfig
    alpha_on_candidates: tuple[float, ...]
    alpha_off_candidates: tuple[float, ...]
    hold_on_candidates: tuple[int, ...]
    hold_off_candidates: tuple[int, ...]
    unique_test_excitations: int
    switch_time_s: float
    additional_noise_std_pu: float
    load_step_frequency_proxy_pu: float
    load_step_start_s: float
    load_step_end_s: float
    reliability_bins: int

    @classmethod
    def from_base_config(cls, base_config: Mapping[str, Any]) -> "Phase4Settings":
        project = _mapping(base_config.get("project"), "project")
        grid = _mapping(base_config.get("grid"), "grid")
        identification = _mapping(
            base_config.get("identification"), "identification"
        )
        generation = _mapping(
            identification.get("generation"), "identification.generation"
        )
        belief = _mapping(base_config.get("belief"), "belief")
        ood = _mapping(base_config.get("ood"), "ood")
        search = _mapping(ood.get("calibration_search"), "ood.calibration_search")
        evaluation = _mapping(
            base_config.get("phase4_evaluation"), "phase4_evaluation"
        )
        if base_config.get("schema_version") != 1:
            raise ValueError("base config must use schema_version 1")
        seed = project.get("seed")
        if isinstance(seed, bool) or int(seed) != seed or int(seed) < 0:
            raise ValueError("project.seed must be a non-negative integer")
        epsilon = _finite_nonnegative(
            belief.get("switch_epsilon"), "belief.switch_epsilon"
        )
        epsilon_values = _number_sequence(
            belief.get("switch_epsilon_sensitivity"),
            "belief.switch_epsilon_sensitivity",
            positive=True,
        )
        if epsilon not in epsilon_values:
            raise ValueError("configured switch epsilon must appear in sensitivity list")
        alpha_on = _finite_positive(ood.get("alpha_on"), "ood.alpha_on")
        alpha_off = _finite_positive(ood.get("alpha_off"), "ood.alpha_off")
        hold_on = _positive_integer(ood.get("hold_on_steps"), "ood.hold_on_steps")
        hold_off = _positive_integer(
            ood.get("hold_off_steps"), "ood.hold_off_steps"
        )
        alpha_on_candidates = _number_sequence(
            search.get("alpha_on"), "ood.calibration_search.alpha_on", positive=True
        )
        alpha_off_candidates = _number_sequence(
            search.get("alpha_off"),
            "ood.calibration_search.alpha_off",
            positive=True,
        )
        hold_on_candidates = _integer_sequence(
            search.get("hold_on_steps"),
            "ood.calibration_search.hold_on_steps",
        )
        hold_off_candidates = _integer_sequence(
            search.get("hold_off_steps"),
            "ood.calibration_search.hold_off_steps",
        )
        if alpha_on not in alpha_on_candidates or alpha_off not in alpha_off_candidates:
            raise ValueError("declared OOD thresholds must appear in calibration search")
        if hold_on not in hold_on_candidates or hold_off not in hold_off_candidates:
            raise ValueError("declared OOD holds must appear in calibration search")
        if ood.get("calibration_known_modes_only") is not True:
            raise ValueError("OOD calibration must be explicitly known-modes-only")
        variance_floor = _finite_positive(
            belief.get("residual_variance_floor"),
            "belief.residual_variance_floor",
        )
        start = _finite_nonnegative(
            evaluation.get("load_step_start_s"),
            "phase4_evaluation.load_step_start_s",
        )
        end = _finite_nonnegative(
            evaluation.get("load_step_end_s"),
            "phase4_evaluation.load_step_end_s",
        )
        if end <= start:
            raise ValueError("load-step proxy end must follow its start")
        return cls(
            master_seed=int(seed),
            control_period_s=_finite_positive(
                grid.get("control_period_s"), "grid.control_period_s"
            ),
            integration_step_s=_finite_positive(
                grid.get("integration_step_s"), "grid.integration_step_s"
            ),
            measurement_noise_std_pu=_finite_nonnegative(
                generation.get("power_measurement_noise_std_pu"),
                "identification.generation.power_measurement_noise_std_pu",
            ),
            epsilon_switch=epsilon,
            epsilon_sensitivity=epsilon_values,
            belief_floor=_finite_positive(
                belief.get("probability_floor"), "belief.probability_floor"
            ),
            variance_floor_pu2=variance_floor,
            belief_detection_threshold=_finite_positive(
                belief.get("detection_probability"),
                "belief.detection_probability",
            ),
            belief_detection_hold_steps=_positive_integer(
                belief.get("detection_hold_steps"),
                "belief.detection_hold_steps",
            ),
            false_alarm_hold_steps=_positive_integer(
                belief.get("false_alarm_hold_steps"),
                "belief.false_alarm_hold_steps",
            ),
            default_ood_config=OODDetectorConfig(
                alpha_on=alpha_on,
                alpha_off=alpha_off,
                L_on=hold_on,
                L_off=hold_off,
                variance_floor=variance_floor,
            ),
            alpha_on_candidates=alpha_on_candidates,
            alpha_off_candidates=alpha_off_candidates,
            hold_on_candidates=hold_on_candidates,
            hold_off_candidates=hold_off_candidates,
            unique_test_excitations=_positive_integer(
                evaluation.get("unique_test_excitations"),
                "phase4_evaluation.unique_test_excitations",
            ),
            switch_time_s=_finite_positive(
                evaluation.get("switch_time_s"),
                "phase4_evaluation.switch_time_s",
            ),
            additional_noise_std_pu=_finite_nonnegative(
                evaluation.get("additional_noise_std_pu"),
                "phase4_evaluation.additional_noise_std_pu",
            ),
            load_step_frequency_proxy_pu=_finite_real(
                evaluation.get("load_step_frequency_proxy_pu"),
                "phase4_evaluation.load_step_frequency_proxy_pu",
            ),
            load_step_start_s=start,
            load_step_end_s=end,
            reliability_bins=_positive_integer(
                evaluation.get("reliability_bins"),
                "phase4_evaluation.reliability_bins",
            ),
        )


@dataclass(frozen=True, slots=True)
class CalibrationComputation:
    """Known-only calibration artifact plus auditable row-wise residuals."""

    artifact: OODCalibrationArtifact
    scores_by_trajectory: Mapping[str, FloatArray]
    residual_table: pd.DataFrame
    innovation_variances_pu2: FloatArray


@dataclass(frozen=True, slots=True)
class RuntimeEpisode:
    """Evaluation-orchestrator episode; truth is never consumed by runtime."""

    trajectory: IdentificationTrajectory
    trajectory_sha256: str
    source_kind_eval_only: str
    scenario_eval_only: str
    input_sha256: str
    truth_timeline_eval_only: EvaluationTruthTimeline | None = None


@dataclass(frozen=True, slots=True)
class Phase4RunResult:
    output_directory: Path
    calibration_artifact_sha256: str
    runtime_log_sha256: str
    artifact_manifest_sha256: str
    selected_ood_config: OODDetectorConfig
    metrics: Mapping[str, Any]


def compute_all_component_arx_residuals(
    trajectory: IdentificationTrajectory,
    mode_library: ModeLibrary,
) -> FloatArray:
    """Return residuals for every valid ARX sample and every native component."""

    if not isinstance(trajectory, IdentificationTrajectory):
        raise TypeError("trajectory must be an IdentificationTrajectory")
    if not isinstance(mode_library, ModeLibrary):
        raise TypeError("mode_library must be a ModeLibrary")
    thetas = np.vstack([model.theta for model in mode_library.models])
    sample_count = len(trajectory.time_s)
    residuals = np.empty((sample_count - 2, len(mode_library.models)), dtype=float)
    for output_row, sample_index in enumerate(range(2, sample_count)):
        regressor = build_online_arx_regressor(
            p_ibr_k_minus_1_pu=float(trajectory.p_ibr_pu[sample_index - 1]),
            p_ibr_k_minus_2_pu=float(trajectory.p_ibr_pu[sample_index - 2]),
            u_ibr_k_minus_1_pu=float(trajectory.u_ibr_pu[sample_index - 1]),
            u_ibr_k_minus_2_pu=float(trajectory.u_ibr_pu[sample_index - 2]),
            omega_k_minus_1_pu=float(trajectory.omega_pu[sample_index - 1]),
            omega_k_minus_2_pu=float(trajectory.omega_pu[sample_index - 2]),
        )
        predictions = thetas @ regressor
        residuals[output_row] = float(trajectory.p_ibr_pu[sample_index]) - predictions
    if not np.all(np.isfinite(residuals)):
        raise FloatingPointError("calibration ARX residuals became non-finite")
    return residuals


def calibrate_ood_from_trajectories(
    trajectories: Sequence[IdentificationTrajectory],
    mode_library: ModeLibrary,
    *,
    measurement_noise_variance_pu2: float,
    variance_floor_pu2: float,
    dataset_sha256: str,
    split_manifest_sha256: str,
    mode_library_sha256: str,
    source_hash_by_trajectory_id: Mapping[str, str],
) -> CalibrationComputation:
    """Build the strict known-only conformal artifact from authenticated data."""

    episodes = tuple(trajectories)
    if not episodes:
        raise ValueError("calibration trajectories must be non-empty")
    if not isinstance(mode_library, ModeLibrary):
        raise TypeError("mode_library must be a ModeLibrary")
    measurement_variance = _finite_nonnegative(
        measurement_noise_variance_pu2, "measurement_noise_variance_pu2"
    )
    variance_floor = _finite_positive(variance_floor_pu2, "variance_floor_pu2")
    identifiers = tuple(trajectory.trajectory_id for trajectory in episodes)
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("calibration trajectory IDs must be unique")
    source_hashes = dict(source_hash_by_trajectory_id)
    if set(source_hashes) != set(identifiers):
        raise ValueError("source hashes must exactly cover calibration trajectories")
    variances = np.maximum(
        np.asarray(
            [model.residual_variance for model in mode_library.models],
            dtype=np.float64,
        )
        + measurement_variance,
        variance_floor,
    )
    all_scores: list[FloatArray] = []
    scores_by_id: dict[str, FloatArray] = {}
    rows: list[dict[str, object]] = []
    for trajectory in sorted(episodes, key=lambda item: item.trajectory_id):
        residuals = compute_all_component_arx_residuals(trajectory, mode_library)
        scores = calibration_scores_from_residuals(
            residuals,
            variances,
            variance_floor=variance_floor,
        )
        scores_by_id[trajectory.trajectory_id] = scores.copy()
        all_scores.append(scores)
        for local_index, (residual, score) in enumerate(
            zip(residuals, scores, strict=True), start=2
        ):
            row: dict[str, object] = {
                "trajectory_id": trajectory.trajectory_id,
                "sample_index": local_index,
                "time_s": float(trajectory.time_s[local_index]),
                "ood_score": float(score),
            }
            for component_id, value in enumerate(residual):
                row[f"residual_{component_id}_pu"] = float(value)
                row[f"innovation_variance_{component_id}_pu2"] = float(
                    variances[component_id]
                )
            rows.append(row)
    concatenated = np.concatenate(all_scores)
    component_ids = tuple(range(len(mode_library.models)))
    artifact = OODCalibrationArtifact(
        calibration_scores=tuple(float(value) for value in concatenated),
        dataset_sha256=dataset_sha256,
        split_manifest_sha256=split_manifest_sha256,
        mode_library_sha256=mode_library_sha256,
        mode_library_logical_sha256=sha256_json(mode_library.to_dict()),
        source_trajectory_sha256=tuple(
            source_hashes[identifier] for identifier in sorted(identifiers)
        ),
        known_component_ids=component_ids,
        # Every residual vector is evaluated against every native component.
        covered_component_ids=component_ids,
        measurement_noise_variance_pu2=measurement_variance,
        variance_floor_pu2=variance_floor,
    )
    return CalibrationComputation(
        artifact=artifact,
        scores_by_trajectory=scores_by_id,
        residual_table=pd.DataFrame(rows),
        innovation_variances_pu2=variances,
    )


def _conformal_pvalues(
    runtime_scores: FloatArray,
    reference_scores: FloatArray,
) -> FloatArray:
    sorted_reference = np.sort(np.asarray(reference_scores, dtype=np.float64))
    scores = np.asarray(runtime_scores, dtype=np.float64)
    if sorted_reference.ndim != 1 or sorted_reference.size == 0:
        raise ValueError("reference calibration scores must be non-empty")
    if scores.ndim != 1 or scores.size == 0:
        raise ValueError("runtime score fold must be non-empty")
    first_equal_or_greater = np.searchsorted(
        sorted_reference, scores, side="left"
    )
    greater_or_equal = sorted_reference.size - first_equal_or_greater
    return np.asarray(
        (1.0 + greater_or_equal) / (sorted_reference.size + 1.0),
        dtype=np.float64,
    )


def select_hysteresis_known_only_cv(
    scores_by_trajectory: Mapping[str, ArrayLike],
    *,
    alpha_on_candidates: Sequence[float],
    alpha_off_candidates: Sequence[float],
    hold_on_candidates: Sequence[int],
    hold_off_candidates: Sequence[int],
    declared_default: OODDetectorConfig,
    variance_floor: float,
) -> tuple[OODDetectorConfig, pd.DataFrame]:
    """Select hysteresis by leave-one-trajectory-out known-only false alarms.

    No OOD labels, scores, trajectories, or detection objectives are accepted
    by this API.  Candidate ranking is lexicographic: false-active episodes,
    false-active samples, any non-KNOWN alert samples, then distance to the
    predeclared defaults.  This keeps OOD test data out of model selection.
    """

    folds = {
        str(identifier): np.asarray(scores, dtype=np.float64)
        for identifier, scores in scores_by_trajectory.items()
    }
    if len(folds) < 2:
        raise ValueError("trajectory-level CV requires at least two trajectories")
    if any(
        values.ndim != 1
        or values.size == 0
        or np.any(~np.isfinite(values))
        or np.any(values < 0.0)
        for values in folds.values()
    ):
        raise ValueError("every trajectory score fold must be finite and non-negative")
    on_values = tuple(float(value) for value in alpha_on_candidates)
    off_values = tuple(float(value) for value in alpha_off_candidates)
    lon_values = tuple(int(value) for value in hold_on_candidates)
    loff_values = tuple(int(value) for value in hold_off_candidates)
    if not on_values or not off_values or not lon_values or not loff_values:
        raise ValueError("hysteresis search ranges must be non-empty")
    ordered_ids = tuple(sorted(folds))
    held_out_pvalues: dict[str, FloatArray] = {}
    for identifier in ordered_ids:
        reference = np.concatenate(
            [folds[other] for other in ordered_ids if other != identifier]
        )
        held_out_pvalues[identifier] = _conformal_pvalues(
            folds[identifier], reference
        )

    records: list[dict[str, object]] = []
    for alpha_on, alpha_off, hold_on, hold_off in itertools.product(
        on_values, off_values, lon_values, loff_values
    ):
        if not 0.0 < alpha_on < alpha_off < 1.0:
            continue
        config = OODDetectorConfig(
            alpha_on=alpha_on,
            alpha_off=alpha_off,
            L_on=hold_on,
            L_off=hold_off,
            variance_floor=variance_floor,
        )
        active_samples = 0
        alert_samples = 0
        active_episodes = 0
        alert_episodes = 0
        sample_count = 0
        for identifier in ordered_ids:
            machine = OODHysteresisStateMachine(config)
            episode_active = False
            episode_alert = False
            for pvalue in held_out_pvalues[identifier]:
                update = machine.update(float(pvalue))
                is_active = update.state is OODState.OOD_ACTIVE
                is_alert = update.state is not OODState.KNOWN
                active_samples += int(is_active)
                alert_samples += int(is_alert)
                episode_active = episode_active or is_active
                episode_alert = episode_alert or is_alert
                sample_count += 1
            active_episodes += int(episode_active)
            alert_episodes += int(episode_alert)
        distance = (
            abs(math.log(alpha_on / declared_default.alpha_on))
            + abs(math.log(alpha_off / declared_default.alpha_off))
            + abs(hold_on - declared_default.L_on) / declared_default.L_on
            + abs(hold_off - declared_default.L_off) / declared_default.L_off
        )
        records.append(
            {
                "alpha_on": alpha_on,
                "alpha_off": alpha_off,
                "hold_on_steps": hold_on,
                "hold_off_steps": hold_off,
                "known_cv_trajectory_count": len(ordered_ids),
                "known_cv_sample_count": sample_count,
                "false_active_episode_count": active_episodes,
                "false_active_episode_rate": active_episodes / len(ordered_ids),
                "false_active_sample_count": active_samples,
                "false_active_sample_rate": active_samples / sample_count,
                "false_alert_episode_count": alert_episodes,
                "false_alert_episode_rate": alert_episodes / len(ordered_ids),
                "false_alert_sample_count": alert_samples,
                "false_alert_sample_rate": alert_samples / sample_count,
                "tie_break_distance_to_declared_default": distance,
                "selection_population": "known_modes_only",
            }
        )
    if not records:
        raise ValueError("hysteresis search produced no valid alpha_on < alpha_off pair")
    records.sort(
        key=lambda row: (
            int(row["false_active_episode_count"]),
            int(row["false_active_sample_count"]),
            int(row["false_alert_sample_count"]),
            float(row["tie_break_distance_to_declared_default"]),
            float(row["alpha_on"]),
            float(row["alpha_off"]),
            int(row["hold_on_steps"]),
            int(row["hold_off_steps"]),
        )
    )
    for rank, row in enumerate(records, start=1):
        row["selection_rank"] = rank
        row["selected"] = rank == 1
    best = records[0]
    selected = OODDetectorConfig(
        alpha_on=float(best["alpha_on"]),
        alpha_off=float(best["alpha_off"]),
        L_on=int(best["hold_on_steps"]),
        L_off=int(best["hold_off_steps"]),
        variance_floor=variance_floor,
    )
    return selected, pd.DataFrame(records)


def build_majority_component_mapping(
    cluster_assignments: pd.DataFrame,
    private_metadata: Sequence[PrivateTrajectoryMetadata],
    *,
    component_count: int,
    class_labels: Sequence[str],
) -> tuple[dict[int, str], dict[int, dict[str, int]]]:
    """Build a Phase-3-train-only many-to-one component/reference mapping."""

    required = {"trajectory_id", "dataset_split", "component_id"}
    if not required.issubset(cluster_assignments.columns):
        raise ValueError("cluster assignments are missing required columns")
    labels = tuple(str(value) for value in class_labels)
    if not labels or len(set(labels)) != len(labels):
        raise ValueError("class_labels must be non-empty and unique")
    metadata_rows = [
        {
            "trajectory_id": item.trajectory_id,
            "split": item.split,
            "mode_name_eval_only": item.mode_name_eval_only,
        }
        for item in private_metadata
        if item.split == "train"
    ]
    metadata_frame = pd.DataFrame(metadata_rows)
    assignments = cluster_assignments.loc[
        cluster_assignments["dataset_split"] == "train",
        ["trajectory_id", "component_id"],
    ].copy()
    merged = assignments.merge(
        metadata_frame,
        how="inner",
        on="trajectory_id",
        validate="one_to_one",
    )
    if len(merged) != len(assignments):
        raise ValueError("train assignments do not fully join private train metadata")
    if not set(merged["mode_name_eval_only"]).issubset(labels):
        raise ValueError("private train metadata contains unknown reference modes")
    mapping: dict[int, str] = {}
    evidence: dict[int, dict[str, int]] = {}
    for component_id in range(component_count):
        values = merged.loc[
            merged["component_id"] == component_id, "mode_name_eval_only"
        ]
        if values.empty:
            raise ValueError(f"component {component_id} has no Phase-3 train episodes")
        counts = Counter(str(value) for value in values)
        evidence[component_id] = {label: int(counts.get(label, 0)) for label in labels}
        mapping[component_id] = max(
            labels,
            key=lambda label: (counts.get(label, 0), -labels.index(label)),
        )
    return mapping, evidence


def aggregate_component_beliefs(
    component_probabilities: ArrayLike,
    component_to_class: Mapping[int, str],
    class_labels: Sequence[str],
) -> FloatArray:
    """Aggregate native component probabilities through an evaluation-only map."""

    probabilities = np.asarray(component_probabilities, dtype=np.float64)
    if probabilities.ndim != 2 or probabilities.shape[0] == 0:
        raise ValueError("component_probabilities must be a non-empty matrix")
    if np.any(~np.isfinite(probabilities)) or np.any(probabilities < 0.0):
        raise ValueError("component probabilities must be finite and non-negative")
    if not np.allclose(probabilities.sum(axis=1), 1.0, rtol=1e-9, atol=1e-9):
        raise ValueError("component probability rows must sum to one")
    labels = tuple(str(value) for value in class_labels)
    if not labels or len(set(labels)) != len(labels):
        raise ValueError("class_labels must be non-empty and unique")
    mapping = {int(key): str(value) for key, value in component_to_class.items()}
    if set(mapping) != set(range(probabilities.shape[1])):
        raise ValueError("component mapping must cover every probability column")
    if not set(mapping.values()).issubset(labels):
        raise ValueError("component mapping references an unknown class")
    aggregated = np.zeros((probabilities.shape[0], len(labels)), dtype=np.float64)
    label_to_index = {label: index for index, label in enumerate(labels)}
    for component_id, label in mapping.items():
        aggregated[:, label_to_index[label]] += probabilities[:, component_id]
    aggregated /= aggregated.sum(axis=1, keepdims=True)
    return aggregated


def _prepare_output_directory(path: Path) -> Path:
    raw = path.expanduser()
    if raw.is_symlink():
        raise ValueError("Phase-4 output directory must not be a symbolic link")
    output = raw.resolve()
    if output.exists():
        if not output.is_dir():
            raise NotADirectoryError(output)
        if any(output.iterdir()):
            raise FileExistsError(
                f"Phase-4 output directory must be new or empty: {output}"
            )
    else:
        output.mkdir(parents=True)
    return output


def _public_provenance(
    public_directory: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    manifest_path = public_directory / "public_manifest.json"
    split_path = public_directory / "split_manifest.csv"
    manifest = _strict_json(manifest_path)
    if not isinstance(manifest, dict):
        raise ValueError("public manifest must be a JSON object")
    required_manifest = {
        "dataset_sha256",
        "split_manifest_sha256",
        "trajectory_manifest_sha256",
        "split_counts",
        "split_names",
        "trajectory_count",
    }
    if not required_manifest.issubset(manifest):
        raise ValueError("public manifest is missing required provenance fields")
    rows: dict[str, dict[str, str]] = {}
    with split_path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != ("trajectory_id", "split", "sha256"):
            raise ValueError("split manifest columns do not match the public schema")
        for row in reader:
            identifier = str(row["trajectory_id"])
            if identifier in rows:
                raise ValueError("split manifest contains a duplicate trajectory ID")
            rows[identifier] = {
                "split": str(row["split"]),
                "sha256": str(row["sha256"]),
            }
    if len(rows) != int(manifest["trajectory_count"]):
        raise ValueError("split manifest trajectory count mismatch")
    return manifest, rows


def _load_modes(path: Path, *, ood: bool) -> dict[str, IBRModeParams]:
    payload = load_yaml(path)
    if payload.get("schema_version") != 1:
        raise ValueError(f"mode config must use schema_version 1: {path}")
    if payload.get("truth_access") != "simulator_and_evaluation_only":
        raise ValueError("mode truth must be simulator/evaluation-only")
    key = "ood_modes" if ood else "known_modes"
    if ood and (
        payload.get("exclude_from_identification_training") is not True
        or payload.get("exclude_from_ood_calibration") is not True
    ):
        raise ValueError("OOD modes must be excluded from fitting and calibration")
    values = payload.get(key)
    if not isinstance(values, Mapping) or not values:
        raise ValueError(f"mode config contains no {key} mapping")
    return {
        str(name): IBRModeParams.from_mapping(str(name), fields)
        for name, fields in values.items()
    }


def _external_signal_hash(trajectory: IdentificationTrajectory) -> str:
    return sha256_json(
        {
            "time_s": trajectory.time_s.tolist(),
            "u_ibr_pu": trajectory.u_ibr_pu.tolist(),
            "omega_pu": trajectory.omega_pu.tolist(),
        }
    )


def _select_unique_test_inputs(
    test_trajectories: Sequence[IdentificationTrajectory],
    required_count: int,
) -> tuple[tuple[IdentificationTrajectory, str], ...]:
    selected: list[tuple[IdentificationTrajectory, str]] = []
    seen: set[str] = set()
    for trajectory in sorted(test_trajectories, key=lambda item: item.trajectory_id):
        digest = _external_signal_hash(trajectory)
        if digest in seen:
            continue
        seen.add(digest)
        selected.append((trajectory, digest))
        if len(selected) == required_count:
            break
    if len(selected) != required_count:
        raise ValueError(
            f"test split provides {len(selected)} distinct external inputs; "
            f"{required_count} required"
        )
    return tuple(selected)


def _signals_from_trajectory(
    trajectory: IdentificationTrajectory,
    *,
    omega_override: FloatArray | None = None,
) -> ExcitationSignals:
    # The public schema intentionally withholds the private excitation family.
    # ``family`` is not used by the simulator; the whitelisted placeholder is
    # recorded in the final limitations and never treated as evaluation truth.
    omega = trajectory.omega_pu if omega_override is None else omega_override
    return ExcitationSignals(
        family="prbs",
        time_s=trajectory.time_s,
        u_ibr_pu=trajectory.u_ibr_pu,
        omega_pu=omega,
    )


def _opaque_generated_id(
    scenario: str,
    input_sha256: str,
    seed: int,
) -> str:
    return sha256_json(
        {"scenario": scenario, "input_sha256": input_sha256, "seed": seed}
    )[:32]


def _generate_evaluation_episodes(
    selected_inputs: Sequence[tuple[IdentificationTrajectory, str]],
    known_modes: Mapping[str, IBRModeParams],
    ood_modes: Mapping[str, IBRModeParams],
    settings: Phase4Settings,
    generated_directory: Path,
) -> tuple[RuntimeEpisode, ...]:
    if not {"nominal", "sluggish", "unavailable"}.issubset(known_modes):
        raise ValueError("known modes required for Phase-4 switch scenarios are missing")
    if not {"asymmetric_limit", "time_varying_delay"}.issubset(ood_modes):
        raise ValueError("required Phase-4 OOD modes are missing")
    if len(selected_inputs) < 4:
        raise ValueError("four distinct public test inputs are required")
    generated_directory.mkdir(parents=True, exist_ok=False)
    mode_union = {**known_modes, **ood_modes}
    episodes: list[RuntimeEpisode] = []
    for ordinal, (scenario, input_index, destination_mode) in enumerate(
        PHASE4_GENERATED_SCENARIOS
    ):
        source, input_hash = selected_inputs[input_index]
        seed = settings.master_seed + 40_000 + ordinal
        identifier = _opaque_generated_id(scenario, input_hash, seed)
        omega_override: FloatArray | None = None
        if scenario == "load_step_no_mode":
            omega_override = np.asarray(source.omega_pu, dtype=np.float64).copy()
            window = (
                (source.time_s >= settings.load_step_start_s)
                & (source.time_s <= settings.load_step_end_s)
            )
            omega_override[window] += settings.load_step_frequency_proxy_pu
        signals = _signals_from_trajectory(source, omega_override=omega_override)
        schedule = PiecewiseConstantModeSchedule.from_pairs(
            "nominal",
            []
            if destination_mode is None
            else [(settings.switch_time_s, destination_mode)],
        )
        trajectory, truth = simulate_scheduled_ibr_trajectory(
            signals,
            mode_union,
            schedule,
            trajectory_id=identifier,
            integration_step_s=settings.integration_step_s,
            power_measurement_noise_std_pu=(
                0.0
                if scenario == "noise_change_no_mode"
                else settings.measurement_noise_std_pu
            ),
            measurement_seed=seed,
        )
        if scenario == "noise_change_no_mode":
            rng = np.random.Generator(np.random.PCG64(seed))
            standard_deviation = np.full(
                len(trajectory.time_s),
                settings.measurement_noise_std_pu,
                dtype=np.float64,
            )
            standard_deviation[
                trajectory.time_s >= settings.switch_time_s
            ] = settings.additional_noise_std_pu
            observed = trajectory.p_ibr_pu + rng.normal(
                0.0, standard_deviation, size=len(trajectory.time_s)
            )
            trajectory = IdentificationTrajectory(
                trajectory_id=trajectory.trajectory_id,
                time_s=trajectory.time_s,
                u_ibr_pu=trajectory.u_ibr_pu,
                omega_pu=trajectory.omega_pu,
                p_ibr_pu=observed,
            )
        destination = generated_directory / f"{identifier}.parquet"
        trajectory.to_frame().to_parquet(
            destination,
            engine="pyarrow",
            index=False,
            compression="zstd",
        )
        episodes.append(
            RuntimeEpisode(
                trajectory=trajectory,
                trajectory_sha256=sha256_file(destination),
                source_kind_eval_only="generated_public_signals",
                scenario_eval_only=scenario,
                input_sha256=input_hash,
                truth_timeline_eval_only=truth,
            )
        )
    return tuple(episodes)


def _diagnose_trajectory(
    trajectory: IdentificationTrajectory,
    mode_library: ModeLibrary,
    calibration_artifact: OODCalibrationArtifact,
    settings: Phase4Settings,
    ood_config: OODDetectorConfig,
    *,
    epsilon_switch: float,
) -> pd.DataFrame:
    transition = build_sticky_transition_matrix(
        len(mode_library.models), epsilon_switch
    )
    diagnostic = OnlineModeDiagnostic(
        mode_library,
        calibration_artifact,
        measurement_noise_variance_pu2=settings.measurement_noise_std_pu**2,
        belief_floor=settings.belief_floor,
        variance_floor_pu2=settings.variance_floor_pu2,
        ood_config=ood_config,
        transition_matrix=transition,
    )
    records: list[dict[str, object]] = []
    for sample_index, time_s in enumerate(trajectory.time_s):
        previous_index = max(0, sample_index - 1)
        measurement = Measurement(
            time_s=float(time_s),
            omega_pu=float(trajectory.omega_pu[sample_index]),
            p_mech_pu=0.0,
            p_ibr_pu=float(trajectory.p_ibr_pu[sample_index]),
            u_sg_prev_pu=0.0,
            u_ibr_prev_pu=float(trajectory.u_ibr_pu[previous_index]),
        )
        record = diagnostic.step(measurement).to_log_record()
        record["runtime_episode_id"] = trajectory.trajectory_id
        records.append(record)
    frame = pd.DataFrame(records)
    forbidden_fragments = ("true_mode", "true_ood", "truth", "scenario_eval")
    if any(
        fragment in column.lower()
        for column in frame.columns
        for fragment in forbidden_fragments
    ):
        raise RuntimeError("runtime diagnostic log contains evaluation-only truth")
    return frame


def _runtime_logs_for_episodes(
    trajectories: Sequence[IdentificationTrajectory],
    mode_library: ModeLibrary,
    calibration_artifact: OODCalibrationArtifact,
    settings: Phase4Settings,
    ood_config: OODDetectorConfig,
    *,
    epsilon_switch: float,
) -> pd.DataFrame:
    frames = [
        _diagnose_trajectory(
            trajectory,
            mode_library,
            calibration_artifact,
            settings,
            ood_config,
            epsilon_switch=epsilon_switch,
        )
        for trajectory in trajectories
    ]
    if not frames:
        raise ValueError("runtime episode set must be non-empty")
    return pd.concat(frames, ignore_index=True)


def _load_private_metadata_after_runtime_barrier(
    private_directory: Path,
    public_manifest_path: Path,
) -> tuple[PrivateTrajectoryMetadata, ...]:
    manifest_path = private_directory / "private_manifest.json"
    metadata_path = private_directory / "evaluation_metadata.json"
    manifest = _strict_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("truth_access") != "evaluation_only":
        raise ValueError("private manifest must be marked evaluation_only")
    hashes = manifest.get("hashes")
    if not isinstance(hashes, Mapping):
        raise ValueError("private manifest has no hash mapping")
    if sha256_file(metadata_path) != hashes.get("evaluation_metadata_sha256"):
        raise ValueError("private evaluation metadata hash mismatch")
    if sha256_file(public_manifest_path) != hashes.get("public_manifest_sha256"):
        raise ValueError("private/public manifest provenance mismatch")
    payload = _strict_json(metadata_path)
    if not isinstance(payload, list) or not payload:
        raise ValueError("private evaluation metadata must be a non-empty array")
    metadata = tuple(PrivateTrajectoryMetadata(**dict(item)) for item in payload)
    identifiers = tuple(item.trajectory_id for item in metadata)
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("private evaluation metadata contains duplicate IDs")
    return metadata


def _attach_evaluation_truth(
    runtime_log: pd.DataFrame,
    episodes: Sequence[RuntimeEpisode],
    private_metadata: Sequence[PrivateTrajectoryMetadata],
    *,
    ood_mode_names: Sequence[str],
    component_to_class: Mapping[int, str],
    class_labels: Sequence[str],
) -> pd.DataFrame:
    metadata_by_id = {item.trajectory_id: item for item in private_metadata}
    episode_by_id = {episode.trajectory.trajectory_id: episode for episode in episodes}
    if len(episode_by_id) != len(episodes):
        raise ValueError("evaluation episodes contain duplicate IDs")
    truth_by_episode: dict[str, tuple[str, ...]] = {}
    scenario_by_episode: dict[str, str] = {}
    source_by_episode: dict[str, str] = {}
    input_by_episode: dict[str, str] = {}
    for identifier, episode in episode_by_id.items():
        if episode.truth_timeline_eval_only is None:
            metadata = metadata_by_id.get(identifier)
            if metadata is None or metadata.split != "test":
                raise ValueError(
                    f"fixed public test episode lacks authenticated truth: {identifier}"
                )
            truth = tuple(
                metadata.mode_name_eval_only
                for _ in range(len(episode.trajectory.time_s))
            )
        else:
            if episode.truth_timeline_eval_only.trajectory_id != identifier:
                raise ValueError("simulator truth timeline ID mismatch")
            truth = episode.truth_timeline_eval_only.mode_name_eval_only
        if len(truth) != len(episode.trajectory.time_s):
            raise ValueError("evaluation truth timeline length mismatch")
        truth_by_episode[identifier] = truth
        scenario_by_episode[identifier] = episode.scenario_eval_only
        source_by_episode[identifier] = episode.source_kind_eval_only
        input_by_episode[identifier] = episode.input_sha256

    joined = runtime_log.copy()
    true_modes: list[str] = []
    scenarios: list[str] = []
    sources: list[str] = []
    inputs: list[str] = []
    for identifier, sample_index in zip(
        joined["runtime_episode_id"], joined["sample_index"], strict=True
    ):
        episode_id = str(identifier)
        index = int(sample_index)
        true_modes.append(truth_by_episode[episode_id][index])
        scenarios.append(scenario_by_episode[episode_id])
        sources.append(source_by_episode[episode_id])
        inputs.append(input_by_episode[episode_id])
    joined["scenario_eval_only"] = scenarios
    joined["source_kind_eval_only"] = sources
    joined["input_sha256_eval_only"] = inputs
    joined["true_mode_eval_only"] = true_modes
    ood_names = set(str(name) for name in ood_mode_names)
    joined["true_ood_eval_only"] = [mode in ood_names for mode in true_modes]

    component_columns = [
        f"belief_{index}" for index in range(len(component_to_class))
    ]
    component_probabilities = joined[component_columns].to_numpy(dtype=float)
    aggregate = aggregate_component_beliefs(
        component_probabilities, component_to_class, class_labels
    )
    for index, label in enumerate(class_labels):
        joined[f"known_belief_{label}_eval_only"] = aggregate[:, index]
    labels = np.asarray(tuple(class_labels), dtype=object)
    joined["map_reference_mode_eval_only"] = labels[
        np.argmax(aggregate, axis=1)
    ]
    return joined


def _known_probability_matrix(
    frame: pd.DataFrame,
    class_labels: Sequence[str],
) -> FloatArray:
    return frame[
        [f"known_belief_{label}_eval_only" for label in class_labels]
    ].to_numpy(dtype=float)


def _false_alarm_subset_and_windows(
    joined: pd.DataFrame,
    settings: Phase4Settings,
) -> tuple[pd.DataFrame, tuple[tuple[int, int], ...]]:
    scenarios = {
        "public_test_fixed",
        "load_step_no_mode",
        "noise_change_no_mode",
    }
    subset = joined.loc[
        joined["valid_update"] & joined["scenario_eval_only"].isin(scenarios)
    ].reset_index(drop=True)
    load_mask = (
        (subset["scenario_eval_only"] == "load_step_no_mode")
        & (subset["time_s"] >= settings.load_step_start_s)
        & (subset["time_s"] <= settings.load_step_end_s)
    )
    indices = np.flatnonzero(load_mask.to_numpy())
    windows: tuple[tuple[int, int], ...] = ()
    if indices.size:
        windows = ((int(indices[0]), int(indices[-1])),)
    return subset, windows


def _evaluate_joined_runtime(
    joined: pd.DataFrame,
    *,
    settings: Phase4Settings,
    class_labels: Sequence[str],
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    labels = tuple(class_labels)
    valid = joined["valid_update"].astype(bool)
    known = joined["true_mode_eval_only"].isin(labels)
    known_frame = joined.loc[valid & known].reset_index(drop=True)
    mode_metrics = evaluate_mode_probabilities(
        known_frame["true_mode_eval_only"].tolist(),
        _known_probability_matrix(known_frame, labels),
        class_labels=labels,
        reliability_bin_count=settings.reliability_bins,
        minimum_probability=settings.belief_floor,
    )

    switch_frame = joined.loc[
        valid
        & joined["scenario_eval_only"].isin(
            {"nominal_to_sluggish", "nominal_to_unavailable"}
        )
    ].reset_index(drop=True)
    switch_metrics = evaluate_switch_detection(
        switch_frame["true_mode_eval_only"].tolist(),
        _known_probability_matrix(switch_frame, labels),
        sample_time_s=settings.control_period_s,
        belief_threshold=settings.belief_detection_threshold,
        consecutive_steps=settings.belief_detection_hold_steps,
        class_labels=labels,
        episode_ids=switch_frame["runtime_episode_id"].tolist(),
        time_s=switch_frame["time_s"].to_numpy(dtype=float),
    )

    false_frame, load_windows = _false_alarm_subset_and_windows(joined, settings)
    false_metrics = evaluate_false_alarms(
        false_frame["true_mode_eval_only"].tolist(),
        false_frame["map_reference_mode_eval_only"].tolist(),
        sample_time_s=settings.control_period_s,
        persistence_limit_steps=settings.false_alarm_hold_steps,
        episode_ids=false_frame["runtime_episode_id"].tolist(),
        load_step_windows=load_windows,
    )

    ood_frame = joined.loc[
        valid
        & joined["scenario_eval_only"].isin(
            {"ood_asymmetric_limit", "ood_time_varying_delay"}
        )
    ].reset_index(drop=True)
    ood_metrics = evaluate_ood_detection(
        ood_frame["true_ood_eval_only"].to_numpy(dtype=bool),
        ood_frame["ood_score"].to_numpy(dtype=float),
        ood_frame["ood_active"].to_numpy(dtype=bool),
        sample_time_s=settings.control_period_s,
        episode_ids=ood_frame["runtime_episode_id"].tolist(),
        higher_score_more_ood=True,
        time_s=ood_frame["time_s"].to_numpy(dtype=float),
    )
    metrics = {
        "schema_version": PHASE4_SCHEMA_VERSION,
        "evaluation_only": True,
        "mode_probability": mode_metrics.to_dict(),
        "switch_detection": switch_metrics.to_dict(),
        "false_alarms": false_metrics.to_dict(),
        "ood_detection": ood_metrics.to_dict(),
    }

    reliability_rows = [item.to_dict() for item in mode_metrics.reliability_bins]
    reliability = pd.DataFrame(reliability_rows)
    scenario_rows: list[dict[str, object]] = []
    for scenario, scenario_frame in known_frame.groupby(
        "scenario_eval_only", sort=True
    ):
        probability_metrics = evaluate_mode_probabilities(
            scenario_frame["true_mode_eval_only"].tolist(),
            _known_probability_matrix(scenario_frame, labels),
            class_labels=labels,
            reliability_bin_count=settings.reliability_bins,
            minimum_probability=settings.belief_floor,
        )
        scenario_rows.append(
            {
                "scenario_eval_only": scenario,
                "sample_count": probability_metrics.sample_count,
                "accuracy": probability_metrics.accuracy,
                "macro_f1": probability_metrics.macro_f1,
                "brier_score": probability_metrics.brier_score,
                "negative_log_likelihood": (
                    probability_metrics.negative_log_likelihood
                ),
                "expected_calibration_error": (
                    probability_metrics.expected_calibration_error
                ),
            }
        )
    return metrics, reliability, pd.DataFrame(scenario_rows)


def _epsilon_sensitivity(
    episodes: Sequence[RuntimeEpisode],
    private_metadata: Sequence[PrivateTrajectoryMetadata],
    mode_library: ModeLibrary,
    calibration_artifact: OODCalibrationArtifact,
    selected_ood_config: OODDetectorConfig,
    settings: Phase4Settings,
    *,
    known_labels: Sequence[str],
    ood_labels: Sequence[str],
    component_to_class: Mapping[int, str],
) -> pd.DataFrame:
    known_episodes = tuple(
        episode
        for episode in episodes
        if not episode.scenario_eval_only.startswith("ood_")
    )
    rows: list[dict[str, object]] = []
    for epsilon in settings.epsilon_sensitivity:
        runtime = _runtime_logs_for_episodes(
            tuple(episode.trajectory for episode in known_episodes),
            mode_library,
            calibration_artifact,
            settings,
            selected_ood_config,
            epsilon_switch=epsilon,
        )
        joined = _attach_evaluation_truth(
            runtime,
            known_episodes,
            private_metadata,
            ood_mode_names=ood_labels,
            component_to_class=component_to_class,
            class_labels=known_labels,
        )
        valid = joined["valid_update"].astype(bool)
        probabilities = _known_probability_matrix(joined.loc[valid], known_labels)
        probability_metrics = evaluate_mode_probabilities(
            joined.loc[valid, "true_mode_eval_only"].tolist(),
            probabilities,
            class_labels=known_labels,
            reliability_bin_count=settings.reliability_bins,
            minimum_probability=settings.belief_floor,
        )
        switch = joined.loc[
            valid
            & joined["scenario_eval_only"].isin(
                {"nominal_to_sluggish", "nominal_to_unavailable"}
            )
        ].reset_index(drop=True)
        switch_metrics = evaluate_switch_detection(
            switch["true_mode_eval_only"].tolist(),
            _known_probability_matrix(switch, known_labels),
            sample_time_s=settings.control_period_s,
            belief_threshold=settings.belief_detection_threshold,
            consecutive_steps=settings.belief_detection_hold_steps,
            class_labels=known_labels,
            episode_ids=switch["runtime_episode_id"].tolist(),
            time_s=switch["time_s"].to_numpy(dtype=float),
        )
        false_frame, windows = _false_alarm_subset_and_windows(joined, settings)
        false_metrics = evaluate_false_alarms(
            false_frame["true_mode_eval_only"].tolist(),
            false_frame["map_reference_mode_eval_only"].tolist(),
            sample_time_s=settings.control_period_s,
            persistence_limit_steps=settings.false_alarm_hold_steps,
            episode_ids=false_frame["runtime_episode_id"].tolist(),
            load_step_windows=windows,
        )
        rows.append(
            {
                "evaluation_scope": "known_only_episodes_excluding_ood_scenarios",
                "epsilon_switch": epsilon,
                "accuracy": probability_metrics.accuracy,
                "macro_f1": probability_metrics.macro_f1,
                "brier_score": probability_metrics.brier_score,
                "negative_log_likelihood": (
                    probability_metrics.negative_log_likelihood
                ),
                "expected_calibration_error": (
                    probability_metrics.expected_calibration_error
                ),
                "switch_event_count": switch_metrics.event_count,
                "switch_detected_count": switch_metrics.detected_count,
                "switch_censored_count": switch_metrics.censored_count,
                "switch_detection_rate": switch_metrics.detection_rate,
                "mean_detected_delay_s": switch_metrics.mean_detected_delay_s,
                "false_alarms_per_hour": false_metrics.false_alarms_per_hour,
                "episode_false_alarm_rate": false_metrics.episode_false_alarm_rate,
                "load_step_window_false_alarm_rate": (
                    false_metrics.load_step_window_false_alarm_rate
                ),
            }
        )
    return pd.DataFrame(rows)


def _configure_matplotlib() -> Any:
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    return plt


def _plot_belief_timeline(
    joined: pd.DataFrame,
    class_labels: Sequence[str],
    settings: Phase4Settings,
    destination: Path,
) -> None:
    plt = _configure_matplotlib()
    frame = joined.loc[
        joined["scenario_eval_only"] == "nominal_to_sluggish"
    ]
    if frame.empty:
        raise ValueError("nominal-to-sluggish timeline is missing")
    figure, axis = plt.subplots(figsize=(8.0, 4.5), constrained_layout=True)
    for label in class_labels:
        axis.plot(
            frame["time_s"],
            frame[f"known_belief_{label}_eval_only"],
            label=label,
            linewidth=1.4,
        )
    axis.axvline(
        settings.switch_time_s,
        color="black",
        linestyle="--",
        linewidth=1.0,
        label="true switch (evaluation only)",
    )
    axis.set(xlabel="Time (s)", ylabel="Aggregated mode probability", ylim=(0, 1.02))
    axis.grid(alpha=0.25)
    axis.legend(ncol=2, fontsize=8)
    figure.savefig(destination, dpi=180, metadata={"CreationDate": None})
    plt.close(figure)


def _plot_ood_timeline(
    joined: pd.DataFrame,
    selected: OODDetectorConfig,
    settings: Phase4Settings,
    destination: Path,
) -> None:
    plt = _configure_matplotlib()
    frame = joined.loc[
        joined["scenario_eval_only"] == "ood_asymmetric_limit"
    ]
    if frame.empty:
        raise ValueError("asymmetric-limit OOD timeline is missing")
    figure, axis = plt.subplots(figsize=(8.0, 4.5), constrained_layout=True)
    axis.plot(frame["time_s"], frame["ood_pvalue"], label="conformal p-value")
    axis.axhline(selected.alpha_on, color="tab:red", linestyle="--", label="alpha_on")
    axis.axhline(
        selected.alpha_off, color="tab:green", linestyle=":", label="alpha_off"
    )
    axis.axvline(
        settings.switch_time_s,
        color="black",
        linestyle="--",
        linewidth=1.0,
        label="OOD onset (evaluation only)",
    )
    axis.fill_between(
        frame["time_s"].to_numpy(dtype=float),
        0.0,
        1.0,
        where=frame["ood_active"].to_numpy(dtype=bool),
        color="tab:red",
        alpha=0.12,
        label="OOD_ACTIVE",
    )
    axis.set(xlabel="Time (s)", ylabel="p-value", ylim=(0, 1.02))
    axis.grid(alpha=0.25)
    axis.legend(ncol=2, fontsize=8)
    figure.savefig(destination, dpi=180, metadata={"CreationDate": None})
    plt.close(figure)


def _plot_reliability(reliability: pd.DataFrame, destination: Path) -> None:
    plt = _configure_matplotlib()
    nonempty = reliability.loc[reliability["count"] > 0]
    figure, axis = plt.subplots(figsize=(5.0, 5.0), constrained_layout=True)
    axis.plot([0, 1], [0, 1], color="black", linestyle="--", label="ideal")
    axis.plot(
        nonempty["mean_confidence"],
        nonempty["empirical_accuracy"],
        marker="o",
        label="online diagnosis",
    )
    axis.set(
        xlabel="Mean confidence",
        ylabel="Empirical accuracy",
        xlim=(0, 1),
        ylim=(0, 1),
    )
    axis.grid(alpha=0.25)
    axis.legend()
    figure.savefig(destination, dpi=180, metadata={"CreationDate": None})
    plt.close(figure)


def _plot_epsilon_sensitivity(
    sensitivity: pd.DataFrame,
    destination: Path,
) -> None:
    plt = _configure_matplotlib()
    figure, left = plt.subplots(figsize=(7.0, 4.5), constrained_layout=True)
    left.plot(
        sensitivity["epsilon_switch"],
        sensitivity["macro_f1"],
        marker="o",
        color="tab:blue",
        label="macro-F1",
    )
    left.set_xscale("log")
    left.set(xlabel="Sticky-switch epsilon", ylabel="Macro-F1", ylim=(0, 1.02))
    right = left.twinx()
    right.plot(
        sensitivity["epsilon_switch"],
        sensitivity["switch_detection_rate"],
        marker="s",
        color="tab:orange",
        label="switch detection rate",
    )
    right.set(ylabel="Detection rate", ylim=(0, 1.02))
    left.grid(alpha=0.25)
    lines = left.lines + right.lines
    left.legend(lines, [line.get_label() for line in lines], loc="best")
    figure.savefig(destination, dpi=180, metadata={"CreationDate": None})
    plt.close(figure)


def run_phase4_pipeline(
    *,
    base_config_path: str | Path,
    known_modes_config_path: str | Path,
    ood_modes_config_path: str | Path,
    public_data_directory: str | Path,
    private_data_directory: str | Path,
    mode_library_path: str | Path,
    cluster_assignments_path: str | Path,
    output_directory: str | Path,
    verify_trajectory_hashes: bool = True,
) -> Phase4RunResult:
    """Run calibration, runtime diagnosis, and post-barrier evaluation.

    ``output_directory`` must be new or empty.  This prevents a partial run
    from being mistaken for a reproducible canonical artifact set.
    """

    if not isinstance(verify_trajectory_hashes, bool):
        raise TypeError("verify_trajectory_hashes must be boolean")
    output = _prepare_output_directory(Path(output_directory))
    repository_root = Path(__file__).resolve().parents[3]
    raw_paths = {
        "base_config": base_config_path,
        "known_modes_config": known_modes_config_path,
        "ood_modes_config": ood_modes_config_path,
        "public_data_directory": public_data_directory,
        "private_data_directory_eval_only": private_data_directory,
        "mode_library": mode_library_path,
        "cluster_assignments_eval_only": cluster_assignments_path,
        "output_directory": output_directory,
    }
    base_path = Path(base_config_path).expanduser().resolve()
    known_path = Path(known_modes_config_path).expanduser().resolve()
    ood_path = Path(ood_modes_config_path).expanduser().resolve()
    public_directory = Path(public_data_directory).expanduser().resolve()
    private_directory = Path(private_data_directory).expanduser().resolve()
    library_path = Path(mode_library_path).expanduser().resolve()
    assignments_path = Path(cluster_assignments_path).expanduser().resolve()

    base_config = load_yaml(base_path)
    settings = Phase4Settings.from_base_config(base_config)
    provenance_path = _write_json(
        output / "reproducibility_provenance.json",
        _reproducibility_provenance(repository_root, settings),
    )
    mode_library = ModeLibrary.load_json(library_path)
    mode_library_digest = sha256_file(library_path)

    # Both splits pass the hardened public loader before any Phase-4 use.
    calibration_trajectories = load_public_identification_data(
        public_directory,
        split="ood_calibration",
        verify_hashes=verify_trajectory_hashes,
    )
    test_trajectories = load_public_identification_data(
        public_directory,
        split="test",
        verify_hashes=verify_trajectory_hashes,
    )
    public_manifest, split_rows = _public_provenance(public_directory)
    calibration_hashes = {
        trajectory.trajectory_id: split_rows[trajectory.trajectory_id]["sha256"]
        for trajectory in calibration_trajectories
    }
    test_hashes = {
        trajectory.trajectory_id: split_rows[trajectory.trajectory_id]["sha256"]
        for trajectory in test_trajectories
    }
    if any(
        split_rows[identifier]["split"] != "ood_calibration"
        for identifier in calibration_hashes
    ):
        raise ValueError("calibration loader returned a non-calibration trajectory")
    if any(split_rows[identifier]["split"] != "test" for identifier in test_hashes):
        raise ValueError("test loader returned a non-test trajectory")

    calibration = calibrate_ood_from_trajectories(
        calibration_trajectories,
        mode_library,
        measurement_noise_variance_pu2=settings.measurement_noise_std_pu**2,
        variance_floor_pu2=settings.variance_floor_pu2,
        dataset_sha256=str(public_manifest["dataset_sha256"]),
        split_manifest_sha256=str(public_manifest["split_manifest_sha256"]),
        mode_library_sha256=mode_library_digest,
        source_hash_by_trajectory_id=calibration_hashes,
    )
    calibration_path = _write_json(
        output / "ood_calibration_artifact.json", calibration.artifact.to_dict()
    )
    calibration.residual_table.to_parquet(
        output / "ood_calibration_residuals.parquet",
        engine="pyarrow",
        index=False,
        compression="zstd",
    )
    selected_ood, cv_table = select_hysteresis_known_only_cv(
        calibration.scores_by_trajectory,
        alpha_on_candidates=settings.alpha_on_candidates,
        alpha_off_candidates=settings.alpha_off_candidates,
        hold_on_candidates=settings.hold_on_candidates,
        hold_off_candidates=settings.hold_off_candidates,
        declared_default=settings.default_ood_config,
        variance_floor=settings.variance_floor_pu2,
    )
    cv_table.to_csv(output / "ood_hysteresis_known_only_cv.csv", index=False)
    selected_payload = {
        "schema_version": PHASE4_SCHEMA_VERSION,
        "selection_population": "known_modes_only",
        "selection_unit": "leave_one_trajectory_out",
        "selection_objective": [
            "false_active_episode_count",
            "false_active_sample_count",
            "false_alert_sample_count",
            "distance_to_predeclared_default",
        ],
        "search_range": {
            "alpha_on": list(settings.alpha_on_candidates),
            "alpha_off": list(settings.alpha_off_candidates),
            "hold_on_steps": list(settings.hold_on_candidates),
            "hold_off_steps": list(settings.hold_off_candidates),
        },
        "selected": {
            "alpha_on": selected_ood.alpha_on,
            "alpha_off": selected_ood.alpha_off,
            "hold_on_steps": selected_ood.L_on,
            "hold_off_steps": selected_ood.L_off,
            "variance_floor": selected_ood.variance_floor,
        },
        "ood_data_used_for_selection": False,
        "state_machine_confirmation_semantics": (
            "The L_on-th consecutive low p-value enters SUSPECT; the next "
            "continuing low p-value enters OOD_ACTIVE, exactly following the "
            "four-state specification diagram."
        ),
    }
    _write_json(output / "ood_hysteresis_selection.json", selected_payload)

    selected_inputs = _select_unique_test_inputs(
        test_trajectories, settings.unique_test_excitations
    )
    known_modes = _load_modes(known_path, ood=False)
    ood_modes = _load_modes(ood_path, ood=True)
    generated = _generate_evaluation_episodes(
        selected_inputs,
        known_modes,
        ood_modes,
        settings,
        output / "generated_trajectories",
    )
    fixed = tuple(
        RuntimeEpisode(
            trajectory=trajectory,
            trajectory_sha256=test_hashes[trajectory.trajectory_id],
            source_kind_eval_only="authenticated_public_test",
            scenario_eval_only="public_test_fixed",
            input_sha256=_external_signal_hash(trajectory),
            truth_timeline_eval_only=None,
        )
        for trajectory in sorted(test_trajectories, key=lambda item: item.trajectory_id)
    )
    episodes = (*fixed, *generated)
    ood_generated_hashes = tuple(
        episode.trajectory_sha256
        for episode in generated
        if episode.scenario_eval_only.startswith("ood_")
    )
    calibration.artifact.assert_disjoint_from(
        test_trajectory_sha256=tuple(test_hashes.values()),
        ood_trajectory_sha256=ood_generated_hashes,
    )
    split_integrity = {
        "schema_version": PHASE4_SCHEMA_VERSION,
        "calibration_trajectory_sha256": sorted(calibration_hashes.values()),
        "test_trajectory_sha256": sorted(test_hashes.values()),
        "ood_generated_trajectory_sha256": sorted(ood_generated_hashes),
        "pairwise_disjoint": True,
        "unique_test_external_input_sha256": [
            digest for _, digest in selected_inputs
        ],
        "unique_test_external_input_count": len(selected_inputs),
    }
    _write_json(output / "split_integrity.json", split_integrity)

    # Runtime-information barrier: no private metadata or train/reference
    # mapping has been opened above this point.  Freeze and hash runtime first.
    runtime_log = _runtime_logs_for_episodes(
        tuple(episode.trajectory for episode in episodes),
        mode_library,
        calibration.artifact,
        settings,
        selected_ood,
        epsilon_switch=settings.epsilon_switch,
    )
    runtime_path = output / "runtime_diagnostics.parquet"
    runtime_log.to_parquet(
        runtime_path,
        engine="pyarrow",
        index=False,
        compression="zstd",
    )
    runtime_digest = sha256_file(runtime_path)
    runtime_manifest_path = _write_json(
        output / "runtime_diagnostics_manifest.json",
        {
            "schema_version": RUNTIME_LOG_SCHEMA_VERSION,
            "runtime_log_sha256": runtime_digest,
            "row_count": len(runtime_log),
            "columns": list(runtime_log.columns),
            "episode_trajectory_sha256": {
                episode.trajectory.trajectory_id: episode.trajectory_sha256
                for episode in episodes
            },
            "contains_evaluation_truth": False,
        },
    )
    runtime_manifest_digest_before_truth = sha256_file(runtime_manifest_path)

    # Evaluation-only truth is first opened after the immutable runtime hash.
    private_metadata = _load_private_metadata_after_runtime_barrier(
        private_directory, public_directory / "public_manifest.json"
    )
    cluster_assignments = pd.read_csv(assignments_path)
    class_labels = tuple(known_modes)
    component_mapping, mapping_evidence = build_majority_component_mapping(
        cluster_assignments,
        private_metadata,
        component_count=len(mode_library.models),
        class_labels=class_labels,
    )
    mapping_path = _write_json(
        output / "component_reference_mapping_eval_only.json",
        {
            "schema_version": PHASE4_SCHEMA_VERSION,
            "evaluation_only": True,
            "source_assignments_split": "train",
            "mapping_method": "many_to_one_majority_with_declared_label_order_ties",
            "component_to_reference_mode": {
                str(key): value for key, value in component_mapping.items()
            },
            "train_count_evidence": {
                str(key): value for key, value in mapping_evidence.items()
            },
            "never_fed_to_runtime": True,
        },
    )
    joined = _attach_evaluation_truth(
        runtime_log,
        episodes,
        private_metadata,
        ood_mode_names=tuple(ood_modes),
        component_to_class=component_mapping,
        class_labels=class_labels,
    )
    joined_path = output / "diagnostics_with_truth_eval_only.parquet"
    joined.to_parquet(
        joined_path,
        engine="pyarrow",
        index=False,
        compression="zstd",
    )
    if sha256_file(runtime_path) != runtime_digest:
        raise RuntimeError("runtime diagnostic log changed after truth join")
    if sha256_file(runtime_manifest_path) != runtime_manifest_digest_before_truth:
        raise RuntimeError("runtime manifest changed after truth join")

    metrics, reliability, scenario_metrics = _evaluate_joined_runtime(
        joined, settings=settings, class_labels=class_labels
    )
    metrics_path = _write_json(output / "phase4_metrics.json", metrics)
    reliability.to_csv(output / "reliability_bins.csv", index=False)
    scenario_metrics.to_csv(output / "scenario_mode_metrics.csv", index=False)

    sensitivity = _epsilon_sensitivity(
        episodes,
        private_metadata,
        mode_library,
        calibration.artifact,
        selected_ood,
        settings,
        known_labels=class_labels,
        ood_labels=tuple(ood_modes),
        component_to_class=component_mapping,
    )
    sensitivity.to_csv(output / "epsilon_sensitivity.csv", index=False)

    _plot_belief_timeline(
        joined, class_labels, settings, output / "belief_timeline.png"
    )
    _plot_ood_timeline(
        joined, selected_ood, settings, output / "ood_timeline.png"
    )
    _plot_reliability(reliability, output / "reliability_diagram.png")
    _plot_epsilon_sensitivity(
        sensitivity, output / "epsilon_sensitivity.png"
    )

    scenario_manifest = {
        "schema_version": PHASE4_SCHEMA_VERSION,
        "evaluation_only": True,
        "runtime_log_sha256_before_truth_read": runtime_digest,
        "episodes": [
            {
                "runtime_episode_id": episode.trajectory.trajectory_id,
                "scenario_eval_only": episode.scenario_eval_only,
                "source_kind_eval_only": episode.source_kind_eval_only,
                "input_sha256": episode.input_sha256,
                "trajectory_sha256": episode.trajectory_sha256,
                "truth_modes_eval_only": sorted(
                    set(
                        joined.loc[
                            joined["runtime_episode_id"]
                            == episode.trajectory.trajectory_id,
                            "true_mode_eval_only",
                        ].tolist()
                    )
                ),
            }
            for episode in episodes
        ],
        "load_step_implementation": {
            "kind": "external_frequency_proxy",
            "proxy_pu": settings.load_step_frequency_proxy_pu,
            "start_s": settings.load_step_start_s,
            "end_s": settings.load_step_end_s,
            "limitation": (
                "This Phase-4 diagnosis test uses an external omega proxy; "
                "it is not a coupled closed-loop grid load-step simulation."
            ),
        },
        "public_excitation_family_placeholder": (
            "ExcitationSignals requires a whitelisted family, while the public "
            "test schema deliberately withholds that private field; the family "
            "placeholder does not affect simulation."
        ),
    }
    _write_json(output / "scenario_manifest_eval_only.json", scenario_manifest)

    resolved = {
        "schema_version": PHASE4_SCHEMA_VERSION,
        "base_config": base_config,
        "selected_ood_hysteresis": selected_payload["selected"],
        "component_count": len(mode_library.models),
        "known_reference_classes_eval_only": list(class_labels),
        "paths": {
            "base_config": _portable_path(
                base_path, repository_root, raw_paths["base_config"]
            ),
            "known_modes_config": _portable_path(
                known_path, repository_root, raw_paths["known_modes_config"]
            ),
            "ood_modes_config": _portable_path(
                ood_path, repository_root, raw_paths["ood_modes_config"]
            ),
            "public_data_directory": _portable_path(
                public_directory,
                repository_root,
                raw_paths["public_data_directory"],
            ),
            "private_data_directory_eval_only": _portable_path(
                private_directory,
                repository_root,
                raw_paths["private_data_directory_eval_only"],
            ),
            "mode_library": _portable_path(
                library_path, repository_root, raw_paths["mode_library"]
            ),
            "cluster_assignments_eval_only": _portable_path(
                assignments_path,
                repository_root,
                raw_paths["cluster_assignments_eval_only"],
            ),
        },
        "source_sha256": {
            "base_config": sha256_file(base_path),
            "known_modes_config": sha256_file(known_path),
            "ood_modes_config": sha256_file(ood_path),
            "mode_library": mode_library_digest,
            "cluster_assignments_eval_only": sha256_file(assignments_path),
        },
    }
    resolved_path = save_yaml(resolved, output / "resolved_phase4_config.yaml")
    summary = {
        "schema_version": PHASE4_SCHEMA_VERSION,
        "output_directory": _portable_path(
            output, repository_root, raw_paths["output_directory"]
        ),
        "config_sha256": config_sha256(base_config),
        "calibration_trajectory_count": len(calibration_trajectories),
        "calibration_score_count": len(calibration.artifact.calibration_scores),
        "test_trajectory_count": len(test_trajectories),
        "generated_trajectory_count": len(generated),
        "native_component_count": len(mode_library.models),
        "reference_class_count_eval_only": len(class_labels),
        "calibration_artifact_sha256": sha256_file(calibration_path),
        "runtime_log_sha256_before_truth_read": runtime_digest,
        "runtime_manifest_sha256_before_truth_read": (
            runtime_manifest_digest_before_truth
        ),
        "truth_join_sha256": sha256_file(joined_path),
        "component_mapping_sha256_eval_only": sha256_file(mapping_path),
        "metrics_sha256_eval_only": sha256_file(metrics_path),
        "resolved_config_sha256": sha256_file(resolved_path),
        "reproducibility_provenance_sha256": sha256_file(provenance_path),
        "split_hashes_pairwise_disjoint": True,
        "hysteresis_tuned_with_ood": False,
        "metrics": metrics,
    }
    _write_json(output / "phase4_summary.json", summary)

    files_before_manifest = file_sha256_manifest(output)
    artifact_set_digest = sha256_json(files_before_manifest)
    artifact_manifest_path = _write_json(
        output / "artifact_manifest.json",
        {
            "schema_version": PHASE4_SCHEMA_VERSION,
            "scope": "all_phase4_artifacts_except_manifest_and_hash_sidecar",
            "artifact_set_sha256": artifact_set_digest,
            "files": list(files_before_manifest),
        },
    )
    artifact_manifest_digest = sha256_file(artifact_manifest_path)
    (output / "artifact_manifest.sha256").write_text(
        artifact_manifest_digest + "\n",
        encoding="ascii",
        newline="\n",
    )
    return Phase4RunResult(
        output_directory=output,
        calibration_artifact_sha256=sha256_file(calibration_path),
        runtime_log_sha256=runtime_digest,
        artifact_manifest_sha256=artifact_manifest_digest,
        selected_ood_config=selected_ood,
        metrics=metrics,
    )


__all__ = [
    "CalibrationComputation",
    "PHASE4_GENERATED_SCENARIOS",
    "PHASE4_SCHEMA_VERSION",
    "Phase4RunResult",
    "Phase4Settings",
    "aggregate_component_beliefs",
    "build_majority_component_mapping",
    "calibrate_ood_from_trajectories",
    "compute_all_component_arx_residuals",
    "run_phase4_pipeline",
    "select_hysteresis_known_only_cv",
]
