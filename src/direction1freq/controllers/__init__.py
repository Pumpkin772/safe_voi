"""Deployable Phase-E controllers; no API accepts simulator truth."""

from .ace_pi_aw import (
    ACEPIAntiWindup,
    PIControllerDiagnostics,
    delayed_sampled_closed_loop_matrix,
    design_stable_pi,
)
from .lqi_baseline import DiscreteLQIBaseline, LQIDesign, design_discrete_lqi
from .nominal_mpc import FiniteHorizonMPC, MPCDiagnostics, NominalModelMPC
from .rls_adaptive_mpc import RLSAdaptiveMPC
from .robust_capability_mpc import RobustCapabilityMPC

__all__ = [
    "ACEPIAntiWindup", "PIControllerDiagnostics", "delayed_sampled_closed_loop_matrix",
    "design_stable_pi", "DiscreteLQIBaseline", "LQIDesign", "design_discrete_lqi",
    "FiniteHorizonMPC", "MPCDiagnostics", "NominalModelMPC",
    "RLSAdaptiveMPC", "RobustCapabilityMPC",
]
