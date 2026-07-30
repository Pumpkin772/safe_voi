"""Phase-E transparent two-area Plant A with stable-unit conventions."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .bess_capability_v2 import (
    BESSDiagnosticsV2,
    BESSParametersV2,
    BESSStateV2,
    CapabilityTruthV2,
    step_bess_v2,
)


@dataclass(frozen=True, slots=True)
class PlantAParametersV2:
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
    bess: BESSParametersV2 = field(default_factory=BESSParametersV2)


@dataclass(frozen=True, slots=True)
class PlantAStateV2:
    omega_pu: np.ndarray
    tie_pu: float
    valve_pu: np.ndarray
    mechanical_power_pu: np.ndarray
    bess: BESSStateV2

    @classmethod
    def equilibrium(
        cls, parameters: PlantAParametersV2, dt_s: float, soc: tuple[float, float] = (0.5, 0.5),
    ) -> "PlantAStateV2":
        return cls(
            omega_pu=np.zeros(2), tie_pu=0.0, valve_pu=np.zeros(2), mechanical_power_pu=np.zeros(2),
            bess=BESSStateV2.equilibrium(parameters.bess, dt_s, soc),
        )


@dataclass(frozen=True, slots=True)
class PublicObservationV2:
    time_s: float
    frequency_deviation_hz: np.ndarray
    ace_pu: np.ndarray
    tie_line_pu: float
    sg_mechanical_power_pu: np.ndarray
    bess_power_pu: np.ndarray
    issued_command_pu: np.ndarray


@dataclass(frozen=True, slots=True)
class PlantADiagnosticsV2:
    ace_pu: np.ndarray
    power_balance_residual_pu: np.ndarray
    mechanical_rate_pu_per_s: np.ndarray
    valve_rate_pu_per_s: np.ndarray
    sg_boundary_active: np.ndarray
    bess: BESSDiagnosticsV2


class TwoAreaPlantAV2:
    """Transparent nonlinear aggregate plant used for proofs and experiments."""

    def __init__(self, parameters: PlantAParametersV2 | None = None, dt_s: float = 0.01) -> None:
        self.parameters = PlantAParametersV2() if parameters is None else parameters
        self.dt_s = float(dt_s)
        if abs(self.parameters.bess.system_base_mva - self.parameters.system_base_mva) > 1e-12:
            raise ValueError("Plant and BESS power bases must match")

    def equilibrium(self, soc: tuple[float, float] = (0.5, 0.5)) -> PlantAStateV2:
        return PlantAStateV2.equilibrium(self.parameters, self.dt_s, soc)

    def ace(self, state: PlantAStateV2) -> np.ndarray:
        bias = np.asarray(self.parameters.frequency_bias_pu_power_per_pu_frequency)
        return np.array([
            bias[0] * state.omega_pu[0] + state.tie_pu,
            bias[1] * state.omega_pu[1] - state.tie_pu,
        ])

    def initial_rocof_hz_s(self, load_step_pu: np.ndarray) -> np.ndarray:
        return -self.parameters.nominal_frequency_hz * np.asarray(load_step_pu) / (
            2.0 * np.asarray(self.parameters.inertia_s)
        )

    def _grid_derivative(
        self, vector: np.ndarray, sg_command_pu: np.ndarray, load_pu: np.ndarray, bess_power_pu: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        p = self.parameters
        omega = vector[:2]
        tie = vector[2]
        valve = vector[3:5]
        mechanical = vector[5:7]
        governor_rate = (-valve - omega / np.asarray(p.droop_pu_frequency_per_pu_power) + sg_command_pu) / np.asarray(p.governor_time_constant_s)
        at_valve_upper = valve >= np.asarray(p.valve_upper_pu) - 1e-13
        at_valve_lower = valve <= np.asarray(p.valve_lower_pu) + 1e-13
        governor_rate = np.where(at_valve_upper & (governor_rate > 0.0), 0.0, governor_rate)
        governor_rate = np.where(at_valve_lower & (governor_rate < 0.0), 0.0, governor_rate)

        raw_mechanical_rate = (valve - mechanical) / np.asarray(p.turbine_time_constant_s)
        mechanical_rate = np.minimum(
            np.maximum(raw_mechanical_rate, -np.asarray(p.grc_down_pu_per_s)),
            np.asarray(p.grc_up_pu_per_s),
        )
        at_sg_upper = mechanical >= np.asarray(p.sg_power_upper_pu) - 1e-13
        at_sg_lower = mechanical <= np.asarray(p.sg_power_lower_pu) + 1e-13
        mechanical_rate = np.where(at_sg_upper & (mechanical_rate > 0.0), 0.0, mechanical_rate)
        mechanical_rate = np.where(at_sg_lower & (mechanical_rate < 0.0), 0.0, mechanical_rate)

        signed_tie = np.array([tie, -tie])
        rhs = mechanical + bess_power_pu - load_pu - np.asarray(p.damping_pu_per_pu_frequency) * omega - signed_tie
        omega_rate = rhs / (2.0 * np.asarray(p.inertia_s))
        tie_rate = (
            2.0 * np.pi * p.nominal_frequency_hz * p.tie_coefficient_pu_per_rad
            * (omega[0] - omega[1])
        )
        return np.r_[omega_rate, tie_rate, governor_rate, mechanical_rate], governor_rate, mechanical_rate

    def step(
        self,
        state: PlantAStateV2,
        command_pu: np.ndarray,
        load_pu: np.ndarray,
        capability_truth: CapabilityTruthV2 | None = None,
    ) -> tuple[PlantAStateV2, PlantADiagnosticsV2]:
        command = np.asarray(command_pu, dtype=float)
        load = np.asarray(load_pu, dtype=float)
        if command.shape != (4,):
            raise ValueError("command order is [SG1,BESS1,SG2,BESS2]")
        if load.shape != (2,):
            raise ValueError("load must contain two area increments")
        truth = CapabilityTruthV2() if capability_truth is None else capability_truth
        sg_command = command[[0, 2]]
        bess_command = command[[1, 3]]
        next_bess, bess_diagnostics = step_bess_v2(
            state.bess, state.omega_pu, bess_command, self.parameters.bess, truth, self.dt_s
        )
        average_bess = 0.5 * (state.bess.power_pu + next_bess.power_pu)
        initial = np.r_[state.omega_pu, state.tie_pu, state.valve_pu, state.mechanical_power_pu]

        def derivative(value: np.ndarray) -> np.ndarray:
            return self._grid_derivative(value, sg_command, load, average_bess)[0]

        h = self.dt_s
        k1 = derivative(initial)
        k2 = derivative(initial + 0.5 * h * k1)
        k3 = derivative(initial + 0.5 * h * k2)
        k4 = derivative(initial + h * k3)
        updated = initial + h * (k1 + 2.0 * k2 + 2.0 * k3 + k4) / 6.0

        # These are event-consistent landings at physical valve/mechanical
        # boundaries.  No frequency, energy, or controller-integrator state is reset.
        updated[3:5] = np.minimum(
            np.maximum(updated[3:5], self.parameters.valve_lower_pu), self.parameters.valve_upper_pu
        )
        updated[5:7] = np.minimum(
            np.maximum(updated[5:7], self.parameters.sg_power_lower_pu), self.parameters.sg_power_upper_pu
        )
        next_state = PlantAStateV2(updated[:2], float(updated[2]), updated[3:5], updated[5:7], next_bess)
        rates, valve_rate, mechanical_rate = self._grid_derivative(updated, sg_command, load, next_bess.power_pu)
        lhs = 2.0 * np.asarray(self.parameters.inertia_s) * rates[:2]
        rhs = (
            updated[5:7] + next_bess.power_pu - load
            - np.asarray(self.parameters.damping_pu_per_pu_frequency) * updated[:2]
            - np.array([updated[2], -updated[2]])
        )
        diagnostics = PlantADiagnosticsV2(
            ace_pu=self.ace(next_state),
            power_balance_residual_pu=lhs - rhs,
            mechanical_rate_pu_per_s=mechanical_rate,
            valve_rate_pu_per_s=valve_rate,
            sg_boundary_active=(
                (updated[5:7] <= np.asarray(self.parameters.sg_power_lower_pu) + 1e-12)
                | (updated[5:7] >= np.asarray(self.parameters.sg_power_upper_pu) - 1e-12)
            ),
            bess=bess_diagnostics,
        )
        return next_state, diagnostics

    def public_observation(
        self, time_s: float, state: PlantAStateV2, issued_command_pu: np.ndarray,
    ) -> PublicObservationV2:
        return PublicObservationV2(
            time_s=float(time_s),
            frequency_deviation_hz=self.parameters.nominal_frequency_hz * state.omega_pu.copy(),
            ace_pu=self.ace(state),
            tie_line_pu=float(state.tie_pu),
            sg_mechanical_power_pu=state.mechanical_power_pu.copy(),
            bess_power_pu=state.bess.power_pu.copy(),
            issued_command_pu=np.asarray(issued_command_pu, dtype=float).copy(),
        )

    def linear_continuous_model(
        self, sg_fraction: float = 0.70,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Return xdot=A*x+B*u+E*load, ACE=C*x for nominal design.

        State order is ``omega1, omega2, tie, valve1, valve2, pm1, pm2,
        pb1, pb2``.  ``u`` is one total SFR request per area split using the
        fixed nominal SG fraction; local BESS PFR remains in ``A``.
        """

        p = self.parameters
        a = np.zeros((9, 9))
        b = np.zeros((9, 2))
        e = np.zeros((9, 2))
        h = np.asarray(p.inertia_s)
        damping = np.asarray(p.damping_pu_per_pu_frequency)
        droop = np.asarray(p.droop_pu_frequency_per_pu_power)
        tg = np.asarray(p.governor_time_constant_s)
        tt = np.asarray(p.turbine_time_constant_s)
        tb = p.bess.actuator_time_constant_s
        for area in range(2):
            a[area, area] = -damping[area] / (2.0 * h[area])
            a[area, 5 + area] = 1.0 / (2.0 * h[area])
            a[area, 7 + area] = 1.0 / (2.0 * h[area])
            e[area, area] = -1.0 / (2.0 * h[area])
            a[3 + area, area] = -1.0 / (droop[area] * tg[area])
            a[3 + area, 3 + area] = -1.0 / tg[area]
            b[3 + area, area] = sg_fraction / tg[area]
            a[5 + area, 3 + area] = 1.0 / tt[area]
            a[5 + area, 5 + area] = -1.0 / tt[area]
            a[7 + area, area] = -p.bess.pfr_gain_pu_power_per_pu_frequency / tb
            a[7 + area, 7 + area] = -1.0 / tb
            b[7 + area, area] = (1.0 - sg_fraction) / tb
        tie_gain = 2.0 * np.pi * p.nominal_frequency_hz * p.tie_coefficient_pu_per_rad
        a[0, 2] = -1.0 / (2.0 * h[0])
        a[1, 2] = 1.0 / (2.0 * h[1])
        a[2, 0] = tie_gain
        a[2, 1] = -tie_gain
        c = np.zeros((2, 9))
        bias = np.asarray(p.frequency_bias_pu_power_per_pu_frequency)
        c[0, 0] = bias[0]
        c[1, 1] = bias[1]
        c[0, 2] = 1.0
        c[1, 2] = -1.0
        return a, b, c, e

    def linear_continuous_model_separate(
        self,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Return the nominal model with separate [SG1,B1,SG2,B2] inputs."""

        a, _combined, c, e = self.linear_continuous_model(sg_fraction=0.5)
        p = self.parameters
        b = np.zeros((9, 4))
        b[3, 0] = 1.0 / p.governor_time_constant_s[0]
        b[7, 1] = 1.0 / p.bess.actuator_time_constant_s
        b[4, 2] = 1.0 / p.governor_time_constant_s[1]
        b[8, 3] = 1.0 / p.bess.actuator_time_constant_s
        return a, b, c, e

    @staticmethod
    def state_vector(state: PlantAStateV2) -> np.ndarray:
        return np.r_[
            state.omega_pu, state.tie_pu, state.valve_pu,
            state.mechanical_power_pu, state.bess.power_pu,
        ]
