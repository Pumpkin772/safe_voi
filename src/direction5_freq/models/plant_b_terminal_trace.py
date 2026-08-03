"""Native Plant-B trace exposing every Phase-H terminal-window boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from direction1freq.models.bess_capability_v2 import (
    BESSParametersV2,
    BESSStateV2,
    CapabilityTruthV2,
    step_bess_v2,
)
from direction1freq.models.plant_a_v2 import PublicObservationV2
from direction1freq.models.plant_b_andes_v2 import AndesKundurPlantBV2, PublicPolicy


@dataclass(frozen=True, slots=True)
class NativeTerminalTrace:
    time_s: np.ndarray
    frequency_deviation_hz: np.ndarray
    tie_line_pu: np.ndarray
    sg_valve_increment_pu: np.ndarray
    sg_mechanical_increment_pu: np.ndarray
    bess_power_pu: np.ndarray
    bess_energy_mwh: np.ndarray
    issued_command_pu: np.ndarray
    load_increment_pu: np.ndarray
    valve_boundary_active: np.ndarray
    bess_power_limit_active: np.ndarray
    bess_ramp_limit_active: np.ndarray
    bess_energy_limit_active: np.ndarray
    command_saturated: np.ndarray
    grc_active: np.ndarray
    algebraic_power_balance_p99_pu: float
    converged: bool
    native_network: bool


class Direction5NativePlantB(AndesKundurPlantBV2):
    """ANDES Plant B with terminal-boundary telemetry, not a surrogate."""

    def run_terminal_closed_loop(
        self,
        duration_s: float,
        control_period_s: float,
        load_profile: Callable[[float], np.ndarray],
        policy: PublicPolicy,
        capability_profile: Callable[[float], CapabilityTruthV2] | None = None,
        initial_soc: tuple[float, float] = (0.5, 0.5),
    ) -> NativeTerminalTrace:
        truth_profile = capability_profile or (lambda _time: CapabilityTruthV2())
        system = self._base_system(add_native_events=False)
        system.TDS.config.tf = float(duration_s)
        bess_parameters = BESSParametersV2()
        bess_state = BESSStateV2.equilibrium(bess_parameters, self.dt_s, initial_soc)
        command = np.zeros(4)
        next_control_time = 0.0
        initial_load: dict[str, float] = {}
        initial_tie: float | None = None
        initial_pm: np.ndarray | None = None
        initial_valve: np.ndarray | None = None
        records: list[tuple] = []
        residuals: list[float] = []

        def callback(time_value, active_system) -> None:
            nonlocal bess_state, command, next_control_time
            nonlocal initial_tie, initial_pm, initial_valve
            time_s = float(time_value)
            if active_system.dae.g.size:
                residuals.append(
                    float(np.max(np.abs(active_system.dae.g[active_system.Bus.a.a])))
                )
            if not initial_load:
                initial_load["A"] = float(
                    active_system.PQ.get(src="Req", idx="PQ_0", attr="v")
                )
                initial_load["B"] = float(
                    active_system.PQ.get(src="Req", idx="PQ_1", attr="v")
                )
            area_omega, tie_native, pm_native = self._area_quantities(active_system)
            valve_device = np.asarray(
                active_system.dae.x[
                    np.asarray(active_system.TGOV1.LAG_y.a, dtype=int)
                ],
                dtype=float,
            )
            valve_native = np.array(
                [valve_device[:2].sum(), valve_device[2:].sum()]
            )
            if initial_tie is None:
                initial_tie = tie_native
                initial_pm = pm_native.copy()
                initial_valve = valve_native.copy()
            assert initial_pm is not None and initial_valve is not None
            tie = (tie_native - initial_tie) / self.external_to_andes_pu
            mechanical = (pm_native - initial_pm) / self.external_to_andes_pu
            valve = (valve_native - initial_valve) / self.external_to_andes_pu
            ace = np.array(
                [21.0 * area_omega[0] + tie, 21.0 * area_omega[1] - tie]
            )
            observation = PublicObservationV2(
                time_s=time_s,
                frequency_deviation_hz=self.nominal_frequency_hz * area_omega,
                ace_pu=ace,
                tie_line_pu=tie,
                sg_mechanical_power_pu=mechanical.copy(),
                bess_power_pu=bess_state.power_pu.copy(),
                issued_command_pu=command.copy(),
            )
            command_saturated = False
            if time_s + 1e-9 >= next_control_time:
                command = np.asarray(policy(observation), dtype=float)
                if command.shape != (4,):
                    raise ValueError("Plant-B policy must return four commands")
                command_saturated = bool(
                    getattr(policy, "last_command_saturated", False)
                )
                next_control_time += control_period_s
            truth = truth_profile(time_s)
            bess_state, bess_diag = step_bess_v2(
                bess_state,
                area_omega,
                command[[1, 3]],
                bess_parameters,
                truth,
                self.dt_s,
            )
            load = np.asarray(load_profile(time_s), dtype=float)
            active_system.PQ.set(
                src="Req",
                idx="PQ_0",
                attr="v",
                value=initial_load["A"] + load[0] * self.external_to_andes_pu,
            )
            active_system.PQ.set(
                src="Req",
                idx="PQ_1",
                attr="v",
                value=initial_load["B"] + load[1] * self.external_to_andes_pu,
            )
            voltage_refs = (0.97928, 0.89054)
            for area, device in enumerate(self.bess_device_ids):
                native_power = bess_state.power_pu[area] * self.external_to_andes_pu
                active_system.Shunt.set(
                    src="g",
                    idx=device,
                    attr="v",
                    value=-native_power / voltage_refs[area] ** 2,
                )
            native_sg_area = command[[0, 2]] * self.external_to_andes_pu
            active_system.TGOV1.paux0.v[:] = np.asarray(
                active_system.TGOV1.R.v
            ) * np.repeat(0.5 * native_sg_area, 2)
            lower = np.asarray(active_system.TGOV1.VMIN.v, dtype=float)
            upper = np.asarray(active_system.TGOV1.VMAX.v, dtype=float)
            valve_at_bound = bool(
                np.any(valve_device <= lower + 1e-5)
                or np.any(valve_device >= upper - 1e-5)
            )
            records.append(
                (
                    time_s,
                    area_omega.copy(),
                    tie,
                    valve.copy(),
                    mechanical.copy(),
                    bess_state.power_pu.copy(),
                    bess_state.energy_mwh.copy(),
                    command.copy(),
                    load.copy(),
                    valve_at_bound,
                    bool(np.any(bess_diag.power_saturation)),
                    bool(
                        np.any(
                            np.isclose(
                                np.abs(bess_diag.actual_ramp_pu_per_s),
                                np.maximum(
                                    bess_diag.capability.ramp_up_pu_per_s,
                                    bess_diag.capability.ramp_down_pu_per_s,
                                ),
                                rtol=0.0,
                                atol=1e-8,
                            )
                        )
                    ),
                    bool(np.any(bess_diag.energy_boundary_active)),
                    command_saturated,
                )
            )

        system.TDS.callpert = callback
        success = system.TDS.run(no_summary=True)
        if not success:
            raise RuntimeError(f"ANDES native terminal trace failed: {system.TDS.err_msg}")
        by_time = {round(row[0], 10): row for row in records}
        ordered = [by_time[key] for key in sorted(by_time)]
        time = np.asarray([row[0] for row in ordered], dtype=float)
        mechanical = np.vstack([row[4] for row in ordered])
        rate = np.zeros_like(mechanical)
        if len(time) > 1:
            rate[1:] = np.diff(mechanical, axis=0) / np.maximum(
                np.diff(time)[:, None], 1e-9
            )
        grc_active = np.any(
            np.c_[rate[:, 0] >= 0.012 - 1e-6, rate[:, 1] >= 0.012 - 1e-6]
            | np.c_[rate[:, 0] <= -0.015 + 1e-6, rate[:, 1] <= -0.015 + 1e-6],
            axis=1,
        )
        return NativeTerminalTrace(
            time_s=time,
            frequency_deviation_hz=self.nominal_frequency_hz
            * np.vstack([row[1] for row in ordered]),
            tie_line_pu=np.asarray([row[2] for row in ordered]),
            sg_valve_increment_pu=np.vstack([row[3] for row in ordered]),
            sg_mechanical_increment_pu=mechanical,
            bess_power_pu=np.vstack([row[5] for row in ordered]),
            bess_energy_mwh=np.vstack([row[6] for row in ordered]),
            issued_command_pu=np.vstack([row[7] for row in ordered]),
            load_increment_pu=np.vstack([row[8] for row in ordered]),
            valve_boundary_active=np.asarray([row[9] for row in ordered]),
            bess_power_limit_active=np.asarray([row[10] for row in ordered]),
            bess_ramp_limit_active=np.asarray([row[11] for row in ordered]),
            bess_energy_limit_active=np.asarray([row[12] for row in ordered]),
            command_saturated=np.asarray([row[13] for row in ordered]),
            grc_active=grc_active,
            algebraic_power_balance_p99_pu=float(np.quantile(residuals, 0.99)),
            converged=bool(system.TDS.converged and not system.TDS.busted),
            native_network=True,
        )
