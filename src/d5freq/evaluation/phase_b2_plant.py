"""Factories and registered paths for the Phase-B2 physical Plant B."""

from __future__ import annotations

from pathlib import Path

from d5freq.models.two_area_plant_b import (
    PlantBParameters,
    TwoAreaPlantB,
    TwoAreaPlantBSimulator,
    plant_b_parameters_from_config,
)
from d5freq.utils.config import load_yaml


DEFAULT_PLANT_B_CONFIG = Path("configs/phase_b2_plant_b.yaml")


def load_plant_b_parameters(
    config_path: str | Path = DEFAULT_PLANT_B_CONFIG,
    *,
    sg_level: str = "adequate",
    upper_control_period_s: float | None = None,
) -> PlantBParameters:
    """Load one preregistered Plant-B capability/control-period variant."""

    return plant_b_parameters_from_config(
        load_yaml(config_path),
        sg_level=sg_level,
        upper_control_period_s=upper_control_period_s,
    )


def make_plant_b_simulator(
    config_path: str | Path = DEFAULT_PLANT_B_CONFIG,
    *,
    sg_level: str = "adequate",
    upper_control_period_s: float | None = None,
    random_seed: int = 0,
) -> TwoAreaPlantBSimulator:
    """Construct a fresh simulator without exposing its hidden truth to control."""

    parameters = load_plant_b_parameters(
        config_path,
        sg_level=sg_level,
        upper_control_period_s=upper_control_period_s,
    )
    return TwoAreaPlantBSimulator(
        TwoAreaPlantB(parameters),
        random_seed=random_seed,
    )


__all__ = [
    "DEFAULT_PLANT_B_CONFIG",
    "load_plant_b_parameters",
    "make_plant_b_simulator",
]
