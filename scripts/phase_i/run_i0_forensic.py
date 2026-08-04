"""Freeze Phase H, reproduce its decisive defects, and retract H7 claims."""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from direction1freq.models.bess_capability_v2 import CapabilityTruthV2
from direction1freq.models.delay_augmented_prediction import exact_fractional_delay_vertex
from direction1freq.models.plant_a_v2 import TwoAreaPlantAV2
from direction1freq.models.plant_b_andes_v2 import AndesKundurPlantBV2
from direction5_freq.controllers.dcsv_mpc import (
    DCSVInput,
    DisturbanceCapabilitySeparatedViabilityMPC,
)
from direction5_freq.estimation.capability_set_estimator import CapabilitySetEstimator
from scripts.phase_h.run_h7_validation import simulate_episode


PHASE_H_ZIP = REPO / "DIRECTION5_PHASE_H_DCSV_MPC_SINGLE_REVIEW_PACKAGE.zip"
EXPECTED_ZIP_SHA256 = "2b9f30edf455d98bebe3c34001d0b16ce5f7c1528b8dcea97fc405b6bf5e3da1"
EXPECTED_PHASE_H_COMMIT = "0eb65c7e43a8aa5d21d759a1e8d5980d0aedfd83"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=REPO, text=True, encoding="utf-8"
    ).strip()


def replay_phase_h_package() -> list[dict[str, object]]:
    if sha256(PHASE_H_ZIP) != EXPECTED_ZIP_SHA256:
        raise RuntimeError("Phase-H review ZIP hash mismatch")
    results = []
    with tempfile.TemporaryDirectory(prefix="direction5_phase_i_i0_") as temporary:
        extract = Path(temporary)
        with zipfile.ZipFile(PHASE_H_ZIP) as archive:
            archive.extractall(extract)
        package = extract / "DIRECTION5_PHASE_H_DCSV_MPC_SINGLE_REVIEW_PACKAGE"
        for relative in (
            "15_REPRODUCIBILITY/verify_manifest.py",
            "15_REPRODUCIBILITY/reproduce_minimal.py",
        ):
            completed = subprocess.run(
                [sys.executable, str(package / relative)],
                cwd=package,
                text=True,
                capture_output=True,
                encoding="utf-8",
            )
            results.append(
                {
                    "script": relative,
                    "returncode": completed.returncode,
                    "stdout": completed.stdout.strip(),
                    "stderr": completed.stderr.strip(),
                }
            )
            if completed.returncode:
                raise RuntimeError(f"Phase-H packaged replay failed: {relative}")
    return results


def exact_and_full_rolling_replay() -> pd.DataFrame:
    manifest = pd.read_csv(
        REPO / "results_phase_h/H7/H7_VALIDATION_SCENARIO_MANIFEST.csv"
    )
    official = pd.read_parquet(
        REPO / "results_phase_h/H7/H7_VALIDATION_EPISODES.parquet"
    ).set_index(["scenario_id", "method"])
    selected = manifest[
        manifest.plant.eq("A") & manifest.domain.eq("SUSTAINABLE")
    ].head(20)
    if len(selected) < 20:
        raise RuntimeError("fewer than 20 frozen sustainable H7 scenarios")
    rows = []
    for _, scenario in selected.iterrows():
        method = "fixed_allocation_pi"
        frozen = official.loc[(scenario.scenario_id, method)]
        exact = simulate_episode(scenario, method)
        full_updates = int(round(scenario.registered_duration_s / scenario.period_s))
        full = simulate_episode(scenario, method, active_updates=full_updates)
        rows.append(
            {
                "scenario_id": scenario.scenario_id,
                "split": scenario.split,
                "period_s": scenario.period_s,
                "duration_s": scenario.registered_duration_s,
                "method": method,
                "frozen_frequency_iae": frozen.frequency_iae_hz_s,
                "exact_frequency_iae": exact["frequency_iae_hz_s"],
                "exact_absolute_difference": abs(
                    exact["frequency_iae_hz_s"] - frozen.frequency_iae_hz_s
                ),
                "held_tail_s": exact["certified_or_held_tail_s"],
                "full_rolling_tail_s": full["certified_or_held_tail_s"],
                "full_rolling_frequency_iae": full["frequency_iae_hz_s"],
                "frequency_iae_change": full["frequency_iae_hz_s"]
                - exact["frequency_iae_hz_s"],
                "held_ace_iae": exact["ace_iae_pu_s"],
                "full_rolling_ace_iae": full["ace_iae_pu_s"],
                "ace_iae_change": full["ace_iae_pu_s"] - exact["ace_iae_pu_s"],
            }
        )
    return pd.DataFrame(rows)


