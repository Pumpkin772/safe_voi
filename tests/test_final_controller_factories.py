from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from d5freq.controllers.final_arx_mpc import (
    FixedReferenceSelectionArtifact,
    ReferenceCandidateScore,
)
from d5freq.evaluation.controller_factories import (
    FinalControllerFactory,
    LibraryArtifactBinding,
    LibraryConstructionProtocol,
    SDBMPCVariantConfig,
    SolverExecutionTier,
)
from d5freq.identification.model_library import ModeLibrary
from d5freq.interfaces import FrequencyController
from d5freq.utils.hashing import sha256_file, sha256_json


ROOT = Path(__file__).resolve().parents[1]
LIBRARY_PATH = ROOT / "artifacts" / "mode_discovery" / "mode_library.json"
CALIBRATION_PATH = (
    ROOT / "artifacts" / "online_diagnosis" / "ood_calibration_artifact.json"
)
OOD_SELECTION_PATH = (
    ROOT / "artifacts" / "online_diagnosis" / "ood_hysteresis_selection.json"
)


def _binding() -> LibraryArtifactBinding:
    library = ModeLibrary.load_json(LIBRARY_PATH)
    return LibraryArtifactBinding(
        artifact_id="canonical_native_k6",
        construction_protocol=LibraryConstructionProtocol.DISCOVERED_BIC_LABEL_FREE,
        component_count=6,
        mode_library_file_sha256=sha256_file(LIBRARY_PATH),
        mode_library_logical_sha256=sha256_json(library.to_dict()),
        ood_calibration_file_sha256=sha256_file(CALIBRATION_PATH),
        identification_train_dataset_sha256="1" * 64,
        identification_validation_dataset_sha256="2" * 64,
    )


def _factory(
    tier: SolverExecutionTier,
    *,
    mpc_config_path: Path | None = None,
) -> FinalControllerFactory:
    return FinalControllerFactory(
        base_config_path=ROOT / "configs" / "base.yaml",
        mpc_config_path=mpc_config_path or ROOT / "configs" / "mpc.yaml",
        mode_library_path=LIBRARY_PATH,
        ood_calibration_path=CALIBRATION_PATH,
        library_binding=_binding(),
        solver_tier=tier,
    )


def _selection() -> FixedReferenceSelectionArtifact:
    binding = _binding()
    scores = tuple(
        ReferenceCandidateScore(index, float(index + 1), 10, 10, 0)
        for index in range(6)
    )
    return FixedReferenceSelectionArtifact(
        mode_library_file_sha256=binding.mode_library_file_sha256,
        mode_library_logical_sha256=binding.mode_library_logical_sha256,
        component_count=6,
        selected_component_id=0,
        selection_split="closed_loop_validation",
        criterion="registered_episode_mean_cost",
        direction="minimize",
        selection_dataset_sha256="3" * 64,
        protocol_sha256="4" * 64,
        label_access="none",
        candidate_scores=scores,
    )


def test_library_binding_rejects_tampering_and_enforces_alternate_k4_contract() -> None:
    binding = _binding()
    payload = binding.to_dict()
    assert LibraryArtifactBinding.from_dict(payload) == binding
    with pytest.raises(ValueError, match="file SHA"):
        replace(binding, mode_library_file_sha256="0" * 64).validate_files(
            LIBRARY_PATH, CALIBRATION_PATH
        )
    for protocol in (
        LibraryConstructionProtocol.FIXED_K4_UNLABELED,
        LibraryConstructionProtocol.LABELED_TRAINING_ONLY,
    ):
        with pytest.raises(ValueError, match="K=4"):
            replace(binding, construction_protocol=protocol, component_count=6)


def test_final_tier_excludes_debug_solvers_and_factories_share_uniform_api() -> None:
    factory = _factory(SolverExecutionTier.FINAL)
    assert factory._controller_config.solver_priority == ("MOSEK", "GUROBI")
    assert (
        factory._controller_config.solver_options["MOSEK"]["mosek_params"][
            "MSK_IPAR_NUM_THREADS"
        ]
        == 1
    )
    assert factory._controller_config.solver_options["GUROBI"]["Threads"] == 1
    builds = (
        factory.build_b0_lqi(),
        factory.build_b1_fixed_reference(_selection()),
        factory.build_b2_rls(_selection()),
        factory.build_b3_hard_map(),
        factory.build_proposed_or_ablation(),
        factory.build_proposed_or_ablation(SDBMPCVariantConfig.no_worst_mode()),
        factory.build_proposed_or_ablation(SDBMPCVariantConfig.no_ood()),
        factory.build_proposed_or_ablation(SDBMPCVariantConfig.no_tightening()),
        factory.build_proposed_or_ablation(SDBMPCVariantConfig.no_transition_prior()),
    )
    assert all(isinstance(build.controller, FrequencyController) for build in builds)
    assert all(build.metadata.eligible_for_final_solver_claims for build in builds)
    assert all(
        "solver_threads_per_episode=1" in build.metadata.qualifications
        for build in builds
    )
    assert builds[1].metadata.qualifications[0] == "source_component_id=0"
    assert builds[2].controller.problem_cache.graph_build_count == 0
    assert [build.metadata.method_id for build in builds[5:]] == [
        "no-worst",
        "no-OOD",
        "no-tightening",
        "no-transition-prior",
    ]
    no_ood = builds[6].controller
    assert not no_ood.controller_config.enable_ood_fallback
    assert no_ood._diagnostic.__class__.__name__ == "OnlineModeDiagnostic"


