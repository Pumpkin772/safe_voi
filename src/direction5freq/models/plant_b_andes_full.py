"""Native ANDES Kundur Plant B with the Phase-I public control interface.

This module contains the complete native bridge used by Phase I.  It does not
call a reduced dynamic surrogate and it intentionally leaves ANDES
initialization diagnostics enabled and auditable.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Callable, Protocol

import numpy as np

from .capability_contract import BESSParameters, BESSState, CapabilityRealization, step_bess
from .plant_a_full import PublicObservation
from .slow_reserve import SlowReserveParameters, SlowReserveState, step_slow_reserve


class PublicPolicy(Protocol):
    def __call__(self, observation: PublicObservation) -> np.ndarray: ...


@dataclass(frozen=True, slots=True)
class NativeClosedLoopTrace:
    time_s: np.ndarray
    frequency_deviation_hz: np.ndarray
    ace_pu: np.ndarray
    tie_line_pu: np.ndarray
    valve_pu: np.ndarray
    sg_mechanical_increment_pu: np.ndarray
    bess_actual_poi_power_pu: np.ndarray
    measured_soc: np.ndarray
    slow_reserve_power_pu: np.ndarray
    issued_command_pu: np.ndarray
    load_increment_pu: np.ndarray
    controller_update_times_s: np.ndarray
    algebraic_power_balance_p99_pu: float
    converged: bool
    native_network: bool
    native_case: str
    initialization_diagnostic_enabled: bool


class PlantBAndesFull:
    """Native 10-bus/four-GENROU RMS/DAE plant with BESS bus injections."""

    native_case = "kundur/kundur_vsc.xlsx"
    external_system_base_mva = 1000.0
    andes_system_base_mva = 100.0
    nominal_frequency_hz = 60.0
    bess_device_ids = ("D5_BESS_A", "D5_BESS_B")
    bess_bus_ids = (5, 9)
    voltage_refs = (0.97928, 0.89054)

    def __init__(self, dt_s: float = 0.02) -> None:
        self.dt_s = float(dt_s)
        if self.dt_s <= 0.0:
            raise ValueError("dt_s must be positive")

    @property
    def external_to_andes_pu(self) -> float:
        return self.external_system_base_mva / self.andes_system_base_mva

    def _base_system(self):
        if os.environ.get("DIRECTION5_RESOURCE_GUARDED") != "1":
            raise RuntimeError(
                "Native ANDES execution is refused outside the Direction5 resource guard."
            )
        import andes
        from andes.system.codegen import CodegenManager
        from andes.utils.paths import get_pycode_path

        pycode_path = Path(get_pycode_path(None, mkdir=False))
        initializer = pycode_path / "__init__.py"
        if not initializer.is_file():
            raise RuntimeError(
                "ANDES generated-code cache is missing. Automatic code generation "
                "is forbidden during a Direction5 simulation; prepare it separately "
                "with one process under the resource guard."
            )
        declared_models = re.findall(
            r"^from \. import ([A-Za-z0-9_]+)",
            initializer.read_text(encoding="utf-8"),
            flags=re.MULTILINE,
        )
        missing = [name for name in declared_models if not (pycode_path / f"{name}.py").is_file()]
        if len(declared_models) < 80 or missing:
            raise RuntimeError(
                "ANDES generated-code cache is incomplete; automatic parallel "
                f"generation is forbidden (declared={len(declared_models)}, missing={missing[:8]})."
            )

        # ANDES normally regenerates stale/missing code using one worker per
        # logical CPU. A cache failure must be explicit here, never an
        # unbounded process-spawn fallback. ``autogen_stale=False`` is the
        # documented multiprocessing-safe load mode; the temporary method
        # guard also refuses generation if importing the cache fails.
        original_prepare = CodegenManager.prepare

        def refuse_automatic_codegen(*_args, **_kwargs):
            raise RuntimeError(
                "ANDES attempted automatic code generation inside a Direction5 "
                "simulation. The run was stopped before child processes were created."
            )

        CodegenManager.prepare = refuse_automatic_codegen
        try:
            system = andes.load(
                andes.get_case(self.native_case),
                setup=False,
                no_output=True,
                autogen_stale=False,
            )
        finally:
            CodegenManager.prepare = original_prepare

        if system is None:
            raise RuntimeError("ANDES failed to load the native Kundur case")
        for idx, bus in zip(self.bess_device_ids, self.bess_bus_ids, strict=True):
            system.add("Shunt", idx=idx, name=idx, bus=bus, Vn=230.0, Sn=100.0, g=0.0, b=0.0)
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
        # Required by Phase I: do not suppress native initialization warnings.
        system.TDS.config.test_init = 1
        return system

    @staticmethod
    def _area_quantities(system) -> tuple[np.ndarray, float, np.ndarray, np.ndarray]:
        machine_speed = np.asarray(system.dae.x[np.asarray(system.GENROU.omega.a, dtype=int)]) - 1.0
        inertia = np.asarray(system.GENROU.M.v, dtype=float)
        area_omega = np.array((
            np.average(machine_speed[:2], weights=inertia[:2]),
            np.average(machine_speed[2:], weights=inertia[2:]),
        ))
        angles = np.asarray(system.dae.y[np.asarray(system.Bus.a.a, dtype=int)])
        voltages = np.asarray(system.dae.y[np.asarray(system.Bus.v.a, dtype=int)])
        bus_7, bus_8 = int(system.Bus.idx2uid(7)), int(system.Bus.idx2uid(8))
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
        pm_area = np.array((mechanical[:2].sum(), mechanical[2:].sum()))
        # ANDES 2.0.0 exposes the governor lag state as ``LAG_y``.  This is the
        # native TGOV1 valve/servo state; it is not reconstructed by a reduced
        # surrogate.
        valve = np.asarray(system.dae.x[np.asarray(system.TGOV1.LAG_y.a, dtype=int)])
        valve_area = np.array((valve[:2].mean(), valve[2:].mean()))
        return area_omega, float(tie), pm_area, valve_area

    def run_causal_closed_loop(
        self,
        duration_s: float,
        control_period_s: float,
        load_profile: Callable[[float], np.ndarray],
        policy: PublicPolicy,
        capability_profile: Callable[[float], CapabilityRealization] | None = None,
        slow_reserve_profile: Callable[[float, PublicObservation], np.ndarray] | None = None,
        control_jitter_profile: Callable[[float], float] | None = None,
        initial_soc: tuple[float, float] = (0.5, 0.5),
    ) -> NativeClosedLoopTrace:
        if control_period_s <= 0.0:
            raise ValueError("control period must be positive")
        truth_profile = capability_profile or (lambda _time: CapabilityRealization())
        reserve_policy = slow_reserve_profile or (lambda _time, _observation: np.zeros(2))
        jitter_profile = control_jitter_profile or (lambda _time: 0.0)
        system = self._base_system()
        system.TDS.config.tf = float(duration_s)
        bess_parameters = BESSParameters()
        bess_state = BESSState.equilibrium(bess_parameters, self.dt_s, initial_soc)
        reserve_parameters = SlowReserveParameters()
        reserve_state = SlowReserveState.equilibrium()
        command = np.zeros(4)
        next_control_time = 0.0
        control_times: list[float] = []
        initial_load: dict[str, float] = {}
        initial_tie: float | None = None
        initial_pm: np.ndarray | None = None
        initial_valve: np.ndarray | None = None
        records: list[tuple] = []
        residuals: list[float] = []

        def callback(time_value, active_system) -> None:
            nonlocal bess_state, reserve_state, command, next_control_time
            nonlocal initial_tie, initial_pm, initial_valve
            time_s = float(time_value)
            if active_system.dae.g.size:
                residuals.append(float(np.max(np.abs(active_system.dae.g[active_system.Bus.a.a]))))
            if not initial_load:
                initial_load["A"] = float(active_system.PQ.get(src="Req", idx="PQ_0", attr="v"))
                initial_load["B"] = float(active_system.PQ.get(src="Req", idx="PQ_1", attr="v"))

            area_omega, tie_native, pm_native, valve_native = self._area_quantities(active_system)
            if initial_tie is None:
                initial_tie = tie_native
                initial_pm = pm_native.copy()
                initial_valve = valve_native.copy()
            tie_external = (tie_native - initial_tie) / self.external_to_andes_pu
            pm_external = (pm_native - initial_pm) / self.external_to_andes_pu
            valve_external = (valve_native - initial_valve) / self.external_to_andes_pu
            voltages = np.asarray(active_system.dae.y[np.asarray(active_system.Bus.v.a, dtype=int)])
            poi_actual = np.array([
                bess_state.power_pu[area]
                * (voltages[int(active_system.Bus.idx2uid(bus))] / self.voltage_refs[area]) ** 2
                for area, bus in enumerate(self.bess_bus_ids)
            ])
            bias = np.array((21.0, 21.0))
            ace = np.array((
                bias[0] * area_omega[0] + tie_external,
                bias[1] * area_omega[1] - tie_external,
            ))
            observation = PublicObservation(
                time_s=time_s,
                frequency_deviation_hz=self.nominal_frequency_hz * area_omega,
                ace_pu=ace,
                tie_line_pu=tie_external,
                valve_pu=valve_external.copy(),
                sg_mechanical_power_pu=pm_external.copy(),
                bess_actual_power_pu=poi_actual.copy(),
                measured_soc=bess_state.measured_soc(bess_parameters),
                slow_reserve_power_pu=reserve_state.power_pu.copy(),
                issued_command_pu=command.copy(),
            )
            if time_s + 1e-9 >= next_control_time:
                new_command = np.asarray(policy(observation), dtype=float)
                if new_command.shape != (4,):
                    raise ValueError("Plant-B policy must return [SG1,BESS1,SG2,BESS2]")
                command = new_command
                control_times.append(time_s)
                while next_control_time <= time_s + 1e-9:
                    jitter_s = float(jitter_profile(time_s))
                    next_control_time += max(
                        control_period_s + jitter_s, 0.5 * control_period_s
                    )

            reserve_request = np.asarray(reserve_policy(time_s, observation), dtype=float)
            reserve_state, _ = step_slow_reserve(reserve_state, reserve_request, reserve_parameters, self.dt_s)
            bess_state, _ = step_bess(
                bess_state,
                area_omega,
                command[[1, 3]],
                bess_parameters,
                truth_profile(time_s),
                self.dt_s,
            )
            load = np.asarray(load_profile(time_s), dtype=float)
            if load.shape != (2,):
                raise ValueError("load profile must return two increments")
            active_system.PQ.set(
                src="Req", idx="PQ_0", attr="v",
                value=initial_load["A"] + load[0] * self.external_to_andes_pu,
            )
            active_system.PQ.set(
                src="Req", idx="PQ_1", attr="v",
                value=initial_load["B"] + load[1] * self.external_to_andes_pu,
            )
            for area, device in enumerate(self.bess_device_ids):
                native_power = bess_state.power_pu[area] * self.external_to_andes_pu
                active_system.Shunt.set(
                    src="g", idx=device, attr="v", value=-native_power / self.voltage_refs[area] ** 2
                )
            native_sg_area = (command[[0, 2]] + reserve_state.power_pu) * self.external_to_andes_pu
            per_machine = np.repeat(0.5 * native_sg_area, 2)
            active_system.TGOV1.paux0.v[:] = np.asarray(active_system.TGOV1.R.v) * per_machine
            records.append((
                time_s, area_omega.copy(), ace.copy(), tie_external,
                valve_external.copy(), pm_external.copy(), poi_actual.copy(),
                bess_state.measured_soc(bess_parameters).copy(), reserve_state.power_pu.copy(),
                command.copy(), load.copy(),
            ))

        system.TDS.callpert = callback
        success = system.TDS.run(no_summary=True)
        if not success:
            raise RuntimeError(f"ANDES native closed-loop TDS failed: {system.TDS.err_msg}")
        by_time: dict[float, tuple] = {round(row[0], 10): row for row in records}
        ordered = [by_time[key] for key in sorted(by_time)]
        return NativeClosedLoopTrace(
            time_s=np.array([row[0] for row in ordered]),
            frequency_deviation_hz=self.nominal_frequency_hz * np.vstack([row[1] for row in ordered]),
            ace_pu=np.vstack([row[2] for row in ordered]),
            tie_line_pu=np.array([row[3] for row in ordered]),
            valve_pu=np.vstack([row[4] for row in ordered]),
            sg_mechanical_increment_pu=np.vstack([row[5] for row in ordered]),
            bess_actual_poi_power_pu=np.vstack([row[6] for row in ordered]),
            measured_soc=np.vstack([row[7] for row in ordered]),
            slow_reserve_power_pu=np.vstack([row[8] for row in ordered]),
            issued_command_pu=np.vstack([row[9] for row in ordered]),
            load_increment_pu=np.vstack([row[10] for row in ordered]),
            controller_update_times_s=np.asarray(control_times),
            algebraic_power_balance_p99_pu=float(np.quantile(residuals, 0.99)),
            converged=bool(system.TDS.converged and not system.TDS.busted),
            native_network=True,
            native_case=self.native_case,
            initialization_diagnostic_enabled=bool(system.TDS.config.test_init),
        )
