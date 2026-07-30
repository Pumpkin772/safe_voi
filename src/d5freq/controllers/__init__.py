"""Controller implementations and controller-side safety helpers."""

from d5freq.controllers.base import (
    FallbackTrigger,
    GridStateEstimator,
    clip_with_rate_limit,
    fallback_required,
    should_trigger_fallback,
    withdraw_toward_zero,
)
from d5freq.controllers.fixed_model_mpc import FixedNominalMPCController
from d5freq.controllers.final_arx_mpc import (
    FinalARXMPCController,
    FixedReferenceSelectionArtifact,
    MutableSingletonProblemCache,
    ParameterizedSingletonProblem,
    ReferenceCandidateScore,
    build_fixed_reference_arx_controller,
)
from d5freq.controllers.hard_map_mpc import (
    DiagnosticProjectionRecord,
    DiagnosticRuntimeProjection,
    HardMAPMPCController,
)
from d5freq.controllers.lqi_fallback import (
    DEFAULT_LQI_Q_WEIGHTS,
    LQIFallbackConfig,
    LQIFallbackController,
    design_lqi_gain,
    reduced_discrete_grid_matrices,
)
from d5freq.controllers.phase_b2_conventional import (
    ConventionalACEPIController,
    ConventionalPIConfig,
)
from d5freq.controllers.sd_bmpc import (
    FallbackEvent,
    OnlineDiagnosticRuntime,
    PrecompileRecord,
    ProblemCacheRuntime,
    SDBMPCController,
    SDBMPCControllerConfig,
    SDBMPCProvenance,
    SDBMPCStepRecord,
    SDControllerState,
)
from d5freq.controllers.rls_adaptive_mpc import (
    RLSAdaptiveMPCController,
    RLSConfig,
    RLSUpdateRecord,
)

__all__ = [
    "DEFAULT_LQI_Q_WEIGHTS",
    "ConventionalACEPIController",
    "ConventionalPIConfig",
    "FallbackTrigger",
    "FallbackEvent",
    "FinalARXMPCController",
    "FixedNominalMPCController",
    "FixedReferenceSelectionArtifact",
    "GridStateEstimator",
    "LQIFallbackConfig",
    "LQIFallbackController",
    "MutableSingletonProblemCache",
    "OnlineDiagnosticRuntime",
    "ParameterizedSingletonProblem",
    "PrecompileRecord",
    "ProblemCacheRuntime",
    "SDBMPCController",
    "SDBMPCControllerConfig",
    "SDBMPCProvenance",
    "SDBMPCStepRecord",
    "SDControllerState",
    "DiagnosticProjectionRecord",
    "DiagnosticRuntimeProjection",
    "HardMAPMPCController",
    "RLSAdaptiveMPCController",
    "RLSConfig",
    "RLSUpdateRecord",
    "ReferenceCandidateScore",
    "build_fixed_reference_arx_controller",
    "clip_with_rate_limit",
    "design_lqi_gain",
    "fallback_required",
    "reduced_discrete_grid_matrices",
    "should_trigger_fallback",
    "withdraw_toward_zero",
]
