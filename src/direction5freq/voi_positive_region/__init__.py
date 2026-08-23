"""Direction5 safe-VOI positive-region rebuild.

The package is deliberately separate from the frozen predecessor boundary
implementation.  It exposes preregistered scenario construction, physical-time
probe generation, vector observation tubes, and nested value accounting.
"""

from .probe_library import (
    ProbeDesign,
    registered_control_aligned_library,
    registered_probe_library,
)
from .control_aligned_policy import (
    ControlAlignedConfig,
    ControlAlignedSequentialProbe,
)
from .prior_value_boundary import BinaryPriorValueBoundary
from .information_value_surface import OpportunityValuePoint, select_opportunity
from .factorial_design import FactorialCell, development_factorial
from .physical_metrics import GridMetricScales, PhysicalMetrics, trajectory_metrics
from .scenario_registry import ScenarioSpec, StudySplit, generate_scenarios
from .value_accounting import NestedValueInputs, NestedValueResult, evaluate_nested_value
from .vector_observation import VectorObservationTube, causal_posterior

__all__ = [
    "NestedValueInputs",
    "NestedValueResult",
    "ProbeDesign",
    "ControlAlignedConfig",
    "ControlAlignedSequentialProbe",
    "BinaryPriorValueBoundary",
    "OpportunityValuePoint",
    "FactorialCell",
    "GridMetricScales",
    "PhysicalMetrics",
    "ScenarioSpec",
    "StudySplit",
    "VectorObservationTube",
    "causal_posterior",
    "evaluate_nested_value",
    "generate_scenarios",
    "registered_probe_library",
    "registered_control_aligned_library",
    "trajectory_metrics",
    "select_opportunity",
    "development_factorial",
]