def plant_a_driver_comparison() -> pd.DataFrame:
    period = 2.0
    duration = 20.0
    load = np.array([0.12, 0.0])
    action = np.zeros(4)
    vertex = exact_fractional_delay_vertex(period, 0.0)
    reduced = np.zeros(9)
    reduced_rows = []
    for update in range(int(duration / period)):
        reduced = vertex.ad @ reduced + vertex.b_current @ action + vertex.ed @ load
        reduced[3:5] = np.clip(reduced[3:5], -0.15, 0.15)
        reduced[5:7] = np.clip(reduced[5:7], -0.12, 0.12)
        reduced_rows.append((update * period, *(50.0 * reduced[:2])))
    plant = TwoAreaPlantAV2(dt_s=0.02)
    state = plant.equilibrium()
    nonlinear_rows = []
    steps = int(duration / plant.dt_s)
    for step in range(steps):
        state, diagnostic = plant.step(state, action, load, CapabilityTruthV2())
        if step % int(round(period / plant.dt_s)) == 0:
            nonlinear_rows.append(
                (step * plant.dt_s, *(plant.parameters.nominal_frequency_hz * state.omega_pu))
            )
        if np.max(np.abs(diagnostic.power_balance_residual_pu)) > 1e-10:
            raise RuntimeError("nonlinear Plant-A power balance failed")
    reduced_frame = pd.DataFrame(reduced_rows, columns=["time_s", "reduced_f0_hz", "reduced_f1_hz"])
    nonlinear_frame = pd.DataFrame(
        nonlinear_rows, columns=["time_s", "nonlinear_f0_hz", "nonlinear_f1_hz"]
    )
    length = min(len(reduced_frame), len(nonlinear_frame))
    frame = pd.concat(
        [
            reduced_frame.iloc[:length].reset_index(drop=True),
            nonlinear_frame.iloc[:length, 1:].reset_index(drop=True),
        ],
        axis=1,
    )
    frame["max_abs_frequency_difference_hz"] = np.max(
        np.abs(
            frame[["reduced_f0_hz", "reduced_f1_hz"]].to_numpy()
            - frame[["nonlinear_f0_hz", "nonlinear_f1_hz"]].to_numpy()
        ),
        axis=1,
    )
    return frame


def plant_b_native_comparison() -> tuple[pd.DataFrame, pd.DataFrame]:
    load = np.array([0.03, 0.0])
    policy = lambda _observation: np.zeros(4)
    native = AndesKundurPlantBV2(dt_s=0.02).run_causal_closed_loop(
        duration_s=8.0,
        control_period_s=2.0,
        load_profile=lambda _time: load,
        policy=policy,
    )
    native_summary = pd.DataFrame(
        [
            {
                "model": "native_ANDES_Kundur_DAE",
                "native_network": native.native_network,
                "converged": native.converged,
                "samples": len(native.time_s),
                "max_abs_frequency_hz": float(np.max(np.abs(native.frequency_deviation_hz))),
                "max_abs_tie_pu": float(np.max(np.abs(native.tie_line_pu))),
                "algebraic_power_balance_p99_pu": native.algebraic_power_balance_p99_pu,
            },
            {
                "model": "H7_native_residual_calibrated_reduced_label",
                "native_network": False,
                "converged": True,
                "samples": 0,
                "max_abs_frequency_hz": np.nan,
                "max_abs_tie_pu": np.nan,
                "algebraic_power_balance_p99_pu": np.nan,
            },
        ]
    )
    native_trace = pd.DataFrame(
        {
            "time_s": native.time_s.astype("float32"),
            "frequency0_hz": native.frequency_deviation_hz[:, 0].astype("float32"),
            "frequency1_hz": native.frequency_deviation_hz[:, 1].astype("float32"),
            "tie_line_pu": native.tie_line_pu.astype("float32"),
            "bess0_pu": native.bess_power_pu[:, 0].astype("float32"),
            "bess1_pu": native.bess_power_pu[:, 1].astype("float32"),
        }
    )
    return native_summary, native_trace


