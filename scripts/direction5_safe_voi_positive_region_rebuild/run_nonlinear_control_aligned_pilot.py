"""Guarded nonlinear Plant-A pilot for control-aligned sequential excitation."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

import numpy as np

from direction5freq.accr.resource_guard import (
    GIB,
    ResourceLimits,
    run_guarded,
    wait_for_memory_preflight,
)
from direction5freq.voi_positive_region import (
    ControlAlignedConfig,
    ControlAlignedSequentialProbe,
)


ROOT = Path(__file__).resolve().parents[2]
SCRATCH = ROOT / "scratch_direction5_voi_boundary"
OUTPUT = ROOT / "research_outputs_direction5_safe_voi_positive_region_rebuild" / "R1_NONLINEAR_PILOT"
sys.path.insert(0, str(SCRATCH))


def worker(arguments: argparse.Namespace) -> None:
    if os.environ.get("DIRECTION5_RESOURCE_GUARDED") != "1":
        raise SystemExit("refusing unguarded nonlinear pilot")

    import nonlinear_boundary_validation as nonlinear
    from rolling_boundary_controller import RollingBoundaryController
    from voi_boundary_engine import BoundaryPoint

    created_controllers = []

    class ControlAlignedController(RollingBoundaryController):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.aligned_probe = ControlAlignedSequentialProbe(ControlAlignedConfig(
                amplitude_pu=arguments.amplitude,
                active_steps=arguments.active_steps,
                cooldown_steps=arguments.cooldown_steps,
                maximum_windows=arguments.maximum_windows,
                certificate_samples=arguments.certificate_samples,
                certificate_validity_s=arguments.certificate_validity,
                observation_residual_bound_pu=arguments.poi_residual_bound,
            ))
            self.all_models = self.models
            self.power_certificate_active = False
            self.power_certificate_time_s = None
            created_controllers.append(self)

        def propose(self, observation):
            if arguments.method == "dual":
                newly_certified = self.aligned_probe.observe_delivery(
                    observation.time_s,
                    self.last_action[[1, 3]],
                    observation.bess_actual_power_pu,
                )
                if newly_certified and self.power_certificate_time_s is None:
                    self.power_certificate_time_s = float(observation.time_s)
                self.power_certificate_active = self.aligned_probe.power_certified(
                    observation.time_s
                )
            self.models = (
                tuple(
                    model for model in self.all_models
                    if model.power_pu > 0.045 + 1e-8
                )
                if self.power_certificate_active else self.all_models
            )
            contract = super().propose(observation)
            if arguments.method == "dual" and self.power_certificate_active:
                return contract
            windows_before = self.aligned_probe.windows_started
            action = self.aligned_probe.overlay(
                contract,
                observation.time_s,
                observation.frequency_deviation_hz,
                observation.ace_pu,
                observation.measured_soc,
            )
            self.probe_triggers += self.aligned_probe.windows_started - windows_before
            if action is not contract:
                self.probe_active_calls += 1
                self.probe_l1 += float(np.sum(np.abs(action - contract))) * self.template.period_s
            self.last_action = np.asarray(action, dtype=float)
            return self.last_action

    point = BoundaryPoint(
        "R1_NONLINEAR_CONTROL_ALIGNED",
        4.0,
        "medium",
        0.070,
        0.023,
        0.014,
        0.0,
        0.0010,
        0.50,
        0.0,
        arguments.objective,
    )
    row = {
        "scenario_id": (
            f"R1_{arguments.capability.upper()}_{arguments.method.upper()}_"
            f"{arguments.objective.upper()}"
            if arguments.method == "contract"
            else (
                f"R1_{arguments.capability.upper()}_{arguments.method.upper()}_"
                f"A{arguments.amplitude:.4f}_W{arguments.maximum_windows}_"
                f"{arguments.evidence_label.upper()}_{arguments.objective.upper()}"
            )
        ),
        "design_cell": f"power_ramp_binding|{arguments.objective}",
        "known_ood": "known",
        "seed": 8100,
        "duration_s": arguments.duration,
        "initial_soc": 0.50,
        "capability_change_time_s": 90.0,
        "load_event_time_s": 120.0,
        "load_magnitude_pu": 0.070,
        "load_sign": 1.0,
        "load_area": "both",
        "true_power_pu": 0.045 if arguments.capability == "low" else 0.068,
        "true_ramp_pu_per_s": 0.025 if arguments.capability == "low" else 0.039,
        "true_delay_s": 1.50,
        "frequency_noise_std_hz": 0.001,
        "poi_noise_std_pu": 0.001,
    }

    original = nonlinear.RollingBoundaryController
    try:
        if arguments.method != "contract":
            nonlinear.RollingBoundaryController = ControlAlignedController
        result = nonlinear.simulate_plant_a(
            row,
            "contract_mpc",
            point,
            dt_s=0.02,
        )
    finally:
        nonlinear.RollingBoundaryController = original
    result["method"] = arguments.method
    if arguments.method != "contract" and created_controllers:
        controller = created_controllers[0]
        result["power_certified"] = controller.power_certificate_time_s is not None
        result["power_certificate_active_at_end"] = controller.power_certificate_active
        result["power_certificate_time_s"] = controller.power_certificate_time_s
        result["probe_windows_started"] = controller.aligned_probe.windows_started
        result["evidence_started_at_s"] = controller.aligned_probe.evidence_started_at_s
        result["power_certified_until_s"] = (
            controller.aligned_probe.power_certified_until_s
            if np.isfinite(controller.aligned_probe.power_certified_until_s)
            else None
        )
        result["signed_delivery_evidence_pu"] = controller.aligned_probe.signed_delivery_samples
    OUTPUT.mkdir(parents=True, exist_ok=True)
    destination = OUTPUT / f"{row['scenario_id']}.json"
    destination.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2, sort_keys=True))


def guarded(arguments: argparse.Namespace) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    stem = (
        f"R1_{arguments.capability.upper()}_{arguments.method.upper()}_"
        f"{arguments.objective.upper()}"
        if arguments.method == "contract"
        else (
            f"R1_{arguments.capability.upper()}_{arguments.method.upper()}_"
            f"A{arguments.amplitude:.4f}_W{arguments.maximum_windows}_"
            f"{arguments.evidence_label.upper()}_{arguments.objective.upper()}"
        )
    )
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--capability",
        arguments.capability,
        "--method",
        arguments.method,
        "--duration",
        str(arguments.duration),
        "--amplitude",
        str(arguments.amplitude),
        "--active-steps",
        str(arguments.active_steps),
        "--cooldown-steps",
        str(arguments.cooldown_steps),
        "--maximum-windows",
        str(arguments.maximum_windows),
        "--poi-residual-bound",
        str(arguments.poi_residual_bound),
        "--certificate-samples",
        str(arguments.certificate_samples),
        "--certificate-validity",
        str(arguments.certificate_validity),
        "--evidence-label",
        arguments.evidence_label,
        "--objective",
        arguments.objective,
    ]
    environment = dict(os.environ)
    environment.update(
        DIRECTION5_RESOURCE_GUARDED="1",
        OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
        NUMEXPR_NUM_THREADS="1",
    )
    limits = ResourceLimits(
        max_system_commit_fraction=0.92,
        max_system_commit_growth_bytes=10 * GIB,
        min_available_physical_bytes=5 * GIB,
        max_tree_private_bytes=4 * GIB,
        max_descendant_processes=2,
        timeout_s=7200.0,
        poll_interval_s=0.5,
        preflight_max_system_commit_fraction=0.85,
    )
    wait_for_memory_preflight(
        limits,
        log_path=OUTPUT / f"{stem}_preflight.jsonl",
        timeout_s=1800.0,
        poll_interval_s=5.0,
    )
    code = run_guarded(
        command,
        cwd=ROOT,
        environment=environment,
        limits=limits,
        monitor_log=OUTPUT / f"{stem}_memory.jsonl",
        summary_path=OUTPUT / f"{stem}_resource.json",
    )
    if code:
        raise SystemExit(code)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--worker", action="store_true")
    result.add_argument("--capability", choices=("low", "high"), required=True)
    result.add_argument("--method", choices=("contract", "exploit_only", "dual"), required=True)
    result.add_argument("--duration", type=float, default=300.0)
    result.add_argument("--amplitude", type=float, default=0.003)
    result.add_argument("--active-steps", type=int, default=2)
    result.add_argument("--cooldown-steps", type=int, default=4)
    result.add_argument("--maximum-windows", type=int, default=10)
    result.add_argument("--poi-residual-bound", type=float, default=0.00025)
    result.add_argument("--certificate-samples", type=int, default=2)
    result.add_argument("--certificate-validity", type=float, default=120.0)
    result.add_argument("--evidence-label", default="stacked_ar1")
    result.add_argument(
        "--objective",
        choices=("balanced", "regional_responsibility", "resource_economy"),
        default="resource_economy",
    )
    return result


if __name__ == "__main__":
    args = parser().parse_args()
    worker(args) if args.worker else guarded(args)
