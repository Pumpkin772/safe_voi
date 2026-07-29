"""Resumable Phase-B1 closed-loop experiment construction and execution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np

from d5freq.controllers.final_arx_mpc import FixedReferenceSelectionArtifact
from d5freq.evaluation.baselines.oracle import OracleARXArtifact
from d5freq.evaluation.closed_loop_runner import (
    EpisodeRunnerConfig,
    EvaluationContribution,
    oracle_action_from_truth,
    run_closed_loop_episode,
    scenario_truth_provider,
)
from d5freq.evaluation.closed_loop_scenarios import load_experiment_protocol
from d5freq.evaluation.controller_factories import (
    FinalControllerFactory,
    LibraryArtifactBinding,
    SDBMPCVariantConfig,
    SolverExecutionTier,
)
from d5freq.evaluation.exact_nonlinear_oracle import (
    ExactNonlinearOracleController,
    ExactOracleBounds,
    ExactOracleContext,
    ExactOraclePlannerConfig,
    ExactOracleWeights,
    exact_oracle_action_from_truth,
)
from d5freq.evaluation.experiment_store import PerRunExperimentStore, RunIdentity
from d5freq.evaluation.phase6_experiments import (
    load_component_mapping_eval_only,
    load_simulator_private_modes_eval_only,
    responsibility_event_time_eval_only,
)
from d5freq.evaluation.phase_b1_counterfactuals import (
    COUNTERFACTUAL_FACTORS,
    build_phase_b1_counterfactual,
)
from d5freq.evaluation.phase_b1_audits import (
    constraint_activation_episode_rows,
    exact_vs_arx_episode_rows,
    passive_identifiability_episode_rows,
)
from d5freq.evaluation.phase_b1_protocol import (
    ALL_METHODS,
    PhaseB1Paths,
    SG_LEVELS,
    build_phase_b1_metric_config,
    ensure_protocol_lock,
    ensure_resolved_base_configs,
    load_sg_capabilities,
    protocol_lock_sha256,
    seeds_for,
    stable_phase_b1_run_id,
)
from d5freq.simulation.hybrid_simulator import HiddenModeFrequencySimulator
from d5freq.identification.model_library import ModeLibrary
from d5freq.utils.config import config_sha256, load_yaml
from d5freq.utils.hashing import sha256_file, sha256_json


PHASE_B1_RUN_PROVENANCE_SCHEMA = "d5freq.phase_b1.run_provenance.v1"
_FACTORY_CACHE: dict[tuple[str, str, str, str], FinalControllerFactory] = {}


@dataclass(frozen=True, slots=True)
class PhaseB1RunSpec:
    stage: str
    scenario_id: str
    method_id: str
    seed: int
    sg_level: str
    solver_tier: str
    oracle_candidate_id: str | None
    oracle_horizon_s: float | None
    repo_root: Path

    def __post_init__(self) -> None:
        if self.stage not in {"smoke", "validation", "final"}:
            raise ValueError("stage must be smoke, validation, or final")
        if self.method_id not in ALL_METHODS and not self.method_id.startswith("B5_"):
            raise ValueError("unknown Phase-B1 method")
        if self.sg_level not in SG_LEVELS:
            raise ValueError("sg_level must be A, B, or C")
        if self.solver_tier not in {"DEBUG", "FINAL"}:
            raise ValueError("solver_tier must be DEBUG or FINAL")
        if self.stage == "final" and self.solver_tier != "FINAL":
            raise ValueError("final runs require the FINAL solver tier")
        is_b5 = self.method_id == "B5" or self.method_id.startswith("B5_")
        if is_b5 != (self.oracle_candidate_id is not None):
            raise ValueError("only B5 run specs carry an Oracle candidate")
        if is_b5 and self.oracle_horizon_s not in {2.0, 4.0, 6.0}:
            raise ValueError("B5 horizon must be one preregistered candidate")
        object.__setattr__(self, "repo_root", Path(self.repo_root).resolve())

    @property
    def identity(self) -> RunIdentity:
        return RunIdentity(
            run_id=stable_phase_b1_run_id(
                stage=self.stage,  # type: ignore[arg-type]
                scenario_id=self.scenario_id,
                method_id=self.method_id,
                seed=self.seed,
                sg_level=self.sg_level,
            ),
            scenario_id=self.scenario_id,
            method=self.method_id,
            seed=self.seed,
        )


@dataclass(frozen=True, slots=True)
class PhaseB1RunReceipt:
    run_id: str
    envelope_sha256: str
    resumed: bool
    scientific_success: bool
    failure_stage: str | None
    wall_time_s: float | None


def _oracle_candidates(paths: PhaseB1Paths) -> Mapping[str, Mapping[str, Any]]:
    payload = load_yaml(paths.oracle_config)
    rows = payload.get("validation_candidates")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        raise TypeError("Oracle validation_candidates must be a sequence")
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError("Oracle candidate must be a mapping")
        candidate_id = str(row.get("candidate_id"))
        if candidate_id in result:
            raise ValueError("duplicate Oracle candidate ID")
        result[candidate_id] = MappingProxyType(dict(row))
    if set(result) != {"H2", "H4", "H6"}:
        raise ValueError("Oracle candidate IDs must be exactly H2/H4/H6")
    return MappingProxyType(result)


def oracle_planner_config(paths: PhaseB1Paths, candidate_id: str) -> ExactOraclePlannerConfig:
    payload = load_yaml(paths.oracle_config)
    planner = payload.get("planner")
    if not isinstance(planner, Mapping):
        raise TypeError("Oracle config lacks planner mapping")
    idle = planner.get("idle_equilibrium_gate")
    if not isinstance(idle, Mapping):
        raise TypeError("Oracle config lacks idle_equilibrium_gate")
    row = _oracle_candidates(paths)[candidate_id]
    return ExactOraclePlannerConfig(
        horizon_s=float(row["horizon_s"]),
        integration_step_s=float(planner["integration_step_s"]),
        sg_normalized_ramp_offsets=tuple(
            float(value)
            for value in planner["candidate_first_action_grid"][
                "sg_normalized_ramp_offsets"
            ]
        ),
        ibr_normalized_ramp_offsets=tuple(
            float(value)
            for value in planner["candidate_first_action_grid"][
                "ibr_normalized_ramp_offsets"
            ]
        ),
        terminal_cost_multiplier=float(row["terminal_cost_multiplier"]),
        idle_frequency_threshold_hz=float(idle["frequency_abs_max_hz"]),
        idle_power_imbalance_threshold_pu=float(
            idle["estimated_power_imbalance_abs_max_pu"]
        ),
    )


def oracle_weights(paths: PhaseB1Paths) -> ExactOracleWeights:
    payload = load_yaml(paths.oracle_config)
    cost = payload.get("cost")
    planner = payload.get("planner")
    if not isinstance(cost, Mapping) or not isinstance(planner, Mapping):
        raise TypeError("Oracle config lacks cost/planner mapping")
    return ExactOracleWeights(
        q_freq=float(cost["q_freq"]),
        q_integral=float(cost["q_integral"]),
        q_rocof=float(cost["q_rocof"]),
        r_sg=float(cost["r_sg"]),
        r_ibr=float(cost["r_ibr"]),
        s_delta_sg=float(cost["s_delta_sg"]),
        s_delta_ibr=float(cost["s_delta_ibr"]),
        q_terminal_freq=float(cost["q_terminal_freq"]),
        q_terminal_integral=float(cost["q_terminal_integral"]),
        safety_violation_penalty=float(planner["safety_violation_penalty"]),
    )


def _factory(
    paths: PhaseB1Paths,
    *,
    sg_level: str,
    library_kind: str,
    solver_tier: str,
) -> FinalControllerFactory:
    ensure_resolved_base_configs(paths)
    key = (str(paths.repo_root), sg_level, library_kind, solver_tier)
    if key in _FACTORY_CACHE:
        return _FACTORY_CACHE[key]
    library, calibration, binding = paths.phase6.library_files(library_kind)  # type: ignore[arg-type]
    ood_selection = {
        "native_k6": paths.phase6.native_ood_hysteresis_selection,
        "labeled_training_k4": paths.phase6.labeled_ood_hysteresis_selection,
    }.get(library_kind)
    if ood_selection is None:
        raise ValueError("Phase B1 uses only native K6 or labeled K4 factories")
    factory = FinalControllerFactory(
        base_config_path=paths.resolved_base_config(sg_level),
        mpc_config_path=paths.mpc_config,
        mode_library_path=library,
        ood_calibration_path=calibration,
        ood_selection_path=ood_selection,
        library_binding=LibraryArtifactBinding.load_json(binding),
        solver_tier=SolverExecutionTier(solver_tier.lower()),
    )
    _FACTORY_CACHE[key] = factory
    return factory


def _mode_to_component_eval_only(paths: PhaseB1Paths) -> Mapping[str, int]:
    mapping = load_component_mapping_eval_only(paths.phase6, "labeled_training_k4")
    return MappingProxyType({semantic: component for component, semantic in mapping.items()})


def _build_controller(
    spec: PhaseB1RunSpec,
    paths: PhaseB1Paths,
    scenario: object,
    modes_eval_only: Mapping[str, object],
) -> tuple[object, dict[str, Any], dict[str, Any]]:
    method = spec.method_id
    truth_kwargs: dict[str, Any] = {}
    audit: dict[str, Any] = {
        "schema_version": PHASE_B1_RUN_PROVENANCE_SCHEMA,
        "method_id": method,
        "sg_level": spec.sg_level,
        "evaluation_truth_required": False,
    }
    if method == "B5" or method.startswith("B5_"):
        factory = _factory(
            paths,
            sg_level=spec.sg_level,
            library_kind="native_k6",
            solver_tier=spec.solver_tier,
        )
        capability = load_sg_capabilities(paths.sg_levels_config)[spec.sg_level]
        assert spec.oracle_candidate_id is not None
        controller = ExactNonlinearOracleController(
            ExactOracleContext(
                grid_model=factory.grid_model,
                mode_params_eval_only=modes_eval_only,  # type: ignore[arg-type]
                scenario_eval_only=scenario,  # type: ignore[arg-type]
                seed=spec.seed,
                sg_level=spec.sg_level,
                bounds=ExactOracleBounds(
                    sg_min_pu=capability.command_min_pu,
                    sg_max_pu=capability.command_max_pu,
                    sg_ramp_pu_per_s=capability.ramp_pu_per_s,
                ),
                planner=oracle_planner_config(paths, spec.oracle_candidate_id),
                weights=oracle_weights(paths),
            )
        )
        truth_kwargs = {
            "oracle_action_callback": exact_oracle_action_from_truth,
            "truth_provider": scenario_truth_provider,
        }
        audit.update(
            {
                "evaluation_truth_required": True,
                "truth_scope": "current_mode_and_exact_ibr_parameters_only",
                "future_load_or_mode_access": False,
                "oracle_candidate_id": spec.oracle_candidate_id,
                "oracle_horizon_s": spec.oracle_horizon_s,
            }
        )
        return controller, truth_kwargs, audit

    library_kind = (
        "labeled_training_k4"
        if method in {
            "B4",
            "C0_true_arx_expected",
            "C1_true_arx_worst",
            "C2_perfect_belief_current_mpc",
        }
        else "native_k6"
    )
    factory = _factory(
        paths,
        sg_level=spec.sg_level,
        library_kind=library_kind,
        solver_tier=spec.solver_tier,
    )
    if method == "B0":
        build = factory.build_b0_lqi()
        controller = build.controller
        audit["controller_metadata"] = asdict(build.metadata)
    elif method == "B2":
        selection = FixedReferenceSelectionArtifact.load_json(
            paths.phase6.fixed_reference_selection
        )
        build = factory.build_b2_rls(selection)
        controller = build.controller
        audit["controller_metadata"] = asdict(build.metadata)
    elif method == "B4":
        build = factory.build_b4_oracle(
            OracleARXArtifact.load_json(paths.phase6.oracle_arx_artifact_eval_only)
        )
        controller = build.controller
        truth_kwargs = {
            "oracle_action_callback": oracle_action_from_truth,
            "truth_provider": scenario_truth_provider,
        }
        audit.update(
            {
                "controller_metadata": asdict(build.metadata),
                "evaluation_truth_required": True,
                "truth_scope": "current_true_mode_ARX_routing_only",
            }
        )
    elif method == "P_old":
        build = factory.build_proposed_or_ablation(SDBMPCVariantConfig.proposed())
        controller = build.controller
        audit["controller_metadata"] = asdict(build.metadata)
    else:
        counterfactual = build_phase_b1_counterfactual(
            factory,
            method,
            mode_to_component_eval_only=(
                _mode_to_component_eval_only(paths)
                if method in {
                    "C0_true_arx_expected",
                    "C1_true_arx_worst",
                    "C2_perfect_belief_current_mpc",
                }
                else None
            ),
        )
        controller = counterfactual.controller
        audit.update(
            {
                "counterfactual_factors": asdict(counterfactual.factors),
                "evaluation_truth_required": counterfactual.evaluation_truth_required,
            }
        )
        if counterfactual.evaluation_truth_required:
            truth_kwargs = {
                "oracle_action_callback": oracle_action_from_truth,
                "truth_provider": scenario_truth_provider,
            }
    return controller, truth_kwargs, audit


def _run_evaluator(
    audit: Mapping[str, Any],
    *,
    paths: PhaseB1Paths,
    grid_model: object,
    modes_eval_only: Mapping[str, object],
    method_id: str,
    scenario_id: str,
    sg_level: str,
):
    audit_config = load_yaml(paths.audit_config)
    model_scope = frozenset(
        str(value)
        for value in audit_config["scenario_scope"]["model_adequacy"]["scenario_ids"]
    )
    identification_scope = frozenset(
        str(value)
        for value in audit_config["scenario_scope"]["control_design"]["scenario_ids"]
    )
    oracle_models = (
        OracleARXArtifact.load_json(
            paths.phase6.oracle_arx_artifact_eval_only
        ).models_by_key
        if method_id == "B0" and scenario_id in model_scope
        else None
    )
    bayes_library = (
        ModeLibrary.load_json(paths.phase6.labeled_library)
        if method_id == "P_old" and scenario_id in identification_scope
        else None
    )
    bayes_component_to_semantic = (
        load_component_mapping_eval_only(paths.phase6, "labeled_training_k4")
        if bayes_library is not None
        else None
    )
    diagnostic_component_to_semantic = (
        load_component_mapping_eval_only(paths.phase6, "native_k6")
        if bayes_library is not None
        else None
    )

    def evaluate(data: object) -> EvaluationContribution:
        records = getattr(data, "controller_records", ())
        statuses: dict[str, int] = {}
        outcomes: dict[str, int] = {}
        authority: list[float] = []
        mirror_errors: list[float] = []
        for record in records:
            if not isinstance(record, Mapping):
                continue
            status = str(record.get("solver_status", "unknown"))
            outcome = str(record.get("solver_outcome", "unknown"))
            statuses[status] = statuses.get(status, 0) + 1
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
            if record.get("ibr_authority_ratio") is not None:
                authority.append(float(record["ibr_authority_ratio"]))
            if record.get("mirror_measurement_max_abs_error") is not None:
                mirror_errors.append(float(record["mirror_measurement_max_abs_error"]))
        artifacts: dict[str, Any] = {
            "run_audit": dict(audit),
            "solver_status_counts": dict(sorted(statuses.items())),
            "solver_outcome_counts": dict(sorted(outcomes.items())),
            "mean_ibr_authority_ratio": (
                None if not authority else float(np.mean(authority))
            ),
            "max_exact_mirror_error": (
                None if not mirror_errors else float(max(mirror_errors))
            ),
            "compact_scientific_audits": {},
            "compact_scientific_audit_failures": [],
        }
        if bool(getattr(data, "run_completed", False)):
            if oracle_models is not None:
                try:
                    artifacts["compact_scientific_audits"][
                        "closed_loop_prediction_error"
                    ] = exact_vs_arx_episode_rows(
                        data,
                        grid_model=grid_model,
                        arx_models_by_true_mode_eval_only=oracle_models,
                        mode_params_eval_only=modes_eval_only,
                        sg_level=sg_level,
                    )
                    artifacts["compact_scientific_audits"][
                        "constraint_activation"
                    ] = constraint_activation_episode_rows(
                        data,
                        mode_params_eval_only=modes_eval_only,
                        sg_level=sg_level,
                    )
                except Exception as error:  # retained as an explicit audit failure
                    artifacts["compact_scientific_audit_failures"].append(
                        {
                            "audit": "model_adequacy",
                            "failure_type": type(error).__name__,
                            "failure_message": str(error),
                        }
                    )
            if (
                bayes_library is not None
                and bayes_component_to_semantic is not None
                and diagnostic_component_to_semantic is not None
            ):
                try:
                    artifacts["compact_scientific_audits"].update(
                        passive_identifiability_episode_rows(
                            data,
                            bayes_candidate_library_eval_only=bayes_library,
                            bayes_component_to_semantic_eval_only=(
                                bayes_component_to_semantic
                            ),
                            diagnostic_component_to_semantic_eval_only=(
                                diagnostic_component_to_semantic
                            ),
                            sg_level=sg_level,
                            windows_s=tuple(
                                float(value)
                                for value in audit_config["identifiability"]["windows_s"]
                            ),
                            eigenvalue_threshold=float(
                                audit_config["identifiability"][
                                    "gramian_eigenvalue_threshold"
                                ]
                            ),
                            condition_threshold=float(
                                audit_config["identifiability"][
                                    "gramian_condition_threshold"
                                ]
                            ),
                            likelihood_margin_threshold=float(
                                audit_config["identifiability"][
                                    "log_likelihood_margin_threshold"
                                ]
                            ),
                        )
                    )
                except Exception as error:  # retained as an explicit audit failure
                    artifacts["compact_scientific_audit_failures"].append(
                        {
                            "audit": "passive_identifiability",
                            "failure_type": type(error).__name__,
                            "failure_message": str(error),
                        }
                    )
        return EvaluationContribution(artifacts=artifacts)

    return evaluate


def _provenance(spec: PhaseB1RunSpec, paths: PhaseB1Paths) -> Mapping[str, Any]:
    final_lock = None
    if spec.stage == "final":
        ensure_protocol_lock(paths)
        final_lock = protocol_lock_sha256(paths)
    payload = {
        "schema_version": PHASE_B1_RUN_PROVENANCE_SCHEMA,
        "stage": spec.stage,
        "sg_level": spec.sg_level,
        "oracle_candidate_id": spec.oracle_candidate_id,
        "oracle_horizon_s": spec.oracle_horizon_s,
        "solver_tier": spec.solver_tier,
        "final_protocol_lock_sha256": final_lock,
        "config_logical_sha256": {
            "audit": config_sha256(load_yaml(paths.audit_config)),
            "sg_levels": config_sha256(load_yaml(paths.sg_levels_config)),
            "oracle": config_sha256(load_yaml(paths.oracle_config)),
            "resolved_base": config_sha256(
                load_yaml(paths.resolved_base_config(spec.sg_level))
            ),
            "mpc": config_sha256(load_yaml(paths.mpc_config)),
        },
    }
    normalized = json.loads(json.dumps(payload, sort_keys=True, allow_nan=False))
    return MappingProxyType(normalized)


def execute_phase_b1_run(spec: PhaseB1RunSpec) -> PhaseB1RunReceipt:
    """Execute or strictly resume one Phase-B1 episode."""

    paths = PhaseB1Paths.from_repo(spec.repo_root)
    ensure_resolved_base_configs(paths)
    if spec.stage == "final":
        ensure_protocol_lock(paths)
        selection = json.loads(paths.validation_selection.read_text(encoding="utf-8"))
        selected = str(selection["selected_candidate_id"])
        if (spec.method_id == "B5" and spec.oracle_candidate_id != selected):
            raise RuntimeError("final B5 spec differs from the locked validation selection")
    protocol = load_experiment_protocol(paths.experiments_config)
    scenario = protocol.build_scenario(spec.scenario_id)
    modes = load_simulator_private_modes_eval_only(paths.phase6)
    controller, truth_kwargs, audit = _build_controller(spec, paths, scenario, modes)
    grid_model = (
        controller.context.grid_model
        if isinstance(controller, ExactNonlinearOracleController)
        else _factory(
            paths,
            sg_level=spec.sg_level,
            library_kind=(
                "labeled_training_k4"
                if spec.method_id in {
                    "B4",
                    "C0_true_arx_expected",
                    "C1_true_arx_worst",
                    "C2_perfect_belief_current_mpc",
                }
                else "native_k6"
            ),
            solver_tier=spec.solver_tier,
        ).grid_model
    )
    store = PerRunExperimentStore(
        paths.results_root / "runs" / spec.stage / "per_run"
    )
    representative = load_yaml(paths.audit_config)["representative_trajectories"]
    persist_representative = bool(
        spec.stage == "final"
        and spec.seed == int(representative["seed"])
        and spec.sg_level == str(representative["sg_level"])
        and spec.scenario_id in set(representative["scenario_ids"])
        and spec.method_id in set(representative["method_ids"])
    )
    outcome = run_closed_loop_episode(
        identity=spec.identity,
        simulator=HiddenModeFrequencySimulator(grid_model, modes),
        scenario=scenario,
        controller=controller,
        metric_config=build_phase_b1_metric_config(
            paths.resolved_base_config(spec.sg_level)
        ),
        store=store,
        runner_config=EpisodeRunnerConfig(
            expected_duration_s=180.0,
            resume=True,
            replace_existing=False,
            persist_control_trajectory=persist_representative,
            persist_high_frequency_trace=False,
            persist_controller_records=False,
        ),
        evaluators=(
            _run_evaluator(
                audit,
                paths=paths,
                grid_model=grid_model,
                modes_eval_only=modes,
                method_id=spec.method_id,
                scenario_id=spec.scenario_id,
                sg_level=spec.sg_level,
            ),
        ),
        responsibility_event_time_s=responsibility_event_time_eval_only(scenario),
        run_provenance=_provenance(spec, paths),
        **truth_kwargs,
    )
    result = outcome.episode_result
    return PhaseB1RunReceipt(
        run_id=spec.identity.run_id,
        envelope_sha256=outcome.stored_run.sha256,
        resumed=outcome.resumed,
        scientific_success=bool(result.scientific_success),
        failure_stage=result.failure_stage,
        wall_time_s=result.wall_time_s,
    )


def build_development_plan(
    paths: PhaseB1Paths,
    *,
    stage: str,
    scenario_ids: Sequence[str],
    method_ids: Sequence[str],
    sg_levels: Sequence[str] = SG_LEVELS,
    oracle_candidate_ids: Sequence[str] = (),
) -> tuple[PhaseB1RunSpec, ...]:
    if stage not in {"smoke", "validation"}:
        raise ValueError("development plan stage must be smoke or validation")
    protocol = load_experiment_protocol(paths.experiments_config)
    known_scenarios = {row.scenario_id for row in protocol.scenario_variants}
    if not set(scenario_ids) <= known_scenarios:
        raise ValueError("development plan contains an unknown scenario")
    if not set(sg_levels) <= set(SG_LEVELS):
        raise ValueError("development plan contains an unknown SG level")
    candidates = _oracle_candidates(paths)
    specs: list[PhaseB1RunSpec] = []
    for scenario_id in scenario_ids:
        for level in sg_levels:
            for seed in seeds_for(
                stage,  # type: ignore[arg-type]
                scenario_id,
                audit_config=paths.audit_config,
                experiments_config=paths.experiments_config,
            ):
                for method in method_ids:
                    if method == "B5":
                        for candidate_id in oracle_candidate_ids:
                            row = candidates[candidate_id]
                            specs.append(
                                PhaseB1RunSpec(
                                    stage=stage,
                                    scenario_id=scenario_id,
                                    method_id=f"B5_{candidate_id}",
                                    seed=seed,
                                    sg_level=level,
                                    solver_tier="DEBUG",
                                    oracle_candidate_id=candidate_id,
                                    oracle_horizon_s=float(row["horizon_s"]),
                                    repo_root=paths.repo_root,
                                )
                            )
                    else:
                        specs.append(
                            PhaseB1RunSpec(
                                stage=stage,
                                scenario_id=scenario_id,
                                method_id=method,
                                seed=seed,
                                sg_level=level,
                                solver_tier="DEBUG",
                                oracle_candidate_id=None,
                                oracle_horizon_s=None,
                                repo_root=paths.repo_root,
                            )
                        )
    identities = [spec.identity.run_id for spec in specs]
    if len(identities) != len(set(identities)):
        raise RuntimeError("development run plan contains duplicate identities")
    return tuple(specs)


def build_final_core_plan(paths: PhaseB1Paths) -> tuple[PhaseB1RunSpec, ...]:
    """Preregistered all-scenario B0/B2/B4/B5 materiality/model matrix."""

    ensure_protocol_lock(paths)
    selection = json.loads(paths.validation_selection.read_text(encoding="utf-8"))
    selected = str(selection["selected_candidate_id"])
    candidate = _oracle_candidates(paths)[selected]
    protocol = load_experiment_protocol(paths.experiments_config)
    specs: list[PhaseB1RunSpec] = []
    for scenario in protocol.scenario_variants:
        for level in SG_LEVELS:
            for seed in seeds_for(
                "final",
                scenario.scenario_id,
                audit_config=paths.audit_config,
                experiments_config=paths.experiments_config,
            ):
                for method in ("B0", "B2", "B4", "B5"):
                    specs.append(
                        PhaseB1RunSpec(
                            stage="final",
                            scenario_id=scenario.scenario_id,
                            method_id=method,
                            seed=seed,
                            sg_level=level,
                            solver_tier="FINAL",
                            oracle_candidate_id=selected if method == "B5" else None,
                            oracle_horizon_s=(
                                float(candidate["horizon_s"]) if method == "B5" else None
                            ),
                            repo_root=paths.repo_root,
                        )
                    )
    return tuple(specs)


def build_final_control_plan(paths: PhaseB1Paths) -> tuple[PhaseB1RunSpec, ...]:
    """Preregistered control-design matrix; C0--C2 are known-mode only."""

    ensure_protocol_lock(paths)
    audit = load_yaml(paths.audit_config)
    scenario_ids = tuple(audit["scenario_scope"]["control_design"]["scenario_ids"])
    protocol = load_experiment_protocol(paths.experiments_config)
    truth = {row.scenario_id: row.truth_class for row in protocol.scenario_variants}
    specs: list[PhaseB1RunSpec] = []
    for scenario_id in scenario_ids:
        methods = [
            "P_old",
            "C3_current_belief_expected",
            "C4_gradual_authority",
            "C5_no_sticky_prior",
        ]
        if truth[scenario_id] == "known":
            methods.extend(
                [
                    "C0_true_arx_expected",
                    "C1_true_arx_worst",
                    "C2_perfect_belief_current_mpc",
                ]
            )
        for level in SG_LEVELS:
            for seed in seeds_for(
                "final",
                scenario_id,
                audit_config=paths.audit_config,
                experiments_config=paths.experiments_config,
            ):
                for method in methods:
                    specs.append(
                        PhaseB1RunSpec(
                            stage="final",
                            scenario_id=scenario_id,
                            method_id=method,
                            seed=seed,
                            sg_level=level,
                            solver_tier="FINAL",
                            oracle_candidate_id=None,
                            oracle_horizon_s=None,
                            repo_root=paths.repo_root,
                        )
                    )
    return tuple(specs)


__all__ = [
    "PHASE_B1_RUN_PROVENANCE_SCHEMA",
    "PhaseB1RunReceipt",
    "PhaseB1RunSpec",
    "build_development_plan",
    "build_final_control_plan",
    "build_final_core_plan",
    "execute_phase_b1_run",
    "oracle_planner_config",
    "oracle_weights",
]
