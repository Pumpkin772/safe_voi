"""Guarded nonlinear Plant-A pilot for control-aligned sequential excitation."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from direction5freq.accr.resource_guard import (
    GIB,
    ResourceLimits,
    run_guarded,
    wait_for_memory_preflight,
)


ROOT = Path(__file__).resolve().parents[2]
SCRATCH = ROOT / "scratch_direction5_voi_boundary"
OUTPUT = ROOT / "research_outputs_direction5_safe_voi_positive_region_rebuild" / "R1_NONLINEAR_PILOT"
TARGET_OUTPUT = (
    ROOT
    / "research_outputs_direction5_safe_voi_positive_region_rebuild"
    / "R3_MEAN_REVERTING_DEVELOPMENT"
)
sys.path.insert(0, str(SCRATCH))


def output_directory(arguments: argparse.Namespace) -> Path:
    return TARGET_OUTPUT if arguments.target_distribution else OUTPUT


def worker(arguments: argparse.Namespace) -> None:
    if os.environ.get("DIRECTION5_RESOURCE_GUARDED") != "1":
        raise SystemExit("refusing unguarded nonlinear pilot")

    import numpy as np

    from direction5freq.voi_positive_region import (
        ControlAlignedConfig,
        ControlAlignedSequentialProbe,
        DynamicCapabilityCandidate,
        DynamicCapabilityEstimator,
        DynamicEvidenceConfig,
        StudySplit,
        generate_scenario,
        registered_continuation_load_bank,
    )
    import nonlinear_boundary_validation as nonlinear
    from rolling_boundary_controller import RollingBoundaryController
    from voi_boundary_engine import (
        BoundaryPoint,
        Probe,
        evaluate_acquisition_information_value,
        objective_scales,
        solve_policy,
    )

    target_scenario = (
        generate_scenario(StudySplit.DEVELOPMENT, arguments.seed)
        if arguments.target_distribution else None
    )
    period_s = 4.0 if target_scenario is None else target_scenario.period_s
    effective_active_steps = (
        arguments.active_steps
        if arguments.active_duration_s <= 0.0
        else int(round(arguments.active_duration_s / period_s))
    )
    effective_cooldown_steps = (
        arguments.cooldown_steps
        if arguments.cooldown_duration_s <= 0.0
        else int(round(arguments.cooldown_duration_s / period_s))
    )
    created_controllers = []

    class ControlAlignedController(RollingBoundaryController):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.aligned_probe = ControlAlignedSequentialProbe(ControlAlignedConfig(
                amplitude_pu=arguments.amplitude,
                second_window_amplitude_pu=(
                    None
                    if arguments.second_window_amplitude <= 0.0
                    else arguments.second_window_amplitude
                ),
                active_steps=effective_active_steps,
                cooldown_steps=effective_cooldown_steps,
                maximum_windows=arguments.maximum_windows,
                certificate_samples=arguments.certificate_samples,
                certificate_validity_s=arguments.certificate_validity,
                measurement_noise_std_pu=0.0015,
                observation_residual_bound_pu=arguments.poi_residual_bound,
            ))
            self.all_models = self.models
            self.dynamic_estimator = None
            if arguments.evidence_engine == "dynamic_vector":
                self.dynamic_estimator = DynamicCapabilityEstimator(
                    (
                        DynamicCapabilityCandidate(
                            model.model_id,
                            model.power_pu,
                            model.ramp_pu_per_s,
                            model.delay_s,
                        )
                        for model in self.all_models
                    ),
                    DynamicEvidenceConfig(
                        actuator_time_constant_s=(
                            self.parameters.bess.actuator_time_constant_s
                        ),
                        pfr_gain_pu_power_per_pu_frequency=(
                            self.parameters.bess.pfr_gain_pu_power_per_pu_frequency
                        ),
                        nominal_frequency_hz=self.parameters.nominal_frequency_hz,
                        measurement_noise_std_pu=0.0015,
                        ar1_correlation=arguments.poi_correlation,
                        deterministic_residual_bound_pu=(
                            arguments.dynamic_model_residual_bound
                        ),
                        maximum_windows=arguments.maximum_windows,
                        information_validity_s=arguments.certificate_validity,
                    ),
                )
            self.power_certificate_active = False
            self.power_certificate_time_s = None
            self.causal_value_evaluations = []
            self._gate_allow_new_window = True
            self._next_gate_evaluation_s = -float("inf")
            created_controllers.append(self)

        def _probe_start_eligible(self, contract, observation) -> bool:
            bess = np.asarray(contract)[[1, 3]]
            return bool(
                self.aligned_probe._remaining_active == 0
                # overlay() decrements a final cooldown count before deciding
                # whether a new window may start, so value must be refreshed
                # when the pre-overlay count is either zero or one.
                and self.aligned_probe._remaining_cooldown <= 1
                and self.aligned_probe.windows_started
                < self.aligned_probe.config.maximum_windows
                and not self.aligned_probe.futility_stopped
                and np.max(np.abs(bess))
                >= self.aligned_probe.config.binding_command_pu
                and np.max(np.abs(observation.frequency_deviation_hz))
                <= self.aligned_probe.config.maximum_frequency_hz
                and np.max(np.abs(observation.ace_pu))
                <= self.aligned_probe.config.maximum_ace_pu
                and np.all(
                    (observation.measured_soc >= 0.25)
                    & (observation.measured_soc <= 0.75)
                )
            )

        def _causal_high_posterior_value(
            self, observation, previous_applied_action
        ) -> dict:
            load = np.asarray(self.observer._load, dtype=float).copy()
            point = self._causal_point(observation, load)
            state = np.r_[
                observation.frequency_deviation_hz
                / self.parameters.nominal_frequency_hz,
                observation.tie_line_pu,
                observation.valve_pu,
                observation.sg_mechanical_power_pu,
            ]
            common = dict(
                horizon_steps=int(round(self.horizon_s / point.period_s)),
                initial_grid_state=state,
                initial_bess_power=observation.bess_actual_power_pu,
                previous_sg_command=previous_applied_action[[0, 2]],
                previous_bess_command=previous_applied_action[[1, 3]],
                initial_energy_mwh=(
                    observation.measured_soc * self.parameters.bess.energy_mwh
                ),
                load_forecast_pu=load,
                scales=objective_scales(point.objective),
            )
            contract_solution = self.last_solution
            assert contract_solution is not None
            high_models = tuple(
                model for model in self.all_models
                if model.power_pu > 0.045 + 1e-8
            )
            high_solution = solve_policy(point, high_models, **common)
            self.attempts += 1
            self.solve_times.append(high_solution.solve_time_s)
            finite = bool(
                np.isfinite(contract_solution.objective)
                and np.isfinite(high_solution.objective)
            )
            if not finite:
                self.failures += int(not np.isfinite(high_solution.objective))
            value = (
                float(contract_solution.objective - high_solution.objective)
                if finite else -float("inf")
            )
            action_separation = (
                float(np.max(np.abs(
                    contract_solution.bess_command[:, 0]
                    - high_solution.bess_command[:, 0]
                )))
                if finite else 0.0
            )
            return {
                "time_s": float(observation.time_s),
                "estimated_load_pu": load.tolist(),
                "public_grid_state": state.tolist(),
                "actual_bess_poi_power_pu": np.asarray(
                    observation.bess_actual_power_pu, dtype=float
                ).tolist(),
                "measured_soc": np.asarray(
                    observation.measured_soc, dtype=float
                ).tolist(),
                "previous_applied_action": np.asarray(
                    previous_applied_action, dtype=float
                ).tolist(),
                "contract_action": np.asarray((
                    contract_solution.sg_command[0, 0],
                    contract_solution.bess_command[0, 0],
                    contract_solution.sg_command[1, 0],
                    contract_solution.bess_command[1, 0],
                )).tolist(),
                "contract_set_cost": float(contract_solution.objective),
                "high_posterior_set_cost": float(high_solution.objective),
                "predicted_high_posterior_value": value,
                "first_bess_action_separation_pu": action_separation,
            }

        def _causal_acquisition_information_value(
            self, observation, previous_applied_action, contract_action
        ) -> dict:
            load = np.asarray(self.observer._load, dtype=float).copy()
            point = self._causal_point(observation, load)
            state = np.r_[
                observation.frequency_deviation_hz
                / self.parameters.nominal_frequency_hz,
                observation.tie_line_pu,
                observation.valve_pu,
                observation.sg_mechanical_power_pu,
            ]
            bess = np.asarray(contract_action, dtype=float)[[1, 3]]
            area = int(np.argmax(np.abs(bess)))
            direction = int(np.sign(bess[area]))
            if direction == 0:
                return {
                    "safe": True,
                    "reason": "ZERO_CONTRACT_DIRECTION",
                    "weakly_dominates_without_prior": False,
                    "solver_attempts": 0,
                    "solver_failures": 0,
                }
            active_sequence = tuple(
                direction * arguments.amplitude
                for _ in range(effective_active_steps)
            )
            recovery_s = (
                self.dynamic_estimator.config.post_action_response_s
                if self.dynamic_estimator is not None else 0.0
            )
            recovery_steps = int(np.ceil(recovery_s / point.period_s))
            sequence = active_sequence + tuple(0.0 for _ in range(recovery_steps))
            probe = Probe(
                probe_id="registered_control_aligned_surplus",
                duration_s=len(sequence) * point.period_s,
                amplitude_pu=arguments.amplitude,
                shape="surplus_plateau",
                area=area,
                sign=direction,
                sequence_pu=sequence,
                sg_compensation=False,
            )
            continuation_duration_s = max(
                0.0,
                min(
                    arguments.certificate_validity - probe.duration_s,
                    (
                        target_scenario.episode_duration_s
                        if target_scenario is not None else arguments.duration
                    ) - observation.time_s - probe.duration_s,
                ),
            )
            continuation_paths = registered_continuation_load_bank(
                current_time_s=observation.time_s + probe.duration_s,
                current_load_estimate_pu=load,
                period_s=point.period_s,
                duration_s=continuation_duration_s,
            )
            result = evaluate_acquisition_information_value(
                point,
                self.all_models,
                self.last_solution,
                probe,
                horizon_steps=int(round(self.horizon_s / point.period_s)),
                scales=objective_scales(point.objective),
                initial_grid_state=state,
                initial_bess_power=observation.bess_actual_power_pu,
                previous_sg_command=previous_applied_action[[0, 2]],
                previous_bess_command=previous_applied_action[[1, 3]],
                initial_energy_mwh=(
                    observation.measured_soc * self.parameters.bess.energy_mwh
                ),
                load_forecast_pu=load,
                continuation_load_paths_pu=continuation_paths,
                current_time_s=observation.time_s,
                load_observer=self.observer,
            )
            self.attempts += result.solver_attempts
            self.failures += result.solver_failures
            return {
                "safe": result.safe,
                "reason": result.reason,
                "probe_area": area,
                "probe_direction": direction,
                "probe_prefix_s": probe.duration_s,
                "low_branch_information_value": result.low_branch_value,
                "high_branch_information_value": result.high_branch_value,
                "break_even_high_probability": (
                    result.break_even_high_probability
                ),
                "weakly_dominates_without_prior": (
                    result.weakly_dominates_without_prior
                ),
                "branch_information_value": result.branch_value,
                "solver_attempts": result.solver_attempts,
                "solver_failures": result.solver_failures,
                "continuation_path_count": result.continuation_path_count,
                "continuation_steps": result.continuation_steps,
                "continuation_duration_s": (
                    result.continuation_steps * point.period_s
                ),
            }

        def _update_power_evidence(self, observation) -> None:
            if self.dynamic_estimator is None:
                newly_certified = self.aligned_probe.observe_delivery(
                    observation.time_s,
                    self.last_action[[1, 3]],
                    observation.bess_actual_power_pu,
                )
            else:
                newly_certified = self.dynamic_estimator.observe(
                    observation.time_s,
                    self.last_action[[1, 3]],
                    observation.bess_actual_power_pu,
                    observation.frequency_deviation_hz,
                )
                self.aligned_probe.power_certified_until_s = (
                    self.dynamic_estimator.power_certified_until_s
                )
                if (
                    self.dynamic_estimator.window_results
                    and not self.dynamic_estimator.high_capability_still_possible
                ):
                    self.aligned_probe.futility_stopped = True
            if newly_certified and self.power_certificate_time_s is None:
                self.power_certificate_time_s = float(observation.time_s)
            self.power_certificate_active = (
                self.aligned_probe.power_certified(observation.time_s)
                if self.dynamic_estimator is None
                else self.dynamic_estimator.power_certified(observation.time_s)
            )

        def observe_actual(self, observation) -> None:
            super().observe_actual(observation)
            if arguments.target_distribution and arguments.method == "dual":
                self._update_power_evidence(observation)

        def propose(self, observation):
            previous_applied_action = self.last_action.copy()
            if arguments.method == "dual":
                if not arguments.target_distribution:
                    self._update_power_evidence(observation)
                else:
                    self.power_certificate_active = (
                        self.aligned_probe.power_certified(observation.time_s)
                        if self.dynamic_estimator is None
                        else self.dynamic_estimator.power_certified(observation.time_s)
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
            if (
                arguments.minimum_predicted_high_value is not None
                and self._probe_start_eligible(contract, observation)
                and observation.time_s >= self._next_gate_evaluation_s
            ):
                value_record = self._causal_high_posterior_value(
                    observation, previous_applied_action
                )
                screen_positive = bool(
                    value_record["predicted_high_posterior_value"]
                    >= arguments.minimum_predicted_high_value
                )
                diagnostic_requested = bool(
                    arguments.offline_second_stage_time_s is not None
                    and abs(
                        float(observation.time_s)
                        - arguments.offline_second_stage_time_s
                    ) <= 0.5 * period_s
                )
                acquisition_record = None
                if (
                    (screen_positive or diagnostic_requested)
                    and arguments.acquisition_value_gate
                ):
                    acquisition_record = self._causal_acquisition_information_value(
                        observation, previous_applied_action, contract
                    )
                self._gate_allow_new_window = bool(
                    screen_positive
                    and arguments.offline_second_stage_time_s is None
                    and (
                        not arguments.acquisition_value_gate
                        or acquisition_record[
                            "weakly_dominates_without_prior"
                        ]
                    )
                )
                value_record["minimum_required_value"] = (
                    arguments.minimum_predicted_high_value
                )
                value_record["acquisition_value_gate_enabled"] = (
                    arguments.acquisition_value_gate
                )
                value_record["acquisition_information_value"] = (
                    acquisition_record
                )
                value_record["offline_second_stage_diagnostic"] = (
                    diagnostic_requested
                )
                value_record["probe_permitted"] = self._gate_allow_new_window
                self.causal_value_evaluations.append(value_record)
                self._next_gate_evaluation_s = (
                    float(observation.time_s) + effective_cooldown_steps * period_s
                )
            windows_before = self.aligned_probe.windows_started
            action = self.aligned_probe.overlay(
                contract,
                observation.time_s,
                observation.frequency_deviation_hz,
                observation.ace_pu,
                observation.measured_soc,
                allow_new_window=self._gate_allow_new_window,
            )
            self.probe_triggers += self.aligned_probe.windows_started - windows_before
            if action is not contract:
                self.probe_active_calls += 1
                self.probe_l1 += float(np.sum(np.abs(action - contract))) * self.template.period_s
            self.last_action = np.asarray(action, dtype=float)
            return self.last_action

    suffix_parts = []
    if arguments.run_label:
        suffix_parts.append(arguments.run_label.upper())
    if arguments.seed != 8100:
        suffix_parts.append(f"S{arguments.seed}")
    run_suffix = "_" + "_".join(suffix_parts) if suffix_parts else ""
    stage = "R3" if arguments.target_distribution else "R1"
    row = {
        "scenario_id": (
            f"{stage}_{arguments.capability.upper()}_{arguments.method.upper()}_"
            f"{arguments.objective.upper()}{run_suffix}"
            if arguments.method in {"contract", "oracle"}
            else (
                f"{stage}_{arguments.capability.upper()}_{arguments.method.upper()}_"
                f"A{arguments.amplitude:.4f}_W{arguments.maximum_windows}_"
                f"{arguments.evidence_label.upper()}_{arguments.objective.upper()}"
                f"{run_suffix}"
            )
        ),
        "design_cell": f"power_ramp_binding|{arguments.objective}",
        "known_ood": "known",
        "seed": arguments.seed,
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
    if arguments.target_distribution:
        assert target_scenario is not None
        scenario = target_scenario
        method_scenario_id = str(row["scenario_id"])
        row.update(scenario.evaluation_record())
        row.update(
            scenario_id=method_scenario_id,
            duration_s=scenario.episode_duration_s,
            capability_change_time_s=scenario.capability_transition_time_s,
            information_validity_horizon_s=arguments.certificate_validity,
            design_cell=f"registered_event_distribution|{arguments.objective}",
            # The paired binary development cell isolates usable power.  Ramp
            # and delay are identical across the two truth branches and remain
            # uncertain inside the ordinary controller.
            true_power_pu=0.045 if arguments.capability == "low" else 0.068,
            true_ramp_pu_per_s=0.039,
            true_delay_s=1.50,
            source_scenario_known_ood=scenario.known_ood,
            known_ood="known",
            frequency_noise_std_hz=0.001,
            poi_noise_std_pu=scenario.measurement_noise_std_pu,
            poi_observation_period_s=0.2,
            poi_noise_correlation=arguments.poi_correlation,
        )
    point = BoundaryPoint(
        f"{stage}_NONLINEAR_CONTROL_ALIGNED",
        float(row.get("period_s", 4.0)),
        "medium",
        float(row["load_magnitude_pu"]),
        0.023,
        0.014,
        1.30 if arguments.target_distribution else 0.0,
        0.0015 if arguments.target_distribution else float(row["poi_noise_std_pu"]),
        float(row["initial_soc"]),
        0.0,
        arguments.objective,
    )

    original = nonlinear.RollingBoundaryController
    try:
        if arguments.method not in {"contract", "oracle"}:
            nonlinear.RollingBoundaryController = ControlAlignedController
        simulation_method = (
            "perfect_capability_oracle"
            if arguments.method == "oracle" else "contract_mpc"
        )
        result = nonlinear.simulate_plant_a(
            row,
            simulation_method,
            point,
            dt_s=0.02,
        )
    finally:
        nonlinear.RollingBoundaryController = original
    result["method"] = arguments.method
    result["comparison_group"] = arguments.comparison_group
    result["candidate_delay_spread_s"] = point.delay_spread_s
    result["objective_preference"] = arguments.objective
    result["decision_relevance_screen_threshold"] = (
        arguments.minimum_predicted_high_value
    )
    result["acquisition_value_gate_enabled"] = (
        arguments.acquisition_value_gate
    )
    result["offline_second_stage_time_s"] = (
        arguments.offline_second_stage_time_s
    )
    result["probe_amplitude_pu"] = (
        0.0 if arguments.method in {"contract", "oracle"} else arguments.amplitude
    )
    result["second_window_amplitude_pu"] = (
        0.0
        if arguments.method in {"contract", "oracle"}
        else arguments.second_window_amplitude
    )
    result["maximum_probe_windows"] = (
        0 if arguments.method in {"contract", "oracle"} else arguments.maximum_windows
    )
    result["evidence_model"] = (
        "none" if arguments.method != "dual" else arguments.evidence_label
    )
    result["evidence_engine"] = (
        "none" if arguments.method != "dual" else arguments.evidence_engine
    )
    result["certificate_validity_s"] = (
        0.0 if arguments.method != "dual" else arguments.certificate_validity
    )
    result["probe_window_duration_s"] = (
        0.0
        if arguments.method in {"contract", "oracle"}
        else effective_active_steps * period_s
    )
    result["probe_cooldown_duration_s"] = (
        0.0
        if arguments.method in {"contract", "oracle"}
        else effective_cooldown_steps * period_s
    )
    if arguments.method not in {"contract", "oracle"} and created_controllers:
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
        result["futility_stopped"] = controller.aligned_probe.futility_stopped
        if controller.dynamic_estimator is not None:
            result["dynamic_retained_candidate_ids"] = (
                controller.dynamic_estimator.retained_candidate_ids
            )
            result["dynamic_model_inconsistent"] = (
                controller.dynamic_estimator.model_inconsistent
            )
            result["dynamic_windows"] = [
                {
                    "start_time_s": window.start_time_s,
                    "end_time_s": window.end_time_s,
                    "area": window.area,
                    "direction": window.direction,
                    "raw_samples": window.raw_samples,
                    "scored_samples": window.scored_samples,
                    "window_alpha": window.window_alpha,
                    "likelihood_radius": window.likelihood_radius,
                    "retained_candidate_ids": window.retained_candidate_ids,
                    "score_by_candidate": window.score_by_candidate,
                }
                for window in controller.dynamic_estimator.window_results
            ]
        result["causal_value_evaluations"] = controller.causal_value_evaluations
    output = output_directory(arguments)
    output.mkdir(parents=True, exist_ok=True)
    destination = output / f"{row['scenario_id']}.json"
    destination.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2, sort_keys=True))


def guarded(arguments: argparse.Namespace) -> None:
    output = output_directory(arguments)
    output.mkdir(parents=True, exist_ok=True)
    stage = "R3" if arguments.target_distribution else "R1"
    stem = (
        f"{stage}_{arguments.capability.upper()}_{arguments.method.upper()}_"
        f"{arguments.objective.upper()}"
        if arguments.method in {"contract", "oracle"}
        else (
            f"{stage}_{arguments.capability.upper()}_{arguments.method.upper()}_"
            f"A{arguments.amplitude:.4f}_W{arguments.maximum_windows}_"
            f"{arguments.evidence_label.upper()}_{arguments.objective.upper()}"
        )
    )
    if arguments.run_label:
        stem += f"_{arguments.run_label.upper()}"
    if arguments.seed != 8100:
        stem += f"_S{arguments.seed}"
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
        "--active-duration-s",
        str(arguments.active_duration_s),
        "--second-window-amplitude",
        str(arguments.second_window_amplitude),
        "--cooldown-steps",
        str(arguments.cooldown_steps),
        "--cooldown-duration-s",
        str(arguments.cooldown_duration_s),
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
        "--evidence-engine",
        arguments.evidence_engine,
        "--poi-correlation",
        str(arguments.poi_correlation),
        "--dynamic-model-residual-bound",
        str(arguments.dynamic_model_residual_bound),
        "--objective",
        arguments.objective,
        "--run-label",
        arguments.run_label,
        "--comparison-group",
        arguments.comparison_group,
        "--seed",
        str(arguments.seed),
    ]
    if arguments.minimum_predicted_high_value is not None:
        command.extend((
            "--minimum-predicted-high-value",
            str(arguments.minimum_predicted_high_value),
        ))
    if arguments.acquisition_value_gate:
        command.append("--acquisition-value-gate")
    if arguments.offline_second_stage_time_s is not None:
        command.extend((
            "--offline-second-stage-time-s",
            str(arguments.offline_second_stage_time_s),
        ))
    if arguments.target_distribution:
        command.append("--target-distribution")
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
        max_system_commit_growth_bytes=20 * GIB,
        min_available_physical_bytes=5 * GIB,
        max_tree_private_bytes=4 * GIB,
        max_descendant_processes=2,
        timeout_s=14400.0 if arguments.acquisition_value_gate else 7200.0,
        poll_interval_s=0.5,
        preflight_max_system_commit_fraction=0.85,
    )
    wait_for_memory_preflight(
        limits,
        log_path=output / f"{stem}_preflight.jsonl",
        timeout_s=120.0,
        poll_interval_s=5.0,
    )
    code = run_guarded(
        command,
        cwd=ROOT,
        environment=environment,
        limits=limits,
        monitor_log=output / f"{stem}_memory.jsonl",
        summary_path=output / f"{stem}_resource.json",
    )
    if code:
        raise SystemExit(code)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--worker", action="store_true")
    result.add_argument("--capability", choices=("low", "high"), required=True)
    result.add_argument(
        "--method", choices=("contract", "exploit_only", "dual", "oracle"),
        required=True,
    )
    result.add_argument("--duration", type=float, default=300.0)
    result.add_argument("--amplitude", type=float, default=0.003)
    result.add_argument("--active-steps", type=int, default=2)
    result.add_argument("--active-duration-s", type=float, default=0.0)
    result.add_argument("--second-window-amplitude", type=float, default=0.0)
    result.add_argument("--cooldown-steps", type=int, default=4)
    result.add_argument("--cooldown-duration-s", type=float, default=0.0)
    result.add_argument("--maximum-windows", type=int, default=2)
    result.add_argument("--poi-residual-bound", type=float, default=0.00025)
    result.add_argument("--certificate-samples", type=int, default=2)
    result.add_argument("--certificate-validity", type=float, default=120.0)
    result.add_argument("--minimum-predicted-high-value", type=float)
    result.add_argument("--acquisition-value-gate", action="store_true")
    result.add_argument("--offline-second-stage-time-s", type=float)
    result.add_argument("--evidence-label", default="stacked_ar1")
    result.add_argument(
        "--evidence-engine",
        choices=("mean_ar1", "dynamic_vector"),
        default="dynamic_vector",
    )
    result.add_argument("--poi-correlation", type=float, default=0.2)
    result.add_argument(
        "--dynamic-model-residual-bound", type=float, default=0.0005
    )
    result.add_argument(
        "--objective",
        choices=(
            "balanced", "regional_responsibility", "resource_economy",
            "grid_service", "sg_conserving_4", "sg_conserving_16",
            "sg_conserving_64",
        ),
        default="resource_economy",
    )
    result.add_argument("--run-label", default="")
    result.add_argument("--comparison-group", default="")
    result.add_argument("--seed", type=int, default=8100)
    result.add_argument("--target-distribution", action="store_true")
    return result


if __name__ == "__main__":
    args = parser().parse_args()
    worker(args) if args.worker else guarded(args)
