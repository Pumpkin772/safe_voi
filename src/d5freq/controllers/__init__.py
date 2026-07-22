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

__all__ = [
    "DEFAULT_LQI_Q_WEIGHTS",
    "FallbackTrigger",
    "FixedNominalMPCController",
    "GridStateEstimator",
    "LQIFallbackConfig",
    "LQIFallbackController",
    "clip_with_rate_limit",
    "design_lqi_gain",
    "fallback_required",
    "reduced_discrete_grid_matrices",
    "should_trigger_fallback",
    "withdraw_toward_zero",
]
