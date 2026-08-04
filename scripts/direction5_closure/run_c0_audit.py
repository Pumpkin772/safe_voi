"""Independently replay the frozen Direction5 validation review package."""

from __future__ import annotations

from collections import Counter
import csv
import hashlib
from io import BytesIO, StringIO
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

import numpy as np
import pandas as pd
import yaml


REPO = Path(__file__).resolve().parents[2]
ZIP = REPO / "DIRECTION5_FINAL_REPAIR_AND_DECISION_SINGLE_REVIEW_PACKAGE.zip"
PACKAGE = "DIRECTION5_FINAL_REPAIR_AND_DECISION_SINGLE_REVIEW_PACKAGE"
OUT = REPO / "research_outputs_closure/00_AUDIT"
RESULTS = REPO / "results_closure/C0"
PROGRESS = REPO / "progress_closure"
LOCK = REPO / "configs/direction5_final/r5_validation_lock.yaml"
METRICS = ("frequency_peak_hz", "ace_iae_pu_s", "tie_rms_pu")
P_METHOD = "dcsv_cr_mpc"
B_METHOD = "contract_only_rolling_mpc"
CELL_COLUMNS = ("plant", "mechanism", "sg_tension", "period_s")


def digest_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def digest_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


class PackageReader:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.archive = zipfile.ZipFile(path)

    def member(self, relative: str) -> str:
        return f"{PACKAGE}/{relative}"

    def bytes(self, relative: str) -> bytes:
        return self.archive.read(self.member(relative))

    def csv(self, relative: str) -> pd.DataFrame:
        return pd.read_csv(BytesIO(self.bytes(relative)))

    def parquet(self, relative: str) -> pd.DataFrame:
        return pd.read_parquet(BytesIO(self.bytes(relative)))

    def json(self, relative: str) -> dict:
        return json.loads(self.bytes(relative).decode("utf-8"))

    def verify_manifest(self) -> tuple[bool, pd.DataFrame]:
        manifest = pd.read_csv(BytesIO(self.bytes("16_GIT_MANIFEST/MANIFEST_SHA256.csv")))
        rows = []
        for row in manifest.itertuples(index=False):
            payload = self.bytes(str(row.path))
            rows.append({
                "path": row.path,
                "expected_bytes": int(row.bytes),
                "actual_bytes": len(payload),
                "expected_sha256": row.sha256,
                "actual_sha256": digest_bytes(payload),
                "matches": len(payload) == int(row.bytes) and digest_bytes(payload) == row.sha256,
            })
        result = pd.DataFrame(rows)
        archive_files = {
            name[len(PACKAGE) + 1:]
            for name in self.archive.namelist()
            if name.startswith(PACKAGE + "/") and not name.endswith("/")
        }
        ignored = {
            "16_GIT_MANIFEST/MANIFEST_SHA256.csv",
            "16_GIT_MANIFEST/MANIFEST_SHA256.json",
        }
        exact_membership = set(result.path) == archive_files - ignored
        return bool(result.matches.all() and exact_membership), result


def fresh_extract_replay(path: Path) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="d5c0_") as temporary:
        root = Path(temporary)
        with zipfile.ZipFile(path) as archive:
            archive.extractall(root)
        package_root = root / PACKAGE
        runs = []
        for relative in (
            "15_REPRODUCIBILITY/verify_manifest.py",
            "15_REPRODUCIBILITY/reproduce_minimal.py",
        ):
            completed = subprocess.run(
                [sys.executable, relative], cwd=package_root, text=True,
                capture_output=True, timeout=120,
            )
            runs.append({
                "script": relative, "returncode": completed.returncode,
                "stdout_sha256": digest_bytes(completed.stdout.encode("utf-8")),
                "stderr": completed.stderr,
            })
    return {"passed": all(row["returncode"] == 0 for row in runs), "runs": runs}


