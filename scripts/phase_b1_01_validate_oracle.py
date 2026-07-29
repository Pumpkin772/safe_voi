"""Run the preregistered B5 validation matrix and lock one global candidate."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
from dataclasses import asdict
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from d5freq.evaluation.experiment_store import PerRunExperimentStore
from d5freq.evaluation.phase_b1_experiments import (
    PhaseB1RunSpec,
    build_development_plan,
    execute_phase_b1_run,
)
from d5freq.evaluation.phase_b1_protocol import PhaseB1Paths
from d5freq.utils.config import config_sha256, load_yaml
from d5freq.utils.hashing import sha256_file


SCHEMA_VERSION = "d5freq.phase_b1.oracle_validation_selection.v1"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--workers", type=int, default=4)
    return parser


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty CSV {path}")
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _strict_json(path: Path, payload: Any, *, immutable: bool = False) -> None:
    serialized = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if immutable and path.exists():
        if path.read_text(encoding="utf-8") != serialized:
            raise RuntimeError(f"immutable validation selection differs at {path}")
        return
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(serialized, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _execute(specs: tuple[PhaseB1RunSpec, ...], workers: int) -> list[dict[str, Any]]:
    if workers < 1 or workers > 4:
        raise ValueError("workers must lie in [1, 4]")
    receipts: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(execute_phase_b1_run, spec): spec for spec in specs}
        completed = 0
        for future in as_completed(futures):
            spec = futures[future]
            try:
                receipt = future.result()
            except Exception as exc:
                raise RuntimeError(f"validation worker escaped for {spec.identity.run_id}") from exc
            receipts.append(asdict(receipt))
            completed += 1
            if completed % 25 == 0 or completed == len(specs):
                print(f"validation progress: {completed}/{len(specs)}", flush=True)
    return receipts


def _episode_rows(paths: PhaseB1Paths, specs: tuple[PhaseB1RunSpec, ...]) -> list[dict[str, Any]]:
    store = PerRunExperimentStore(paths.results_root / "runs/validation/per_run")
    protocol = load_yaml(paths.experiments_config)
    truth = {
        row["scenario_id"]: row["truth_class"]
        for row in protocol["scenario_variants"]
    }
    rows: list[dict[str, Any]] = []
    for spec in specs:
        stored = store.load(spec.identity)
        if stored is None:
            raise RuntimeError(f"validation run is missing: {spec.identity.run_id}")
        row = stored.episode_result.to_json_dict()
        row.update(
            {
                "stage": spec.stage,
                "sg_level": spec.sg_level,
                "truth_class": truth[spec.scenario_id],
                "oracle_candidate_id": spec.oracle_candidate_id,
                "oracle_horizon_s": spec.oracle_horizon_s,
                "envelope_sha256": stored.sha256,
            }
        )
        rows.append(row)
    return rows


def _finite(rows: list[dict[str, Any]], name: str) -> np.ndarray:
    values = [float(row[name]) for row in rows if row.get(name) is not None]
    return np.asarray(values, dtype=float)


def _candidate_summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for candidate_id in ("H2", "H4", "H6"):
        group = [row for row in rows if row["oracle_candidate_id"] == candidate_id]
        if not group:
            raise RuntimeError(f"validation has no rows for {candidate_id}")
        iae = _finite(group, "freq_iae")
        max_frequency = _finite(group, "max_abs_freq_hz")
        wall = _finite(group, "wall_time_s")
        failure_count = sum(not bool(row.get("scientific_success")) for row in group)
        summaries.append(
            {
                "candidate_id": candidate_id,
                "episode_count": len(group),
                "scientific_failure_count": failure_count,
                "scientific_failure_rate": failure_count / len(group),
                "complete_freq_iae_count": int(iae.size),
                "mean_frequency_iae_hz_s": None if not iae.size else float(np.mean(iae)),
                "q95_max_abs_frequency_hz": (
                    None if not max_frequency.size else float(np.quantile(max_frequency, 0.95))
                ),
                "mean_wall_time_s": None if not wall.size else float(np.mean(wall)),
            }
        )
    if any(row["complete_freq_iae_count"] != row["episode_count"] for row in summaries):
        raise RuntimeError("an Oracle candidate has incomplete validation metrics")
    return summaries


def _rank_key(row: dict[str, Any]) -> tuple[float, float, float, float, str]:
    def number(name: str) -> float:
        value = row[name]
        return math.inf if value is None else float(value)

    return (
        number("scientific_failure_rate"),
        number("mean_frequency_iae_hz_s"),
        number("q95_max_abs_frequency_hz"),
        number("mean_wall_time_s"),
        str(row["candidate_id"]),
    )


def main() -> int:
    arguments = _parser().parse_args()
    paths = PhaseB1Paths.from_repo(arguments.repo_root)
    oracle = load_yaml(paths.oracle_config)
    selection_config = oracle["validation_selection"]
    scenario_ids = tuple(selection_config["scenario_ids"])
    sg_levels = tuple(selection_config["sg_levels"])
    candidate_ids = tuple(row["candidate_id"] for row in oracle["validation_candidates"])
    specs = build_development_plan(
        paths,
        stage="validation",
        scenario_ids=scenario_ids,
        method_ids=("B0", "B5"),
        sg_levels=sg_levels,
        oracle_candidate_ids=candidate_ids,
    )
    expected_count = len(scenario_ids) * len(sg_levels) * 10 * (1 + len(candidate_ids))
    if len(specs) != expected_count:
        raise AssertionError(f"validation plan has {len(specs)} runs; expected {expected_count}")
    receipts = _execute(specs, arguments.workers)
    output = paths.results_root / "oracle_validation"
    episode_rows = _episode_rows(paths, specs)
    summaries = _candidate_summaries(episode_rows)
    ranked = sorted(summaries, key=_rank_key)
    selected = ranked[0]
    _write_csv(episode_rows, output / "per_episode_metrics.csv")
    _write_csv(summaries, output / "candidate_summary.csv")
    _write_csv(receipts, output / "worker_receipts.csv")
    selection = {
        "schema_version": SCHEMA_VERSION,
        "split": "phase_b1_validation",
        "final_seed_feedback_used": False,
        "validation_seeds": list(range(400, 410)),
        "scenario_ids": list(scenario_ids),
        "sg_levels": list(sg_levels),
        "candidate_ids": list(candidate_ids),
        "ordered_objectives": list(selection_config["ordered_objectives"]),
        "tie_breaker": selection_config["tie_breaker"],
        "selected_candidate_id": selected["candidate_id"],
        "selected_horizon_s": next(
            float(row["horizon_s"])
            for row in oracle["validation_candidates"]
            if row["candidate_id"] == selected["candidate_id"]
        ),
        "candidate_ranking": [row["candidate_id"] for row in ranked],
        "candidate_summaries": summaries,
        "episode_count": len(episode_rows),
        "all_attempts_retained": len(episode_rows) == expected_count,
        "oracle_config_file_sha256": sha256_file(paths.oracle_config),
        "oracle_config_logical_sha256": config_sha256(oracle),
    }
    _strict_json(paths.validation_selection, selection, immutable=True)
    _strict_json(output / "selection.json", selection)
    print(
        f"selected {selection['selected_candidate_id']} "
        f"({selection['selected_horizon_s']} s); {len(episode_rows)} rows retained"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
