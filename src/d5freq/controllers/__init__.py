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
from d5freq.controllers.lqi_fallback import (
    DEFAULT_LQI_Q_WEIGHTS,
    LQIFallbackConfig,
    LQIFallbackController,
    design_lqi_gain,
    reduced_discrete_grid_matrices,
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

__all__ = [
    "DEFAULT_LQI_Q_WEIGHTS",
    "FallbackTrigger",
    "FallbackEvent",
    "FixedNominalMPCController",
    "GridStateEstimator",
    "LQIFallbackConfig",
    "LQIFallbackController",
    "OnlineDiagnosticRuntime",
    "PrecompileRecord",
    "ProblemCacheRuntime",
    "SDBMPCController",
    "SDBMPCControllerConfig",
    "SDBMPCProvenance",
    "SDBMPCStepRecord",
    "SDControllerState",
    "clip_with_rate_limit",
    "design_lqi_gain",
    "fallback_required",
    "reduced_discrete_grid_matrices",
    "should_trigger_fallback",
    "withdraw_toward_zero",
]
