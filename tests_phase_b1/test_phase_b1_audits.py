from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from d5freq.evaluation.phase_b1_audits import (
    exact_vs_arx_episode_rows,
    gaussian_jsd,
    information_gramian,
)
from d5freq.interfaces import ControlAction, Measurement
from d5freq.models.grid_frequency import GridFrequencyModel, GridParams
from d5freq.models.hidden_mode_ibr import IBRModeParams


def _grid() -> GridFrequencyModel:
    return GridFrequencyModel(
        GridParams(
            f0_hz=50.0,
            M_s=8.0,
            D_pu=1.0,
            T_t_s=0.5,
            T_g_s=0.2,
            R_pu=0.08,
            control_period_s=0.5,
            integration_step_s=0.02,
        )
    )


def test_information_gramian_reports_rank_and_condition() -> None:
    regressors = np.eye(7)
    gramian, minimum, condition = information_gramian(regressors)
    np.testing.assert_allclose(gramian, np.eye(7))
    assert minimum == 1.0
    assert condition == 1.0
    _, deficient_minimum, deficient_condition = information_gramian(
        np.ones((10, 7))
    )
    assert deficient_minimum <= 1e-12
    assert deficient_condition > 1e10


def test_gaussian_jsd_is_zero_for_identical_and_positive_for_separated_models() -> None:
    assert gaussian_jsd(0.0, 1.0, 0.0, 1.0, grid_size=101) < 1e-12
    separated = gaussian_jsd(-2.0, 0.2, 2.0, 0.2, grid_size=101)
    assert 0.5 < separated <= np.log(2.0)


def test_exact_vs_arx_power_error_uses_rolling_origin_without_future_power() -> None:
    times = np.arange(5, dtype=float) * 0.5
    power = np.arange(5, dtype=float) * 0.1
    command = power[1:]
    measurements = tuple(
        Measurement(
            time_s=float(time),
            omega_pu=0.0,
            p_mech_pu=0.0,
            p_ibr_pu=float(power[index]),
            u_sg_prev_pu=0.0,
            u_ibr_prev_pu=0.0 if index == 0 else float(command[index - 1]),
        )
        for index, time in enumerate(times)
    )
    actions = tuple(
        ControlAction(u_sg_pu=0.0, u_ibr_pu=float(value)) for value in command
    )
    truth = tuple(
        {
            "time_s": float(time),
            "omega_true_pu": 0.0,
            "rocof_true_hz_per_s": 0.0,
            "p_mech_true_pu": 0.0,
            "p_ibr_true_pu": float(power[index]),
            "load_disturbance_pu": 0.0,
            "true_mode_eval_only": "nominal",
        }
        for index, time in enumerate(times)
    )
    data = SimpleNamespace(
        identity=SimpleNamespace(
            run_id="fixture", scenario_id="fixture-scenario", seed=1
        ),
        measurements=measurements,
        actions=actions,
        truth_points_eval_only=truth,
    )
    # p[k+1] = u[k], so every one-step prediction is exact.
    model = SimpleNamespace(theta=np.array([0, 0, 1, 0, 0, 0, 0], dtype=float))
    rows = exact_vs_arx_episode_rows(
        data,
        grid_model=_grid(),
        arx_models_by_true_mode_eval_only={"nominal": model},
        mode_params_eval_only={
            "nominal": IBRModeParams(
                name="nominal",
                command_gain=1.0,
                frequency_gain=0.0,
                command_filter_time_s=0.1,
                power_response_time_s=0.1,
                delay_s=0.0,
                p_max_pos_pu=1.0,
                p_max_neg_pu=1.0,
                ramp_up_pu_per_s=1.0,
                ramp_down_pu_per_s=1.0,
                deadband_pu=0.0,
            )
        },
        sg_level="A",
        horizons=(1,),
    )
    power_row = next(row for row in rows if row["metric"] == "ibr_power_pu")
    assert power_row["sample_count"] == 3
    assert power_row["rmse"] < 1e-15
