"""Full nonlinear two-area physical Plant A for Direction5 Phase I."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .capability_contract import (
    BESSDiagnostics,
    BESSParameters,
    BESSState,
    CapabilityRealization,
    step_bess,
)
from .slow_reserve import (
    SlowReserveDiagnostics,
    SlowReserveParameters,
    SlowReserveState,
    step_slow_reserve,
)


@dataclass(frozen=True, slots=True)
class PlantAParameters:
    nominal_frequency_hz: float = 50.0
    system_base_mva: float = 1000.0
    inertia_s: tuple[float, float] = (5.0, 4.5)
    damping_pu_per_pu_frequency: tuple[float, float] = (1.0, 1.0)
    droop_pu_frequency_per_pu_power: tuple[float, float] = (0.05, 0.05)
    frequency_bias_pu_power_per_pu_frequency: tuple[float, float] = (21.0, 21.0)
    tie_coefficient_pu_per_rad: float = 0.07
    governor_time_constant_s: tuple[float, float] = (0.20, 0.25)
    turbine_time_constant_s: tuple[float, float] = (0.50, 0.60)
    grc_up_pu_per_s: tuple[float, float] = (0.012, 0.012)
    grc_down_pu_per_s: tuple[float, float] = (0.015, 0.015)
    valve_lower_pu: tuple[float, float] = (-0.15, -0.15)
    valve_upper_pu: tuple[float, float] = (0.15, 0.15)
    sg_power_lower_pu: tuple[float, float] = (-0.12, -0.12)
    sg_power_upper_pu: tuple[float, float] = (0.12, 0.12)
    bess: BESSParameters = field(default_factory=BESSParameters)
    slow_reserve: SlowReserveParameters = field(default_factory=SlowReserveParameters)


@dataclass(frozen=True, slots=True)
class PlantAState:
    omega_pu: np.ndarray
    tie_pu: float
    valve_pu: np.ndarray
    mechanical_power_pu: np.ndarray
    bess: BESSState
    slow_reserve: SlowReserveState

    @classmethod
    def equilibrium(
        cls,
        parameters: PlantAParameters,
        dt_s: float,
        soc: tuple[float, float] = (0.5, 0.5),
    ) -> "PlantAState":
        return cls(
            omega_pu=np.zeros(2),
            tie_pu=0.0,
            valve_pu=np.zeros(2),
            mechanical_power_pu=np.zeros(2),
            bess=BESSState.equilibrium(parameters.bess, dt_s, soc),
            slow_reserve=SlowReserveState.equilibrium(),
        )


@dataclass(frozen=True, slots=True)
class PublicObservation:
    time_s: float
    frequency_deviation_hz: np.ndarray
    ace_pu: np.ndarray
    tie_line_pu: float
    valve_pu: np.ndarray
    sg_mechanical_power_pu: np.ndarray
    bess_actual_power_pu: np.ndarray
    measured_soc: np.ndarray
    slow_reserve_power_pu: np.ndarray
    issued_command_pu: np.ndarray


@dataclass(frozen=True, slots=True)
class PlantADiagnostics:
    ace_pu: np.ndarray
    power_balance_residual_pu: np.ndarray
    valve_rate_pu_per_s: np.ndarray
    mechanical_rate_pu_per_s: np.ndarray
    valve_boundary_active: np.ndarray
    sg_boundary_active: np.ndarray
    grc_active: np.ndarray
    bess: BESSDiagnostics
    slow_reserve: SlowReserveDiagnostics


class PlantAFull:
    """Transparent nonlinear aggregate plant with RK4 grid dynamics."""

    def __init__(self, parameters: PlantAParameters | None = None, dt_s: float = 0.02) -> None:
        self.parameters = PlantAParameters() if parameters is None else parameters
        self.dt_s = float(dt_s)
        if self.dt_s <= 0.0:
            raise ValueError("dt_s must be positive")
        if abs(self.parameters.bess.system_base_mva - self.parameters.system_base_mva) > 1e-12:
            raise ValueError("Plant and BESS bases must match")

    def equilibrium(self, soc: tuple[float, float] = (0.5, 0.5)) -> PlantAState:
        return PlantAState.equilibrium(self.parameters, self.dt_s, soc)

    def ace(self, state: PlantAState) -> np.ndarray:
        bias = np.asarray(self.parameters.frequency_bias_pu_power_per_pu_frequency)
        return np.array((
            bias[0] * state.omega_pu[0] + state.tie_pu,
            bias[1] * state.omega_pu[1] - state.tie_pu,
        ))

    def initial_rocof_hz_s(self, load_step_pu: np.ndarray) -> np.ndarray:
        return -self.parameters.nominal_frequency_hz * np.asarray(load_step_pu) / (
            2.0 * np.asarray(self.parameters.inertia_s)
        )

    def _grid_derivative(
        self,
        vector: np.ndarray,
        sg_command_pu: np.ndarray,
        load_pu: np.ndarray,
        bess_power_pu: np.ndarray,
        slow_reserve_power_pu: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        p = self.parameters
        omega, tie = vector[:2], vector[2]
        valve, mechanical = vector[3:5], vector[5:7]
        raw_governor = (
            -valve
            - omega / np.asarray(p.droop_pu_frequency_per_pu_power)
            + sg_command_pu
        ) / np.asarray(p.governor_time_constant_s)
        governor_rate = raw_governor.copy()
        at_valve_upper = valve >= np.asarray(p.valve_upper_pu) - 1e-13
        at_valve_lower = valve <= np.asarray(p.valve_lower_pu) + 1e-13
        governor_rate = np.where(at_valve_upper & (governor_rate > 0.0), 0.0, governor_rate)
        governor_rate = np.where(at_valve_lower & (governor_rate < 0.0), 0.0, governor_rate)

        raw_mechanical = (valve - mechanical) / np.asarray(p.turbine_time_constant_s)
        mechanical_rate = np.clip(
            raw_mechanical,
            -np.asarray(p.grc_down_pu_per_s),
            np.asarray(p.grc_up_pu_per_s),
        )
        at_sg_upper = mechanical >= np.asarray(p.sg_power_upper_pu) - 1e-13
        at_sg_lower = mechanical <= np.asarray(p.sg_power_lower_pu) + 1e-13
        mechanical_rate = np.where(at_sg_upper & (mechanical_rate > 0.0), 0.0, mechanical_rate)
        mechanical_rate = np.where(at_sg_lower & (mechanical_rate < 0.0), 0.0, mechanical_rate)

        signed_tie = np.array((tie, -tie))
        rhs = (
            mechanical
            + bess_power_pu
            + slow_reserve_power_pu
            - load_pu
            - np.asarray(p.damping_pu_per_pu_frequency) * omega
            - signed_tie
        )
        omega_rate = rhs / (2.0 * np.asarray(p.inertia_s))
        tie_rate = (
            2.0 * np.pi * p.nominal_frequency_hz * p.tie_coefficient_pu_per_rad
            * (omega[0] - omega[1])
        )
        return (
            np.r_[omega_rate, tie_rate, governor_rate, mechanical_rate],
            raw_governor,
            governor_rate,
            raw_mechanical,
        )

    def step(
        self,
        state: PlantAState,
        command_pu: np.ndarray,
        load_pu: np.ndarray,
        capability_truth: CapabilityRealization | None = None,
        slow_reserve_request_pu: np.ndarray | None = None,
    ) -> tuple[PlantAState, PlantADiagnostics]:
        command = np.asarray(command_pu, dtype=float)
        load = np.asarray(load_pu, dtype=float)
        if command.shape != (4,):
            raise ValueError("command order is [SG1,BESS1,SG2,BESS2]")
        if load.shape != (2,):
            raise ValueError("load must contain two area increments")
        truth = CapabilityRealization() if capability_truth is None else capability_truth
        reserve_request = np.zeros(2) if slow_reserve_request_pu is None else np.asarray(slow_reserve_request_pu, dtype=float)
        if reserve_request.shape != (2,):
            raise ValueError("slow reserve request must contain two areas")

        next_reserve, reserve_diag = step_slow_reserve(
            state.slow_reserve, reserve_request, self.parameters.slow_reserve, self.dt_s
        )
        next_bess, bess_diag = step_bess(
            state.bess,
            state.omega_pu,
            command[[1, 3]],
            self.parameters.bess,
            truth,
            self.dt_s,
        )
        average_bess = 0.5 * (state.bess.power_pu + next_bess.power_pu)
        average_reserve = 0.5 * (state.slow_reserve.power_pu + next_reserve.power_pu)
        initial = np.r_[state.omega_pu, state.tie_pu, state.valve_pu, state.mechanical_power_pu]
        sg_command = command[[0, 2]]

        def derivative(value: np.ndarray) -> np.ndarray:
            return self._grid_derivative(value, sg_command, load, average_bess, average_reserve)[0]

        h = self.dt_s
        k1 = derivative(initial)
        k2 = derivative(initial + 0.5 * h * k1)
        k3 = derivative(initial + 0.5 * h * k2)
        k4 = derivative(initial + h * k3)
        updated = initial + h * (k1 + 2.0 * k2 + 2.0 * k3 + k4) / 6.0
        updated[3:5] = np.clip(updated[3:5], self.parameters.valve_lower_pu, self.parameters.valve_upper_pu)
        updated[5:7] = np.clip(updated[5:7], self.parameters.sg_power_lower_pu, self.parameters.sg_power_upper_pu)
        next_state = PlantAState(
            omega_pu=updated[:2],
            tie_pu=float(updated[2]),
            valve_pu=updated[3:5],
            mechanical_power_pu=updated[5:7],
            bess=next_bess,
            slow_reserve=next_reserve,
        )
        rates, raw_governor, governor_rate, raw_mechanical = self._grid_derivative(
            updated, sg_command, load, next_bess.power_pu, next_reserve.power_pu
        )
        lhs = 2.0 * np.asarray(self.parameters.inertia_s) * rates[:2]
        rhs = (
            updated[5:7]
            + next_bess.power_pu
            + next_reserve.power_pu
            - load
            - np.asarray(self.parameters.damping_pu_per_pu_frequency) * updated[:2]
            - np.array((updated[2], -updated[2]))
        )
        diagnostics = PlantADiagnostics(
            ace_pu=self.ace(next_state),
            power_balance_residual_pu=lhs - rhs,
            valve_rate_pu_per_s=governor_rate,
            mechanical_rate_pu_per_s=np.clip(
                raw_mechanical,
                -np.asarray(self.parameters.grc_down_pu_per_s),
                np.asarray(self.parameters.grc_up_pu_per_s),
            ),
            valve_boundary_active=(
                (updated[3:5] <= np.asarray(self.parameters.valve_lower_pu) + 1e-12)
                | (updated[3:5] >= np.asarray(self.parameters.valve_upper_pu) - 1e-12)
            ),
            sg_boundary_active=(
                (updated[5:7] <= np.asarray(self.parameters.sg_power_lower_pu) + 1e-12)
                | (updated[5:7] >= np.asarray(self.parameters.sg_power_upper_pu) - 1e-12)
            ),
            grc_active=np.abs(raw_mechanical - np.clip(
                raw_mechanical,
                -np.asarray(self.parameters.grc_down_pu_per_s),
                np.asarray(self.parameters.grc_up_pu_per_s),
            )) > 1e-12,
            bess=bess_diag,
            slow_reserve=reserve_diag,
        )
        return next_state, diagnostics

    def public_observation(
        self, time_s: float, state: PlantAState, issued_command_pu: np.ndarray
    ) -> PublicObservation:
        return PublicObservation(
            time_s=float(time_s),
            frequency_deviation_hz=self.parameters.nominal_frequency_hz * state.omega_pu.copy(),
            ace_pu=self.ace(state),
            tie_line_pu=float(state.tie_pu),
            valve_pu=state.valve_pu.copy(),
            sg_mechanical_power_pu=state.mechanical_power_pu.copy(),
            bess_actual_power_pu=state.bess.power_pu.copy(),
            measured_soc=state.bess.measured_soc(self.parameters.bess),
            slow_reserve_power_pu=state.slow_reserve.power_pu.copy(),
            issued_command_pu=np.asarray(issued_command_pu, dtype=float).copy(),
        )

    def linear_continuous_model_separate(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Nominal nine-state model used by estimators and predictive control."""

        p = self.parameters
        a = np.zeros((9, 9)); b = np.zeros((9, 4)); e = np.zeros((9, 2))
        h = np.asarray(p.inertia_s); damping = np.asarray(p.damping_pu_per_pu_frequency)
        droop = np.asarray(p.droop_pu_frequency_per_pu_power)
        tg = np.asarray(p.governor_time_constant_s); tt = np.asarray(p.turbine_time_constant_s)
        tb = p.bess.actuator_time_constant_s
        for area in range(2):
            a[area, area] = -damping[area] / (2.0 * h[area])
            a[area, 5 + area] = 1.0 / (2.0 * h[area])
            a[area, 7 + area] = 1.0 / (2.0 * h[area])
            e[area, area] = -1.0 / (2.0 * h[area])
            a[3 + area, area] = -1.0 / (droop[area] * tg[area])
            a[3 + area, 3 + area] = -1.0 / tg[area]
            a[5 + area, 3 + area] = 1.0 / tt[area]
            a[5 + area, 5 + area] = -1.0 / tt[area]
            a[7 + area, area] = -p.bess.pfr_gain_pu_power_per_pu_frequency / tb
            a[7 + area, 7 + area] = -1.0 / tb
        gain = 2.0 * np.pi * p.nominal_frequency_hz * p.tie_coefficient_pu_per_rad
        a[0, 2] = -1.0 / (2.0 * h[0]); a[1, 2] = 1.0 / (2.0 * h[1])
        a[2, 0] = gain; a[2, 1] = -gain
        b[3, 0] = 1.0 / tg[0]; b[7, 1] = 1.0 / tb
        b[4, 2] = 1.0 / tg[1]; b[8, 3] = 1.0 / tb
        c = np.zeros((2, 9)); bias = np.asarray(p.frequency_bias_pu_power_per_pu_frequency)
        c[0, 0] = bias[0]; c[1, 1] = bias[1]; c[0, 2] = 1.0; c[1, 2] = -1.0
        return a, b, c, e

    @staticmethod
    def state_vector(state: PlantAState) -> np.ndarray:
        return np.r_[
            state.omega_pu,
            state.tie_pu,
            state.valve_pu,
            state.mechanical_power_pu,
            state.bess.power_pu,
        ]