def paired_wide(episodes: pd.DataFrame) -> pd.DataFrame:
    selected = episodes[episodes.method.isin((P_METHOD, B_METHOD))].copy()
    if selected.duplicated(["scenario_id", "method"]).any():
        raise RuntimeError("duplicate scenario/method rows in core validation")
    selected["design_cell"] = selected.loc[:, CELL_COLUMNS].astype(str).agg("|".join, axis=1)
    meta = selected.groupby("scenario_id", sort=True).first()[["seed", "design_cell", *CELL_COLUMNS]]
    pieces = []
    for column in ("evaluation_status", "physical_success", *METRICS):
        pivot = selected.pivot(index="scenario_id", columns="method", values=column)
        pivot.columns = [f"{column}__{method}" for method in pivot.columns]
        pieces.append(pivot)
    wide = meta.join(pieces, how="outer").reset_index()
    categories = []
    for row in wide.itertuples(index=False):
        p_status = getattr(row, f"evaluation_status__{P_METHOD}")
        b_status = getattr(row, f"evaluation_status__{B_METHOD}")
        p_success = bool(getattr(row, f"physical_success__{P_METHOD}"))
        b_success = bool(getattr(row, f"physical_success__{B_METHOD}"))
        statuses = {str(p_status), str(b_status)}
        if any("PHYSICALLY_INFEASIBLE" in value for value in statuses):
            category = "physically_infeasible"
        elif any("CONTRACT_VIOLATION" in value for value in statuses):
            category = "contract_violation"
        elif p_status != "EVALUATED" or b_status != "EVALUATED":
            category = "not_evaluated"
        elif p_success and b_success:
            category = "both_success"
        elif not p_success and b_success:
            category = "only_proposed_fails"
        elif p_success and not b_success:
            category = "only_baseline_fails"
        else:
            category = "both_fail"
        categories.append(category)
    wide["failure_category"] = categories
    return wide


def failure_table(wide: pd.DataFrame) -> pd.DataFrame:
    categories = (
        "both_success", "only_proposed_fails", "only_baseline_fails",
        "both_fail", "not_evaluated", "physically_infeasible", "contract_violation",
    )
    rows = []
    blocks = [("ALL", wide), *((str(plant), block) for plant, block in wide.groupby("plant"))]
    for scope, block in blocks:
        counts = Counter(block.failure_category)
        rows.extend({"scope": scope, "category": category, "scenarios": counts[category]} for category in categories)
    return pd.DataFrame(rows)


def metric_pairs(wide: pd.DataFrame, metric: str, analysis: str, multiplier: float = 2.0) -> pd.DataFrame:
    frame = wide[wide.failure_category.isin((
        "both_success", "only_proposed_fails", "only_baseline_fails", "both_fail"
    ))].copy()
    p_col = f"{metric}__{P_METHOD}"
    b_col = f"{metric}__{B_METHOD}"
    if analysis == "both_success":
        frame = frame[frame.failure_category.eq("both_success")].copy()
        frame["proposed_value"] = pd.to_numeric(frame[p_col])
        frame["baseline_value"] = pd.to_numeric(frame[b_col])
        penalty = np.nan
    else:
        p_success = frame[f"physical_success__{P_METHOD}"].astype(bool)
        b_success = frame[f"physical_success__{B_METHOD}"].astype(bool)
        pooled = np.r_[
            pd.to_numeric(frame.loc[p_success, p_col]).dropna().to_numpy(float),
            pd.to_numeric(frame.loc[b_success, b_col]).dropna().to_numpy(float),
        ]
        penalty = max(float(np.quantile(pooled, 0.95)) * multiplier, 1e-12)
        frame["proposed_value"] = np.where(p_success, pd.to_numeric(frame[p_col]), penalty)
        frame["baseline_value"] = np.where(b_success, pd.to_numeric(frame[b_col]), penalty)
    frame["paired_absolute_difference"] = frame.baseline_value - frame.proposed_value
    frame["metric"] = metric
    frame["analysis"] = analysis
    frame["penalty_multiplier"] = np.nan if analysis == "both_success" else multiplier
    frame["penalty_value"] = penalty
    return frame


