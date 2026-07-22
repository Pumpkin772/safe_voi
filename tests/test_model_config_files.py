from __future__ import annotations

from pathlib import Path

import numpy as np

from d5freq.estimation import GridKalmanFilter
from d5freq.models import (
    GridFrequencyModel,
    GridParams,
    IBRModeParams,
    SinusoidalDelayProfile,
)
from d5freq.utils.config import load_yaml


ROOT = Path(__file__).resolve().parents[1]


def test_all_versioned_physical_model_configs_build() -> None:
    base = load_yaml(ROOT / "configs" / "base.yaml")
    grid_keys = (
        "f0_hz",
        "M_s",
        "D_pu",
        "T_t_s",
        "T_g_s",
        "R_pu",
        "control_period_s",
        "integration_step_s",
    )
    grid = GridParams(**{key: base["grid"][key] for key in grid_keys})
    assert grid.integration_steps_per_control_period == 25

    known = load_yaml(ROOT / "configs" / "modes_known.yaml")["known_modes"]
    ood = load_yaml(ROOT / "configs" / "modes_ood.yaml")["ood_modes"]
    modes = {
        name: IBRModeParams.from_mapping(name, values)
        for name, values in {**known, **ood}.items()
    }
    assert set(modes) == {
        "nominal",
        "sluggish",
        "derated",
        "unavailable",
        "asymmetric_limit",
        "time_varying_delay",
    }
    assert isinstance(modes["time_varying_delay"].delay_profile, SinusoidalDelayProfile)

    kalman = base["estimation"]["grid_kalman"]
    estimator = GridKalmanFilter(
        GridFrequencyModel(grid),
        process_noise_covariance=np.diag(kalman["process_noise_diagonal"]),
        measurement_noise_covariance=np.diag(
            kalman["measurement_noise_diagonal"]
        ),
        initial_covariance=np.diag(kalman["initial_covariance_diagonal"]),
        load_random_walk_std_pu_per_s=kalman[
            "load_random_walk_std_pu_per_s"
        ],
    )
    assert estimator.process_noise_covariance.shape == (5, 5)