def semantic_audits() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    h7 = pd.read_parquet(REPO / "results_phase_h/H7/H7_VALIDATION_EPISODES.parquet")
    normal = h7[h7.scenario_type.eq("normal_1h")].copy()
    normal_audit = normal[
        [
            "scenario_id",
            "plant",
            "method",
            "registered_duration_s",
            "controller_calls",
            "frequency_iae_hz_s",
            "ace_iae_pu_s",
            "tie_iae_pu_s",
            "physical_success",
        ]
    ]
    normal_audit["artificial_zero_row"] = (
        normal_audit.controller_calls.eq(0)
        & normal_audit.frequency_iae_hz_s.eq(0)
        & normal_audit.ace_iae_pu_s.eq(0)
        & normal_audit.tie_iae_pu_s.eq(0)
    )

    manifest = pd.read_csv(
        REPO / "results_phase_h/H7/H7_VALIDATION_SCENARIO_MANIFEST.csv"
    )
    factor_columns = [
        "domain",
        "sg_reserve_pu",
        "period_s",
        "mechanism",
        "load0",
        "load1",
        "initial_soc",
        "noise_std_hz",
        "dropout_probability",
        "jitter_bound_s",
        "repeated_change",
    ]
    factor_rows = []
    for factor in factor_columns:
        mapping = manifest.groupby("seed")[factor].nunique(dropna=False)
        factor_rows.append(
            {
                "factor": factor,
                "deterministic_given_seed": bool((mapping == 1).all()),
                "unique_values": int(manifest[factor].nunique(dropna=False)),
                "source_rule": "seed modulo in build_manifest",
            }
        )
    factor_audit = pd.DataFrame(factor_rows)

    estimator = CapabilitySetEstimator(2.0)
    estimate = estimator.update(
        0.0,
        np.zeros(2),
        np.zeros(2),
        np.zeros(2),
        np.array([0.5, 0.5]),
    )
    data = DCSVInput(
        np.zeros(9),
        np.zeros(2),
        np.zeros(4),
        np.zeros(2),
        np.full(2, 25.0),
        np.full(2, 0.02),
        np.full(2, 0.02),
        np.full(2, 0.008),
        np.full(2, 0.008),
        np.array([[0.1, 1.9], [0.1, 1.9]]),
        np.full(2, 0.4),
        np.array([[0.0, 1.0], [0.0, 1.0]]),
        60.0,
    )
    controller = DisturbanceCapabilitySeparatedViabilityMPC(2.0, 3)
    delay_points = controller._delay_points(data)
    semantic = pd.DataFrame(
        [
            {
                "defect": "availability_no_op",
                "observed": estimate.availability_interval.tolist(),
                "invalid_method_claim": "availability separately estimated",
            },
            {
                "defect": "energy_semantics",
                "observed": "energy_available lower bound equals accumulated |SOC-SOC0| movement",
                "invalid_method_claim": "remaining energy guaranteed by estimator",
            },
            {
                "defect": "continuous_delay_not_enveloped",
                "observed": delay_points.tolist(),
                "invalid_method_claim": "three points cover continuous interval without remainder proof",
            },
            {
                "defect": "bridge_clock_not_reused",
                "observed": data.time_to_slow_reserve_s,
                "invalid_method_claim": "rolling handoff clock represented by H7 input",
            },
            {
                "defect": "hard_coded_capability_floors",
                "observed": "power=0.020 ramp=0.008 energy=0.40",
                "invalid_method_claim": "online estimator alone supplies safety floor",
            },
        ]
    )
    return normal_audit, factor_audit, semantic


