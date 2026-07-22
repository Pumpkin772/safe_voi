"""Auditable Phase-5 validation for the frozen native-K6 SD-BMPC.

This module is evaluation-only.  It exercises the real 20-step convex QCQP,
records strict solver outcomes, renders the controller state machine from a
machine-readable source, and optionally runs a short closed-loop controller
smoke test.  Simulator-private mode truth is never passed to the controller or
written into the runtime smoke log.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import inspect
import json
import math
from pathlib import Path
import re
import subprocess
import sys
from time import perf_counter
from typing import Any

import cvxpy as cp
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
import numpy as np
import pandas as pd

from d5freq.estimation.ood_detector import OODCalibrationArtifact, OODDetectorConfig
from d5freq.identification.model_library import ModeLibrary
from d5freq.models.grid_frequency import GridFrequencyModel, GridParams
from d5freq.optimization.mpc_problem import (
    REQUIRED_NATIVE_COMPONENT_COUNT,
    SDBMPCBounds,
    SDBMPCConfig,
    SDBMPCProblemCache,
    SDBMPCWeights,
    modes_from_library,
)
from d5freq.optimization.solver_utils import (
    SolverResult,
    shift_warm_start_sequence,
    solve_cvxpy_problem,
)
from d5freq.utils.config import load_yaml, save_yaml
from d5freq.utils.environment import collect_environment_info
from d5freq.utils.hashing import file_sha256_manifest, sha256_file, sha256_json


PHASE5_SCHEMA_VERSION = "d5freq.phase5_validation.v1"
REQUIRED_HORIZON_STEPS = 20
COMMERCIAL_SOLVERS = frozenset({"MOSEK", "GUROBI"})
PHASE5_SOURCE_PATHS: tuple[str, ...] = (
    "scripts/phase5_validate_sd_bmpc.py",
    "src/d5freq/evaluation/phase5_validation.py",
    "src/d5freq/controllers/sd_bmpc.py",
    "src/d5freq/controllers/lqi_fallback.py",
    "src/d5freq/optimization/mpc_problem.py",
    "src/d5freq/optimization/solver_utils.py",
    "src/d5freq/optimization/joint_prediction.py",
    "src/d5freq/estimation/online_diagnostic.py",
    "src/d5freq/estimation/mode_belief_filter.py",
    "src/d5freq/estimation/ood_detector.py",
    "src/d5freq/estimation/grid_kalman_filter.py",
    "src/d5freq/identification/model_library.py",
    "src/d5freq/models/grid_frequency.py",
    "src/d5freq/models/hidden_mode_ibr.py",
    "src/d5freq/simulation/hybrid_simulator.py",
    "src/d5freq/simulation/disturbances.py",
    "src/d5freq/simulation/mode_schedules.py",
    "src/d5freq/interfaces.py",
    "src/d5freq/utils/config.py",
    "src/d5freq/utils/environment.py",
    "src/d5freq/utils/hashing.py",
)
_SHA256 = re.compile(r"[0-9a-f]{64}")
_FORBIDDEN_RUNTIME_KEY_FRAGMENTS = (
    "true_mode",
    "mode_truth",
    "hidden_mode",
    "truth_label",
)


@dataclass(frozen=True, slots=True)
class Phase5Settings:
    """Validated Phase-5 settings resolved from the two project configs."""

    grid_params: GridParams
    mpc_config: SDBMPCConfig
    solver_priority: tuple[str, ...]
    solve_timeout_s: float
    max_acceptable_slack_hz: float
    recovery_hold_steps: int
    return_blend_steps: int
    ibr_withdraw_rate_pu_per_s: float
    belief_switch_epsilon: float
    belief_floor: float
    belief_variance_floor_pu2: float
    ood_config: OODDetectorConfig

    @classmethod
    def from_configs(
        cls,
        base_config: Mapping[str, Any],
        mpc_config: Mapping[str, Any],
    ) -> "Phase5Settings":
        if base_config.get("schema_version") != 1:
            raise ValueError("base config must use schema_version 1")
        if mpc_config.get("schema_version") != 1:
            raise ValueError("MPC config must use schema_version 1")
        grid = _mapping(base_config.get("grid"), "grid")
        ibr = _mapping(base_config.get("ibr_command"), "ibr_command")
        belief = _mapping(base_config.get("belief"), "belief")
        ood = _mapping(base_config.get("ood"), "ood")
        raw_mpc = _mapping(mpc_config.get("mpc"), "mpc")
        fallback = _mapping(mpc_config.get("fallback"), "fallback")
        if ood.get("calibration_known_modes_only") is not True:
            raise ValueError("OOD calibration must be declared known-modes-only")

        grid_params = GridParams(
            f0_hz=_positive(grid.get("f0_hz"), "grid.f0_hz"),
            M_s=_positive(grid.get("M_s"), "grid.M_s"),
            D_pu=_nonnegative(grid.get("D_pu"), "grid.D_pu"),
            T_t_s=_positive(grid.get("T_t_s"), "grid.T_t_s"),
            T_g_s=_positive(grid.get("T_g_s"), "grid.T_g_s"),
            R_pu=_positive(grid.get("R_pu"), "grid.R_pu"),
            control_period_s=_positive(
                grid.get("control_period_s"), "grid.control_period_s"
            ),
            integration_step_s=_positive(
                grid.get("integration_step_s"), "grid.integration_step_s"
            ),
        )
        horizon = _positive_integer(raw_mpc.get("horizon_steps"), "mpc.horizon_steps")
        if horizon != REQUIRED_HORIZON_STEPS:
            raise ValueError(
                "canonical Phase-5 validation requires frozen horizon_steps=20"
            )
        weights = SDBMPCWeights(
            q_freq=_nonnegative(raw_mpc.get("q_freq"), "mpc.q_freq"),
            q_integral=_nonnegative(
                raw_mpc.get("q_integral"), "mpc.q_integral"
            ),
            q_rocof=_nonnegative(raw_mpc.get("q_rocof"), "mpc.q_rocof"),
            r_sg=_nonnegative(raw_mpc.get("r_sg"), "mpc.r_sg"),
            r_ibr=_nonnegative(raw_mpc.get("r_ibr"), "mpc.r_ibr"),
            s_delta_sg=_nonnegative(
                raw_mpc.get("s_delta_sg"), "mpc.s_delta_sg"
            ),
            s_delta_ibr=_nonnegative(
                raw_mpc.get("s_delta_ibr"), "mpc.s_delta_ibr"
            ),
            q_terminal_freq=_nonnegative(
                raw_mpc.get("q_terminal_freq"), "mpc.q_terminal_freq"
            ),
            q_terminal_integral=_nonnegative(
                raw_mpc.get("q_terminal_integral"), "mpc.q_terminal_integral"
            ),
            lambda_worst_base=_nonnegative(
                raw_mpc.get("lambda_worst_base"), "mpc.lambda_worst_base"
            ),
            lambda_worst_entropy=_nonnegative(
                raw_mpc.get("lambda_worst_entropy"),
                "mpc.lambda_worst_entropy",
            ),
            rho_freq_slack=_nonnegative(
                raw_mpc.get("rho_freq_slack"), "mpc.rho_freq_slack"
            ),
            rho_rocof_slack=_nonnegative(
                raw_mpc.get("rho_rocof_slack"), "mpc.rho_rocof_slack"
            ),
            rho_power_slack=_nonnegative(
                raw_mpc.get("rho_power_slack"), "mpc.rho_power_slack"
            ),
        )
        bounds = SDBMPCBounds(
            u_min_pu=(
                _finite(grid.get("u_sg_min_pu"), "grid.u_sg_min_pu"),
                _finite(ibr.get("u_min_pu"), "ibr_command.u_min_pu"),
            ),
            u_max_pu=(
                _finite(grid.get("u_sg_max_pu"), "grid.u_sg_max_pu"),
                _finite(ibr.get("u_max_pu"), "ibr_command.u_max_pu"),
            ),
            ramp_pu_per_s=(
                _nonnegative(
                    grid.get("u_sg_ramp_pu_per_s"),
                    "grid.u_sg_ramp_pu_per_s",
                ),
                _nonnegative(
                    ibr.get("ramp_pu_per_s"), "ibr_command.ramp_pu_per_s"
                ),
            ),
            freq_limit_hz=_positive(
                grid.get("freq_limit_hz"), "grid.freq_limit_hz"
            ),
            rocof_limit_hz_per_s=_positive(
                grid.get("rocof_limit_hz_per_s"),
                "grid.rocof_limit_hz_per_s",
            ),
        )
        use_tightening = raw_mpc.get("use_constraint_tightening")
        if not isinstance(use_tightening, bool):
            raise TypeError("mpc.use_constraint_tightening must be boolean")
        resolved_mpc = SDBMPCConfig(
            horizon_steps=horizon,
            sample_time_s=grid_params.control_period_s,
            f0_hz=grid_params.f0_hz,
            credible_mass=_probability(
                raw_mpc.get("credible_mass"), "mpc.credible_mass", include_zero=False
            ),
            entropy_use_all_modes=_probability(
                raw_mpc.get("entropy_use_all_modes"),
                "mpc.entropy_use_all_modes",
                include_zero=True,
            ),
            use_constraint_tightening=use_tightening,
            weights=weights,
            bounds=bounds,
        )
        solver_priority = _solver_sequence(raw_mpc.get("solver_priority"))
        return cls(
            grid_params=grid_params,
            mpc_config=resolved_mpc,
            solver_priority=solver_priority,
            solve_timeout_s=_positive(
                raw_mpc.get("solve_timeout_s"), "mpc.solve_timeout_s"
            ),
            max_acceptable_slack_hz=_nonnegative(
                raw_mpc.get("max_acceptable_slack_hz"),
                "mpc.max_acceptable_slack_hz",
            ),
            recovery_hold_steps=_positive_integer(
                fallback.get("recovery_hold_steps"),
                "fallback.recovery_hold_steps",
            ),
            return_blend_steps=_positive_integer(
                fallback.get("return_blend_steps"), "fallback.return_blend_steps"
            ),
            ibr_withdraw_rate_pu_per_s=_nonnegative(
                fallback.get("ibr_withdraw_rate_pu_per_s"),
                "fallback.ibr_withdraw_rate_pu_per_s",
            ),
            belief_switch_epsilon=_nonnegative(
                belief.get("switch_epsilon"), "belief.switch_epsilon"
            ),
            belief_floor=_positive(
                belief.get("probability_floor"), "belief.probability_floor"
            ),
            belief_variance_floor_pu2=_positive(
                belief.get("residual_variance_floor"),
                "belief.residual_variance_floor",
            ),
            ood_config=OODDetectorConfig(
                alpha_on=_positive(ood.get("alpha_on"), "ood.alpha_on"),
                alpha_off=_positive(ood.get("alpha_off"), "ood.alpha_off"),
                L_on=_positive_integer(
                    ood.get("hold_on_steps"), "ood.hold_on_steps"
                ),
                L_off=_positive_integer(
                    ood.get("hold_off_steps"), "ood.hold_off_steps"
                ),
                variance_floor=_positive(
                    belief.get("residual_variance_floor"),
                    "belief.residual_variance_floor",
                ),
            ),
        )


@dataclass(frozen=True, slots=True)
class Phase5ValidationResult:
    """Paths and canonical digests returned by :func:`run_phase5_validation`."""

    output_directory: Path
    summary_sha256: str
    solver_log_sha256: str
    runtime_smoke_log_sha256: str | None
    artifact_manifest_sha256: str


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise TypeError(f"{name} must be a string-keyed mapping")
    return dict(value)


def _finite(value: object, name: str) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise TypeError(f"{name} must be a real number")
    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be a real number") from exc
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


def _positive(value: object, name: str) -> float:
    normalized = _finite(value, name)
    if normalized <= 0.0:
        raise ValueError(f"{name} must be positive")
    return normalized


def _nonnegative(value: object, name: str) -> float:
    normalized = _finite(value, name)
    if normalized < 0.0:
        raise ValueError(f"{name} must be non-negative")
    return normalized


def _positive_integer(value: object, name: str) -> int:
    if isinstance(value, (bool, np.bool_)):
        raise TypeError(f"{name} must be an integer")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be an integer") from exc
    if normalized != value or normalized <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return normalized


def _probability(value: object, name: str, *, include_zero: bool) -> float:
    normalized = _finite(value, name)
    valid = 0.0 <= normalized <= 1.0 if include_zero else 0.0 < normalized <= 1.0
    if not valid:
        interval = "[0, 1]" if include_zero else "(0, 1]"
        raise ValueError(f"{name} must lie in {interval}")
    return normalized


def _solver_sequence(value: object) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError("mpc.solver_priority must be a sequence")
    result = tuple(str(item).strip().upper() for item in value)
    if not result or any(not item for item in result) or len(set(result)) != len(result):
        raise ValueError("mpc.solver_priority must be non-empty and unique")
    return result


def _strict_json(path: Path) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r} in {path}")
            result[key] = value
        return result

    def reject(token: str) -> None:
        raise ValueError(f"non-finite JSON token {token!r} in {path}")

    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=unique,
        parse_constant=reject,
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


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                + "\n"
            )
    return path


def _prepare_output_directory(path: Path) -> Path:
    output = path.expanduser().resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise FileExistsError("Phase-5 output directory must be new or empty")
    output.mkdir(parents=True, exist_ok=True)
    return output


def _portable_path(path: Path, repository_root: Path, raw: str | Path) -> str:
    try:
        return path.resolve().relative_to(repository_root.resolve()).as_posix()
    except ValueError:
        literal = Path(raw)
        if not literal.is_absolute():
            return literal.as_posix()
        return f"<external>/{path.name}"


def _sanitize_text(value: object, repository_root: Path) -> str | None:
    if value is None:
        return None
    rendered = str(value)
    replacements = (
        (str(repository_root), "<repository_root>"),
        (str(Path.home()), "<user_home>"),
    )
    for source, replacement in replacements:
        rendered = rendered.replace(source, replacement).replace(
            source.replace("\\", "/"), replacement
        )
    return rendered[:2000]


def _git_provenance(repository_root: Path) -> dict[str, object]:
    def run(*arguments: str) -> str:
        completed = subprocess.run(
            [
                "git",
                "-c",
                f"safe.directory={repository_root.as_posix()}",
                *arguments,
            ],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15.0,
        )
        return completed.stdout

    try:
        commit = run("rev-parse", "HEAD").strip()
        status = run("status", "--porcelain=v1", "--untracked-files=all")
        diff = run("diff", "--no-ext-diff", "--binary")
        cached_diff = run("diff", "--cached", "--no-ext-diff", "--binary")
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("Phase-5 validation requires readable Git provenance") from exc
    if _SHA256.fullmatch(commit) is None and not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("git rev-parse returned an invalid commit digest")
    changed = sorted(
        line[3:].replace("\\", "/") for line in status.splitlines() if len(line) >= 4
    )
    return {
        "commit": commit,
        "worktree_dirty": bool(status),
        "changed_path_count": len(changed),
        "changed_paths": changed,
        "status_sha256": sha256_json(status.splitlines()),
        "tracked_diff_sha256": sha256_json(diff),
        "cached_diff_sha256": sha256_json(cached_diff),
    }


def phase5_source_hashes(repository_root: str | Path) -> dict[str, str]:
    """Hash every source that materially contributes to Phase-5 evidence."""

    root = Path(repository_root).expanduser().resolve()
    result: dict[str, str] = {}
    for relative in PHASE5_SOURCE_PATHS:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(f"Phase-5 source must be a regular file: {path}")
        result[relative] = sha256_file(path)
    return result


def controller_state_machine_source() -> dict[str, object]:
    """Return the declarative source used to render the Phase-5 state graph."""

    return {
        "schema_version": PHASE5_SCHEMA_VERSION,
        "coordinate_system": "normalized_figure_axes",
        "states": [
            {
                "id": "NORMAL_BELIEF_MPC",
                "position": [0.18, 0.76],
                "description": "credible-set shared-input QCQP",
            },
            {
                "id": "ROBUST_BELIEF_MPC",
                "position": [0.82, 0.76],
                "description": "all-known-mode shared-input QCQP",
            },
            {
                "id": "FALLBACK",
                "position": [0.50, 0.18],
                "description": "fresh LQI + rate-limited IBR withdrawal; hold then blend",
            },
        ],
        "transitions": [
            {
                "from": "NORMAL_BELIEF_MPC",
                "to": "ROBUST_BELIEF_MPC",
                "code": "T1",
                "label": "high entropy or OOD SUSPECT",
                "curvature": 0.12,
                "label_position": [0.50, 0.89],
            },
            {
                "from": "ROBUST_BELIEF_MPC",
                "to": "NORMAL_BELIEF_MPC",
                "code": "T2",
                "label": "confidence restored + KNOWN",
                "curvature": 0.12,
                "label_position": [0.50, 0.65],
            },
            {
                "from": "NORMAL_BELIEF_MPC",
                "to": "FALLBACK",
                "code": "T3",
                "label": "OOD ACTIVE / non-exact solve / rejected slack",
                "curvature": 0.05,
                "label_position": [0.24, 0.48],
            },
            {
                "from": "ROBUST_BELIEF_MPC",
                "to": "FALLBACK",
                "code": "T4",
                "label": "OOD ACTIVE / non-exact solve / rejected slack",
                "curvature": -0.05,
                "label_position": [0.76, 0.48],
            },
            {
                "from": "FALLBACK",
                "to": "NORMAL_BELIEF_MPC",
                "code": "T5",
                "label": "KNOWN for hold; linear blend completes",
                "curvature": -0.18,
                "label_position": [0.37, 0.36],
            },
            {
                "from": "FALLBACK",
                "to": "ROBUST_BELIEF_MPC",
                "code": "T6",
                "label": "return completes while robust condition remains",
                "curvature": 0.18,
                "label_position": [0.63, 0.36],
            },
        ],
        "fallback_internal_semantics": {
            "ibr_withdrawal": "rate_limited_toward_zero_every_fallback_step",
            "sg_command": "fresh_LQI_recomputed_every_fallback_step",
            "recovery": "KNOWN_hold_then_linear_LQI_to_MPC_blend",
            "recurrence": "any_non_KNOWN_diagnostic_resets_hold_and_blend",
        },
    }


def render_controller_state_machine(
    source: Mapping[str, Any] | str | Path,
    output_path: str | Path,
) -> Path:
    """Render a deterministic PNG from :func:`controller_state_machine_source`."""

    payload = (
        _strict_json(Path(source).expanduser().resolve())
        if isinstance(source, (str, Path))
        else dict(source)
    )
    states = payload.get("states")
    transitions = payload.get("transitions")
    if not isinstance(states, list) or not isinstance(transitions, list):
        raise ValueError("state-machine source must contain state and transition lists")
    by_id: dict[str, tuple[float, float]] = {}
    figure, (axis, legend_axis) = plt.subplots(
        1,
        2,
        figsize=(13.0, 6.8),
        gridspec_kw={"width_ratios": [2.35, 1.0]},
        constrained_layout=True,
    )
    axis.set_xlim(0.0, 1.0)
    axis.set_ylim(0.0, 1.0)
    axis.axis("off")
    colors = {
        "NORMAL_BELIEF_MPC": "#D9EAF7",
        "ROBUST_BELIEF_MPC": "#FFE7B3",
        "FALLBACK": "#F8C7C7",
    }
    for item in states:
        if not isinstance(item, Mapping):
            raise TypeError("each state-machine state must be a mapping")
        identifier = str(item["id"])
        position = item["position"]
        if not isinstance(position, list) or len(position) != 2:
            raise ValueError("state position must have two entries")
        x, y = float(position[0]), float(position[1])
        by_id[identifier] = (x, y)
        width = 0.32 if identifier != "FALLBACK" else 0.42
        box = FancyBboxPatch(
            (x - width / 2.0, y - 0.075),
            width,
            0.15,
            boxstyle="round,pad=0.015,rounding_size=0.025",
            facecolor=colors.get(identifier, "#EEEEEE"),
            edgecolor="#263238",
            linewidth=1.4,
            zorder=3,
        )
        axis.add_patch(box)
        axis.text(
            x,
            y + 0.018,
            identifier,
            ha="center",
            va="center",
            fontsize=10,
            fontweight="bold",
            zorder=4,
        )
        axis.text(
            x,
            y - 0.030,
            str(item["description"]),
            ha="center",
            va="center",
            fontsize=7.5,
            zorder=4,
        )
    legend_lines: list[str] = []
    for transition in transitions:
        if not isinstance(transition, Mapping):
            raise TypeError("each state-machine transition must be a mapping")
        start = by_id[str(transition["from"])]
        end = by_id[str(transition["to"])]
        curvature = float(transition.get("curvature", 0.0))
        arrow_start = start
        arrow_end = end
        shrink = 58
        if math.isclose(start[1], end[1], rel_tol=0.0, abs_tol=1.0e-12):
            direction = 1.0 if end[0] > start[0] else -1.0
            arrow_start = (start[0] + direction * 0.17, start[1])
            arrow_end = (end[0] - direction * 0.17, end[1])
            shrink = 3
        axis.annotate(
            "",
            xy=arrow_end,
            xytext=arrow_start,
            arrowprops={
                "arrowstyle": "-|>",
                "color": "#455A64",
                "linewidth": 1.15,
                "shrinkA": shrink,
                "shrinkB": shrink,
                "connectionstyle": f"arc3,rad={curvature}",
            },
            zorder=2,
        )
        code = str(transition["code"])
        position = transition["label_position"]
        if not isinstance(position, list) or len(position) != 2:
            raise ValueError("transition label_position must have two entries")
        axis.text(
            float(position[0]),
            float(position[1]),
            code,
            ha="center",
            va="center",
            fontsize=8.5,
            fontweight="bold",
            color="white",
            bbox={
                "boxstyle": "round,pad=0.22",
                "facecolor": "#455A64",
                "edgecolor": "white",
                "linewidth": 0.8,
            },
            zorder=5,
        )
        legend_lines.append(f"{code}  {transition['label']}")
    axis.set_title("SD-BMPC controller state machine", fontsize=14, pad=8)
    legend_axis.axis("off")
    legend_axis.set_xlim(0.0, 1.0)
    legend_axis.set_ylim(0.0, 1.0)
    legend_axis.text(
        0.02,
        0.94,
        "Transition conditions",
        fontsize=12,
        fontweight="bold",
        va="top",
    )
    legend_axis.text(
        0.02,
        0.87,
        "\n\n".join(legend_lines),
        fontsize=9,
        va="top",
        linespacing=1.25,
        wrap=True,
    )
    semantics = _mapping(
        payload.get("fallback_internal_semantics"),
        "fallback_internal_semantics",
    )
    legend_axis.text(
        0.02,
        0.34,
        "Fallback invariants",
        fontsize=12,
        fontweight="bold",
        va="top",
    )
    invariant_lines = [
        f"- {str(value).replace('_', ' ')}" for value in semantics.values()
    ]
    legend_axis.text(
        0.02,
        0.28,
        "\n".join(invariant_lines),
        fontsize=8.7,
        va="top",
        linespacing=1.35,
        wrap=True,
    )
    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(
        destination,
        dpi=180,
        metadata={"Software": "d5freq.phase5_validation"},
    )
    plt.close(figure)
    return destination


def _validate_frozen_inputs(
    library: ModeLibrary,
    library_path: Path,
    calibration: OODCalibrationArtifact,
) -> dict[str, object]:
    component_ids = tuple(model.component_id for model in library.models)
    expected = tuple(range(REQUIRED_NATIVE_COMPONENT_COUNT))
    if component_ids != expected:
        raise ValueError(f"canonical Phase-5 library must retain native IDs {expected}")
    file_digest = sha256_file(library_path)
    logical_digest = sha256_json(library.to_dict())
    if calibration.mode_library_sha256 != file_digest:
        raise ValueError("OOD calibration mode-library file hash mismatch")
    if calibration.mode_library_logical_sha256 != logical_digest:
        raise ValueError("OOD calibration logical mode-library hash mismatch")
    if calibration.known_component_ids != expected:
        raise ValueError("OOD calibration does not bind all native K6 components")
    return {
        "native_component_count": len(component_ids),
        "native_component_ids": list(component_ids),
        "mode_library_sha256": file_digest,
        "mode_library_logical_sha256": logical_digest,
        "ood_calibration_source_split": calibration.source_split,
        "ood_calibration_source_population": calibration.source_population,
        "ood_calibration_score_count": len(calibration.calibration_scores),
        "ood_calibration_binding_verified": True,
    }


def _precompile(
    problem: Any,
    solver_priority: Sequence[str],
    repository_root: Path,
) -> tuple[str, float, list[dict[str, object]]]:
    installed = {str(item).upper() for item in cp.installed_solvers()}
    attempts: list[dict[str, object]] = []
    for solver in solver_priority:
        if solver not in installed:
            attempts.append(
                {
                    "solver": solver,
                    "installed": False,
                    "success": False,
                    "wall_time_s": 0.0,
                    "error_type": "SolverNotInstalled",
                    "error_message": None,
                }
            )
            continue
        start = perf_counter()
        try:
            wall_time = float(problem.precompile(solver))
        except Exception as exc:
            attempts.append(
                {
                    "solver": solver,
                    "installed": True,
                    "success": False,
                    "wall_time_s": perf_counter() - start,
                    "error_type": type(exc).__name__,
                    "error_message": _sanitize_text(exc, repository_root),
                }
            )
            continue
        attempts.append(
            {
                "solver": solver,
                "installed": True,
                "success": True,
                "wall_time_s": wall_time,
                "error_type": None,
                "error_message": None,
            }
        )
        return solver, wall_time, attempts
    raise RuntimeError("no configured solver could precompile the native K6 template")


def _sanitized_solver_log(
    result: SolverResult,
    repository_root: Path,
) -> dict[str, object]:
    payload = result.to_log_dict()
    payload["error_message"] = _sanitize_text(payload.get("error_message"), repository_root)
    attempts = payload.get("attempts")
    if isinstance(attempts, list):
        for item in attempts:
            if isinstance(item, dict):
                item["error_message"] = _sanitize_text(
                    item.get("error_message"), repository_root
                )
    return payload


def _max_solution_value(result: SolverResult, name: str) -> float | None:
    if not result.success:
        return None
    value = np.asarray(result.value(name), dtype=float)
    return float(np.max(value)) if value.size else 0.0


def _run_optimization_audit(
    *,
    grid_model: GridFrequencyModel,
    library: ModeLibrary,
    settings: Phase5Settings,
    singleton_component_id: int,
    repeat_count: int,
    repository_root: Path,
) -> tuple[pd.DataFrame, list[dict[str, object]], dict[str, object]]:
    modes = modes_from_library(grid_model, library)
    component_ids = tuple(mode.component_id for mode in modes)
    if singleton_component_id not in component_ids:
        raise ValueError("singleton_component_id is absent from the native library")
    singleton_index = component_ids.index(singleton_component_id)
    initial_state = np.zeros(10, dtype=np.float64)
    initial_state[0] = -1.0e-3
    initial_state[3] = -2.5e-4
    initial_state[4] = 4.0e-2
    initial_state[8] = -1.0e-3
    initial_state[9] = 1.0
    previous_input = np.zeros(2, dtype=np.float64)
    uniform = np.full(len(modes), 1.0 / len(modes), dtype=np.float64)
    singleton = np.zeros(len(modes), dtype=np.float64)
    singleton[singleton_index] = 1.0

    cache = SDBMPCProblemCache(modes, config=settings.mpc_config)
    bundle = cache.prepare(
        initial_state,
        uniform,
        previous_input,
        entropy_normalized=1.0,
        ood_suspect=False,
    )
    problem_identity = id(bundle.problem)
    precompile_solver, precompile_time, precompile_attempts = _precompile(
        bundle, settings.solver_priority, repository_root
    )

    flat_rows: list[dict[str, object]] = []
    detailed_rows: list[dict[str, object]] = []
    warm_start: np.ndarray | None = None
    for repeat_index in range(repeat_count):
        for case, belief, entropy in (
            ("all_modes", uniform, 1.0),
            (f"singleton_component_{singleton_component_id}", singleton, 0.0),
        ):
            bundle = cache.prepare(
                initial_state,
                belief,
                previous_input,
                entropy_normalized=entropy,
                ood_suspect=False,
            )
            same_template = id(bundle.problem) == problem_identity
            if not same_template:
                raise RuntimeError("risk-mask update rebuilt the CVXPY problem")
            bundle.set_warm_start(warm_start)
            result = solve_cvxpy_problem(
                bundle.problem,
                solution_variables=bundle.solution_variables(),
                solver_priority=settings.solver_priority,
                timeout_s=settings.solve_timeout_s,
                warm_start=True,
            )
            freq_slack = _max_solution_value(result, "freq_slack_hz")
            rocof_slack = _max_solution_value(result, "rocof_slack_hz_per_s")
            power_slack = _max_solution_value(result, "power_slack_pu")
            first_sg: float | None = None
            first_ibr: float | None = None
            if result.success:
                sequence = np.asarray(result.value("shared_input"), dtype=float)
                if sequence.shape != (2, REQUIRED_HORIZON_STEPS):
                    raise RuntimeError("solver returned an invalid shared input shape")
                first_sg = float(sequence[0, 0])
                first_ibr = float(sequence[1, 0])
                warm_start = shift_warm_start_sequence(sequence)
            else:
                warm_start = None
            flat = {
                "case": case,
                "repeat_index": repeat_index,
                "same_cvxpy_problem_object": same_template,
                "native_component_count": len(component_ids),
                "risk_component_ids": json.dumps(list(bundle.risk_component_ids)),
                "risk_component_count": len(bundle.risk_component_ids),
                "shared_input_rows": int(bundle.shared_input.shape[0]),
                "horizon_steps": int(bundle.shared_input.shape[1]),
                "problem_is_dcp": bool(bundle.problem.is_dcp()),
                "problem_is_dpp": bool(bundle.problem.is_dcp(dpp=True)),
                "status": result.status,
                "outcome": result.outcome.value,
                "success": result.success,
                "solver": result.solver,
                "solver_version": result.solver_version,
                "total_wall_time_s": result.total_wall_time_s,
                "solver_solve_time_s": result.solver_solve_time_s,
                "solver_setup_time_s": result.solver_setup_time_s,
                "iterations": result.iterations,
                "objective": result.objective,
                "max_freq_slack_hz": freq_slack,
                "max_rocof_slack_hz_per_s": rocof_slack,
                "max_power_slack_pu": power_slack,
                "first_u_sg_pu": first_sg,
                "first_u_ibr_pu": first_ibr,
                "within_configured_wall_budget": (
                    result.total_wall_time_s < settings.solve_timeout_s
                ),
                "commercial_solver": result.solver in COMMERCIAL_SOLVERS,
                "error_type": result.error_type,
                "error_message": _sanitize_text(result.error_message, repository_root),
            }
            flat_rows.append(flat)
            detailed_rows.append(
                {
                    "schema_version": PHASE5_SCHEMA_VERSION,
                    "case": case,
                    "repeat_index": repeat_index,
                    "risk_component_ids": list(bundle.risk_component_ids),
                    "same_cvxpy_problem_object": same_template,
                    "max_slack": {
                        "frequency_hz": freq_slack,
                        "rocof_hz_per_s": rocof_slack,
                        "power_pu": power_slack,
                    },
                    "first_action_pu": {"u_sg": first_sg, "u_ibr": first_ibr},
                    "solver_result": _sanitized_solver_log(result, repository_root),
                }
            )
    table = pd.DataFrame(flat_rows)
    structural = {
        "native_component_count": len(component_ids),
        "component_ids": list(component_ids),
        "horizon_steps": REQUIRED_HORIZON_STEPS,
        "shared_input_shape": [2, REQUIRED_HORIZON_STEPS],
        "single_shared_input_variable": True,
        "problem_is_dcp": bool(bundle.problem.is_dcp()),
        "problem_is_dpp": bool(bundle.problem.is_dcp(dpp=True)),
        "template_identity_stable_across_all_updates": bool(
            table["same_cvxpy_problem_object"].all()
        ),
        "all_mode_mask_observed": bool(
            (table.loc[table["case"] == "all_modes", "risk_component_count"] == 6).all()
        ),
        "singleton_mask_observed": bool(
            (
                table.loc[
                    table["case"] == f"singleton_component_{singleton_component_id}",
                    "risk_component_count",
                ]
                == 1
            ).all()
        ),
        "precompile_solver": precompile_solver,
        "precompile_wall_time_s": precompile_time,
        "precompile_attempts": precompile_attempts,
        "timed_solve_count": len(table),
        "repeat_count_per_mask": repeat_count,
        "configured_timeout_s": settings.solve_timeout_s,
        "timeout_enforcement": (
            "solver_cooperative_soft_wall_deadline_checked_after_solver_return; "
            "not a hard real-time preemption guarantee"
        ),
        "power_constraint_source": (
            "per-component train/validation capability bounds and directional "
            "power-rate bounds with one shared nonnegative power slack"
        ),
        "power_q95_used_as_equation_65_66_tightening": False,
    }
    return table, detailed_rows, structural


def assert_runtime_truth_free(records: Sequence[Mapping[str, Any]]) -> None:
    """Reject runtime records whose keys expose simulator-private mode truth."""

    def visit(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                normalized = str(key).casefold()
                if any(fragment in normalized for fragment in _FORBIDDEN_RUNTIME_KEY_FRAGMENTS):
                    raise ValueError(f"runtime record contains forbidden truth key at {path}.{key}")
                visit(item, f"{path}.{key}")
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")

    visit(list(records), "records")


def _load_ood_selection(path: Path) -> OODDetectorConfig:
    payload = _strict_json(path)
    if not isinstance(payload, Mapping):
        raise TypeError("OOD selection artifact must be a mapping")
    selected = _mapping(payload.get("selected"), "OOD selection selected")
    if payload.get("ood_data_used_for_selection") is not False:
        raise ValueError("OOD selection must attest no OOD data use")
    return OODDetectorConfig(
        alpha_on=_positive(selected.get("alpha_on"), "selected.alpha_on"),
        alpha_off=_positive(selected.get("alpha_off"), "selected.alpha_off"),
        L_on=_positive_integer(
            selected.get("hold_on_steps"), "selected.hold_on_steps"
        ),
        L_off=_positive_integer(
            selected.get("hold_off_steps"), "selected.hold_off_steps"
        ),
        variance_floor=_positive(
            selected.get("variance_floor"), "selected.variance_floor"
        ),
    )


def _run_controller_smoke(
    *,
    grid_model: GridFrequencyModel,
    base_config_path: Path,
    mpc_config_path: Path,
    mode_library_path: Path,
    ood_calibration_path: Path,
    known_modes_config_path: Path,
    settings: Phase5Settings,
    smoke_steps: int,
    seed: int,
    repository_root: Path,
) -> tuple[
    pd.DataFrame,
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, object],
]:
    # Import controller implementation lazily so optimization-only tooling can
    # still be imported while the controller is under development.
    from d5freq.controllers.sd_bmpc import SDBMPCController
    from d5freq.models.hidden_mode_ibr import IBRModeParams
    from d5freq.simulation.disturbances import LoadDisturbanceSpec, LoadEvent
    from d5freq.simulation.hybrid_simulator import HiddenModeFrequencySimulator, Scenario
    from d5freq.simulation.mode_schedules import PiecewiseConstantModeSchedule

    controller = SDBMPCController.from_project_files(
        base_config_path=base_config_path,
        mpc_config_path=mpc_config_path,
        mode_library_path=mode_library_path,
        ood_calibration_path=ood_calibration_path,
    )
    if controller.mpc_config != settings.mpc_config:
        raise RuntimeError("production factory resolved a different MPC configuration")
    if tuple(mode.component_id for mode in controller.modes) != tuple(range(6)):
        raise RuntimeError("production factory did not retain native K6 component IDs")
    factory_provenance = controller.provenance
    if factory_provenance is None:
        raise RuntimeError("production factory omitted immutable artifact provenance")
    factory_provenance_payload = {
        name: getattr(factory_provenance, name)
        for name in factory_provenance.__dataclass_fields__
    }

    # Simulator truth is loaded only by this evaluation orchestrator, after the
    # controller is fully constructed from public/frozen runtime artifacts.
    raw_modes = load_yaml(known_modes_config_path)
    modes_mapping = _mapping(raw_modes.get("known_modes"), "known_modes")
    simulator_modes = {
        name: IBRModeParams.from_mapping(name, value)
        for name, value in modes_mapping.items()
    }
    duration = smoke_steps * settings.grid_params.control_period_s
    scenario = Scenario(
        mode_schedule=PiecewiseConstantModeSchedule("nominal"),
        duration_s=duration,
        disturbance=LoadDisturbanceSpec(
            events=(
                LoadEvent(
                    start_time_s=min(
                        2.0 * settings.grid_params.control_period_s,
                        duration - settings.grid_params.control_period_s,
                    ),
                    magnitude_pu=0.02,
                ),
            ),
            sample_period_s=settings.grid_params.control_period_s,
        ),
        name="phase5_controller_smoke",
    )
    simulator = HiddenModeFrequencySimulator(grid_model, simulator_modes)
    measurement = simulator.reset(seed, scenario)
    controller.reset(measurement)

    runtime_rows: list[dict[str, Any]] = []
    simulator_private_records_discarded = 0
    for step_index in range(smoke_steps):
        action = controller.act(measurement)
        runtime_rows.append(
            {
                "step_index": step_index,
                "time_s": measurement.time_s,
                "omega_pu": measurement.omega_pu,
                "p_mech_pu": measurement.p_mech_pu,
                "p_ibr_pu": measurement.p_ibr_pu,
                "u_sg_prev_pu": measurement.u_sg_prev_pu,
                "u_ibr_prev_pu": measurement.u_ibr_prev_pu,
                "u_sg_pu": action.u_sg_pu,
                "u_ibr_pu": action.u_ibr_pu,
                "controller_state": action.controller_state,
                "solver_status": action.solver_status,
                "solve_time_s": action.solve_time_s,
                "max_freq_slack_hz": action.max_freq_slack_hz,
            }
        )
        if step_index + 1 < smoke_steps:
            measurement, private_evaluation = simulator.step(action)
            # The object is deliberately neither inspected nor persisted.
            del private_evaluation
            simulator_private_records_discarded += 1

    step_records = [record.to_log_record() for record in controller.step_records]
    for record in step_records:
        if "error_message" in record:
            record["error_message"] = _sanitize_text(
                record.get("error_message"), repository_root
            )
    fallback_events = [event.to_log_record() for event in controller.fallback_events]
    precompile_records = [
        {
            "solver": record.solver,
            "success": record.success,
            "wall_time_s": record.wall_time_s,
            "error_type": record.error_type,
            "error_message": _sanitize_text(record.error_message, repository_root),
        }
        for record in controller.precompile_records
    ]
    assert_runtime_truth_free(runtime_rows)
    assert_runtime_truth_free(step_records)
    assert_runtime_truth_free(fallback_events)
    assert_runtime_truth_free(precompile_records)
    act_parameters = list(inspect.signature(controller.act).parameters)
    if act_parameters != ["measurement"]:
        raise RuntimeError("proposed-controller act API has an unexpected signature")
    boundary = {
        "controller_constructed_before_simulator_truth_config_loaded": True,
        "production_from_project_files_factory_used": True,
        "controller_constructor_received_known_modes_config": False,
        "production_factory_provenance": factory_provenance_payload,
        "controller_act_parameters": act_parameters,
        "simulator_private_records_returned_then_discarded": (
            simulator_private_records_discarded
        ),
        "runtime_log_contains_simulator_truth": False,
        "runtime_step_count": len(runtime_rows),
        "controller_step_record_count": len(step_records),
        "fallback_event_count": len(fallback_events),
        "precompile_record_count": len(precompile_records),
    }
    return (
        pd.DataFrame(runtime_rows),
        step_records,
        fallback_events,
        precompile_records,
        boundary,
    )


def _case_timing_summary(table: pd.DataFrame, case: str) -> dict[str, object]:
    selected = table.loc[table["case"] == case]
    values = selected["total_wall_time_s"].to_numpy(dtype=float)
    successes = selected["success"].to_numpy(dtype=bool)
    return {
        "solve_count": int(len(selected)),
        "exact_optimal_count": int(np.count_nonzero(successes)),
        "exact_optimal_rate": float(np.mean(successes)),
        "wall_time_s": {
            "minimum": float(np.min(values)),
            "median": float(np.median(values)),
            "p95": float(np.quantile(values, 0.95)),
            "maximum": float(np.max(values)),
        },
        "within_configured_wall_budget_count": int(
            selected["within_configured_wall_budget"].sum()
        ),
        "commercial_solver_success_count": int(
            (selected["success"] & selected["commercial_solver"]).sum()
        ),
        "statuses": {
            str(key): int(value)
            for key, value in selected["status"].value_counts(dropna=False).items()
        },
    }


def write_phase5_artifact_manifest(output_directory: str | Path) -> tuple[Path, str]:
    """Write the final self-verifying manifest and its SHA-256 sidecar."""

    output = Path(output_directory).expanduser().resolve()
    manifest_path = output / "artifact_manifest.json"
    sidecar_path = output / "artifact_manifest.sha256"
    if manifest_path.exists() or sidecar_path.exists():
        raise FileExistsError("artifact manifest already exists")
    files = file_sha256_manifest(output)
    payload = {
        "schema_version": PHASE5_SCHEMA_VERSION,
        "scope": "all_phase5_artifacts_except_manifest_and_hash_sidecar",
        "artifact_set_sha256": sha256_json(files),
        "files": list(files),
    }
    _write_json(manifest_path, payload)
    digest = sha256_file(manifest_path)
    sidecar_path.write_text(digest + "\n", encoding="ascii", newline="\n")
    return manifest_path, digest


def verify_phase5_artifact_manifest(output_directory: str | Path) -> bool:
    """Verify manifest sidecar, complete file set, sizes, and every file hash."""

    output = Path(output_directory).expanduser().resolve()
    manifest_path = output / "artifact_manifest.json"
    sidecar_path = output / "artifact_manifest.sha256"
    payload = _strict_json(manifest_path)
    if not isinstance(payload, Mapping):
        raise TypeError("artifact manifest must be a mapping")
    expected_manifest_digest = sidecar_path.read_text(encoding="ascii").strip()
    if _SHA256.fullmatch(expected_manifest_digest) is None:
        raise ValueError("artifact manifest sidecar is not a SHA-256 digest")
    if sha256_file(manifest_path) != expected_manifest_digest:
        raise ValueError("artifact manifest sidecar mismatch")
    files = payload.get("files")
    if not isinstance(files, list):
        raise TypeError("artifact manifest files must be a list")
    current = tuple(
        item
        for item in file_sha256_manifest(output)
        if item["path"] not in {"artifact_manifest.json", "artifact_manifest.sha256"}
    )
    if list(current) != files:
        raise ValueError("artifact file set, size, or SHA-256 mismatch")
    if sha256_json(current) != payload.get("artifact_set_sha256"):
        raise ValueError("artifact-set logical digest mismatch")
    return True


def run_phase5_validation(
    *,
    base_config_path: str | Path,
    mpc_config_path: str | Path,
    mode_library_path: str | Path,
    ood_calibration_path: str | Path,
    ood_selection_path: str | Path,
    known_modes_config_path: str | Path,
    output_directory: str | Path,
    repeat_count: int = 5,
    singleton_component_id: int = 3,
    controller_smoke_steps: int = 8,
    controller_smoke_seed: int = 20260722,
    run_controller_smoke: bool = True,
) -> Phase5ValidationResult:
    """Produce the complete, parameterized Phase-5 audit artifact directory."""

    repeats = _positive_integer(repeat_count, "repeat_count")
    smoke_steps = _positive_integer(controller_smoke_steps, "controller_smoke_steps")
    if isinstance(singleton_component_id, bool) or int(singleton_component_id) != singleton_component_id:
        raise TypeError("singleton_component_id must be an integer")
    if isinstance(controller_smoke_seed, bool) or int(controller_smoke_seed) != controller_smoke_seed:
        raise TypeError("controller_smoke_seed must be an integer")
    if int(controller_smoke_seed) < 0:
        raise ValueError("controller_smoke_seed must be non-negative")
    if not isinstance(run_controller_smoke, bool):
        raise TypeError("run_controller_smoke must be boolean")

    python_environment_name = Path(sys.prefix).name
    if python_environment_name != "topo_sfr":
        raise RuntimeError(
            "canonical Phase-5 validation must run in the topo_sfr Conda environment"
        )
    output = _prepare_output_directory(Path(output_directory))
    repository_root = Path(__file__).resolve().parents[3]
    raw_paths = {
        "base_config": base_config_path,
        "mpc_config": mpc_config_path,
        "mode_library": mode_library_path,
        "ood_calibration": ood_calibration_path,
        "ood_selection": ood_selection_path,
        "known_modes_simulator_only": known_modes_config_path,
        "output_directory": output_directory,
    }
    paths = {
        key: Path(value).expanduser().resolve()
        for key, value in raw_paths.items()
        if key != "output_directory"
    }
    base_config = load_yaml(paths["base_config"])
    raw_mpc_config = load_yaml(paths["mpc_config"])
    settings = Phase5Settings.from_configs(base_config, raw_mpc_config)
    library = ModeLibrary.load_json(paths["mode_library"])
    calibration_payload = _strict_json(paths["ood_calibration"])
    if not isinstance(calibration_payload, Mapping):
        raise TypeError("OOD calibration artifact must be a mapping")
    calibration = OODCalibrationArtifact.from_dict(calibration_payload)
    selected_ood_config = _load_ood_selection(paths["ood_selection"])
    if selected_ood_config != settings.ood_config:
        raise ValueError(
            "frozen OOD selection differs from the runtime defaults in base.yaml"
        )
    frozen_binding = _validate_frozen_inputs(
        library, paths["mode_library"], calibration
    )
    frozen_binding["ood_selection_matches_base_runtime_defaults"] = True
    frozen_binding["ood_calibration_sha256"] = sha256_file(
        paths["ood_calibration"]
    )
    frozen_binding["ood_selection_sha256"] = sha256_file(paths["ood_selection"])
    grid_model = GridFrequencyModel(settings.grid_params)

    git_provenance = _git_provenance(repository_root)
    environment = collect_environment_info(
        extra={
            "project_environment": "topo_sfr",
            "python_prefix_name": python_environment_name,
            "phase": 5,
            "solver_policy": "exact_optimal_only",
        }
    )
    source_hashes = phase5_source_hashes(repository_root)
    git_path = _write_json(output / "git_provenance.json", git_provenance)
    environment_path = _write_json(output / "environment.json", environment)
    source_hashes_path = _write_json(output / "source_sha256.json", source_hashes)
    provenance = {
        "schema_version": PHASE5_SCHEMA_VERSION,
        "git": git_provenance,
        "environment": environment,
        "randomness": {
            "optimization_audit": "deterministic_no_rng",
            "controller_smoke_seed": int(controller_smoke_seed),
        },
        "source_sha256": source_hashes,
    }
    provenance_path = _write_json(
        output / "reproducibility_provenance.json", provenance
    )

    state_source_path = _write_json(
        output / "controller_state_machine_source.json",
        controller_state_machine_source(),
    )
    state_figure_path = render_controller_state_machine(
        state_source_path, output / "controller_state_machine.png"
    )

    solver_table, detailed_solver_rows, structural = _run_optimization_audit(
        grid_model=grid_model,
        library=library,
        settings=settings,
        singleton_component_id=int(singleton_component_id),
        repeat_count=repeats,
        repository_root=repository_root,
    )
    solver_csv = output / "solver_timing_status.csv"
    solver_parquet = output / "solver_timing_status.parquet"
    solver_jsonl = output / "solver_attempts.jsonl"
    solver_table.to_csv(solver_csv, index=False, float_format="%.17g")
    solver_table.to_parquet(
        solver_parquet, engine="pyarrow", index=False, compression="zstd"
    )
    _write_jsonl(solver_jsonl, detailed_solver_rows)
    structural_path = _write_json(
        output / "optimization_structure.json", structural
    )

    runtime_smoke_path: Path | None = None
    runtime_smoke_sha256: str | None = None
    smoke_summary: dict[str, object] = {
        "requested": run_controller_smoke,
        "executed": False,
    }
    if run_controller_smoke:
        (
            runtime_table,
            step_records,
            fallback_events,
            precompile_records,
            boundary,
        ) = _run_controller_smoke(
            grid_model=grid_model,
            base_config_path=paths["base_config"],
            mpc_config_path=paths["mpc_config"],
            mode_library_path=paths["mode_library"],
            ood_calibration_path=paths["ood_calibration"],
            known_modes_config_path=paths["known_modes_simulator_only"],
            settings=settings,
            smoke_steps=smoke_steps,
            seed=int(controller_smoke_seed),
            repository_root=repository_root,
        )
        runtime_smoke_path = output / "controller_smoke_runtime.parquet"
        runtime_table.to_parquet(
            runtime_smoke_path, engine="pyarrow", index=False, compression="zstd"
        )
        runtime_table.to_csv(
            output / "controller_smoke_runtime.csv",
            index=False,
            float_format="%.17g",
        )
        _write_jsonl(output / "controller_step_records.jsonl", step_records)
        _write_jsonl(output / "fallback_events.jsonl", fallback_events)
        _write_jsonl(
            output / "controller_precompile_records.jsonl", precompile_records
        )
        runtime_smoke_sha256 = sha256_file(runtime_smoke_path)
        boundary_path = _write_json(
            output / "controller_runtime_information_boundary.json",
            {
                "schema_version": PHASE5_SCHEMA_VERSION,
                **boundary,
                "runtime_log_sha256": runtime_smoke_sha256,
            },
        )
        smoke_summary = {
            "requested": True,
            "executed": True,
            "runtime_step_count": len(runtime_table),
            "controller_states": {
                str(key): int(value)
                for key, value in runtime_table["controller_state"].value_counts().items()
            },
            "solver_statuses": {
                str(key): int(value)
                for key, value in runtime_table["solver_status"].value_counts().items()
            },
            "fallback_event_count": len(fallback_events),
            "precompile_record_count": len(precompile_records),
            "runtime_log_sha256": runtime_smoke_sha256,
            "information_boundary_sha256": sha256_file(boundary_path),
        }

    resolved = {
        "schema_version": PHASE5_SCHEMA_VERSION,
        "base_config": base_config,
        "mpc_config": raw_mpc_config,
        "validation": {
            "repeat_count_per_mask": repeats,
            "singleton_component_id": int(singleton_component_id),
            "controller_smoke_steps": smoke_steps,
            "controller_smoke_seed": int(controller_smoke_seed),
            "run_controller_smoke": run_controller_smoke,
        },
        "paths": {
            key: _portable_path(paths[key], repository_root, raw_paths[key])
            for key in paths
        },
        "input_sha256": {key: sha256_file(value) for key, value in paths.items()},
        "information_boundary": {
            "known_modes_config_role": "simulator_only_never_controller_input",
            "mode_library_role": "runtime_native_component_models_no_truth_labels",
            "ood_calibration_role": "known_only_calibration_runtime_input",
        },
    }
    resolved_path = save_yaml(resolved, output / "resolved_phase5_config.yaml")

    case_names = tuple(dict.fromkeys(str(item) for item in solver_table["case"]))
    timing = {case: _case_timing_summary(solver_table, case) for case in case_names}
    all_exact = bool(solver_table["success"].all())
    all_commercial = bool(
        solver_table.loc[solver_table["success"], "commercial_solver"].all()
    )
    summary = {
        "schema_version": PHASE5_SCHEMA_VERSION,
        "output_directory": _portable_path(
            output, repository_root, raw_paths["output_directory"]
        ),
        "canonical_problem": {
            "native_component_count": REQUIRED_NATIVE_COMPONENT_COUNT,
            "horizon_steps": REQUIRED_HORIZON_STEPS,
            "shared_input_shape": [2, REQUIRED_HORIZON_STEPS],
            "convex_dcp": structural["problem_is_dcp"],
            "disciplined_parametrized_program": structural["problem_is_dpp"],
            "same_template_for_dynamic_masks": structural[
                "template_identity_stable_across_all_updates"
            ],
        },
        "frozen_artifact_binding": frozen_binding,
        "precompile": {
            "solver": structural["precompile_solver"],
            "wall_time_s": structural["precompile_wall_time_s"],
            "outside_timed_solve_loop": True,
        },
        "timing_and_status_by_case": timing,
        "all_timed_solves_exact_optimal": all_exact,
        "all_successful_solves_used_commercial_solver": all_commercial,
        "solver_timing_claim_eligible": all_exact and all_commercial,
        "timing_scope_note": (
            "Measurements are machine- and license-specific Phase-5 audit evidence, "
            "not portable real-time guarantees. CLARABEL/SCS results are debug-only."
        ),
        "solver_deadline_limitation": structural["timeout_enforcement"],
        "power_constraint_semantics": {
            "source": structural["power_constraint_source"],
            "power_q95_used_as_equation_65_66_tightening": structural[
                "power_q95_used_as_equation_65_66_tightening"
            ],
        },
        "controller_smoke": smoke_summary,
        "artifacts": {
            "solver_csv_sha256": sha256_file(solver_csv),
            "solver_parquet_sha256": sha256_file(solver_parquet),
            "solver_jsonl_sha256": sha256_file(solver_jsonl),
            "optimization_structure_sha256": sha256_file(structural_path),
            "state_machine_source_sha256": sha256_file(state_source_path),
            "state_machine_png_sha256": sha256_file(state_figure_path),
            "resolved_config_sha256": sha256_file(resolved_path),
            "reproducibility_provenance_sha256": sha256_file(provenance_path),
            "environment_sha256": sha256_file(environment_path),
            "git_provenance_sha256": sha256_file(git_path),
            "source_hashes_sha256": sha256_file(source_hashes_path),
        },
    }
    summary_path = _write_json(output / "phase5_summary.json", summary)
    _, manifest_digest = write_phase5_artifact_manifest(output)
    if not verify_phase5_artifact_manifest(output):
        raise RuntimeError("Phase-5 artifact manifest verification failed")
    return Phase5ValidationResult(
        output_directory=output,
        summary_sha256=sha256_file(summary_path),
        solver_log_sha256=sha256_file(solver_parquet),
        runtime_smoke_log_sha256=runtime_smoke_sha256,
        artifact_manifest_sha256=manifest_digest,
    )


__all__ = [
    "COMMERCIAL_SOLVERS",
    "PHASE5_SCHEMA_VERSION",
    "Phase5Settings",
    "Phase5ValidationResult",
    "assert_runtime_truth_free",
    "controller_state_machine_source",
    "phase5_source_hashes",
    "render_controller_state_machine",
    "run_phase5_validation",
    "verify_phase5_artifact_manifest",
    "write_phase5_artifact_manifest",
]
