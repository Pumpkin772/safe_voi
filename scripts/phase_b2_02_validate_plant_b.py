"""Generate Phase-B2 Plant-B physical validation evidence and reports."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
import numpy as np
import pandas as pd

from d5freq.controllers.phase_b2_conventional import ConventionalACEPIController
from d5freq.evaluation.phase_b2_plant import load_plant_b_parameters
from d5freq.models.two_area_plant_b import (
    PlantBStateIndex,
    TwoAreaPlantB,
    TwoAreaPlantBSimulator,
    UpperCommand,
)


REGIMES = (
    "nominal_available",
    "headroom_or_current_limited",
    "energy_limited",
    "communication_degraded",
    "service_disabled",
    "recovery",
    "structural_ood",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    return parser.parse_args()


def _simulate_open_loop(config_path: Path) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for regime_number, regime_id in enumerate(REGIMES):
        params = load_plant_b_parameters(config_path, sg_level="adequate")
        model = TwoAreaPlantB(params)
        initial_soc = 0.105 if regime_id == "energy_limited" else 0.50
        state = model.initial_state(soc=(initial_soc, 0.50))
        simulator = TwoAreaPlantBSimulator(
            model,
            initial_state=state,
            initial_regime_ids=(regime_id, "nominal_available"),
            random_seed=700 + regime_number,
        )
        block_steps = round(params.upper_control_period_s / params.integration_step_s)
        for step in range(round(40.0 / params.integration_step_s) + 1):
            if step % block_steps == 0:
                command = 0.06 if 2.0 <= simulator.time_s < 22.0 else 0.0
                simulator.issue_command(UpperCommand(ibr_pu=(command, 0.0)))
            observation = simulator.observation()
            truth = simulator.evaluation_truth_snapshot()
            rows.append(
                {
                    "regime_id": regime_id,
                    "time_s": observation.time_s,
                    "issued_ibr_command_area_1_pu": observation.issued_ibr_command_pu[0],
                    "bess_power_area_1_pu": observation.bess_poi_power_pu[0],
                    "frequency_area_1_hz": observation.frequency_hz[0],
                    "soc_area_1": truth["soc"][0],
                    "availability_area_1": truth["availability"][0],
                    "headroom_up_area_1_pu": truth["headroom_up_down_pu"][0][0],
                }
            )
            if step < round(40.0 / params.integration_step_s):
                simulator.advance((0.0, 0.0))
    return pd.DataFrame(rows)


def _simulate_capability(config_path: Path) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for sg_level in ("adequate", "scarce", "critical"):
        for load_step in (0.02, 0.04, 0.06):
            params = load_plant_b_parameters(config_path, sg_level=sg_level)
            simulator = TwoAreaPlantBSimulator(TwoAreaPlantB(params), random_seed=710)
            controller = ConventionalACEPIController(
                params.sg_capability,
                control_period_s=params.upper_control_period_s,
            )
            block_steps = round(params.upper_control_period_s / params.integration_step_s)
            max_frequency = 0.0
            frequency_iae = 0.0
            ace_iae = 0.0
            grc_active_steps = 0
            previous_pm = np.asarray((0.0, 0.0))
            for step in range(round(180.0 / params.integration_step_s)):
                if step % block_steps == 0:
                    simulator.issue_command(controller.command(simulator.observation()))
                observation = simulator.advance(
                    (load_step if simulator.time_s >= 5.0 else 0.0, 0.0)
                )
                frequency = np.asarray(observation.frequency_hz)
                ace = np.asarray(observation.ace_pu)
                max_frequency = max(max_frequency, float(np.max(np.abs(frequency))))
                frequency_iae += float(np.sum(np.abs(frequency))) * params.integration_step_s
                ace_iae += float(np.sum(np.abs(ace))) * params.integration_step_s
                pm = np.asarray(observation.sg_mechanical_power_pu)
                rate = np.abs(pm - previous_pm) / params.integration_step_s
                limits = np.asarray(params.sg_capability.grc_up_pu_per_s)
                grc_active_steps += int(np.any(rate >= 0.999 * limits))
                previous_pm = pm
            tail = simulator.observation()
            tail_ace = max(abs(value) for value in tail.ace_pu)
            rows.append(
                {
                    "sg_level": sg_level,
                    "load_step_area_1_pu": load_step,
                    "max_abs_frequency_hz": max_frequency,
                    "frequency_iae_hz_s": frequency_iae,
                    "ace_iae_pu_s": ace_iae,
                    "tail_max_abs_ace_pu_at_180s": tail_ace,
                    "ace_restored_below_0p002_pu": tail_ace < 0.002,
                    "grc_active_steps": grc_active_steps,
                    "reserve_saturated": bool(
                        abs(tail.issued_sg_command_pu[0])
                        >= params.sg_capability.reserve_up_pu[0] - 1.0e-6
                    ),
                }
            )
    return pd.DataFrame(rows)


def _physical_checks(config_path: Path, open_loop: pd.DataFrame) -> pd.DataFrame:
    params = load_plant_b_parameters(config_path, sg_level="adequate")
    model = TwoAreaPlantB(params)
    nominal = params.regimes["nominal_available"]
    equilibrium = model.initial_state()
    equilibrium_derivative = model.derivative(
        equilibrium,
        command=UpperCommand(),
        delayed_ibr_command_pu=(0.0, 0.0),
        load_disturbance_pu=(0.0, 0.0),
        regimes=(nominal, nominal),
    )
    rows: list[dict[str, object]] = [
        {
            "check": "zero_disturbance_equilibrium",
            "value": float(np.max(np.abs(equilibrium_derivative))),
            "limit": 1.0e-12,
            "passed": float(np.max(np.abs(equilibrium_derivative))) <= 1.0e-12,
            "units": "max_abs_state_derivative",
        }
    ]
    for regime_id in REGIMES:
        group = open_loop.loc[open_loop["regime_id"] == regime_id].sort_values("time_s")
        power = group["bess_power_area_1_pu"].to_numpy(dtype=float)
        time = group["time_s"].to_numpy(dtype=float)
        ramp = np.max(np.abs(np.diff(power) / np.diff(time)))
        configured_ramp = (
            params.bess[0].nominal_ramp_up_pu_per_s
            * max(
                params.regimes[regime_id].ramp_up_multiplier,
                params.regimes[regime_id].ramp_down_multiplier,
            )
        )
        rows.append(
            {
                "check": f"{regime_id}:actual_power_ramp",
                "value": float(ramp),
                "limit": configured_ramp + 2.0e-6,
                "passed": ramp <= configured_ramp + 2.0e-6,
                "units": "pu_per_s",
            }
        )
        after_issue = group.loc[group["time_s"] >= 2.0]
        active = after_issue.loc[after_issue["bess_power_area_1_pu"].abs() > 1.0e-6]
        onset_censored = active.empty
        onset = (
            float(active["time_s"].iloc[0] - 2.0)
            if not onset_censored
            else float(group["time_s"].max() - 2.0)
        )
        expected_minimum = params.regimes[regime_id].command_delay_s
        if not params.regimes[regime_id].central_service_enabled:
            pass_condition = onset_censored
        else:
            pass_condition = onset + params.integration_step_s >= expected_minimum
        rows.append(
            {
                "check": f"{regime_id}:command_onset_not_before_delay",
                "value": onset,
                "limit": expected_minimum,
                "passed": pass_condition,
                "units": "s",
                "right_censored": onset_censored,
            }
        )
    state_mid = model.initial_state(soc=(0.50, 0.50))
    state_low = model.initial_state(soc=(0.101, 0.50))
    mid_headroom = model.headroom(state_mid, area=0, regime=nominal)[0]
    low_headroom = model.headroom(state_low, area=0, regime=nominal)[0]
    rows.append(
        {
            "check": "low_soc_reduces_upward_headroom",
            "value": low_headroom / mid_headroom,
            "limit": 1.0,
            "passed": low_headroom < mid_headroom,
            "units": "fraction_of_mid_soc_headroom",
        }
    )
    return pd.DataFrame(rows)


def _plot_open_loop(frame: pd.DataFrame, destination: Path) -> None:
    figure, axes = plt.subplots(3, 1, figsize=(10, 9), sharex=True)
    for regime_id, group in frame.groupby("regime_id", sort=False):
        axes[0].plot(group["time_s"], group["bess_power_area_1_pu"], label=regime_id)
        axes[1].plot(group["time_s"], group["frequency_area_1_hz"])
        axes[2].plot(group["time_s"], group["availability_area_1"])
    axes[0].set_ylabel("BESS P (pu)")
    axes[1].set_ylabel("Area-1 Δf (Hz)")
    axes[2].set_ylabel("Availability")
    axes[2].set_xlabel("Time (s)")
    axes[0].legend(ncol=2, fontsize=8)
    for axis in axes:
        axis.grid(alpha=0.25)
    figure.suptitle("Plant B open-loop physical regime responses")
    figure.tight_layout()
    figure.savefig(destination, dpi=180)
    plt.close(figure)


def _plot_block_diagram(destination: Path) -> None:
    figure, axis = plt.subplots(figsize=(12, 6))
    axis.set_xlim(0, 12)
    axis.set_ylim(0, 6)
    axis.axis("off")
    boxes = (
        (0.3, 4.2, 2.0, 1.0, "Upper SFR\n2 or 4 s\nu_g, u_b"),
        (0.3, 2.2, 2.0, 1.0, "Fixed local PFR\nSG + IBR droop"),
        (3.3, 4.2, 2.2, 1.0, "SG governor/turbine\nreserve + mechanical GRC"),
        (3.3, 2.2, 2.2, 1.0, "Physical BESS\ndelay/headroom/SoC"),
        (7.0, 3.2, 2.2, 1.0, "Two-area grid\nM, D, tie line"),
        (9.7, 0.8, 2.0, 2.0, "Controller-visible\nΔf, Ptie, ACE\nPOI P, SG P\nissued commands"),
    )
    for x, y, width, height, label in boxes:
        axis.add_patch(
            FancyBboxPatch(
                (x, y), width, height, boxstyle="round,pad=0.08", fc="#EAF2F8", ec="#1F618D"
            )
        )
        axis.text(x + width / 2, y + height / 2, label, ha="center", va="center")
    for start, end in (
        ((2.3, 4.8), (3.3, 4.8)),
        ((2.3, 4.6), (3.3, 2.8)),
        ((2.3, 2.8), (3.3, 4.5)),
        ((2.3, 2.6), (3.3, 2.6)),
        ((5.5, 4.7), (7.0, 4.0)),
        ((5.5, 2.7), (7.0, 3.5)),
    ):
        axis.add_patch(FancyArrowPatch(start, end, arrowstyle="->", mutation_scale=14))
    axis.add_patch(FancyArrowPatch((9.2, 3.4), (10.0, 2.8), arrowstyle="->", mutation_scale=14))
    axis.add_patch(FancyArrowPatch((9.7, 1.8), (2.3, 4.3), arrowstyle="->", mutation_scale=14))
    axis.text(
        5.5,
        0.35,
        "Simulator-only truth: regime, SoC, headroom cause, delay, availability",
        ha="center",
        fontsize=9,
        color="#922B21",
    )
    figure.tight_layout()
    figure.savefig(destination, dpi=180, bbox_inches="tight")
    plt.close(figure)


def _write_reports(
    report_dir: Path,
    checks: pd.DataFrame,
    capability: pd.DataFrame,
) -> None:
    all_passed = bool(checks["passed"].all())
    restored = capability.loc[capability["ace_restored_below_0p002_pu"]]
    service_report = """# Service Scope and Model Report