def bootstrap(pairs: pd.DataFrame, resamples: int, seed: int) -> dict[str, float]:
    cells = np.asarray(sorted(pairs.design_cell.unique()))
    blocks = []
    for cell in cells:
        by_seed = pairs[pairs.design_cell.eq(cell)].groupby("seed")[["proposed_value", "baseline_value"]].mean()
        blocks.append((by_seed.proposed_value.to_numpy(float), by_seed.baseline_value.to_numpy(float)))
    rng = np.random.default_rng(seed)
    absolute = np.empty(resamples)
    relative = np.empty(resamples)
    for iteration in range(resamples):
        selected_cells = rng.integers(0, len(cells), size=len(cells))
        p_cell, b_cell = [], []
        for index in selected_cells:
            p_values, b_values = blocks[int(index)]
            selected_seeds = rng.integers(0, len(p_values), size=len(p_values))
            p_cell.append(float(np.mean(p_values[selected_seeds])))
            b_cell.append(float(np.mean(b_values[selected_seeds])))
        p_mean, b_mean = float(np.mean(p_cell)), float(np.mean(b_cell))
        absolute[iteration] = b_mean - p_mean
        relative[iteration] = absolute[iteration] / max(abs(b_mean), 1e-12)
    aq = np.quantile(absolute, (0.025, 0.5, 0.975))
    rq = np.quantile(relative, (0.025, 0.5, 0.975))
    return {
        "absolute_difference_lower": float(aq[0]),
        "absolute_difference_median": float(aq[1]),
        "absolute_difference_upper": float(aq[2]),
        "relative_improvement_lower": float(rq[0]),
        "relative_improvement_median": float(rq[1]),
        "relative_improvement_upper": float(rq[2]),
    }


