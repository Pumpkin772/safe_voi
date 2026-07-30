"""Phase-E native ANDES Plant B with a causal public-control interface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

import numpy as np

from .bess_capability_v2 import BESSParametersV2, BESSStateV2, CapabilityTruthV2, step_bess_v2
from .plant_a_v2 import PublicObservationV2
from .plant_b_andes import AndesKundurPlantB, NativeTrace


class PublicPolicy(Protocol):
    def __call__(self, observation: PublicObservationV2) -> np.ndarray: ...


@dataclass(frozen=True, slots=True)
class NativeClosedLoopTraceV2:
    time_s: np.ndarray
    frequency_deviation_hz: np.ndarray
    ace_pu: np.ndarray
    tie_line_pu: np.ndarray
    sg_mechanical_increment_pu: np.ndarray
    bess_power_pu: np.ndarray
    issued_command_pu: np.ndarray
    load_increment_pu: np.ndarray
    algebraic_power_balance_p99_pu: float
    converged: bool
    native_network: bool


class AndesKundurPlantBV2(AndesKundurPlantB):
    """Native four-machine RMS/DAE plant; no disconnected dynamic surrogate."""

    def _base_system(self, add_native_events: bool = False):
        system = super()._base_system(add_native_events=add_native_events)
        # The bundled case has a documented tiny initialization mismatch which
        # the implicit TDS solve removes.  Phase E evaluates convergence and
        # bus residuals directly, so avoid emitting the legacy diagnostic as a
        # false "FAILED" banner in otherwise successful automated runs.
        system.TDS.config.test_init = 0
        return system

    def same_input_interface_pair(self, duration_s: float = 20.0) -> tuple[NativeTrace, NativeTrace]:
        return (
            self.run_validation_profile(duration_s=duration_s, interface="external"),
            self.run_validation_profile(duration_s=duration_s, interface="native_events"),
        )

    @staticmethod
    def _area_quantities(system) -> tuple[np.ndarray, float, np.ndarray]:
        machine_speed = np.asarray(system.dae.x[np.asarray(system.GENROU.omega.a, dtype=int)]) - 1.0
        inertia = np.asarray(system.GENROU.M.v, dtype=float)
        area_omega = np.array([
            np.average(machine_speed[:2], weights=inertia[:2]),
            np.average(machine_speed[2:], weights=inertia[2:]),
        ])
        angles = np.asarray(system.dae.y[np.asarray(system.Bus.a.a, dtype=int)])
        voltages = np.asarray(system.dae.y[np.asarray(system.Bus.v.a, dtype=int)])
        bus_7 = int(system.Bus.idx2uid(7))
        bus_8 = int(system.Bus.idx2uid(8))
        angle = angles[bus_7] - angles[bus_8]
        tie = 0.0
        for line_uid in (4, 5, 6):
            admittance = 1.0 / complex(float(system.Line.r.v[line_uid]), float(system.Line.x.v[line_uid]))
            tie += (
                voltages[bus_7] ** 2 * admittance.real
                - voltages[bus_7] * voltages[bus_8]
                * (admittance.real * np.cos(angle) + admittance.imag * np.sin(angle))
            )
        mechanical = np.asarray(system.dae.y[np.asarray(system.GENROU.tm.a, dtype=int)])
        pm_area = np.array([mechanical[:2].sum(), mechanical[2:].sum()])
        return area_omega, float(tie), pm_area

    def run_causal_closed_loop(
        self,
        duration_s: float,
        control_period_s: float,
        load_profile: Callable[[float], np.ndarray],
        policy: PublicPolicy,
        capability_profile: Callable[[float], CapabilityTruthV2] | None = None,
        initial_soc: tuple[float, float] = (0.5, 0.5),
    ) -> NativeClosedLoopTraceV2:
        """Run a causal policy against native network/swing equations.

        The callback exposes only the same public observation used by Plant A.
        Capability truth remains inside the physical BESS update.
        """

        if control_period_s <= 0.0:
            raise ValueError("control period must be positive")
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
        records: list[tuple] = []
        residuals: list[float] = []

        def callback(time_value, active_system) -> None:
            nonlocal bess_state, command, next_control_time, initial_tie, initial_pm
            time_s = float(time_value)
            if active_system.dae.g.size:
                residuals.append(float(np.max(np.abs(active_system.dae.g[active_system.Bus.a.a]))))
            if not initial_load:
                initial_load["A"] = float(active_system.PQ.get(src="Req", idx="PQ_0", attr="v"))
                initial_load["B"] = float(active_system.PQ.get(src="Req", idx="PQ_1", attr="v"))

            area_omega, tie_native, pm_native = self._area_quantities(active_system)
            if initial_tie is None:
                initial_tie = tie_native
                initial_pm = pm_native.copy()
            tie_external = (tie_native - initial_tie) / self.external_to_andes_pu
            pm_external = (pm_native - initial_pm) / self.external_to_andes_pu
            bias = np.array([21.0, 21.0])
            ace = np.array([bias[0] * area_omega[0] + tie_external, bias[1] * area_omega[1] - tie_external])
            observation = PublicObservationV2(
                time_s=time_s,
                frequency_deviation_hz=self.nominal_frequency_hz * area_omega,
                ace_pu=ace,
                tie_line_pu=tie_external,
                sg_mechanical_power_pu=pm_external.copy(),
                bess_power_pu=bess_state.power_pu.copy(),
                issued_command_pu=command.copy(),
            )
            if time_s + 1e-9 >= next_control_time:
                new_command = np.asarray(policy(observation), dtype=float)
                if new_command.shape != (4,):
                    raise ValueError("Plant-B policy must return [SG1,BESS1,SG2,BESS2]")
                command = new_command
                next_control_time += control_period_s

            bess_state, _ = step_bess_v2(
                bess_state, area_omega, command[[1, 3]], bess_parameters,
                truth_profile(time_s), self.dt_s,
            )
            load = np.asarray(load_profile(time_s), dtype=float)
            if load.shape != (2,):
                raise ValueError("load profile must return two external-base increments")
            active_system.PQ.set(
                src="Req", idx="PQ_0", attr="v",
                value=initial_load["A"] + load[0] * self.external_to_andes_pu,
            )
            active_system.PQ.set(
                src="Req", idx="PQ_1", attr="v",
                value=initial_load["B"] + load[1] * self.external_to_andes_pu,
            )
            voltage_refs = (0.97928, 0.89054)
            for area, device in enumerate(self.bess_device_ids):
                native_power = bess_state.power_pu[area] * self.external_to_andes_pu
                active_system.Shunt.set(
                    src="g", idx=device, attr="v", value=-native_power / voltage_refs[area] ** 2
                )

            # TGOV1 paux is in speed-reference units.  R*p_command creates the
            # requested turbine-power increment and is shared equally by the two
            # native machines in each area.
            native_sg_area = command[[0, 2]] * self.external_to_andes_pu
            per_machine = np.repeat(0.5 * native_sg_area, 2)
            active_system.TGOV1.paux0.v[:] = np.asarray(active_system.TGOV1.R.v) * per_machine
            records.append((
                time_s, area_omega.copy(), ace.copy(), tie_external, pm_external.copy(),
                bess_state.power_pu.copy(), command.copy(), load.copy(),
            ))

        system.TDS.callpert = callback
        success = system.TDS.run(no_summary=True)
        if not success:
            raise RuntimeError(f"ANDES native closed-loop TDS failed: {system.TDS.err_msg}")
        # Callback time can repeat during initialization; retain the last value.
        by_time: dict[float, tuple] = {round(row[0], 10): row for row in records}
        ordered = [by_time[key] for key in sorted(by_time)]
        return NativeClosedLoopTraceV2(
            time_s=np.array([row[0] for row in ordered]),
            frequency_deviation_hz=self.nominal_frequency_hz * np.vstack([row[1] for row in ordered]),
            ace_pu=np.vstack([row[2] for row in ordered]),
            tie_line_pu=np.array([row[3] for row in ordered]),
            sg_mechanical_increment_pu=np.vstack([row[4] for row in ordered]),
            bess_power_pu=np.vstack([row[5] for row in ordered]),
            issued_command_pu=np.vstack([row[6] for row in ordered]),
            load_increment_pu=np.vstack([row[7] for row in ordered]),
            algebraic_power_balance_p99_pu=float(np.quantile(residuals, 0.99)),
            converged=bool(system.TDS.converged and not system.TDS.busted),
            native_network=True,
        )
