"""Native ANDES Kundur Plant B and its causal external-control bridge.

Plant B is not a separately evolved surrogate.  Both validation paths retain
the unmodified Kundur network algebraic equations, four GENROU machines,
exciters and TGOV1 governors.  Two zero-base PQ devices represent BESS POI
injections; negative ``Ppf`` is an active-power injection solved by the native
network DAE at every time step.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np


@dataclass(frozen=True, slots=True)
class NativeTrace:
    time_s: np.ndarray
    area_frequency_hz: np.ndarray
    coi_frequency_hz: np.ndarray
    tie_line_pu: np.ndarray
    sg_mechanical_power_pu: np.ndarray
    sg_electrical_power_pu: np.ndarray
    load_increment_pu: np.ndarray
    bess_injection_pu: np.ndarray
    algebraic_power_balance_p99_pu: float
    converged: bool
    interface: str


def validation_load_profile(time_s: float) -> np.ndarray:
    return np.array([0.01 if time_s >= 1.0 else 0.0, 0.0])


def validation_bess_profile(time_s: float) -> np.ndarray:
    # A 10-step native ramp avoids an algebraic shock and matches the physical
    # BESS ramp contract.  Both validation interfaces use this exact schedule.
    if time_s < 2.1:
        value = 0.0
    elif time_s <= 3.0:
        value = 0.0005 * min(10, int(np.floor((time_s - 2.0 + 1e-8) / 0.1)))
    elif time_s < 12.1:
        value = 0.005
    elif time_s <= 13.0:
        value = 0.005 - 0.0005 * min(10, int(np.floor((time_s - 12.0 + 1e-8) / 0.1)))
    else:
        value = 0.0
    return np.array([max(value, 0.0), 0.0])


class AndesKundurPlantB:
    """Native 10-bus/four-machine RMS/DAE plant with public-control coupling."""

    native_case = "kundur/kundur_vsc.xlsx"
    external_system_base_mva = 1000.0
    andes_system_base_mva = 100.0
    nominal_frequency_hz = 60.0
    bess_device_ids = ("D1_BESS_A", "D1_BESS_B")
    bess_bus_ids = (5, 9)

    def __init__(self, dt_s: float = 0.01) -> None:
        self.dt_s = float(dt_s)

    @property
    def external_to_andes_pu(self) -> float:
        return self.external_system_base_mva / self.andes_system_base_mva

    def _base_system(self, add_native_events: bool = False):
        import andes

        system = andes.load(andes.get_case(self.native_case), setup=False, no_output=True)
        voltage_refs = (0.97928, 0.89054)  # native Kundur area-interface bus values
        for idx, bus in zip(self.bess_device_ids, self.bess_bus_ids, strict=True):
            # The external physical BESS actuator is coupled as a controllable
            # Norton conductance.  Negative g is active injection in ANDES' bus
            # convention and is solved inside the native network DAE.
            system.add("Shunt", idx=idx, name=idx, bus=bus, Vn=230.0, Sn=100.0, g=0.0, b=0.0)
        if add_native_events:
            gain = self.external_to_andes_pu
            # The bundled Kundur case uses impedance-converted PQ loads in TDS;
            # altering Req is therefore the native, documented load event.
            system.add("Alter", idx="D1_LOAD_STEP", model="PQ", dev="PQ_0", src="Req", attr="v", t=1.0, method="+", amount=0.01 * gain)
            for step in range(1, 11):
                conductance_step = 0.0005 * gain / voltage_refs[0] ** 2
                system.add("Alter", idx=f"D1_BESS_ON_{step:02d}", model="Shunt", dev=self.bess_device_ids[0], src="g", attr="v", t=2.0 + 0.1 * step, method="-", amount=conductance_step)
                system.add("Alter", idx=f"D1_BESS_OFF_{step:02d}", model="Shunt", dev=self.bess_device_ids[0], src="g", attr="v", t=12.0 + 0.1 * step, method="+", amount=conductance_step)
        system.setup()
        if not system.PFlow.run():
            raise RuntimeError("ANDES Kundur native power flow failed")
        system.TDS.config.tstep = self.dt_s
        system.TDS.config.fixt = 1
        system.TDS.config.shrinkt = 1
        system.TDS.config.tol = 1e-7
        system.TDS.config.max_iter = 30
        system.TDS.config.no_tqdm = 1
        system.TDS.config.criteria = 0
        system.TDS.config.test_init = 1
        return system

    def _extract(
        self, system, residuals: list[float], interface: str,
        load_profile: Callable[[float], np.ndarray], bess_profile: Callable[[float], np.ndarray],
    ) -> NativeTrace:
        time = np.asarray(system.dae.ts.t, dtype=float).ravel()
        x = np.asarray(system.dae.ts.x, dtype=float)
        y = np.asarray(system.dae.ts.y, dtype=float)
        order = np.argsort(time, kind="stable")
        time = time[order]; x = x[order]; y = y[order]
        unique = np.r_[True, np.diff(time) > 1e-12]
        time = time[unique]; x = x[unique]; y = y[unique]

        machine_speed = x[:, np.asarray(system.GENROU.omega.a, dtype=int)] - 1.0
        inertia = np.asarray(system.GENROU.M.v, dtype=float)
        area_omega = np.column_stack([
            np.average(machine_speed[:, :2], axis=1, weights=inertia[:2]),
            np.average(machine_speed[:, 2:], axis=1, weights=inertia[2:]),
        ])
        coi_omega = np.average(machine_speed, axis=1, weights=inertia)

        angles = y[:, np.asarray(system.Bus.a.a, dtype=int)]
        voltages = y[:, np.asarray(system.Bus.v.a, dtype=int)]
        bus_7 = int(system.Bus.idx2uid(7)); bus_8 = int(system.Bus.idx2uid(8))
        angle = angles[:, bus_7] - angles[:, bus_8]
        vi = voltages[:, bus_7]; vj = voltages[:, bus_8]
        tie = np.zeros_like(time)
        for line_uid in (4, 5, 6):
            resistance = float(system.Line.r.v[line_uid]); reactance = float(system.Line.x.v[line_uid])
            admittance = 1.0 / complex(resistance, reactance)
            conductance, susceptance = admittance.real, admittance.imag
            tie += vi**2 * conductance - vi * vj * (conductance * np.cos(angle) + susceptance * np.sin(angle))
        tie -= tie[0]

        mechanical = y[:, np.asarray(system.GENROU.tm.a, dtype=int)]
        electrical = y[:, np.asarray(system.GENROU.Pe.a, dtype=int)]
        pm_area = np.column_stack((mechanical[:, :2].sum(axis=1), mechanical[:, 2:].sum(axis=1)))
        pe_area = np.column_stack((electrical[:, :2].sum(axis=1), electrical[:, 2:].sum(axis=1)))
        load = np.vstack([load_profile(float(value)) for value in time])
        bess_uid_a = int(system.Bus.idx2uid(self.bess_bus_ids[0]))
        bess_uid_b = int(system.Bus.idx2uid(self.bess_bus_ids[1]))
        bess_voltage = np.column_stack((voltages[:, bess_uid_a], voltages[:, bess_uid_b]))
        commanded_bess = np.vstack([bess_profile(float(value)) for value in time])
        voltage_refs = np.array([0.97928, 0.89054])
        bess = commanded_bess * (bess_voltage / voltage_refs) ** 2
        p99 = float(np.quantile(np.asarray(residuals, dtype=float), 0.99)) if residuals else float(np.max(np.abs(system.dae.g[system.Bus.a.a])))
        return NativeTrace(
            time_s=time,
            area_frequency_hz=self.nominal_frequency_hz * area_omega,
            coi_frequency_hz=self.nominal_frequency_hz * coi_omega,
            tie_line_pu=tie,
            sg_mechanical_power_pu=pm_area,
            sg_electrical_power_pu=pe_area,
            load_increment_pu=load,
            bess_injection_pu=bess,
            algebraic_power_balance_p99_pu=p99,
            converged=bool(system.TDS.converged and not system.TDS.busted),
            interface=interface,
        )

    def run_validation_profile(self, duration_s: float = 60.0, interface: str = "external") -> NativeTrace:
        """Run identical load/BESS signals by external bridge or native Alter events."""

        if interface not in {"external", "native_events"}:
            raise ValueError(interface)
        system = self._base_system(add_native_events=interface == "native_events")
        system.TDS.config.tf = float(duration_s)
        residuals: list[float] = []
        initial_load: dict[str, float] = {}

        def callback(time_value, active_system) -> None:
            # The callback is invoked before the next implicit DAE step; its inputs
            # are current public time/state only. Record the preceding converged bus residual.
            if active_system.dae.g.size:
                residuals.append(float(np.max(np.abs(active_system.dae.g[active_system.Bus.a.a]))))
            if interface != "external":
                return
            if not initial_load:
                initial_load["A"] = float(active_system.PQ.get(src="Req", idx="PQ_0", attr="v"))
                initial_load["B"] = float(active_system.PQ.get(src="Req", idx="PQ_1", attr="v"))
            load = validation_load_profile(float(time_value)) * self.external_to_andes_pu
            bess = validation_bess_profile(float(time_value)) * self.external_to_andes_pu
            active_system.PQ.set(src="Req", idx="PQ_0", attr="v", value=initial_load["A"] + load[0])
            active_system.PQ.set(src="Req", idx="PQ_1", attr="v", value=initial_load["B"] + load[1])
            voltage_refs = (0.97928, 0.89054)
            active_system.Shunt.set(src="g", idx=self.bess_device_ids[0], attr="v", value=-bess[0] / voltage_refs[0] ** 2)
            active_system.Shunt.set(src="g", idx=self.bess_device_ids[1], attr="v", value=-bess[1] / voltage_refs[1] ** 2)

        system.TDS.callpert = callback
        success = system.TDS.run(no_summary=True)
        if not success:
            raise RuntimeError(f"ANDES native TDS failed: {system.TDS.err_msg}")
        return self._extract(system, residuals, interface, validation_load_profile, validation_bess_profile)

    def run_no_disturbance(self, duration_s: float = 300.0) -> NativeTrace:
        system = self._base_system(add_native_events=False)
        system.TDS.config.tf = float(duration_s)
        residuals: list[float] = []

        def callback(_time_value, active_system) -> None:
            residuals.append(float(np.max(np.abs(active_system.dae.g[active_system.Bus.a.a]))))

        system.TDS.callpert = callback
        if not system.TDS.run(no_summary=True):
            raise RuntimeError(f"ANDES no-disturbance TDS failed: {system.TDS.err_msg}")
        zero = lambda _time: np.zeros(2)
        return self._extract(system, residuals, "external_no_disturbance", zero, zero)