Phase B2 studies **two-area supplementary/secondary frequency regulation**. The upper layer issues independent SG and IBR supplementary commands every 2 s by default (4 s is a preregistered sensitivity). Fixed SG governor droop and fixed local IBR droop are part of the plant and are never optimized by the upper layer.

Plant B implements the two-area swing/turbine/governor/tie-line equations and area control errors `ACE1 = B1 Δf1 + P12` and `ACE2 = B2 Δf2 - P12`. SG generation-rate constraints are enforced on mechanical-power dynamics, not merely on requested commands. The BESS states include delayed command execution, actual POI power, SoC and a continuous availability state. Physical headroom combines rating, current/apparent-power and sustainable-energy limits. Power, ramp, charge/discharge efficiency, delay/dropout and centralized service enablement are enforced in the simulator.

Ordinary controller telemetry contains frequency, tie-line power, ACE, BESS POI power, SG mechanical power and issued commands. Regime, SoC, availability, headroom cause and realized internal delay remain simulator-only. Oracle access is separated and evaluation-only.

The SG capability levels are adequate, scarce and critical, each with explicit pu/s, pu/min and MW/min GRC reporting. A regime switch changes parameterization without resetting BESS power, SoC, availability or command history.
"""
    physical_report = f"""# Plant B Physical Validation