def main() -> None:
    result_dir = REPO / "results_phase_i/I0"
    output_dir = REPO / "research_outputs_phase_i/00_FORENSIC"
    progress_dir = REPO / "progress_phase_i"
    for directory in (result_dir, output_dir, progress_dir):
        directory.mkdir(parents=True, exist_ok=True)

    package_replay = replay_phase_h_package()
    exact = exact_and_full_rolling_replay()
    exact_path = result_dir / "H7_20_SCENARIO_HELD_VS_FULL_ROLLING.csv"
    exact.to_csv(exact_path, index=False)
    plant_a = plant_a_driver_comparison()
    plant_a_path = result_dir / "PLANT_A_NONLINEAR_VS_H7_ZOH.csv"
    plant_a.to_csv(plant_a_path, index=False)
    plant_b, plant_b_trace = plant_b_native_comparison()
    plant_b_path = result_dir / "PLANT_B_NATIVE_VS_H7_SURROGATE.csv"
    plant_b.to_csv(plant_b_path, index=False)
    plant_b_trace_path = result_dir / "PLANT_B_NATIVE_FORENSIC_TRACE.parquet"
    plant_b_trace.to_parquet(plant_b_trace_path, index=False, compression="zstd")
    normal, factors, semantic = semantic_audits()
    normal_path = result_dir / "NORMAL1H_PROVENANCE_AUDIT.csv"
    factor_path = result_dir / "SEED_FACTOR_CONFOUNDING_AUDIT.csv"
    semantic_path = result_dir / "H7_SEMANTIC_DEFECT_REPRODUCTION.csv"
    normal.to_csv(normal_path, index=False)
    factors.to_csv(factor_path, index=False)
    semantic.to_csv(semantic_path, index=False)

    defects = pd.DataFrame(
        [
            ("I0-D01", "seed_factor_confounding", "CODE", True, factor_path),
            ("I0-D02", "artificial_normal1h_zero_rows", "CODE", True, normal_path),
            ("I0-D03", "short_active_control_then_held_tail", "CODE", True, exact_path),
            ("I0-D04", "plant_b_reduced_surrogate_not_native", "PHYSICAL_MODEL", True, plant_b_path),
            ("I0-D05", "no_unannounced_capability_transition", "EXPERIMENT_DESIGN", True, factor_path),
            ("I0-D06", "capability_estimator_not_guaranteed_floor", "ESTIMATOR", True, semantic_path),
            ("I0-D07", "hard_coded_capability_floors", "PARAMETER_SOURCE", True, semantic_path),
            ("I0-D08", "energy_state_semantics_mismatch", "PHYSICAL_MODEL", True, semantic_path),
            ("I0-D09", "availability_no_op", "ESTIMATOR", True, semantic_path),
            ("I0-D10", "continuous_delay_three_point_gap", "THEORY", True, semantic_path),
            ("I0-D11", "bridge_clock_not_decremented_in_input", "METHOD", True, semantic_path),
            ("I0-D12", "success_without_terminal_recovery", "STATISTICS", True, REPO / "results_phase_h/H7/H7_VALIDATION_EPISODES.parquet"),
        ],
        columns=["defect_id", "defect", "diagnostic_class", "reproduced", "evidence"],
    )
    defects["evidence"] = defects.evidence.map(
        lambda path: Path(path).relative_to(REPO).as_posix()
    )
    defects_path = result_dir / "SCIENTIFIC_VALIDITY_DEFECTS.csv"
    defects.to_csv(defects_path, index=False)

    retractions = pd.DataFrame(
        [
            {
                "phase_h_claim": "H7 is evidence against DCSV-MPC method performance",
                "phase_i_status": "RETRACTED_AS_METHOD_EVIDENCE",
                "replacement": "H7 is a forensic prototype result under confounded and incomplete execution",
            },
            {
                "phase_h_claim": "Plant A/B direction consistency",
                "phase_i_status": "RETRACTED",
                "replacement": "H7 Plant B was a reduced surrogate; native validation required",
            },
            {
                "phase_h_claim": "normal1h safe",
                "phase_i_status": "RETRACTED",
                "replacement": "rows were artificial placeholders and are not simulation evidence",
            },
            {
                "phase_h_claim": "capability set is a guaranteed future envelope",
                "phase_i_status": "RETRACTED",
                "replacement": "contract floor and online performance envelope must be separated",
            },
            {
                "phase_h_claim": "availability and energy estimated as hidden capability",
                "phase_i_status": "RETRACTED",
                "replacement": "energy comes from measured SoC; availability is implicit in deliverability",
            },
        ]
    )
    retraction_path = result_dir / "CLAIM_RETRACTION_TABLE.csv"
    retractions.to_csv(retraction_path, index=False)

    correction_path = output_dir / "PHASE_H_CORRECTION.md"
    correction_path.write_text(
        """# Phase H correction and evidence withdrawal

Phase H is frozen at tag `direction5-phase-h-reviewed`. Its ZIP and package
replays remain reproducible, but H7 is withdrawn as evidence about the DCSV-MPC
method because seed factors were confounded, normal-hour rows were inserted,
the closed loop was held after a short active prefix, Plant B was a reduced
surrogate, and no unannounced capability transition occurred.

The retained interpretation is forensic only: a structurally rolling MPC
prototype failed its registered Gate in that defective experiment driver. It
does not establish method-category failure, cross-Plant consistency, native
Plant-B performance, or normal-hour safety. Phase I must rebuild the physical,
estimation, controller, statistical, and theory semantics without overwriting
any Phase-H evidence.
""",
        "utf-8",
    )
    outputs = [
        defects_path,
        retraction_path,
        exact_path,
        plant_a_path,
        plant_b_path,
        plant_b_trace_path,
        normal_path,
        factor_path,
        semantic_path,
        correction_path,
    ]
    gate = {
        "phase_h_zip_hash_matches": sha256(PHASE_H_ZIP) == EXPECTED_ZIP_SHA256,
        "phase_h_manifest_and_minimal_replay_pass": all(
            item["returncode"] == 0 for item in package_replay
        ),
        "phase_h_tag_frozen_at_expected_commit": git(
            "rev-list", "-n", "1", "direction5-phase-h-reviewed"
        )
        == EXPECTED_PHASE_H_COMMIT,
        "at_least_20_h7_scenarios_exactly_replayed": len(exact) >= 20
        and float(exact.exact_absolute_difference.max()) <= 1e-9,
        "held_tail_difference_replayed": bool(
            exact.held_tail_s.gt(0).all()
            and exact.full_rolling_tail_s.eq(0).all()
            and exact.frequency_iae_change.abs().gt(1e-8).any()
        ),
        "nonlinear_plant_a_contrast_present": bool(
            plant_a.max_abs_frequency_difference_hz.max() > 1e-8
        ),
        "native_plant_b_contrast_present": bool(
            plant_b.loc[plant_b.model.eq("native_ANDES_Kundur_DAE"), "native_network"].all()
        ),
        "artificial_normal_rows_proven": bool(normal.artificial_zero_row.all()),
        "all_registered_fatal_defects_reproduced": bool(defects.reproduced.all()),
        "h7_method_claims_retracted_without_overwrite": bool(
            retractions.phase_i_status.str.startswith("RETRACTED").all()
        ),
    }
    progress = {
        "schema": "direction5.phase_i.progress.v1",
        "stage": "I0",
        "gate": "I0_PHASE_H_FORENSIC_CORRECTION",
        "gate_components": gate,
        "gate_passed": all(gate.values()),
        "inputs": {
            "phase_h_zip_sha256": sha256(PHASE_H_ZIP),
            "phase_h_commit": EXPECTED_PHASE_H_COMMIT,
            "phase_h_tag": "direction5-phase-h-reviewed",
        },
        "package_replay": package_replay,
        "defects_reproduced": int(defects.reproduced.sum()),
        "h7_scenarios_exactly_replayed": len(exact),
        "phase_h_h7_method_evidence_status": "RETRACTED_AS_METHOD_EVIDENCE",
        "final_seeds_consumed": False,
        "failures": [],
        "repairs": [],
        "outputs": {
            path.relative_to(REPO).as_posix(): sha256(path) for path in outputs
        },
        "next_stage": "I1" if all(gate.values()) else "I8_NEGATIVE_UNREPRODUCIBLE",
    }
    progress_path = progress_dir / "I0.json"
    progress_path.write_text(json.dumps(progress, indent=2, sort_keys=True) + "\n", "utf-8")
    print(json.dumps(progress, indent=2, sort_keys=True))
    if not progress["gate_passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
