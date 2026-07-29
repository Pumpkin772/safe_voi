from __future__ import annotations

import numpy as np

from d5freq.controllers.hard_map_mpc import (
    DiagnosticRuntimeProjection,
    HardMAPMPCController,
)
from d5freq.controllers.sd_bmpc import SDBMPCControllerConfig
from d5freq.estimation.online_diagnostic import DiagnosticOutput
from d5freq.identification.arx import arx_to_state_space
from d5freq.interfaces import Measurement
from d5freq.models.grid_frequency import GridFrequencyModel, GridParams
from d5freq.optimization.joint_prediction import assemble_joint_arx_prediction
from d5freq.optimization.mpc_problem import SDBMPCConfig, SDBMPCMode


def _grid() -> GridFrequencyModel:
    return GridFrequencyModel(GridParams(50.0, 8.0, 1.0, 0.5, 0.2, 0.08, 0.5, 0.02))


def _modes() -> tuple[SDBMPCMode, ...]:
    grid = _grid()
    q = {1: 0.0, 2: 0.0}
    result = []
    for component_id, b0 in enumerate((0.1, 0.4)):
        A, B, F, _ = arx_to_state_space([0.5, -0.1, b0, 0.0, -0.1, 0.0, 0.0])
        result.append(
            SDBMPCMode(
                component_id=component_id,
                prediction_model=assemble_joint_arx_prediction(grid, A, B, F),
                frequency_q95_hz=q,
                rocof_q95_hz_per_s=q,
                power_q95_pu=q,
                p_output_min_pu=-0.08,
                p_output_max_pu=0.08,
                ramp_down_pu_per_s=0.04,
                ramp_up_pu_per_s=0.04,
            )
        )
    return tuple(result)


class _CountingDiagnostic:
    def __init__(self, *, state: str = "KNOWN") -> None:
        self.state = state
        self.reset_calls = 0
        self.step_calls = 0

    def reset(self) -> None:
        self.reset_calls += 1
        self.step_calls = 0

    def step(self, measurement: Measurement) -> DiagnosticOutput:
        index = self.step_calls
        self.step_calls += 1
        active = self.state == "OOD_ACTIVE"
        return DiagnosticOutput(
            time_s=measurement.time_s,
            sample_index=index,
            valid_update=index >= 2,
            mode_belief=np.array([0.2, 0.8]),
            map_mode=1,
            belief_entropy=0.72,
            raw_belief_entropy=0.5,
            mode_predictions_pu=np.zeros(2),
            residuals_pu=np.zeros(2),
            innovation_variances_pu2=np.ones(2),
            nis=np.zeros(2),
            log_normalization_constant=0.0,
            ood_score=2.0 if active else 0.0,
            ood_pvalue=0.0 if active else 1.0,
            ood_active=active,
            diagnostic_state=self.state,
        )


class _CountingEstimator:
    def __init__(self) -> None:
        self.reset_calls = 0
        self.update_calls = 0

    def reset_from_measurement(self, measurement: Measurement) -> np.ndarray:
        self.reset_calls += 1
        return np.array([measurement.omega_pu, measurement.p_mech_pu, 0, 0, 0])

    def update_from_measurement(self, measurement: Measurement) -> np.ndarray:
        self.update_calls += 1
        return np.array([measurement.omega_pu, measurement.p_mech_pu, 0, 0, 0])


def test_hard_map_projects_once_and_shares_single_estimator_update() -> None:
    diagnostic = _CountingDiagnostic()
    estimator = _CountingEstimator()
    controller = HardMAPMPCController(
        _grid(),
        _modes(),
        diagnostic,
        mpc_config=SDBMPCConfig(horizon_steps=2),
        controller_config=SDBMPCControllerConfig(
            solver_priority=("CLARABEL",),
            solver_options={
                "CLARABEL": {
                    "tol_gap_abs": 1.0e-5,
                    "tol_gap_rel": 1.0e-5,
                    "tol_feas": 1.0e-5,
                    "max_iter": 1_000,
                }
            },
            solve_timeout_s=2.0,
            precompile_on_reset=False,
        ),
        estimator=estimator,
    )
    initial = Measurement(0.0, -0.001, 0.0, 0.0, 0.0, 0.0)
    controller.reset(initial)
    first = controller.act(initial)
    assert first.controller_state == "HARD_MAP_MPC"
    assert diagnostic.step_calls == 1
    assert estimator.reset_calls == 1
    assert estimator.update_calls == 0
    assert controller.step_records[-1].risk_component_ids == (1,)
    np.testing.assert_array_equal(
        controller.projection_records[-1].projected_mode_belief, [0.0, 1.0]
    )

    later = Measurement(0.5, -0.001, 0.0, 0.0, first.u_sg_pu, first.u_ibr_pu)
    controller.act(later)
    assert diagnostic.step_calls == 2
    assert estimator.update_calls == 1
    controller.act(later)
    assert diagnostic.step_calls == 2
    assert estimator.update_calls == 1


def test_no_ood_projection_bypasses_state_without_recalling_source() -> None:
    source = _CountingDiagnostic(state="OOD_ACTIVE")
    projection = DiagnosticRuntimeProjection(source, hard_map=False, ignore_ood=True)
    projection.reset()
    output = projection.step(Measurement(0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
    assert source.step_calls == 1
    assert output.diagnostic_state == "KNOWN"
    assert output.ood_pvalue == 1.0
    np.testing.assert_allclose(output.mode_belief, [0.2, 0.8])
    assert projection.records[-1].raw_diagnostic_state == "OOD_ACTIVE"
