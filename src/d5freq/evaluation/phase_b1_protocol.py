"""Frozen Phase-B1 protocol loading, construction, and provenance helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

import yaml

from d5freq.evaluation.closed_loop_metrics import ClosedLoopMetricConfig
from d5freq.evaluation.closed_loop_scenarios import ExperimentProtocol, load_experiment_protocol
from d5freq.evaluation.phase6_experiments import Phase6Paths
from d5freq.models.grid_frequency import GridFrequencyModel, GridParams
from d5freq.utils.config import config_sha256, load_yaml
from d5freq.utils.hashing import sha256_file, sha256_json


Stage = Literal["smoke", "validation", "final"]
SG_LEVELS = ("A", "B", "C")
CORE_METHODS = ("B0", "B2", "B4", "B5", "P_old")
COUNTERFACTUAL_METHODS = (
    "C0_true_arx_expected",
    "C1_true_arx_worst",
    "C2_perfect_belief_current_mpc",
    "C3_current_belief_expected",
    "C4_gradual_authority",
    "C5_no_sticky_prior",
)
ALL_METHODS = CORE_METHODS + COUNTERFACTUAL_METHODS
PHASE_B1_PROTOCOL_LOCK_SCHEMA = "d5freq.phase_b1.protocol_lock.v1"


@dataclass(frozen=True, slots=True)
class SGCapability:
    level: str
    command_min_pu: float
    command_max_pu: float
    ramp_pu_per_s: float
    interpretation: str

    def __post_init__(self) -> None:
        if self.level not in SG_LEVELS:
            raise ValueError("SG capability level must be A, B, or C")
        if not self.command_min_pu < self.command_max_pu:
            raise ValueError("SG lower command bound must be below upper bound")
        if self.ramp_pu_per_s <= 0.0:
            raise ValueError("SG ramp must be positive")


@dataclass(frozen=True, slots=True)
class PhaseB1Paths:
    repo_root: Path
    base_config: Path
    mpc_config: Path
    experiments_config: Path
    audit_config: Path
    sg_levels_config: Path
    oracle_config: Path
    artifacts_root: Path
    results_root: Path
    figures_root: Path
    logs_root: Path
    progress_root: Path
    resolved_config_root: Path
    validation_selection: Path
    protocol_lock: Path
    phase6: Phase6Paths

    @classmethod
    def from_repo(cls, repo_root: str | Path) -> "PhaseB1Paths":
        root = Path(repo_root).expanduser().resolve()
        artifacts = root / "artifacts_phase_b1"
        resolved = artifacts / "resolved_protocol"
        return cls(
            repo_root=root,
            base_config=root / "configs/base.yaml",
            mpc_config=root / "configs/mpc.yaml",
            experiments_config=root / "configs/experiments.yaml",
            audit_config=root / "configs/phase_b1_audit.yaml",
            sg_levels_config=root / "configs/phase_b1_sg_levels.yaml",
            oracle_config=root / "configs/phase_b1_oracle.yaml",
            artifacts_root=artifacts,
            results_root=root / "results_phase_b1",
            figures_root=root / "figures_phase_b1",
            logs_root=root / "logs_phase_b1",
            progress_root=root / "progress_phase_b1",
            resolved_config_root=resolved,
            validation_selection=artifacts / "oracle_validation_selection.json",
            protocol_lock=artifacts / "protocol_lock_phase_b1.json",
            phase6=Phase6Paths.from_repo(root),
        )

    def resolved_base_config(self, level: str) -> Path:
        if level not in SG_LEVELS:
            raise ValueError("level must be A, B, or C")
        return self.resolved_config_root / f"base_sg_{level}.yaml"


def _exact_keys(value: object, expected: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    actual = set(value)
    if actual != expected:
        raise ValueError(
            f"{name} keys differ; missing={sorted(expected-actual)!r}, "
            f"extra={sorted(actual-expected)!r}"
        )
    return value


def load_sg_capabilities(path: str | Path) -> Mapping[str, SGCapability]:
    payload = load_yaml(path)
    if payload.get("schema_version") != "d5freq.phase_b1.sg_levels.v1":
        raise ValueError("unsupported Phase-B1 SG-level schema")
    if payload.get("protocol_status") != "preregistered" or payload.get("frozen_before_final") is not True:
        raise ValueError("SG levels are not frozen before final")
    rows = _exact_keys(payload.get("levels"), set(SG_LEVELS), "levels")
    result: dict[str, SGCapability] = {}
    expected_numeric = {
        "A": (-0.12, 0.12, 0.020),
        "B": (-0.08, 0.08, 0.012),
        "C": (-0.055, 0.055, 0.006),
    }
    for level in SG_LEVELS:
        row = _exact_keys(
            rows[level],
            {"command_min_pu", "command_max_pu", "ramp_pu_per_s", "interpretation"},
            f"levels.{level}",
        )
        capability = SGCapability(
            level=level,
            command_min_pu=float(row["command_min_pu"]),
            command_max_pu=float(row["command_max_pu"]),
            ramp_pu_per_s=float(row["ramp_pu_per_s"]),
            interpretation=str(row["interpretation"]),
        )
        if (
            capability.command_min_pu,
            capability.command_max_pu,
            capability.ramp_pu_per_s,
        ) != expected_numeric[level]:
            raise ValueError(f"SG Level {level} differs from the preregistered numeric values")
        result[level] = capability
    return MappingProxyType(result)


def load_phase_b1_seed_sets(path: str | Path) -> Mapping[str, tuple[int, ...]]:
    payload = load_yaml(path)
    if payload.get("schema_version") != "d5freq.phase_b1.audit_protocol.v1":
        raise ValueError("unsupported Phase-B1 audit protocol schema")
    rows = _exact_keys(
        payload.get("seed_sets"),
        {"smoke", "validation", "final_known", "final_ood_extreme"},
        "seed_sets",
    )
    result: dict[str, tuple[int, ...]] = {}
    for name, row_value in rows.items():
        row = _exact_keys(
            row_value,
            {"start", "stop_inclusive", "count"},
            f"seed_sets.{name}",
        )
        values = tuple(range(int(row["start"]), int(row["stop_inclusive"]) + 1))
        if len(values) != int(row["count"]):
            raise ValueError(f"seed_sets.{name}.count is inconsistent")
        result[name] = values
    expected = {
        "smoke": (300, 301),
        "validation": tuple(range(400, 410)),
        "final_known": tuple(range(3000, 3030)),
        "final_ood_extreme": tuple(range(3000, 3050)),
    }
    if result != expected:
        raise ValueError("Phase-B1 seed sets differ from the preregistration")
    if set(result["smoke"]) & set(result["validation"]):
        raise ValueError("smoke and validation seeds overlap")
    if (set(result["smoke"]) | set(result["validation"])) & set(result["final_ood_extreme"]):
        raise ValueError("development and final seeds overlap")
    return MappingProxyType(result)


def scenario_truth_classes(protocol: ExperimentProtocol) -> Mapping[str, str]:
    return MappingProxyType(
        {row.scenario_id: row.truth_class for row in protocol.scenario_variants}
    )


def seeds_for(
    stage: Stage,
    scenario_id: str,
    *,
    audit_config: str | Path,
    experiments_config: str | Path,
) -> tuple[int, ...]:
    seed_sets = load_phase_b1_seed_sets(audit_config)
    if stage == "smoke":
        return seed_sets["smoke"]
    if stage == "validation":
        return seed_sets["validation"]
    if stage != "final":
        raise ValueError("stage must be smoke, validation, or final")
    protocol = load_experiment_protocol(experiments_config)
    truth = scenario_truth_classes(protocol)
    if scenario_id not in truth:
        raise KeyError(f"unknown scenario {scenario_id!r}")
    return (
        seed_sets["final_known"]
        if truth[scenario_id] == "known"
        else seed_sets["final_ood_extreme"]
    )


def resolved_base_payload(paths: PhaseB1Paths, level: str) -> dict[str, Any]:
    capabilities = load_sg_capabilities(paths.sg_levels_config)
    capability = capabilities[level]
    payload = deepcopy(load_yaml(paths.base_config))
    grid = payload.get("grid")
    project = payload.get("project")
    if not isinstance(grid, dict) or not isinstance(project, dict):
        raise TypeError("base config lacks mutable grid/project mappings")
    grid.update(
        {
            "u_sg_min_pu": capability.command_min_pu,
            "u_sg_max_pu": capability.command_max_pu,
            "u_sg_ramp_pu_per_s": capability.ramp_pu_per_s,
        }
    )
    project.update(
        {
            "output_root": "results_phase_b1",
            "artifact_root": "artifacts_phase_b1",
            "progress_root": "progress_phase_b1",
        }
    )
    payload["phase_b1_sg_level"] = level
    payload["phase_b1_source_base_sha256"] = sha256_file(paths.base_config)
    return payload


def ensure_resolved_base_configs(paths: PhaseB1Paths) -> Mapping[str, Path]:
    paths.resolved_config_root.mkdir(parents=True, exist_ok=True)
    result: dict[str, Path] = {}
    for level in SG_LEVELS:
        destination = paths.resolved_base_config(level)
        payload = resolved_base_payload(paths, level)
        serialized = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
        if destination.exists() and destination.read_text(encoding="utf-8") != serialized:
            raise RuntimeError(f"resolved base config changed for SG Level {level}")
        if not destination.exists():
            temporary = destination.with_suffix(".yaml.tmp")
            temporary.write_text(serialized, encoding="utf-8", newline="\n")
            temporary.replace(destination)
        result[level] = destination
    return MappingProxyType(result)


def build_grid_model(base_config: str | Path) -> GridFrequencyModel:
    payload = load_yaml(base_config)
    values = payload.get("grid")
    if not isinstance(values, Mapping):
        raise TypeError("base config lacks grid mapping")
    return GridFrequencyModel(
        GridParams(
            f0_hz=values["f0_hz"],
            M_s=values["M_s"],
            D_pu=values["D_pu"],
            T_t_s=values["T_t_s"],
            T_g_s=values["T_g_s"],
            R_pu=values["R_pu"],
            control_period_s=values["control_period_s"],
            integration_step_s=values["integration_step_s"],
        )
    )


def build_phase_b1_metric_config(base_config: str | Path) -> ClosedLoopMetricConfig:
    payload = load_yaml(base_config)
    grid = payload.get("grid")
    ibr = payload.get("ibr_command")
    if not isinstance(grid, Mapping) or not isinstance(ibr, Mapping):
        raise TypeError("base config requires grid and ibr_command mappings")
    return ClosedLoopMetricConfig(
        nominal_frequency_hz=float(grid["f0_hz"]),
        frequency_limit_hz=float(grid["freq_limit_hz"]),
        rocof_limit_hz_per_s=float(grid["rocof_limit_hz_per_s"]),
        safety_frequency_limit_hz=float(grid["freq_limit_hz"]),
        settling_band_hz=0.05,
        sg_command_min_pu=float(grid["u_sg_min_pu"]),
        sg_command_max_pu=float(grid["u_sg_max_pu"]),
        sg_slew_limit_pu_per_s=float(grid["u_sg_ramp_pu_per_s"]),
        ibr_command_min_pu=float(ibr["u_min_pu"]),
        ibr_command_max_pu=float(ibr["u_max_pu"]),
        ibr_slew_limit_pu_per_s=float(ibr["ramp_pu_per_s"]),
        command_sample_period_s=float(grid["control_period_s"]),
    )


def stable_phase_b1_run_id(
    *,
    stage: Stage,
    scenario_id: str,
    method_id: str,
    seed: int,
    sg_level: str,
) -> str:
    if stage not in {"smoke", "validation", "final"}:
        raise ValueError("invalid Phase-B1 stage")
    if method_id not in ALL_METHODS and not method_id.startswith("B5_"):
        raise ValueError("unknown Phase-B1 method")
    if sg_level not in SG_LEVELS:
        raise ValueError("invalid SG level")
    if any("::" in value or not value for value in (scenario_id, method_id)):
        raise ValueError("run identity fields are invalid")
    return (
        f"phase-b1::{stage}::sg-{sg_level}::{scenario_id}::"
        f"{method_id}::seed-{int(seed):06d}"
    )


def _canonical_hash_manifest(paths: PhaseB1Paths) -> dict[str, str]:
    source_files = sorted(
        path
        for root in (
            paths.repo_root / "src/d5freq/evaluation",
            paths.repo_root / "scripts",
            paths.repo_root / "tests_phase_b1",
        )
        for path in root.rglob("*.py")
        if path.is_file() and ("phase_b1" in path.name or "exact_nonlinear_oracle" in path.name)
    )
    return {
        path.relative_to(paths.repo_root).as_posix(): sha256_file(path)
        for path in source_files
    }


def build_protocol_lock_payload(
    paths: PhaseB1Paths,
    *,
    validation_selection: Mapping[str, Any],
) -> dict[str, Any]:
    ensure_resolved_base_configs(paths)
    selected_id = validation_selection.get("selected_candidate_id")
    if selected_id not in {"H2", "H4", "H6"}:
        raise ValueError("validation selection has no recognized Oracle candidate")
    configs = {
        path.relative_to(paths.repo_root).as_posix(): {
            "file_sha256": sha256_file(path),
            "logical_sha256": config_sha256(load_yaml(path)),
        }
        for path in (
            paths.audit_config,
            paths.sg_levels_config,
            paths.oracle_config,
            paths.experiments_config,
            paths.base_config,
            paths.mpc_config,
            *(paths.resolved_base_config(level) for level in SG_LEVELS),
        )
    }
    selection_normalized = json.loads(
        json.dumps(validation_selection, sort_keys=True, allow_nan=False)
    )
    return {
        "schema_version": PHASE_B1_PROTOCOL_LOCK_SCHEMA,
        "final_feedback_forbidden": True,
        "final_seed_sets": {
            "known": list(range(3000, 3030)),
            "ood_extreme": list(range(3000, 3050)),
        },
        "selected_oracle_candidate": selected_id,
        "validation_selection": selection_normalized,
        "validation_selection_sha256": sha256_json(selection_normalized),
        "configs": configs,
        "code_files": _canonical_hash_manifest(paths),
        "legacy_baseline_manifest_sha256": sha256_file(
            paths.artifacts_root / "baseline_manifest.json"
        ),
    }


def ensure_protocol_lock(paths: PhaseB1Paths) -> Path:
    if not paths.validation_selection.is_file():
        raise RuntimeError("Oracle validation selection is required before final lock")
    selection = json.loads(paths.validation_selection.read_text(encoding="utf-8"))
    if not isinstance(selection, Mapping):
        raise TypeError("Oracle validation selection must be a JSON object")
    expected = build_protocol_lock_payload(paths, validation_selection=selection)
    paths.protocol_lock.parent.mkdir(parents=True, exist_ok=True)
    if paths.protocol_lock.exists():
        actual = json.loads(paths.protocol_lock.read_text(encoding="utf-8"))
        if actual != expected:
            raise RuntimeError("Phase-B1 protocol changed after its final lock")
        return paths.protocol_lock
    temporary = paths.protocol_lock.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(expected, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(paths.protocol_lock)
    return paths.protocol_lock


def protocol_lock_sha256(paths: PhaseB1Paths) -> str:
    if not paths.protocol_lock.is_file():
        raise FileNotFoundError(paths.protocol_lock)
    return hashlib.sha256(paths.protocol_lock.read_bytes()).hexdigest()


__all__ = [
    "ALL_METHODS",
    "CORE_METHODS",
    "COUNTERFACTUAL_METHODS",
    "PHASE_B1_PROTOCOL_LOCK_SCHEMA",
    "PhaseB1Paths",
    "SGCapability",
    "SG_LEVELS",
    "build_grid_model",
    "build_phase_b1_metric_config",
    "build_protocol_lock_payload",
    "ensure_protocol_lock",
    "ensure_resolved_base_configs",
    "load_phase_b1_seed_sets",
    "load_sg_capabilities",
    "protocol_lock_sha256",
    "resolved_base_payload",
    "seeds_for",
    "stable_phase_b1_run_id",
]