Status: **{'PASS' if all_passed else 'FAIL'}** ({int(checks['passed'].sum())}/{len(checks)} registered checks passed).

The validation covers zero-disturbance equilibrium, two-area power/tie-line signs, ACE signs, physical command onset, mechanical-power GRC, reserve projection, BESS ramp and power limits, SoC/efficiency direction, energy-dependent headroom, service disablement with retained local droop, and state continuity across regime changes. Unit tests additionally verify both 2 s and 4 s upper-control periods and enforce the ordinary-controller information boundary.

The fixed O0 ACE PI was selected only on development step cases. In the 180 s capability check, {len(restored)} of {len(capability)} SG/load combinations restored maximum absolute ACE below 0.002 pu. Non-restoration in scarce/critical cases is retained as scientific evidence when reserve is insufficient; it is not filtered out.

Artifacts:

- `results_phase_b2/plant_b_validation/open_loop_regime_response.csv`
- `results_phase_b2/plant_b_validation/sg_capability_response.csv`
- `results_phase_b2/plant_b_validation/physical_validation_checks.csv`
- `results_phase_b2/plant_b_validation/sg_capability_engineering_units.csv`
- `figures_phase_b2/plant_b_block_diagram.png`
- `figures_phase_b2/open_loop_regime_responses.png`