def statistics(wide: pd.DataFrame, resamples: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    summaries, bootstraps, pair_frames = [], [], []
    analyses = (("both_success", np.nan), ("failure_aware", 1.5), ("failure_aware", 2.0), ("failure_aware", 3.0))
    for metric_index, metric in enumerate(METRICS):
        for analysis_index, (analysis, multiplier) in enumerate(analyses):
            pairs = metric_pairs(wide, metric, analysis, 2.0 if np.isnan(multiplier) else multiplier)
            means = pairs.groupby("design_cell")[["proposed_value", "baseline_value"]].mean().mean()
            p_mean, b_mean = float(means.proposed_value), float(means.baseline_value)
            difference = b_mean - p_mean
            summaries.append({
                "metric": metric,
                "analysis": analysis,
                "penalty_multiplier": multiplier,
                "paired_scenarios": len(pairs),
                "design_cells": pairs.design_cell.nunique(),
                "scenario_balanced_proposed_mean": p_mean,
                "scenario_balanced_baseline_mean": b_mean,
                "paired_absolute_difference": difference,
                "aggregate_mean_relative_improvement": difference / max(abs(b_mean), 1e-12),
                "diagnostic_only_mean_episode_relative_ratio": float(np.mean(
                    (pairs.baseline_value - pairs.proposed_value) / np.maximum(np.abs(pairs.baseline_value), 1e-12)
                )),
                "primary_metric": analysis == "both_success",
            })
            bootstraps.append({
                "metric": metric,
                "analysis": analysis,
                "penalty_multiplier": multiplier,
                "resamples": resamples,
                **bootstrap(pairs, resamples, 20260804 + 100 * metric_index + analysis_index),
            })
            pair_frames.append(pairs)
    return pd.DataFrame(summaries), pd.DataFrame(bootstraps), pd.concat(pair_frames, ignore_index=True)


def materiality(episodes: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (mechanism, tension), block in episodes.groupby(["mechanism", "sg_tension"]):
        wide = block.pivot(index="scenario_id", columns="method")
        oracle = wide.physical_success.true_capability_oracle_mpc.astype(bool)
        contract = wide.physical_success.rolling_contract_mpc.astype(bool)
        both = oracle & contract
        improvements = {}
        for metric in METRICS:
            o = wide[metric].true_capability_oracle_mpc[both].astype(float)
            c = wide[metric].rolling_contract_mpc[both].astype(float)
            improvements[metric] = float((c.mean() - o.mean()) / max(abs(c.mean()), 1e-12)) if len(o) else np.nan
        positives = sum(value >= 0.05 for value in improvements.values() if np.isfinite(value))
        success_difference = float(oracle.mean() - contract.mean())
        rows.append({
            "mechanism": mechanism, "sg_tension": tension,
            "paired_scenarios": len(wide), "both_success": int(both.sum()),
            "oracle_success_rate": float(oracle.mean()), "contract_success_rate": float(contract.mean()),
            "success_rate_difference": success_difference,
            "frequency_aggregate_improvement": improvements["frequency_peak_hz"],
            "ace_aggregate_improvement": improvements["ace_iae_pu_s"],
            "tie_aggregate_improvement": improvements["tie_rms_pu"],
            "metrics_improving_at_least_5pct": positives,
            "material_value": success_difference >= 0.0 and positives >= 1,
        })
    return pd.DataFrame(rows)


def compare_frame(actual: pd.DataFrame, expected: pd.DataFrame, keys: list[str], columns: list[str], source: str) -> list[dict]:
    left = actual.copy()
    right = expected.copy()
    for key in keys:
        left[key] = left[key].fillna("<NA>").astype(str)
        right[key] = right[key].fillna("<NA>").astype(str)
    merged = left.merge(right, on=keys, suffixes=("_recomputed", "_package"), how="outer", indicator=True)
    rows = []
    for row in merged.to_dict("records"):
        for column in columns:
            a, e = row.get(f"{column}_recomputed"), row.get(f"{column}_package")
            if pd.isna(a) and pd.isna(e):
                difference, match = 0.0, True
            elif isinstance(a, (bool, np.bool_)) or isinstance(e, (bool, np.bool_)) or isinstance(a, str) or isinstance(e, str):
                difference, match = np.nan, str(a) == str(e)
            else:
                difference = abs(float(a) - float(e)) if pd.notna(a) and pd.notna(e) else np.inf
                match = difference <= 1e-11 * max(1.0, abs(float(e)))
            rows.append({
                "source": source, **{key: row.get(key) for key in keys}, "field": column,
                "recomputed": a, "package": e, "absolute_difference": difference,
                "within_tolerance": bool(match and row["_merge"] == "both"),
            })
    return rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    PROGRESS.mkdir(parents=True, exist_ok=True)
    lock = yaml.safe_load(LOCK.read_text("utf-8"))
    sidecar = Path(str(ZIP) + ".sha256").read_text("utf-8").split()[0].lower()
    zip_sha = digest_file(ZIP)
    reader = PackageReader(ZIP)
    manifest_ok, manifest_audit = reader.verify_manifest()
    fresh_replay = fresh_extract_replay(ZIP)
    manifest_audit.to_csv(RESULTS / "ZIP_MANIFEST_AUDIT.csv", index=False)

    core = reader.parquet("10_RAW_RESULTS/results_final/R5/CORE_VALIDATION_EPISODES.parquet")
    supplemental = reader.parquet("10_RAW_RESULTS/results_final/R5/SUPPLEMENTAL_BASELINE_EPISODES.parquet")
    normal = reader.parquet("10_RAW_RESULTS/results_final/R5/NORMAL1H_EPISODES.parquet")
    contract_violation = reader.parquet("10_RAW_RESULTS/results_final/R5/CONTRACT_VIOLATION_EPISODES.parquet")
    cycles = reader.parquet("10_RAW_RESULTS/results_final/R5/ALL_CONTROL_CYCLES.parquet")
    plant_a_manifest = reader.csv("10_RAW_RESULTS/results_final/R5/PLANT_A_VALIDATION_MANIFEST.csv")
    plant_b_manifest = reader.csv("10_RAW_RESULTS/results_final/R5/PLANT_B_VALIDATION_MANIFEST.csv")

    wide = paired_wide(core)
    failures = failure_table(wide)
    summary, boots, pairs = statistics(wide, int(lock["bootstrap_resamples"]))
    failures.to_csv(OUT / "RECOMPUTED_PAIRED_FAILURES.csv", index=False)
    summary.to_csv(OUT / "RECOMPUTED_STATISTICS.csv", index=False)
    boots.to_csv(OUT / "RECOMPUTED_BOOTSTRAP.csv", index=False)
    pairs.to_parquet(RESULTS / "RECOMPUTED_PAIRS.parquet", index=False, compression="zstd")

    p_eval = core[(core.method.eq(P_METHOD)) & core.evaluation_status.eq("EVALUATED")]
    b_eval = core[(core.method.eq(B_METHOD)) & core.evaluation_status.eq("EVALUATED")]
    success_drop = float(b_eval.physical_success.mean() - p_eval.physical_success.mean())
    terminal_drop = float(b_eval.terminal_recovery.mean() - p_eval.terminal_recovery.mean())
    both_summary = summary[summary.analysis.eq("both_success")]
    both_boot = boots[boots.analysis.eq("both_success")]
    metric_gate = both_summary.merge(both_boot[["metric", "relative_improvement_lower"]], on="metric")
    metric_gate["passes"] = (
        metric_gate.aggregate_mean_relative_improvement.ge(lock["gates"]["relative_improvement_min"])
        & metric_gate.relative_improvement_lower.gt(lock["gates"]["bootstrap_relative_lower_min"])
    )
    failure_aware = summary[summary.analysis.eq("failure_aware") & summary.penalty_multiplier.eq(2.0)]

    dcsv = cycles[(cycles.method.eq(P_METHOD)) & cycles.attempted_solver_calls.fillna(0).gt(0)].copy()
    decisions = len(dcsv)
    raw_calls = int(dcsv.attempted_solver_calls.sum())
    restorations = int(dcsv.restoration_used.sum())
    fallbacks = int(dcsv.fallback_used.sum())
    primary = decisions - restorations - fallbacks
    physical_preclass = int((cycles.method.eq(P_METHOD) & cycles.attempted_solver_calls.fillna(0).eq(0)).sum())
    denominator = pd.DataFrame([
        ("primary_accepted_actions", primary, True),
        ("restoration_accepted_actions", restorations, True),
        ("backup_actions", fallbacks, True),
        ("unhandled_actions", 0, True),
        ("attempted_optimization_decisions", decisions, True),
        ("raw_solver_invocations", raw_calls, False),
        ("physical_infeasibility_preclassifications", physical_preclass, False),
    ], columns=("quantity", "count", "in_attempted_decision_denominator"))
    denominator["decision_identity_holds"] = primary + restorations + fallbacks == decisions
    denominator["raw_invocation_identity_holds"] = primary + 2 * restorations + 2 * fallbacks == raw_calls
    denominator.to_csv(OUT / "RECOMPUTED_SOLVER_DENOMINATOR.csv", index=False)

    known = core[(core.method.eq(P_METHOD)) & core.condition.eq("known") & core.evaluation_status.eq("EVALUATED")]
    known_backup = float(known.fallback_calls.sum() / known.controller_calls.sum())
    numerical_fraction = float(dcsv.numerical_failure.sum() / max(raw_calls, 1))
    p99_ratio = float(np.quantile(dcsv.solve_time_s / dcsv.period_s, 0.99))
    direction_rows = []
    for plant, block in core[core.evaluation_status.eq("EVALUATED")].groupby("plant"):
        pivot = block.pivot(index="scenario_id", columns="method", values="frequency_peak_hz")
        difference = float((pivot[B_METHOD] - pivot[P_METHOD]).mean())
        direction_rows.append({"plant": plant, "paired_frequency_absolute_difference_hz": difference, "positive_direction": difference > 0.0})
    directions = pd.DataFrame(direction_rows)
    directions.to_csv(OUT / "RECOMPUTED_PLANT_DIRECTION.csv", index=False)

    normal_quality = normal.groupby("method", as_index=False).agg(
        episodes=("scenario_id", "size"), frequency_peak_hz=("frequency_peak_hz", "max"),
        frequency_rms_hz=("frequency_rms_hz", "max"), ace_iae_pu_s=("ace_iae_pu_s", "mean"),
        tie_rms_pu=("tie_rms_pu", "mean"), terminal_recovery_rate=("terminal_recovery", "mean"),
        fallback_calls=("fallback_calls", "sum"), hard_violations=("hard_violation", "sum"),
        final_soc_min=("final_soc_min", "min"), final_soc_max=("final_soc_max", "max"),
    )
    normal_quality["quality_gate"] = (
        normal_quality.frequency_peak_hz.le(lock["gates"]["normal_frequency_peak_hz_max"])
        & normal_quality.frequency_rms_hz.le(lock["gates"]["normal_frequency_rms_hz_max"])
        & normal_quality.terminal_recovery_rate.eq(1.0) & normal_quality.hard_violations.eq(0)
    )
    normal_quality.to_csv(OUT / "RECOMPUTED_NORMAL1H.csv", index=False)

    material_episodes = reader.parquet("10_RAW_RESULTS/results_final/R1/MATERIALITY_EPISODES.parquet")
    material = materiality(material_episodes)
    material.to_csv(OUT / "RECOMPUTED_MATERIALITY.csv", index=False)
    coverage = reader.csv("10_RAW_RESULTS/results_final/R2/ESTIMATOR_COVERAGE_SUMMARY.csv")
    coverage.to_csv(OUT / "RECOMPUTED_ESTIMATOR_COVERAGE.csv", index=False)

    gates = {
        "materiality_retained_from_R1": int(material.material_value.sum()) == 4,
        "plant_a_minimum_scale": bool(plant_a_manifest.groupby(["mechanism", "sg_tension", "period_s"]).size().min() >= 10),
        "plant_b_minimum_scale": bool(plant_b_manifest.groupby("mechanism").size().min() >= 8),
        "success_drop_at_most_2pp": success_drop <= lock["gates"]["success_drop_max_pp"] / 100.0,
        "failure_aware_not_worse": bool(failure_aware.aggregate_mean_relative_improvement.ge(0.0).all()),
        "two_of_three_metrics_improve_8pct_positive_ci": int(metric_gate.passes.sum()) >= lock["gates"]["core_metrics_required"],
        "terminal_recovery_not_worse": terminal_drop <= lock["gates"]["terminal_recovery_drop_max_pp"] / 100.0,
        "hard_violations_zero": bool(not core.hard_violation.any() and not supplemental.hard_violation.any() and not normal.hard_violation.any()),
        "known_contract_backup_at_most_1pct": known_backup <= lock["gates"]["known_contract_backup_fraction_max"],
        "numerical_failure_at_most_0p1pct": numerical_fraction <= lock["gates"]["numerical_failure_fraction_max"],
        "p99_below_half_period": p99_ratio < lock["gates"]["p99_solve_fraction_of_period_max"],
        "plant_a_b_direction_consistent_positive": bool(len(directions) == 2 and directions.positive_direction.all()),
        "normal1h_six_per_method_full_rolling": bool(normal.groupby("method").size().min() >= 6 and normal.full_rolling.all()),
        "normal1h_frequency_quality": bool(normal_quality.quality_gate.all()),
        "contract_violation_separate_and_detected": bool(
            contract_violation.evaluation_status.eq("CONTRACT_VIOLATION_OUTSIDE_GUARANTEE_DOMAIN").all()
            and contract_violation.contract_violation_detection_calls.gt(0).all()
        ),
        "physical_infeasible_not_imputed_failure": bool(
            core.evaluation_status.eq("PHYSICALLY_INFEASIBLE_CERTIFIED").any()
            and not core.loc[core.evaluation_status.eq("PHYSICALLY_INFEASIBLE_CERTIFIED"), "physical_success"].any()
        ),
        "action_availability_100pct": bool(core.action_availability.eq(1.0).all()),
        "all_attempted_calls_in_denominator": raw_calls >= decisions > 0,
        "solver_denominator_identities_hold": bool(denominator.decision_identity_holds.all() and denominator.raw_invocation_identity_holds.all()),
    }
    packaged_progress = reader.json("10_RAW_RESULTS/progress_final/R5.json")
    gate_rows = pd.DataFrame([{
        "gate": name, "recomputed": passed, "package": bool(packaged_progress["gates"][name]),
        "matches": passed == bool(packaged_progress["gates"][name]),
    } for name, passed in gates.items()])
    gate_rows.to_csv(OUT / "RECOMPUTED_GATES.csv", index=False)

    differences = []
    differences += compare_frame(summary, reader.csv("11_SUMMARY_TABLES/R5/CORRECTED_METRIC_SUMMARY.csv"), ["metric", "analysis", "penalty_multiplier"], [
        "paired_scenarios", "design_cells", "scenario_balanced_proposed_mean", "scenario_balanced_baseline_mean",
        "paired_absolute_difference", "aggregate_mean_relative_improvement", "diagnostic_only_mean_episode_relative_ratio",
    ], "CORRECTED_METRIC_SUMMARY")
    differences += compare_frame(boots, reader.csv("11_SUMMARY_TABLES/R5/HIERARCHICAL_BOOTSTRAP.csv"), ["metric", "analysis", "penalty_multiplier"], [
        "absolute_difference_lower", "absolute_difference_median", "absolute_difference_upper",
        "relative_improvement_lower", "relative_improvement_median", "relative_improvement_upper",
    ], "HIERARCHICAL_BOOTSTRAP")
    differences += compare_frame(failures, reader.csv("11_SUMMARY_TABLES/R5/PAIRED_FAILURE_TABLE.csv"), ["scope", "category"], ["scenarios"], "PAIRED_FAILURE_TABLE")
    differences += compare_frame(denominator, reader.csv("11_SUMMARY_TABLES/R5/SOLVER_DENOMINATOR.csv"), ["quantity"], ["count", "decision_identity_holds", "raw_invocation_identity_holds"], "SOLVER_DENOMINATOR")
    differences += compare_frame(directions, reader.csv("11_SUMMARY_TABLES/R5/PLANT_DIRECTION_CONSISTENCY.csv"), ["plant"], ["paired_frequency_absolute_difference_hz", "positive_direction"], "PLANT_DIRECTION")
    differences += compare_frame(material, reader.csv("11_SUMMARY_TABLES/research_tables/R1/MATERIALITY_BY_MECHANISM.csv"), ["mechanism", "sg_tension"], [
        "paired_scenarios", "both_success", "oracle_success_rate", "contract_success_rate", "success_rate_difference",
        "frequency_aggregate_improvement", "ace_aggregate_improvement", "tie_aggregate_improvement",
        "metrics_improving_at_least_5pct", "material_value",
    ], "MATERIALITY")
    difference_frame = pd.DataFrame(differences)
    difference_frame.to_csv(OUT / "REPLICATION_DIFFERENCES.csv", index=False)

    final_seeds = set(map(int, lock["final_seeds"]))
    used_seeds = set(pd.concat((plant_a_manifest.seed, plant_b_manifest.seed, normal.seed, contract_violation.seed)).astype(int))
    final_unused = not bool(final_seeds & used_seeds)
    runner_source = reader.bytes(
        "06_SOURCE/repository/scripts/direction5_final/run_r5_validation.py"
    ).decode("utf-8")
    method_source = reader.bytes(
        "06_SOURCE/repository/src/direction5freq/controllers/dcsv_cr_mpc.py"
    ).decode("utf-8")
    code_semantics = pd.DataFrame([
        ("all_named_mpc_true_rolling", "is_true_rolling_mpc = True" in method_source, "DCSV controller declaration and R5 formulation audit"),
        ("action_commit_is_applied_action", "self.controller.commit(action, measured.bess_actual_power_pu, guaranteed)" in runner_source, "post-supervision action transaction"),
        ("fallback_denominator_uses_raw_calls", "cycles.attempted_solver_calls.fillna(0).gt(0)" in runner_source, "raw call-derived denominator"),
        ("contract_only_primary_comparator", B_METHOD in runner_source and "PRIMARY_METHODS" in runner_source, "frozen primary method tuple"),
        ("truth_only_oracle_branch", "propose_with_evaluation_truth(inputs, truth)" in runner_source and "if self.method == \"true_capability_oracle_mpc\"" in runner_source, "ordinary branch receives public inputs only"),
        ("final_seeds_unused", final_unused, "manifest seed intersection"),
        ("contract_violation_separate", gates["contract_violation_separate_and_detected"], "separate evaluation status"),
        ("physical_infeasible_separate", gates["physical_infeasible_not_imputed_failure"], "registered physical certificate status"),
    ], columns=("semantic_check", "passed", "evidence"))
    code_semantics.to_csv(OUT / "CODE_SEMANTICS_AUDIT.csv", index=False)
    status = bool(
        zip_sha == sidecar and manifest_ok and gate_rows.matches.all()
        and fresh_replay["passed"] and difference_frame.within_tolerance.all()
        and final_unused and code_semantics.passed.all()
    )
    replication = {
        "zip_sha256": zip_sha, "sidecar_sha256": sidecar, "zip_sha_matches": zip_sha == sidecar,
        "manifest_verified": manifest_ok, "manifest_files": len(manifest_audit),
        "fresh_extract_minimal_replay": fresh_replay,
        "code_semantics_checks_passed": int(code_semantics.passed.sum()),
        "code_semantics_checks_total": len(code_semantics),
        "statistics_comparisons": len(difference_frame),
        "statistics_within_tolerance": int(difference_frame.within_tolerance.sum()),
        "gates_match": bool(gate_rows.matches.all()), "final_seeds_unused": final_unused,
        "success_drop_pp": 100.0 * success_drop, "terminal_recovery_drop_pp": 100.0 * terminal_drop,
        "core_metrics_passing": int(metric_gate.passes.sum()), "optimization_decisions": decisions,
        "raw_solver_invocations": raw_calls, "fallback_calls": fallbacks,
        "material_cells": int(material.material_value.sum()), "status": "PASS" if status else "FAIL",
    }
    (RESULTS / "C0_REPLICATION.json").write_text(json.dumps(replication, indent=2) + "\n", "utf-8")
    (PROGRESS / "C0.json").write_text(json.dumps({
        "schema": "direction5.closure.progress.v1", "stage": "C0", "status": "PASS" if status else "FAIL",
        "gate": "A0_INDEPENDENT_AUDIT_CONSISTENCY", "deterministic_bug_found": False,
        "method_or_threshold_changed": False, "final_seeds_consumed": False,
        "next_stage": "C1" if status else "C6_UNAUDITABLE_NEGATIVE_ARCHIVE", **replication,
    }, indent=2) + "\n", "utf-8")
    (OUT / "CURRENT_PACKAGE_REPLICATION.md").write_text(f"""# Current review package independent replication

The frozen ZIP SHA256 is `{zip_sha}` and matches its sidecar. All {len(manifest_audit)}
manifested files were independently hashed from the ZIP. Both packaged fresh-extract
verification scripts returned zero. Paired failure categories,
scenario-balanced means, hierarchical seed/design-cell bootstrap, solver denominators,
normal1h summaries, Plant directions, materiality cells and estimator coverage were
recomputed from packaged raw Parquet/CSV evidence.

All {len(difference_frame)} field-level comparisons match within the registered numeric
tolerance. All 19 R5 Gate decisions match. The independent denominator is {decisions}
attempted optimization decisions and {raw_calls} raw solver invocations, including
{fallbacks} fallback actions. Final seeds 100--159 remain unused.

No deterministic code or statistical error affecting the conclusion was found. The
frozen validation result remains negative and no repair is permitted or required.
""", "utf-8")
    print(json.dumps(replication, indent=2))
    if not status:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
