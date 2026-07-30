"""Transparent two-area aggregate Plant A with correct units and GRC."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .bess import BESSDiagnostics, BESSFleetState, BESSParameters, CapabilityRegime, step_bess_fleet


@dataclass(frozen=True, slots=True)
class PlantAParameters:
    nominal_frequency_hz: float = 50.0
    system_base_mva: float = 1000.0
    inertia_s: tuple[float, float] = (5.0, 4.5)
    damping_pu_per_pu_frequency: tuple[float, float] = (1.0, 1.0)
    droop_pu_frequency_per_pu_power: tuple[float, float] = (0.05, 0.05)
    tie_coefficient_pu_per_rad: float = 0.07
    governor_time_constant_s: tuple[float, float] = (0.20, 0.25)
    turbine_time_constant_s: tuple[float, float] = (0.50, 0.60)
    grc_up_pu_per_s: tuple[float, float] = (0.012, 0.012)
    grc_down_pu_per_s: tuple[float, float] = (0.015, 0.015)
    sg_power_lower_pu: tuple[float, float] = (-0.12, -0.12)
    sg_power_upper_pu: tuple[float, float] = (0.12, 0.12)
    bess: BESSParameters = field(default_factory=BESSParameters)


@dataclass(frozen=True, slots=True)
class PlantAState:
    omega_pu: np.ndarray
    tie_pu: float
    valve_pu: np.ndarray
    mechanical_power_pu: np.ndarray
    bess: BESSFleetState

    @classmethod
    def equilibrium(
        cls, params: PlantAParameters, dt_s: float, soc: tuple[float, float] = (0.5, 0.5),
    ) -> "PlantAState":
        return cls(np.zeros(2), 0.0, np.zeros(2), np.zeros(2), BESSFleetState.equilibrium(params.bess, dt_s, soc))


@dataclass(frozen=True, slots=True)
class PlantADiagnostics:
    ace_pu: np.ndarray
    power_balance_residual_pu: np.ndarray
    mechanical_rate_pu_per_s: np.ndarray
    bess: BESSDiagnostics


class TwoAreaPlantA:
    def __init__(self, params: PlantAParameters | None = None, dt_s: float = 0.01) -> None:
        self.params = PlantAParameters() if params is None else params
        self.dt_s = float(dt_s)

    def equilibrium(self, soc: tuple[float, float] = (0.5, 0.5)) -> PlantAState:
        return PlantAState.equilibrium(self.params, self.dt_s, soc)

    def ace(self, state: PlantAState) -> np.ndarray:
        p = self.params
        bias = np.asarray(p.damping_pu_per_pu_frequency) + 1.0 / np.asarray(p.droop_pu_frequency_per_pu_power)
        return np.array([bias[0] * state.omega_pu[0] + state.tie_pu, bias[1] * state.omega_pu[1] - state.tie_pu])

    def initial_rocof_hz_s(self, load_step_pu: np.ndarray) -> np.ndarray:
        return -self.params.nominal_frequency_hz * np.asarray(load_step_pu) / (2.0 * np.asarray(self.params.inertia_s))

    def _grid_derivative(
        self, x: np.ndarray, sg_command: np.ndarray, load_pu: np.ndarray, bess_power_pu: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        p = self.params
        omega = x[:2]; tie = x[2]; valve = x[3:5]; pm = x[5:7]
        h = np.asarray(p.inertia_s); damping = np.asarray(p.damping_pu_per_pu_frequency)
        droop = np.asarray(p.droop_pu_frequency_per_pu_power)
        tg = np.asarray(p.governor_time_constant_s); tt = np.asarray(p.turbine_time_constant_s)
        valve_dot = (-valve - omega / droop + sg_command) / tg
        raw_pm_dot = (valve - pm) / tt
        pm_dot = np.clip(raw_pm_dot, -np.asarray(p.grc_down_pu_per_s), np.asarray(p.grc_up_pu_per_s))
        at_upper = pm >= np.asarray(p.sg_power_upper_pu) - 1e-13
        at_lower = pm <= np.asarray(p.sg_power_lower_pu) + 1e-13
        pm_dot = np.where(at_upper & (pm_dot > 0), 0.0, pm_dot)
        pm_dot = np.where(at_lower & (pm_dot < 0), 0.0, pm_dot)
        rhs = pm + bess_power_pu - load_pu - damping * omega - np.array([tie, -tie])
        omega_dot = rhs / (2.0 * h)
        tie_dot = 2.0 * np.pi * p.nominal_frequency_hz * p.tie_coefficient_pu_per_rad * (omega[0] - omega[1])
        return np.r_[omega_dot, tie_dot, valve_dot, pm_dot], pm_dot

    def step(
        self, state: PlantAState, command_pu: np.ndarray, load_pu: np.ndarray,
        regime: CapabilityRegime | None = None,
    ) -> tuple[PlantAState, PlantADiagnostics]:
        command = np.asarray(command_pu, dtype=float)
        if command.shape != (4,):
            raise ValueError("command_pu must have shape (4,) ordered [SG1,BESS1,SG2,BESS2]")
        load = np.asarray(load_pu, dtype=float)
        truth = CapabilityRegime() if regime is None else regime
        sg_command = command[[0, 2]]; bess_command = command[[1, 3]]
        next_bess, bess_diag = step_bess_fleet(state.bess, state.omega_pu, bess_command, self.params.bess, truth, self.dt_s)
        average_bess = 0.5 * (state.bess.power_pu + next_bess.power_pu)
        x0 = np.r_[state.omega_pu, state.tie_pu, state.valve_pu, state.mechanical_power_pu]
        derivative = lambda value: self._grid_derivative(value, sg_command, load, average_bess)[0]
        h = self.dt_s
        k1 = derivative(x0); k2 = derivative(x0 + 0.5 * h * k1)
        k3 = derivative(x0 + 0.5 * h * k2); k4 = derivative(x0 + h * k3)
        x1 = x0 + h * (k1 + 2 * k2 + 2 * k3 + k4) / 6.0
        # Event-consistent boundary landing; no SoC or state reset is used.
        x1[5:7] = np.minimum(np.maximum(x1[5:7], self.params.sg_power_lower_pu), self.params.sg_power_upper_pu)
        next_state = PlantAState(x1[:2], float(x1[2]), x1[3:5], x1[5:7], next_bess)
        dx, pm_rate = self._grid_derivative(x1, sg_command, load, next_bess.power_pu)
        lhs = 2.0 * np.asarray(self.params.inertia_s) * dx[:2]
        rhs = x1[5:7] + next_bess.power_pu - load - np.asarray(self.params.damping_pu_per_pu_frequency) * x1[:2] - np.array([x1[2], -x1[2]])
        diag = PlantADiagnostics(self.ace(next_state), lhs - rhs, pm_rate, bess_diag)
        return next_state, diag

    def observation(self, state: PlantAState, issued_command_pu: np.ndarray) -> np.ndarray:
        return np.r_[
            self.params.nominal_frequency_hz * state.omega_pu, self.ace(state), state.tie_pu,
            state.mechanical_power_pu, state.bess.power_pu, np.asarray(issued_command_pu, dtype=float),
        ]

