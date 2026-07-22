"""Regenerate the twelve required Phase-7 figures from persisted evidence.

Missing metrics never become synthetic curves or points.  When a requested
panel cannot be reconstructed, the script writes an unmistakable audit panel
and records ``not_available`` (or ``partial``) plus the missing fields in
``figure_manifest.csv``.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Callable, Iterable, Mapping, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

try:  # Direct script execution.
    from phase7_support import (
        FIGURE_SPECS,
        Phase7AuditError,
        RESULT_CSV_NAMES,
        atomic_write_csv,
        relative_posix,
        require_file,
        require_nonempty_directory,
        resolved,
        sha256_file,
        validate_result_identity,
        validate_selected_trajectory_manifest,
    )
except ImportError:  # Imported as scripts.06_make_figures in a test/tool.
    from scripts.phase7_support import (  # type: ignore[no-redef]
        FIGURE_SPECS,
        Phase7AuditError,
        RESULT_CSV_NAMES,
        atomic_write_csv,
        relative_posix,
        require_file,
        require_nonempty_directory,
        resolved,
        sha256_file,
        validate_result_identity,
        validate_selected_trajectory_manifest,
    )


_METHOD_ORDER: tuple[str, ...] = (
    "B0",
    "B1",
    "B2",
    "B3",
    "B4",
    "P",
    "no-worst",
    "no-OOD",
    "no-tightening",
    "fixed-K4-unlabeled",
    "labeled-library",
    "no-transition-prior",
)
_ABLATION_METHODS = frozenset(
    {
        "P",
        "no-worst",
        "no-OOD",
        "no-tightening",
        "fixed-K4-unlabeled",
        "labeled-library",
        "no-transition-prior",
    }
)
_KNOWN_REPRESENTATIVE_SCENARIO = "S2_sluggish_switch_060"
_OOD_REPRESENTATIVE_SCENARIO = "S7_ood_asymmetric_limit"


@dataclass(frozen=True, slots=True)
class TraceTable:
    path: Path
    frame: pd.DataFrame
    trace_kind: str
    run_id: str
    selection_role: str
    method: str | None = None
    scenario_id: str | None = None
    seed: int | None = None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the twelve required, data-traceable Phase-7 figures."
    )
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--results",
        "--results-dir",
        dest="results_dir",
        type=Path,
        default=Path("results/final"),
    )
    parser.add_argument(
        "--output",
        "--figures-dir",
        dest="figures_dir",
        type=Path,
        default=Path("results/phase7/figures"),
    )
    parser.add_argument("--representative-dir", type=Path, default=None)
    parser.add_argument("--worst-dir", type=Path, default=None)
    parser.add_argument(
        "--replace",
        action="store_true",
        help="replace an existing figure directory after a complete staged build",
    )
    return parser


def _repo_relative(path: Path, root: Path) -> Path:
    return path if path.is_absolute() else root / path


def _numeric(frame: pd.DataFrame, column: str) -> np.ndarray:
    return pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=float)


def _first_column(frame: pd.DataFrame, names: Iterable[str]) -> str | None:
    return next((name for name in names if name in frame.columns), None)


def _frequency_hz(frame: pd.DataFrame, f0_hz: float | None) -> tuple[np.ndarray | None, str | None]:
    direct = _first_column(
        frame,
        (
            "frequency_deviation_hz",
            "delta_frequency_hz",
            "freq_deviation_hz",
            "delta_f_hz",
        ),
    )
    if direct is not None:
        return _numeric(frame, direct), direct
    omega = _first_column(frame, ("omega_true_pu", "omega_pu", "omega_measurement_pu"))
    if omega is not None and f0_hz is not None:
        return f0_hz * _numeric(frame, omega), f"{omega} * f0_hz"
    absolute = _first_column(frame, ("frequency_hz", "freq_hz"))
    if absolute is not None and f0_hz is not None:
        return _numeric(frame, absolute) - f0_hz, f"{absolute} - f0_hz"
    return None, None


def _extract_json_table(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    metadata: dict[str, Any] = {}
    if isinstance(payload, list):
        return pd.DataFrame.from_records(payload), metadata
    if not isinstance(payload, dict):
        return pd.DataFrame(), metadata
    for name in ("method", "scenario_id", "seed", "run_id"):
        if name in payload:
            metadata[name] = payload[name]
    body = payload.get("body") if isinstance(payload.get("body"), dict) else payload
    if isinstance(body, dict):
        identity = body.get("identity")
        if isinstance(identity, dict):
            metadata.update({key: identity.get(key) for key in ("method", "scenario_id", "seed")})
        run_payload = body.get("run_payload")
        if isinstance(run_payload, dict):
            body = run_payload
    if isinstance(body, dict):
        for key in (
            "control_trajectory",
            "trajectory",
            "records",
            "truth_trace_points_eval_only",
        ):
            records = body.get(key)
            if isinstance(records, list):
                return pd.DataFrame.from_records(records), metadata
    return pd.DataFrame(), metadata


def _read_trace(
    path: Path,
    *,
    trace_kind: str,
    entry: Mapping[str, Any],
    require_trace_identity: bool,
) -> TraceTable | None:
    metadata: dict[str, Any] = {
        key: entry.get(key)
        for key in (
            "run_id",
            "selection_role",
            "method",
            "scenario_id",
            "seed",
        )
    }
    try:
        if path.suffix.lower() == ".parquet":
            frame = pd.read_parquet(path)
        elif path.suffix.lower() == ".csv":
            frame = pd.read_csv(path)
        elif path.suffix.lower() == ".json":
            frame, extracted = _extract_json_table(path)
            metadata.update(extracted)
        else:
            return None
    except Exception:
        return None
    if frame.empty:
        return None
    for field in ("run_id", "scenario_id", "method", "seed", "selection_role"):
        if field not in frame.columns or not frame[field].notna().any():
            if require_trace_identity:
                raise Phase7AuditError(
                    f"strict selected trace lacks {field}: {path}"
                )
            continue
        expected = entry.get(field)
        observed = {
            int(value) if field == "seed" else str(value)
            for value in frame.loc[frame[field].notna(), field].tolist()
        }
        normalized_expected = int(expected) if field == "seed" else str(expected)
        if observed != {normalized_expected}:
            raise Phase7AuditError(
                f"selected trace {field} disagrees with its manifest entry: {path}"
            )
    method = metadata.get("method")
    scenario = metadata.get("scenario_id")
    seed = metadata.get("seed")
    try:
        normalized_seed = None if seed is None else int(seed)
    except (TypeError, ValueError):
        normalized_seed = None
    return TraceTable(
        path=path,
        frame=frame,
        trace_kind=trace_kind,
        run_id=str(metadata.get("run_id")),
        selection_role=str(metadata.get("selection_role")),
        method=None if method is None else str(method),
        scenario_id=None if scenario is None else str(scenario),
        seed=normalized_seed,
    )


def _load_traces(
    directory: Path, *, require_trace_identity: bool
) -> list[TraceTable]:
    manifest_path = directory / "trajectory_manifest.json"
    if not manifest_path.is_file():
        raise Phase7AuditError(f"selected trajectory manifest is missing: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise Phase7AuditError(f"selected trajectory manifest is invalid: {manifest_path}") from exc
    entries = manifest.get("entries") if isinstance(manifest, Mapping) else None
    if not isinstance(entries, list) or not entries:
        raise Phase7AuditError("selected trajectory manifest has no entries")
    traces: list[TraceTable] = []
    for entry in entries:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("files"), Mapping):
            raise Phase7AuditError("selected trajectory manifest entry is malformed")
        for trace_kind, record in sorted(entry["files"].items()):
            if not isinstance(record, Mapping):
                raise Phase7AuditError("selected trajectory file record is malformed")
            relative = record.get("relative_path")
            if not isinstance(relative, str) or not relative:
                raise Phase7AuditError("selected trajectory file path is malformed")
            path = (directory / relative).resolve()
            try:
                path.relative_to(directory.resolve())
            except ValueError as exc:
                raise Phase7AuditError(
                    f"selected trajectory file escapes its directory: {relative}"
                ) from exc
            trace = _read_trace(
                path,
                trace_kind=str(trace_kind),
                entry=entry,
                require_trace_identity=require_trace_identity,
            )
            if trace is not None:
                traces.append(trace)
    return traces


def _load_f0(repo_root: Path) -> tuple[float | None, Path | None]:
    config = repo_root / "configs" / "base.yaml"
    if not config.is_file():
        return None, None
    try:
        import yaml

        payload = yaml.safe_load(config.read_text(encoding="utf-8"))
        stack: list[Any] = [payload]
        while stack:
            current = stack.pop()
            if isinstance(current, Mapping):
                for key, value in current.items():
                    if str(key) == "f0_hz":
                        return float(value), config
                    stack.append(value)
            elif isinstance(current, Sequence) and not isinstance(current, (str, bytes)):
                stack.extend(current)
    except Exception:
        pass
    return None, config


def _style() -> None:
    plt.rcParams.update(
        {
            "font.size": 9,
            "axes.titlesize": 11,
            "axes.labelsize": 9,
            "legend.fontsize": 8,
            "figure.figsize": (8.0, 4.8),
            "figure.dpi": 120,
            "savefig.dpi": 160,
            "axes.grid": True,
            "grid.alpha": 0.25,
            "lines.linewidth": 1.35,
        }
    )


def _placeholder(title: str, missing: Sequence[str]) -> plt.Figure:
    figure, axis = plt.subplots(figsize=(8.0, 4.8))
    axis.set_axis_off()
    axis.text(
        0.5,
        0.65,
        title,
        ha="center",
        va="center",
        fontsize=14,
        weight="bold",
        transform=axis.transAxes,
    )
    axis.text(
        0.5,
        0.48,
        "NOT AVAILABLE — metric/data missing",
        ha="center",
        va="center",
        fontsize=12,
        color="#a32020",
        weight="bold",
        transform=axis.transAxes,
    )
    axis.text(
        0.5,
        0.30,
        "\n".join(str(item) for item in missing),
        ha="center",
        va="center",
        fontsize=9,
        color="#444444",
        transform=axis.transAxes,
    )
    return figure


def _write_figure(figure: plt.Figure, path: Path) -> None:
    figure.tight_layout()
    figure.savefig(
        path,
        format="png",
        bbox_inches="tight",
        metadata={"Software": "d5freq deterministic Phase-7 figure builder"},
    )
    plt.close(figure)


def _source_fields(paths: Iterable[Path], repo_root: Path) -> tuple[str, str]:
    unique = sorted({path.resolve() for path in paths if path.is_file()}, key=lambda p: p.as_posix())
    return (
        ";".join(relative_posix(path, repo_root) for path in unique),
        ";".join(
            f"{relative_posix(path, repo_root)}={sha256_file(path)}" for path in unique
        ),
    )


def _manifest_row(
    *,
    figure_id: int,
    filename: str,
    title: str,
    status: str,
    sources: Iterable[Path],
    missing: Sequence[str],
    notes: str,
    output_dir: Path,
    repo_root: Path,
) -> dict[str, Any]:
    source_paths, source_hashes = _source_fields(sources, repo_root)
    figure_path = output_dir / filename
    return {
        "figure_id": figure_id,
        "filename": filename,
        "title": title,
        "status": status,
        "data_sources": source_paths,
        "data_source_sha256": source_hashes,
        "missing_fields": ";".join(missing),
        "notes": notes,
        "figure_sha256": sha256_file(figure_path),
    }


def _overview_figure() -> plt.Figure:
    figure, axis = plt.subplots(figsize=(10.5, 4.6))
    axis.set_axis_off()
    nodes = (
        (0.08, 0.58, "Frequency system +\nhidden-mode IBR"),
        (0.28, 0.58, "Measurements\n(no mode truth)"),
        (0.48, 0.72, "ARX belief +\nconformal OOD"),
        (0.68, 0.58, "SD-BMPC\nshared commands"),
        (0.87, 0.58, "SG / IBR\nactuation"),
        (0.48, 0.24, "LQI fallback\n(OOD/solver failure)"),
    )
    for x, y, label in nodes:
        axis.text(
            x,
            y,
            label,
            ha="center",
            va="center",
            transform=axis.transAxes,
            bbox={"boxstyle": "round,pad=0.45", "facecolor": "#e8f0f8", "edgecolor": "#355d7a"},
        )
    arrows = (
        ((0.16, 0.58), (0.22, 0.58)),
        ((0.36, 0.60), (0.41, 0.69)),
        ((0.55, 0.69), (0.61, 0.60)),
        ((0.75, 0.58), (0.80, 0.58)),
        ((0.87, 0.50), (0.14, 0.50)),
        ((0.48, 0.64), (0.48, 0.33)),
        ((0.55, 0.25), (0.64, 0.49)),
    )
    for start, end in arrows:
        axis.annotate(
            "",
            xy=end,
            xytext=start,
            xycoords="axes fraction",
            arrowprops={"arrowstyle": "->", "color": "#333333", "lw": 1.2},
        )
    axis.set_title("Audited runtime information flow (Oracle truth path excluded)", pad=15)
    return figure


def _overview_figure_with_sources(
    repo_root: Path,
) -> tuple[plt.Figure, str, list[Path], list[str], str]:
    source_root = repo_root / "src"
    if not source_root.is_dir() and (repo_root / "source" / "src").is_dir():
        # The review ZIP intentionally nests the installable repository under
        # source/, while results/configs remain at the package root.
        source_root = repo_root / "source" / "src"
    sources = [
        source_root / "d5freq" / "controllers" / "sd_bmpc.py",
        source_root / "d5freq" / "estimation" / "online_diagnostic.py",
        source_root / "d5freq" / "simulation" / "hybrid_simulator.py",
    ]
    missing = [str(path) for path in sources if not path.is_file()]
    if missing:
        return (
            _placeholder(FIGURE_SPECS[0][1], missing),
            "not_available",
            [path for path in sources if path.is_file()],
            missing,
            "The implementation files required to audit the architecture are absent.",
        )
    return (
        _overview_figure(),
        "available",
        sources,
        [],
        "Architecture schematic derived from the packaged implementation; Oracle truth flow is explicitly outside this runtime path.",
    )


def _truth_response_figure(repo_root: Path) -> tuple[plt.Figure, str, list[Path], list[str], str]:
    source = repo_root / "artifacts" / "phase1" / "known_mode_step_responses.csv"
    if not source.is_file():
        return _placeholder(FIGURE_SPECS[1][1], ["artifacts/phase1/known_mode_step_responses.csv"]), "not_available", [], [str(source)], "No truth response table was found."
    frame = pd.read_csv(source)
    required = {"mode", "time_s", "p_ibr_pu"}
    if not required.issubset(frame.columns):
        missing = sorted(required - set(frame.columns))
        return _placeholder(FIGURE_SPECS[1][1], missing), "not_available", [source], missing, "Required columns are absent."
    figure, axis = plt.subplots()
    for mode, group in frame.groupby("mode", sort=True):
        ordered = group.sort_values("time_s")
        axis.plot(ordered["time_s"], ordered["p_ibr_pu"], label=str(mode))
    axis.set(xlabel="Time (s)", ylabel="Actual IBR power (pu)", title=FIGURE_SPECS[1][1])
    axis.legend(ncol=2)
    return figure, "available", [source], [], "Directly plotted from retained Phase-1 truth responses."


def _bic_cluster_figure(repo_root: Path) -> tuple[plt.Figure, str, list[Path], list[str], str]:
    bic_path = repo_root / "artifacts" / "mode_discovery" / "bic_table.csv"
    features_path = repo_root / "artifacts" / "mode_discovery" / "episode_features.parquet"
    missing_paths = [str(path) for path in (bic_path, features_path) if not path.is_file()]
    if not bic_path.is_file():
        return _placeholder(FIGURE_SPECS[2][1], missing_paths), "not_available", [], missing_paths, "BIC evidence is required for this figure."
    bic = pd.read_csv(bic_path)
    if not {"component_count", "bic"}.issubset(bic.columns):
        missing = sorted({"component_count", "bic"} - set(bic.columns))
        return _placeholder(FIGURE_SPECS[2][1], missing), "not_available", [bic_path], missing, "BIC columns are absent."
    figure, axes = plt.subplots(1, 2, figsize=(10.5, 4.5))
    ordered = bic.sort_values("component_count")
    axes[0].plot(ordered["component_count"], ordered["bic"], marker="o")
    if "selected" in ordered.columns:
        selected = ordered[ordered["selected"].astype(str).str.lower().isin({"true", "1"})]
        if not selected.empty:
            axes[0].scatter(selected["component_count"], selected["bic"], marker="*", s=140, color="#b22222", label="selected")
            axes[0].legend()
    axes[0].set(xlabel="GMM components K", ylabel="BIC", title="Label-free model selection")
    sources = [bic_path]
    status = "available"
    missing: list[str] = []
    if features_path.is_file():
        features = pd.read_parquet(features_path)
        feature_columns = [column for column in features.columns if column.startswith("standardized_feature_")]
        if len(feature_columns) >= 2 and "component_id" in features.columns:
            matrix = features[feature_columns].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
            mask = np.isfinite(matrix).all(axis=1)
            centered = matrix[mask] - np.mean(matrix[mask], axis=0, keepdims=True)
            _, _, vt = np.linalg.svd(centered, full_matrices=False)
            embedding = centered @ vt[:2].T
            labels = features.loc[mask, "component_id"].to_numpy()
            for label in sorted(set(labels.tolist()), key=str):
                chosen = labels == label
                axes[1].scatter(embedding[chosen, 0], embedding[chosen, 1], s=24, label=f"component {label}", alpha=0.8)
            axes[1].set(xlabel="PCA diagnostic axis 1", ylabel="PCA diagnostic axis 2", title="Frozen standardized ARX features")
            axes[1].legend(fontsize=6, ncol=2)
            sources.append(features_path)
        else:
            axes[1].text(0.5, 0.5, "NOT AVAILABLE\nfeature/component columns missing", ha="center", va="center", transform=axes[1].transAxes, color="#a32020")
            axes[1].set_axis_off()
            status = "partial"
            missing.append("standardized_feature_* and component_id")
    else:
        axes[1].text(0.5, 0.5, "NOT AVAILABLE\nepisode_features.parquet missing", ha="center", va="center", transform=axes[1].transAxes, color="#a32020")
        axes[1].set_axis_off()
        status = "partial"
        missing.append(str(features_path))
    return figure, status, sources, missing, "PCA is used only for this evaluation-side visualization."


def _time_and_frequency(trace: TraceTable, f0_hz: float | None) -> tuple[np.ndarray | None, np.ndarray | None, list[str]]:
    time_column = _first_column(trace.frame, ("time_s", "t_s", "time"))
    frequency, frequency_source = _frequency_hz(trace.frame, f0_hz)
    missing: list[str] = []
    if time_column is None:
        missing.append("time_s")
    if frequency is None:
        missing.append("frequency deviation or omega column")
    if time_column is None or frequency is None:
        return None, None, missing
    time = _numeric(trace.frame, time_column)
    valid = np.isfinite(time) & np.isfinite(frequency)
    if not np.any(valid):
        return None, None, ["finite time/frequency samples"]
    _ = frequency_source
    return time[valid], frequency[valid], []


def _parse_belief(value: object) -> list[float] | None:
    if isinstance(value, np.ndarray):
        raw: object = value.tolist()
    elif isinstance(value, (list, tuple)):
        raw = value
    elif isinstance(value, str):
        try:
            raw = json.loads(value)
        except json.JSONDecodeError:
            try:
                raw = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                return None
    else:
        return None
    if not isinstance(raw, (list, tuple)):
        return None
    try:
        values = [float(item) for item in raw]
    except (TypeError, ValueError):
        return None
    return values if values and all(np.isfinite(values)) else None


def _matching_trace(
    traces: Sequence[TraceTable],
    *,
    scenario_id: str,
    method: str,
    trace_kind: str,
) -> TraceTable | None:
    matches = [
        trace
        for trace in traces
        if trace.scenario_id == scenario_id
        and trace.method == method
        and trace.trace_kind == trace_kind
    ]
    if len(matches) > 1:
        raise Phase7AuditError(
            "selected trajectory bundle has duplicate tables for "
            f"scenario={scenario_id}, method={method}, kind={trace_kind}"
        )
    return None if not matches else matches[0]


def _same_run_trace(
    traces: Sequence[TraceTable], source: TraceTable, trace_kind: str
) -> TraceTable | None:
    matches = [
        trace
        for trace in traces
        if trace.run_id == source.run_id and trace.trace_kind == trace_kind
    ]
    if len(matches) > 1:
        raise Phase7AuditError(
            f"selected run {source.run_id} has duplicate {trace_kind} tables"
        )
    return None if not matches else matches[0]


def _switch_belief_figure(traces: list[TraceTable], f0_hz: float | None) -> tuple[plt.Figure, str, list[Path], list[str], str]:
    candidate = _matching_trace(
        traces,
        scenario_id=_KNOWN_REPRESENTATIVE_SCENARIO,
        method="P",
        trace_kind="control_trajectory",
    )
    if candidate is None:
        return _placeholder(FIGURE_SPECS[3][1], ["known-scenario P control trajectory"]), "not_available", [], ["known P trajectory"], "The frozen known-scenario P trajectory was not supplied."
    if "mode_belief" not in candidate.frame.columns:
        return _placeholder(FIGURE_SPECS[3][1], ["mode_belief"]), "not_available", [candidate.path], ["mode_belief"], "The frozen P control trajectory has no belief field."
    time_column = _first_column(candidate.frame, ("time_s", "t_s", "time"))
    beliefs = [_parse_belief(value) for value in candidate.frame["mode_belief"].tolist()]
    valid_indices = [index for index, value in enumerate(beliefs) if value is not None]
    if time_column is None or not valid_indices:
        missing = [name for name, condition in (("time_s", time_column is None), ("parseable mode_belief", not valid_indices)) if condition]
        return _placeholder(FIGURE_SPECS[3][1], missing), "not_available", [candidate.path], missing, "The selected trace could not reconstruct belief time series."
    width = max(len(beliefs[index] or []) for index in valid_indices)
    matrix = np.full((len(candidate.frame), width), np.nan)
    for index, belief in enumerate(beliefs):
        if belief is not None:
            matrix[index, : len(belief)] = belief
    time = _numeric(candidate.frame, time_column)
    figure, axis = plt.subplots()
    for component in range(width):
        axis.plot(time, matrix[:, component], label=f"component {component}")
    truth_trace = _same_run_trace(traces, candidate, "high_frequency_truth")
    if truth_trace is None:
        return _placeholder(FIGURE_SPECS[3][1], ["matching high_frequency_truth"]), "not_available", [candidate.path], ["true_mode_eval_only"], "The matching evaluator-owned truth table is absent."
    truth_time_column = _first_column(truth_trace.frame, ("time_s", "t_s", "time"))
    truth_column = _first_column(
        truth_trace.frame, ("true_mode_eval_only", "mode_eval_only", "true_mode")
    )
    if truth_time_column is None or truth_column is None:
        missing = [
            name
            for name, absent in (
                ("truth time_s", truth_time_column is None),
                ("true_mode_eval_only", truth_column is None),
            )
            if absent
        ]
        return _placeholder(FIGURE_SPECS[3][1], missing), "not_available", [candidate.path, truth_trace.path], missing, "The matching evaluator-owned truth table is incomplete."
    truth_times = _numeric(truth_trace.frame, truth_time_column)
    truth_values = truth_trace.frame[truth_column].astype(str).to_numpy()
    finite_truth = np.isfinite(truth_times)
    truth_times = truth_times[finite_truth]
    truth_values = truth_values[finite_truth]
    if truth_times.size == 0:
        return _placeholder(FIGURE_SPECS[3][1], ["finite truth samples"]), "not_available", [candidate.path, truth_trace.path], ["finite truth samples"], "The evaluator-owned truth table is empty."
    order = np.argsort(truth_times, kind="stable")
    truth_times = truth_times[order]
    truth_values = truth_values[order]
    indices = np.searchsorted(truth_times, time, side="right") - 1
    indices = np.clip(indices, 0, len(truth_times) - 1)
    sampled_truth = truth_values[indices]
    categories = {
        value: index for index, value in enumerate(sorted(set(sampled_truth.tolist())))
    }
    truth_numeric = np.asarray([categories[value] for value in sampled_truth], dtype=float)
    if len(categories) > 1:
        truth_numeric /= max(categories.values())
    axis.step(
        time,
        truth_numeric,
        where="post",
        color="black",
        linestyle="--",
        label=f"truth (eval only): {', '.join(categories)}",
    )
    axis.set(xlabel="Time (s)", ylabel="Probability / normalized truth", ylim=(-0.03, 1.03), title=FIGURE_SPECS[3][1])
    axis.legend(fontsize=6, ncol=2)
    return figure, "available", [candidate.path, truth_trace.path], [], "Native-component beliefs and evaluator-owned truth are joined only for this post-run figure."


def _frequency_comparison_figure(traces: list[TraceTable], f0_hz: float | None) -> tuple[plt.Figure, str, list[Path], list[str], str]:
    usable: list[tuple[TraceTable, np.ndarray, np.ndarray]] = []
    expected_methods = ("B0", "B1", "B2", "B3", "B4", "P")
    for method in expected_methods:
        trace = _matching_trace(
            traces,
            scenario_id=_KNOWN_REPRESENTATIVE_SCENARIO,
            method=method,
            trace_kind="control_trajectory",
        )
        if trace is None:
            continue
        time, frequency, _ = _time_and_frequency(trace, f0_hz)
        if time is not None and frequency is not None:
            usable.append((trace, time, frequency))
    if not usable:
        return _placeholder(FIGURE_SPECS[4][1], ["representative time/frequency traces"]), "not_available", [], ["time_s", "frequency/omega"], "No selected representative trajectory had frequency samples."
    figure, axis = plt.subplots()
    sources: list[Path] = []
    for index, (trace, time, frequency) in enumerate(usable):
        label = trace.method or trace.path.stem
        axis.plot(time, frequency, label=label)
        sources.append(trace.path)
    axis.axhline(0.5, color="#a32020", linestyle=":", linewidth=1)
    axis.axhline(-0.5, color="#a32020", linestyle=":", linewidth=1, label="declared ±0.5 Hz")
    axis.set(xlabel="Time (s)", ylabel="Frequency deviation (Hz)", title=FIGURE_SPECS[4][1])
    axis.legend(fontsize=6, ncol=3)
    observed = {str(trace.method) for trace, _, _ in usable}
    missing = [method for method in expected_methods if method not in observed]
    status = "available" if not missing else "partial"
    return figure, status, sources, missing, f"Plotted {len(usable)} control-rate trajectories from one frozen scenario and seed."


def _command_figure(traces: list[TraceTable]) -> tuple[plt.Figure, str, list[Path], list[str], str]:
    required = ("u_sg_pu", "u_ibr_pu", "p_ibr_true_pu")
    candidate = _matching_trace(
        traces,
        scenario_id=_KNOWN_REPRESENTATIVE_SCENARIO,
        method="P",
        trace_kind="control_trajectory",
    )
    if candidate is not None and not all(
        name in candidate.frame.columns for name in required
    ):
        candidate = None
    if candidate is None:
        return _placeholder(FIGURE_SPECS[5][1], [*required, "time_s"]), "not_available", [], [*required, "time_s"], "No selected trajectory contained all command/output columns."
    time_column = _first_column(candidate.frame, ("time_s", "t_s", "time"))
    if time_column is None:
        return _placeholder(FIGURE_SPECS[5][1], ["time_s"]), "not_available", [candidate.path], ["time_s"], "Selected trajectory has no time column."
    time = _numeric(candidate.frame, time_column)
    figure, axis = plt.subplots()
    axis.plot(time, _numeric(candidate.frame, "u_sg_pu"), label="SG command")
    axis.plot(time, _numeric(candidate.frame, "u_ibr_pu"), label="IBR command")
    axis.plot(time, _numeric(candidate.frame, "p_ibr_true_pu"), label="actual IBR output")
    axis.set(xlabel="Time (s)", ylabel="Power (pu)", title=FIGURE_SPECS[5][1])
    axis.legend()
    return figure, "available", [candidate.path], [], "Commands and evaluator-side actual output are read directly from the selected trace."


def _scatter_figure(episodes: pd.DataFrame, source: Path) -> tuple[plt.Figure, str, list[Path], list[str], str]:
    required = {"detection_delay_s", "freq_iae", "method"}
    missing = sorted(required - set(episodes.columns))
    if missing:
        return _placeholder(FIGURE_SPECS[6][1], missing), "not_available", [source], missing, "Required per-episode metrics are absent."
    frame = episodes.copy()
    frame["detection_delay_s"] = pd.to_numeric(frame["detection_delay_s"], errors="coerce")
    frame["freq_iae"] = pd.to_numeric(frame["freq_iae"], errors="coerce")
    frame = frame.dropna(subset=["detection_delay_s", "freq_iae"])
    if frame.empty:
        return _placeholder(FIGURE_SPECS[6][1], ["observed detection_delay_s/freq_iae pairs"]), "not_available", [source], ["observed pairs"], "Censored/missing values were not imputed."
    figure, axis = plt.subplots()
    for method, group in frame.groupby("method", sort=True):
        axis.scatter(group["detection_delay_s"], group["freq_iae"], s=16, alpha=0.55, label=str(method))
    axis.set(xlabel="Detection delay (s)", ylabel="Frequency IAE (Hz·s)", title=FIGURE_SPECS[6][1])
    axis.legend(fontsize=6, ncol=3)
    return figure, "available", [source], [], f"Uses {len(frame)} observed pairs; missing/censored pairs are omitted, not imputed."


def _ood_figure(traces: list[TraceTable], f0_hz: float | None) -> tuple[plt.Figure, str, list[Path], list[str], str]:
    candidate = _matching_trace(
        traces,
        scenario_id=_OOD_REPRESENTATIVE_SCENARIO,
        method="P",
        trace_kind="control_trajectory",
    )
    if candidate is None:
        return _placeholder(FIGURE_SPECS[7][1], ["frozen OOD P control trajectory"]), "not_available", [], ["OOD P trajectory"], "No frozen OOD P trajectory was supplied."
    if "ood_pvalue" not in candidate.frame.columns:
        return _placeholder(FIGURE_SPECS[7][1], ["ood_pvalue"]), "not_available", [candidate.path], ["ood_pvalue"], "The frozen OOD P trajectory lacks p-values."
    time_column = _first_column(candidate.frame, ("time_s", "t_s", "time"))
    frequency, _ = _frequency_hz(candidate.frame, f0_hz)
    if time_column is None or frequency is None:
        missing = [name for name, condition in (("time_s", time_column is None), ("frequency/omega", frequency is None)) if condition]
        return _placeholder(FIGURE_SPECS[7][1], missing), "not_available", [candidate.path], missing, "OOD trace cannot reconstruct time/frequency."
    time = _numeric(candidate.frame, time_column)
    pvalue = _numeric(candidate.frame, "ood_pvalue")
    if not np.isfinite(pvalue).any():
        return _placeholder(FIGURE_SPECS[7][1], ["finite ood_pvalue"]), "not_available", [candidate.path], ["finite ood_pvalue"], "The frozen OOD P trajectory contains no finite p-value."
    figure, axes = plt.subplots(2, 1, sharex=True, figsize=(8, 6))
    axes[0].plot(time, frequency, label="frequency deviation")
    state_column = _first_column(candidate.frame, ("controller_state", "diagnostic_state"))
    status = "available"
    missing: list[str] = []
    if state_column is not None:
        fallback = candidate.frame[state_column].astype(str).str.upper().str.contains("FALLBACK|RECOVERY|OOD_ACTIVE").to_numpy(dtype=bool)
        axes[0].fill_between(time, np.nanmin(frequency), np.nanmax(frequency), where=fallback, alpha=0.18, color="#b22222", label="fallback/OOD active")
    else:
        status = "partial"
        missing.append("controller_state/diagnostic_state")
    axes[0].set(ylabel="Frequency deviation (Hz)", title=FIGURE_SPECS[7][1])
    axes[0].legend()
    axes[1].plot(time, pvalue, color="#6a3d9a", label="conformal OOD p-value")
    axes[1].set(xlabel="Time (s)", ylabel="p-value", ylim=(-0.02, 1.02))
    axes[1].legend()
    return figure, status, [candidate.path], missing, "No missing p-values or states are reconstructed."


def _boxplot_figure(episodes: pd.DataFrame, source: Path) -> tuple[plt.Figure, str, list[Path], list[str], str]:
    required = {"method", "freq_iae"}
    missing = sorted(required - set(episodes.columns))
    if missing:
        return _placeholder(FIGURE_SPECS[8][1], missing), "not_available", [source], missing, "Required per-episode metrics are absent."
    frame = episodes[["method", "freq_iae"]].copy()
    frame["freq_iae"] = pd.to_numeric(frame["freq_iae"], errors="coerce")
    methods = [method for method in _METHOD_ORDER if frame.loc[frame["method"] == method, "freq_iae"].notna().any()]
    data = [frame.loc[frame["method"] == method, "freq_iae"].dropna().to_numpy() for method in methods]
    if not data:
        return _placeholder(FIGURE_SPECS[8][1], ["observed freq_iae values"]), "not_available", [source], ["observed freq_iae"], "Missing values were not imputed."
    figure, axis = plt.subplots(figsize=(10, 5))
    axis.boxplot(data, showfliers=False)
    axis.set_xticks(np.arange(1, len(methods) + 1))
    axis.set_xticklabels(methods)
    axis.tick_params(axis="x", rotation=35)
    axis.set(ylabel="Frequency IAE (Hz·s)", title=FIGURE_SPECS[8][1])
    return figure, "available", [source], [], "Boxplots retain all observed episode values; missing results are represented in the result CSV, not imputed here."


def _ablation_figure(episodes: pd.DataFrame, source: Path) -> tuple[plt.Figure, str, list[Path], list[str], str]:
    required = {"method", "freq_iae"}
    missing = sorted(required - set(episodes.columns))
    if missing:
        return _placeholder(FIGURE_SPECS[9][1], missing), "not_available", [source], missing, "Required per-episode metrics are absent."
    frame = episodes.loc[episodes["method"].isin(_ABLATION_METHODS), ["method", "freq_iae"]].copy()
    frame["freq_iae"] = pd.to_numeric(frame["freq_iae"], errors="coerce")
    aggregate = frame.groupby("method", sort=False)["freq_iae"].agg(["mean", "count", "std"]).reindex([method for method in _METHOD_ORDER if method in _ABLATION_METHODS])
    aggregate = aggregate.dropna(subset=["mean"])
    if aggregate.empty:
        return _placeholder(FIGURE_SPECS[9][1], ["observed ablation freq_iae"]), "not_available", [source], ["ablation rows"], "No ablation metric was observed."
    error = 1.96 * aggregate["std"].fillna(0.0) / np.sqrt(aggregate["count"].clip(lower=1))
    figure, axis = plt.subplots(figsize=(9, 4.8))
    axis.bar(aggregate.index, aggregate["mean"], yerr=error, capsize=3, color="#4c78a8")
    axis.tick_params(axis="x", rotation=30)
    axis.set(ylabel="Mean frequency IAE (Hz·s)", title=FIGURE_SPECS[9][1])
    return figure, "available", [source], [], "Error bars are descriptive normal-approximation intervals; inferential results remain in statistical_tests.csv."


def _solver_figure(episodes: pd.DataFrame, source: Path) -> tuple[plt.Figure, str, list[Path], list[str], str]:
    column = _first_column(episodes, ("solve_time_mean_s", "solve_time_p95_s"))
    if column is None or "method" not in episodes.columns:
        missing = [name for name, condition in (("method", "method" not in episodes.columns), ("solve_time_mean_s/solve_time_p95_s", column is None)) if condition]
        return _placeholder(FIGURE_SPECS[10][1], missing), "not_available", [source], missing, "Required solver metrics are absent."
    frame = episodes[["method", column]].copy()
    frame[column] = pd.to_numeric(frame[column], errors="coerce")
    methods = [method for method in _METHOD_ORDER if frame.loc[frame["method"] == method, column].notna().any()]
    data = [1000.0 * frame.loc[frame["method"] == method, column].dropna().to_numpy() for method in methods]
    if not data:
        return _placeholder(FIGURE_SPECS[10][1], [f"observed {column}"]), "not_available", [source], [f"observed {column}"], "Missing solve times were not replaced with zeros."
    figure, axis = plt.subplots(figsize=(10, 5))
    axis.boxplot(data, showfliers=False)
    axis.set_xticks(np.arange(1, len(methods) + 1))
    axis.set_xticklabels(methods)
    axis.tick_params(axis="x", rotation=35)
    axis.set(ylabel=f"{column} (ms)", title=FIGURE_SPECS[10][1])
    return figure, "available", [source], [], f"Episode-level {column}; controller-free methods with null timing are excluded."


def _worst_figure(traces: list[TraceTable], f0_hz: float | None) -> tuple[plt.Figure, str, list[Path], list[str], str]:
    candidate: TraceTable | None = None
    candidate_peak = -np.inf
    candidate_series: tuple[np.ndarray, np.ndarray] | None = None
    for trace in traces:
        if trace.trace_kind != "control_trajectory":
            continue
        time, frequency, _ = _time_and_frequency(trace, f0_hz)
        if time is None or frequency is None:
            continue
        peak = float(np.nanmax(np.abs(frequency)))
        if peak > candidate_peak:
            candidate, candidate_peak, candidate_series = trace, peak, (time, frequency)
    if candidate is None or candidate_series is None:
        return _placeholder(FIGURE_SPECS[11][1], ["worst-case retained time/frequency trace"]), "not_available", [], ["worst trace"], "No retained worst-failure trajectory could be plotted."
    time, frequency = candidate_series
    figure, axes = plt.subplots(2, 1, sharex=True, figsize=(8, 6))
    axes[0].plot(time, frequency, color="#b22222", label=f"peak |Δf|={candidate_peak:.4g} Hz")
    axes[0].axhline(0.5, color="black", linestyle=":")
    axes[0].axhline(-0.5, color="black", linestyle=":")
    axes[0].set(ylabel="Frequency deviation (Hz)", title=FIGURE_SPECS[11][1])
    axes[0].legend()
    state_column = _first_column(candidate.frame, ("controller_state", "diagnostic_state", "solver_status"))
    status = "available"
    missing: list[str] = []
    if state_column is not None:
        categories = candidate.frame[state_column].astype(str)
        codes, labels = pd.factorize(categories, sort=True)
        axes[1].step(_numeric(candidate.frame, _first_column(candidate.frame, ("time_s", "t_s", "time")) or "time_s"), codes, where="post")
        axes[1].set_yticks(range(len(labels)), labels=[str(item) for item in labels])
        axes[1].set(ylabel=state_column, xlabel="Time (s)")
    else:
        axes[1].text(0.5, 0.5, "NOT AVAILABLE — state/status missing", ha="center", va="center", transform=axes[1].transAxes, color="#a32020")
        axes[1].set_axis_off()
        status = "partial"
        missing.append("controller_state/diagnostic_state/solver_status")
    return figure, status, [candidate.path], missing, "The largest control-rate peak among the three manifest-ranked retained worst cases is shown; no episode was deleted."


def make_figures(
    *,
    repo_root: Path,
    results_dir: Path,
    figures_dir: Path,
    representative_dir: Path | None = None,
    worst_dir: Path | None = None,
    replace: bool = False,
    strict_audit: bool = True,
) -> Path:
    repo_root = resolved(repo_root)
    results_dir = resolved(results_dir)
    figures_dir = resolved(figures_dir)
    for name in RESULT_CSV_NAMES:
        require_file(results_dir / name, f"final result CSV {name}")
    validate_result_identity(results_dir)
    if figures_dir.exists() and any(figures_dir.iterdir()) and not replace:
        raise Phase7AuditError(
            f"figure output is non-empty; pass --replace for a staged replacement: {figures_dir}"
        )
    representative_dir = resolved(representative_dir or results_dir / "representative_trajectories")
    worst_dir = resolved(worst_dir or results_dir / "worst_failure_cases")
    require_nonempty_directory(
        representative_dir, "selected representative trajectories"
    )
    require_nonempty_directory(worst_dir, "retained worst failure cases")
    validate_selected_trajectory_manifest(
        representative_dir,
        results_dir=results_dir,
        expected_role="representative",
        enforce_frozen_selection=strict_audit,
    )
    validate_selected_trajectory_manifest(
        worst_dir,
        results_dir=results_dir,
        expected_role="worst",
        enforce_frozen_selection=strict_audit,
    )
    representatives = _load_traces(
        representative_dir, require_trace_identity=strict_audit
    )
    worst = _load_traces(worst_dir, require_trace_identity=strict_audit)
    episodes_path = results_dir / "per_episode_metrics.csv"
    episodes = pd.read_csv(episodes_path)
    f0_hz, base_config = _load_f0(repo_root)
    _style()

    figures_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(
        tempfile.mkdtemp(prefix=".phase7_figures_", dir=str(figures_dir.parent))
    )
    rows: list[dict[str, Any]] = []
    try:
        builders: list[Callable[[], tuple[plt.Figure, str, list[Path], list[str], str]]] = [
            lambda: _overview_figure_with_sources(repo_root),
            lambda: _truth_response_figure(repo_root),
            lambda: _bic_cluster_figure(repo_root),
            lambda: _switch_belief_figure(representatives, f0_hz),
            lambda: _frequency_comparison_figure(representatives, f0_hz),
            lambda: _command_figure(representatives),
            lambda: _scatter_figure(episodes, episodes_path),
            lambda: _ood_figure(representatives, f0_hz),
            lambda: _boxplot_figure(episodes, episodes_path),
            lambda: _ablation_figure(episodes, episodes_path),
            lambda: _solver_figure(episodes, episodes_path),
            lambda: _worst_figure(worst, f0_hz),
        ]
        for index, ((filename, title), builder) in enumerate(zip(FIGURE_SPECS, builders), start=1):
            try:
                figure, status, sources, missing, notes = builder()
            except Exception as exc:
                if strict_audit:
                    raise Phase7AuditError(
                        f"required figure {filename} failed: {type(exc).__name__}: {exc}"
                    ) from exc
                # Small dependency-injected fixtures may intentionally omit
                # optional evidence.  Their audit panel stays unmistakable.
                missing = [f"plotting exception: {type(exc).__name__}: {exc}"]
                figure = _placeholder(title, missing)
                status, sources = "not_available", []
                notes = "The plotting failure is retained verbatim; no replacement data were generated."
            if strict_audit and status != "available":
                plt.close(figure)
                raise Phase7AuditError(
                    f"required figure {filename} is {status}; missing={missing}"
                )
            if base_config is not None and index in {4, 5, 8, 12}:
                sources = [*sources, base_config]
            _write_figure(figure, temporary_root / filename)
            rows.append(
                _manifest_row(
                    figure_id=index,
                    filename=filename,
                    title=title,
                    status=status,
                    sources=sources,
                    missing=missing,
                    notes=notes,
                    output_dir=temporary_root,
                    repo_root=repo_root,
                )
            )
        atomic_write_csv(
            temporary_root / "figure_manifest.csv",
            (
                "figure_id",
                "filename",
                "title",
                "status",
                "data_sources",
                "data_source_sha256",
                "missing_fields",
                "notes",
                "figure_sha256",
            ),
            rows,
        )
        if len(rows) != len(FIGURE_SPECS):
            raise Phase7AuditError("figure manifest does not cover all twelve required figures")
        if figures_dir.exists():
            if not replace:
                raise Phase7AuditError(f"figure output already exists: {figures_dir}")
            backup = figures_dir.parent / f".{figures_dir.name}.old-{os.getpid()}"
            if backup.exists():
                shutil.rmtree(backup)
            os.replace(figures_dir, backup)
            try:
                os.replace(temporary_root, figures_dir)
            except Exception:
                os.replace(backup, figures_dir)
                raise
            shutil.rmtree(backup)
        else:
            os.replace(temporary_root, figures_dir)
        return figures_dir / "figure_manifest.csv"
    finally:
        if temporary_root.exists():
            shutil.rmtree(temporary_root)


def main() -> int:
    arguments = _parser().parse_args()
    repo_root = resolved(arguments.repo_root)
    manifest = make_figures(
        repo_root=repo_root,
        results_dir=_repo_relative(arguments.results_dir, repo_root),
        figures_dir=_repo_relative(arguments.figures_dir, repo_root),
        representative_dir=(
            None
            if arguments.representative_dir is None
            else _repo_relative(arguments.representative_dir, repo_root)
        ),
        worst_dir=(
            None
            if arguments.worst_dir is None
            else _repo_relative(arguments.worst_dir, repo_root)
        ),
        replace=arguments.replace,
    )
    print(
        json.dumps(
            {
                "figure_manifest": str(manifest),
                "figure_count": len(FIGURE_SPECS),
                "manifest_sha256": sha256_file(manifest),
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