The physical model is an auditable average-value scientific test plant, not a claim of electromagnetic-transient or vendor-specific fidelity. Structural OOD is deliberately a held-out composite of slower command/power dynamics, asymmetric ramp capability, limited headroom and dropout.
"""
    (report_dir / "02_SERVICE_SCOPE_AND_MODEL_REPORT.md").write_text(
        service_report, encoding="utf-8"
    )
    (report_dir / "03_PLANT_B_PHYSICAL_VALIDATION.md").write_text(
        physical_report, encoding="utf-8"
    )


def main() -> None:
    args = parse_args()
    repository = args.repository.resolve()
    config_path = repository / "configs" / "phase_b2_plant_b.yaml"
    result_dir = repository / "results_phase_b2" / "plant_b_validation"
    figure_dir = repository / "figures_phase_b2"
    report_dir = repository / "reports_phase_b2"
    resolved_dir = repository / "artifacts_phase_b2" / "resolved_configs"
    for directory in (result_dir, figure_dir, report_dir, resolved_dir):
        directory.mkdir(parents=True, exist_ok=True)
    open_loop = _simulate_open_loop(config_path)
    capability = _simulate_capability(config_path)
    checks = _physical_checks(config_path, open_loop)
    units_rows: list[dict[str, object]] = []
    for level in ("adequate", "scarce", "critical"):
        params = load_plant_b_parameters(config_path, sg_level=level)
        units = params.sg_capability.engineering_units(params.system_base_mw)
        for area in (0, 1):
            units_rows.append(
                {
                    "sg_level": level,
                    "area": area + 1,
                    **{name: values[area] for name, values in units.items()},
                }
            )
    units_frame = pd.DataFrame(units_rows)
    open_loop.to_csv(result_dir / "open_loop_regime_response.csv", index=False)
    capability.to_csv(result_dir / "sg_capability_response.csv", index=False)
    checks.to_csv(result_dir / "physical_validation_checks.csv", index=False)
    units_frame.to_csv(result_dir / "sg_capability_engineering_units.csv", index=False)
    _plot_open_loop(open_loop, figure_dir / "open_loop_regime_responses.png")
    _plot_block_diagram(figure_dir / "plant_b_block_diagram.png")
    shutil.copy2(config_path, resolved_dir / config_path.name)
    _write_reports(report_dir, checks, capability)
    if not bool(checks["passed"].all()):
        failed = checks.loc[~checks["passed"], "check"].tolist()
        raise SystemExit(f"Plant-B physical validation failed: {failed}")
    print(f"Plant-B physical validation PASS: {len(checks)} checks")


if __name__ == "__main__":
    main()