def test_factory_uses_hash_audited_known_only_ood_hysteresis_selection() -> None:
    factory = FinalControllerFactory(
        base_config_path=ROOT / "configs" / "base.yaml",
        mpc_config_path=ROOT / "configs" / "mpc.yaml",
        mode_library_path=LIBRARY_PATH,
        ood_calibration_path=CALIBRATION_PATH,
        ood_selection_path=OOD_SELECTION_PATH,
        library_binding=_binding(),
        solver_tier=SolverExecutionTier.DEBUG,
    )
    assert factory._ood_runtime_config.L_on == 3
    assert factory._ood_runtime_config.L_off == 5
    selection_hash = sha256_file(OOD_SELECTION_PATH)
    metadata = factory.build_b0_lqi().metadata
    assert f"ood_hysteresis_selection_sha256={selection_hash}" in metadata.qualifications


def test_debug_tier_is_explicit_and_variant_configuration_is_frozen() -> None:
    factory = _factory(SolverExecutionTier.DEBUG)
    assert factory._controller_config.solver_priority == ("CLARABEL", "SCS")
    build = factory.build_proposed_or_ablation(
        SDBMPCVariantConfig.hard_belief_only()
    )
    assert build.metadata.method_id == "hard-belief"
    assert build.metadata.solver_tier == "debug"
    assert not build.metadata.eligible_for_final_solver_claims
    assert "solver_allowlist=CLARABEL,SCS" in build.metadata.qualifications
    variant = SDBMPCVariantConfig.no_ood()
    with pytest.raises(FrozenInstanceError):
        variant.enable_ood = True  # type: ignore[misc]


@pytest.mark.parametrize(
    ("tier", "removed_solvers", "message"),
    (
        (
            SolverExecutionTier.FINAL,
            ("MOSEK", "GUROBI"),
            "final solver tier requires MOSEK or GUROBI",
        ),
        (
            SolverExecutionTier.DEBUG,
            ("CLARABEL", "SCS"),
            "debug solver tier requires CLARABEL or SCS",
        ),
    ),
)
def test_solver_tier_rejects_configuration_without_an_allowed_solver(
    tier: SolverExecutionTier,
    removed_solvers: tuple[str, ...],
    message: str,
) -> None:
    factory = _factory(tier)
    payload = dict(factory._mpc_payload)
    mpc = dict(payload["mpc"])
    mpc["solver_priority"] = tuple(
        solver
        for solver in mpc["solver_priority"]
        if solver not in removed_solvers
    )
    payload["mpc"] = mpc
    factory._mpc_payload = payload
    with pytest.raises(ValueError, match=message):
        factory._solver_priority()


def test_factory_rejects_cross_protocol_controller_wiring() -> None:
    factory = _factory(SolverExecutionTier.DEBUG)

    with pytest.raises(
        ValueError,
        match="B4 requires labeled_training_only with K=4",
    ):
        factory.build_b4_oracle(None)  # type: ignore[arg-type]

    factory._binding = replace(
        factory.binding,
        construction_protocol=LibraryConstructionProtocol.FIXED_K4_UNLABELED,
        component_count=4,
    )
    native_builders = (
        lambda: factory.build_b1_fixed_reference(_selection()),
        lambda: factory.build_b2_rls(_selection()),
        factory.build_b3_hard_map,
        factory.build_proposed_or_ablation,
        lambda: factory.build_proposed_or_ablation(
            SDBMPCVariantConfig.no_worst_mode()
        ),
        lambda: factory.build_proposed_or_ablation(SDBMPCVariantConfig.no_ood()),
        lambda: factory.build_proposed_or_ablation(
            SDBMPCVariantConfig.no_tightening()
        ),
        lambda: factory.build_proposed_or_ablation(
            SDBMPCVariantConfig.no_transition_prior()
        ),
    )
    for build in native_builders:
        with pytest.raises(
            ValueError,
            match="requires discovered_bic_label_free with K=6",
        ):
            build()

    # B0 is intentionally independent of the library construction protocol.
    assert factory.build_b0_lqi().metadata.method_id == "B0"
