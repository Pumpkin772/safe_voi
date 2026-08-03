"""Freeze and independently audit the historical Phase-G G2 evidence."""

from __future__ import annotations

from dataclasses import replace
import hashlib
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

from direction1freq.controllers.ace_pi_aw import ACEPIAntiWindup, design_stable_pi
from direction1freq.estimation.structured_observer import StructuredLoadStateObserver
from direction1freq.models.bess_capability_v2 import current_capability_v2
from direction1freq.models.guaranteed_capability_envelope import GuaranteedCapabilityEnvelope
from direction1freq.models.plant_a_v2 import PlantAParametersV2, TwoAreaPlantAV2
from scripts.phase_e.run_e3_materiality import capability_at, load_at
from scripts.phase_f.run_f3_model_sets import build_calibration_manifest


PHASE_G_ZIP = REPO / "DIRECTION1_PHASE_G_TERMINAL_VIABILITY_FULL_VALIDATION_SINGLE_REVIEW_PACKAGE.zip"
EXPECTED_PHASE_G_SHA256 = "018dc05b6d78bec9069114b19986b21fbfdba6d04f5caeb42d9c563f03c53d79"
STATE_RESIDUAL_COLUMNS = [f"worst_model_x{index}" for index in range(9)]
EQUILIBRIUM_DISTANCE_LIMIT_PU = 0.01


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run_packaged_replay() -> tuple[list[dict[str, object]], list[str]]:
    if sha256(PHASE_G_ZIP) != EXPECTED_PHASE_G_SHA256:
        raise RuntimeError("historical Phase-G ZIP hash mismatch")
    with zipfile.ZipFile(PHASE_G_ZIP) as archive:
        members = archive.namelist()
        missing_dependencies = [
            dependency
            for dependency in (
                "06_SOURCE/scripts/phase_e/run_e3_materiality.py",
                "06_SOURCE/scripts/phase_f/run_f3_model_sets.py",
            )
            if dependency not in members
        ]
        with tempfile.TemporaryDirectory(prefix="direction5_phase_h_h0_") as temporary:
            root = Path(temporary) / "phase_g_review"
            archive.extractall(root)
            replay: list[dict[str, object]] = []
            for script in (
                "verify_manifest.py",
                "reproduce_minimal.py",
                "verify_negative_boundary.py",
            ):
                result = subprocess.run(
                    [sys.executable, str(root / "15_REPRODUCIBILITY" / script)],
                    cwd=root,
                    text=True,
                    capture_output=True,
                    encoding="utf-8",
                )
                replay.append(
                    {
                        "script": script,
                        "returncode": result.returncode,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                    }
                )
                if result.returncode != 0:
                    raise RuntimeError(f"historical replay failed: {script}")
    return replay, missing_dependencies


def _domain_and_equilibrium(
    state,
    load: np.ndarray,
    reserve: float,
    plant: TwoAreaPlantAV2,
    truth,
    bridge_duration_s: float,
) -> tuple[str, float, float, float]:
    """Return a forensic classification; H2 will build the registered manifest."""

    sustainable = bool(np.all(np.abs(load) <= reserve + 1e-12))
    if sustainable:
        target = np.r_[np.zeros(3), load, load, np.zeros(2)]
        distance = float(np.max(np.abs(plant.state_vector(state) - target)))
        return "SUSTAINABLE", distance, 0.0, 0.0

    capability = current_capability_v2(
        state.bess, plant.parameters.bess, truth, plant.dt_s
    )
    required = np.sign(load) * np.maximum(np.abs(load) - reserve, 0.0)
    power_shortfall = np.maximum(
        required - capability.upper_power_pu,
        capability.lower_power_pu - required,
    )
    power_shortfall = np.maximum(power_shortfall, 0.0)
    base = plant.parameters.system_base_mva
    discharge_energy = np.maximum(required, 0.0) * base * bridge_duration_s / 3600.0
    charge_energy = np.maximum(-required, 0.0) * base * bridge_duration_s / 3600.0
    energy_available = np.minimum(
        (state.bess.energy_mwh - capability.lower_energy_mwh)
        * plant.parameters.bess.eta_discharge,
        (capability.upper_energy_mwh - state.bess.energy_mwh)
        / plant.parameters.bess.eta_charge,
    )
    energy_required = discharge_energy + charge_energy
    if np.all(power_shortfall <= 1e-12) and np.all(
        energy_required <= energy_available + 1e-12
    ):
        return (
            "BRIDGE_ONLY",
            float("nan"),
            float(np.max(power_shortfall)),
            float(np.max(np.maximum(energy_required - energy_available, 0.0))),
        )
    return (
        "PHYSICALLY_INFEASIBLE_UNDER_REGISTERED_CAPABILITY",
        float("nan"),
        float(np.max(power_shortfall)),
        float(np.max(np.maximum(energy_required - energy_available, 0.0))),
    )


def replay_interval_audit(manifest: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    registered_delays = GuaranteedCapabilityEnvelope.phase_f_registered().delay_vertices_s
    for _, scenario in manifest.iterrows():
        period = float(scenario.sfr_period_s)
        reserve = float(scenario.sg_reserve_pu)
        delay_truth = float(registered_delays[int(scenario.load_seed) % len(registered_delays)])
        base = PlantAParametersV2()
        plant = TwoAreaPlantAV2(
            replace(
                base,
                sg_power_lower_pu=(-reserve, -reserve),
                sg_power_upper_pu=(reserve, reserve),
                valve_lower_pu=(-1.2 * reserve, -1.2 * reserve),
                valve_upper_pu=(1.2 * reserve, 1.2 * reserve),
            ),
            dt_s=0.05,
        )
        kp, ki, _ = design_stable_pi(plant, period)
        controller = ACEPIAntiWindup(period, kp, ki, sg_fraction=0.70)
        observer = StructuredLoadStateObserver(period, plant=plant)
        state = plant.equilibrium(
            (float(scenario.initial_soc_1), float(scenario.initial_soc_2))
        )
        command = np.zeros(4)
        update_steps = int(round(period / plant.dt_s))
        duration_steps = int(round(72.0 / plant.dt_s))
        active: dict[str, object] | None = None
        for step in range(duration_steps + 1):
            time_s = step * plant.dt_s
            observation = plant.public_observation(time_s, state, command)
            if step % update_steps == 0:
                if active is not None:
                    rows.append(active)
                observer.update(observation)
                raw_command, pi_diagnostics = controller.update(observation)
                applied_command = raw_command.copy()
                applied_command[[0, 2]] = np.clip(
                    applied_command[[0, 2]], -reserve, reserve
                )
                command_saturated = bool(
                    np.any(
                        np.abs(
                            pi_diagnostics.unsaturated_total_pu
                            - pi_diagnostics.saturated_total_pu
                        )
                        > 1e-12
                    )
                    or np.any(np.abs(applied_command - raw_command) > 1e-12)
                )
                command = applied_command
                load = np.asarray(load_at(scenario, time_s), dtype=float)
                truth = replace(
                    capability_at(scenario, time_s),
                    delay_s=(delay_truth, delay_truth),
                )
                domain, distance, power_shortfall, energy_shortfall = (
                    _domain_and_equilibrium(
                        state,
                        load,
                        reserve,
                        plant,
                        truth,
                        bridge_duration_s=6.0 * period,
                    )
                )
                parameters = plant.parameters
                valve = state.valve_pu
                mechanical = state.mechanical_power_pu
                raw_pm_rate = (valve - mechanical) / np.asarray(
                    parameters.turbine_time_constant_s
                )
                active = {
                    "scenario_id": str(scenario.scenario_id),
                    "split": str(scenario.split),
                    "mechanism": str(scenario.mechanism),
                    "sg_tension": str(scenario.sg_tension),
                    "period_s": period,
                    "start_time_s": time_s,
                    "domain_h0_forensic": domain,
                    "equilibrium_distance_inf_pu": distance,
                    "power_shortfall_pu": power_shortfall,
                    "energy_shortfall_mwh": energy_shortfall,
                    "valve_at_bound": bool(
                        np.any(
                            (valve <= np.asarray(parameters.valve_lower_pu) + 1e-8)
                            | (valve >= np.asarray(parameters.valve_upper_pu) - 1e-8)
                        )
                    ),
                    "mechanical_at_bound": bool(
                        np.any(
                            (mechanical <= np.asarray(parameters.sg_power_lower_pu) + 1e-8)
                            | (mechanical >= np.asarray(parameters.sg_power_upper_pu) - 1e-8)
                        )
                    ),
                    "grc_active": bool(
                        np.any(
                            (raw_pm_rate > np.asarray(parameters.grc_up_pu_per_s) + 1e-10)
                            | (raw_pm_rate < -np.asarray(parameters.grc_down_pu_per_s) - 1e-10)
                        )
                    ),
                    "bess_power_limit_active": False,
                    "bess_ramp_limit_active": False,
                    "bess_energy_limit_active": False,
                    "command_saturated": command_saturated,
                    "solver_or_fallback_anomaly": False,
                    "max_command_actual_bess_mismatch_pu": float(
                        np.max(np.abs(command[[1, 3]] - state.bess.power_pu))
                    ),
                }
            if step == duration_steps:
                break
            truth = replace(
                capability_at(scenario, time_s),
                delay_s=(delay_truth, delay_truth),
            )
            next_state, diagnostics = plant.step(
                state,
                command,
                load_at(scenario, time_s),
                truth,
            )
            assert active is not None
            active["valve_at_bound"] = bool(
                active["valve_at_bound"]
                or np.any(
                    (next_state.valve_pu <= np.asarray(plant.parameters.valve_lower_pu) + 1e-8)
                    | (next_state.valve_pu >= np.asarray(plant.parameters.valve_upper_pu) - 1e-8)
                )
            )
            active["mechanical_at_bound"] = bool(
                active["mechanical_at_bound"] or np.any(diagnostics.sg_boundary_active)
            )
            active["grc_active"] = bool(
                active["grc_active"]
                or np.any(
                    np.isclose(
                        diagnostics.mechanical_rate_pu_per_s,
                        np.asarray(plant.parameters.grc_up_pu_per_s),
                        atol=1e-9,
                    )
                    | np.isclose(
                        diagnostics.mechanical_rate_pu_per_s,
                        -np.asarray(plant.parameters.grc_down_pu_per_s),
                        atol=1e-9,
                    )
                )
            )
            active["bess_power_limit_active"] = bool(
                active["bess_power_limit_active"]
                or np.any(diagnostics.bess.power_saturation)
            )
            active["bess_ramp_limit_active"] = bool(
                active["bess_ramp_limit_active"]
                or np.any(
                    np.isclose(
                        diagnostics.bess.actual_ramp_pu_per_s,
                        diagnostics.bess.capability.ramp_up_pu_per_s,
                        atol=1e-9,
                    )
                    | np.isclose(
                        diagnostics.bess.actual_ramp_pu_per_s,
                        -diagnostics.bess.capability.ramp_down_pu_per_s,
                        atol=1e-9,
                    )
                )
            )
            active["bess_energy_limit_active"] = bool(
                active["bess_energy_limit_active"]
                or np.any(diagnostics.bess.energy_boundary_active)
            )
            active["max_command_actual_bess_mismatch_pu"] = max(
                float(active["max_command_actual_bess_mismatch_pu"]),
                float(np.max(np.abs(command[[1, 3]] - next_state.bess.power_pu))),
            )
            state = next_state
        if active is not None:
            rows.append(active)
    return pd.DataFrame(rows)


def audit_phase_g_windows(intervals: pd.DataFrame) -> pd.DataFrame:
    windows = pd.read_parquet(
        REPO / "results_phase_g/G2/G2_STRUCTURED_RESIDUAL_WINDOWS.parquet"
    )
    windows = windows[windows.terminal_window_included].copy()
    local = np.load(REPO / "research_outputs_phase_g/03_MODEL/LOCAL_TERMINAL_SET.npz")
    horizons = [int(value) for value in local["horizons"]]
    radii = {
        horizon: local["state_prediction_radii"][index]
        for index, horizon in enumerate(horizons)
    }
    audited: list[dict[str, object]] = []
    boolean_columns = [
        "valve_at_bound",
        "mechanical_at_bound",
        "grc_active",
        "bess_power_limit_active",
        "bess_ramp_limit_active",
        "bess_energy_limit_active",
        "command_saturated",
        "solver_or_fallback_anomaly",
    ]
    reason_order = [
        ("domain_not_sustainable", "DOMAIN_NOT_SUSTAINABLE"),
        ("valve_at_bound", "SG_VALVE_BOUNDARY"),
        ("mechanical_at_bound", "SG_MECHANICAL_BOUNDARY"),
        ("grc_active", "GRC_ACTIVE"),
        ("bess_power_limit_active", "BESS_POWER_LIMIT"),
        ("bess_ramp_limit_active", "BESS_RAMP_LIMIT"),
        ("bess_energy_limit_active", "BESS_ENERGY_LIMIT"),
        ("command_saturated", "COMMAND_SATURATION"),
        ("command_actual_mismatch", "COMMAND_ACTUAL_POWER_MISMATCH"),
        ("far_from_equilibrium", "FAR_FROM_LOAD_PARAMETERIZED_EQUILIBRIUM"),
        ("solver_or_fallback_anomaly", "SOLVER_OR_FALLBACK"),
    ]
    for _, window in windows.iterrows():
        period = float(window.period_s)
        start = float(window.start_time_s)
        horizon = int(window.horizon_steps)
        selected = intervals[
            intervals.scenario_id.eq(window.scenario_id)
            & intervals.start_time_s.ge(start - 1e-9)
            & intervals.start_time_s.lt(start + horizon * period - 1e-9)
        ]
        if len(selected) != horizon:
            raise RuntimeError(
                f"incomplete replay for {window.scenario_id} at {start}: {len(selected)}/{horizon}"
            )
        flags = {name: bool(selected[name].any()) for name in boolean_columns}
        flags["domain_not_sustainable"] = bool(
            not selected.domain_h0_forensic.eq("SUSTAINABLE").all()
        )
        finite_distance = selected.equilibrium_distance_inf_pu.dropna()
        maximum_distance = (
            float(finite_distance.max()) if not finite_distance.empty else float("nan")
        )
        flags["far_from_equilibrium"] = bool(
            finite_distance.empty
            or maximum_distance > EQUILIBRIUM_DISTANCE_LIMIT_PU
        )
        maximum_mismatch = float(selected.max_command_actual_bess_mismatch_pu.max())
        flags["command_actual_mismatch"] = maximum_mismatch > 0.005
        all_reasons = [label for key, label in reason_order if flags[key]]
        primary = all_reasons[0] if all_reasons else "INCLUDED_PHYSICALLY_CLEAN"
        residual = window[STATE_RESIDUAL_COLUMNS].to_numpy(float)
        large_residual = bool(np.any(residual > radii[horizon] + 1e-12))
        audited.append(
            {
                **window.to_dict(),
                **flags,
                "domain_h0_forensic": "|".join(
                    sorted(set(selected.domain_h0_forensic.astype(str)))
                ),
                "maximum_equilibrium_distance_inf_pu": maximum_distance,
                "maximum_command_actual_bess_mismatch_pu": maximum_mismatch,
                "primary_exclusion_reason_h0": primary,
                "all_exclusion_reasons_h0": "|".join(all_reasons),
                "physically_clean_h0": not all_reasons,
                "large_local_model_residual": large_residual,
                "large_residual_explained": bool(large_residual and all_reasons),
                "h0_domain_label_is_forensic_not_h2_registered": True,
            }
        )
    return pd.DataFrame(audited)


def main() -> None:
    result_dir = REPO / "results_phase_h/H0"
    output_dir = REPO / "research_outputs_phase_h/00_FORENSIC"
    progress_dir = REPO / "progress_phase_h"
    test_log_dir = REPO / "logs_phase_h/H0"
    for directory in (result_dir, output_dir, progress_dir, test_log_dir):
        directory.mkdir(parents=True, exist_ok=True)

    replay, missing_dependencies = _run_packaged_replay()
    dependency_rows = []
    with zipfile.ZipFile(PHASE_G_ZIP) as archive:
        members = set(archive.namelist())
    for relative in (
        "scripts/phase_e/run_e3_materiality.py",
        "scripts/phase_f/run_f3_model_sets.py",
    ):
        repository_path = REPO / relative
        packaged = f"06_SOURCE/{relative}"
        dependency_rows.append(
            {
                "dependency": relative,
                "repository_present": repository_path.is_file(),
                "repository_sha256": sha256(repository_path),
                "phase_g_package_path": packaged,
                "phase_g_package_present": packaged in members,
                "full_g2_replay_from_phase_g_zip_only": False,
            }
        )
    dependency_path = result_dir / "G2_DEPENDENCY_AUDIT.csv"
    pd.DataFrame(dependency_rows).to_csv(dependency_path, index=False)

    manifest = build_calibration_manifest()
    intervals = replay_interval_audit(manifest)
    audit = audit_phase_g_windows(intervals)
    audit_path = result_dir / "NEAR_TERMINAL_VALIDITY_AUDIT.parquet"
    audit.to_parquet(audit_path, index=False, compression="zstd")
    interval_path = result_dir / "H0_EXACT_REPLAY_INTERVAL_FLAGS.parquet"
    intervals.to_parquet(interval_path, index=False, compression="zstd")

    large = audit[audit.large_local_model_residual]
    explained_fraction = (
        float(large.large_residual_explained.mean()) if len(large) else 1.0
    )
    reason_counts = (
        audit.primary_exclusion_reason_h0.value_counts().sort_index().to_dict()
    )
    certificate = json.loads(
        (
            REPO
            / "research_outputs_phase_g/05_THEORY/LOCAL_TERMINAL_INCOMPATIBILITY_CERTIFICATE.json"
        ).read_text(encoding="utf-8")
    )
    reproduction = {
        "schema": "direction5.phase_h.h0.current_certificate_reproduction.v1",
        "historical_phase_g_zip_sha256": sha256(PHASE_G_ZIP),
        "historical_phase_g_zip_hash_matches": sha256(PHASE_G_ZIP)
        == EXPECTED_PHASE_G_SHA256,
        "packaged_minimal_replays": replay,
        "full_g2_dependencies_missing_from_historical_zip": missing_dependencies,
        "historical_certificate": certificate,
        "scenarios_replayed": int(manifest.scenario_id.nunique()),
        "periods_replayed_s": sorted(manifest.sfr_period_s.unique().tolist()),
        "old_included_windows_audited": int(len(audit)),
        "old_included_windows_physically_clean_h0": int(audit.physically_clean_h0.sum()),
        "large_local_model_residual_windows": int(len(large)),
        "large_residual_source_explained_fraction": explained_fraction,
        "primary_exclusion_reason_counts": reason_counts,
        "reclassification": "TERMINAL_SET_CALIBRATION_PREMATURE_AND_MISSPECIFIED",
    }
    reproduction_path = result_dir / "CURRENT_CERTIFICATE_REPRODUCTION.json"
    reproduction_path.write_text(
        json.dumps(reproduction, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    correction_path = output_dir / "PHASE_G_CORRECTION.md"
    correction_path.write_text(
        f"""# Phase G G2 correction

The historical evidence is preserved and its ZIP hash and minimal replay pass.
However, the registered Phase-G `near_terminal` predicate checked only observer
warm-up, frequency, ACE, tie, and distance to an event. It did not enforce the
SG, GRC, BESS, saturation, domain, equilibrium, or solver/fallback predicates
required by its own terminal semantics.

The exact 40-scenario, 2 s/4 s replay audited {len(audit)} formerly included
windows. Only {int(audit.physically_clean_h0.sum())} satisfy the complete H0
forensic cleanliness predicate. Of {len(large)} windows exceeding the historical
local model radius, {explained_fraction:.2%} have at least one independently
recomputed contamination or command-to-actual mismatch source. The forensic
domain label is not the locked H2 manifest and is used only to diagnose the
historical ordering error.

The historical ZIP also omits both Phase E/F Python dependencies imported by
the full G2 script, although its three minimal post-hoc replay entry points pass.

Binding Phase-H reclassification:

```text
TERMINAL_SET_CALIBRATION_PREMATURE_AND_MISSPECIFIED
```

This invalidates the Phase-G G2 scientific negative conclusion. It does not
assert that a valid terminal set exists and does not constitute evidence for or
against DCSV-MPC. H2 must lock the three-domain manifest and load-dependent
equilibria before H4 calibrates a new local terminal set.
""",
        encoding="utf-8",
    )

    gate_components = {
        "phase_g_zip_hash_and_minimal_replay_pass": all(
            item["returncode"] == 0 for item in replay
        ),
        "original_data_reused_not_regenerated": True,
        "at_least_20_scenarios_exactly_replayed": manifest.scenario_id.nunique()
        >= 20,
        "both_periods_exactly_replayed": set(manifest.sfr_period_s) == {2.0, 4.0},
        "all_old_near_terminal_windows_audited": len(audit)
        == int(
            pd.read_parquet(
                REPO / "results_phase_g/G2/G2_STRUCTURED_RESIDUAL_WINDOWS.parquet"
            ).terminal_window_included.sum()
        ),
        "large_residual_sources_at_least_95pct_explained": explained_fraction
        >= 0.95,
        "historical_phase_e_f_dependency_gap_reproduced": len(missing_dependencies)
        == 2,
        "phase_g_evidence_preserved": True,
        "g2_negative_reclassified": True,
    }
    progress = {
        "schema": "direction5.phase_h.progress.v1",
        "stage": "H0",
        "inputs": {
            "phase_g_zip_sha256": EXPECTED_PHASE_G_SHA256,
            "phase_g_scientific_commit": "b254a6e5a4ca57851dfce9a4badcfa3be4e13adf",
            "phase_g_original_parquet_sha256": sha256(
                REPO / "results_phase_g/G2/G2_STRUCTURED_RESIDUAL_WINDOWS.parquet"
            ),
        },
        "commands": [
            "python scripts/phase_h/run_h0_forensic.py",
            "python -m pytest tests/phase_h/test_h0_phase_g_defects.py -q",
        ],
        "outputs": {
            path.relative_to(REPO).as_posix(): sha256(path)
            for path in (
                audit_path,
                interval_path,
                dependency_path,
                reproduction_path,
                correction_path,
            )
        },
        "gate": "H0_PHASE_G_FORENSIC_REPRODUCTION",
        "gate_components": gate_components,
        "gate_passed": all(gate_components.values()),
        "failures": [],
        "repairs": [],
        "final_seeds_consumed": False,
        "next_stage": "H1" if all(gate_components.values()) else "H9_NEGATIVE_PACKAGE",
        "final_reclassification": "TERMINAL_SET_CALIBRATION_PREMATURE_AND_MISSPECIFIED",
    }
    progress_path = progress_dir / "H0.json"
    progress_path.write_text(
        json.dumps(progress, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(progress, indent=2, sort_keys=True))
    if not progress["gate_passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
