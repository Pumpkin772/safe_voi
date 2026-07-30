"""Corrected transparent two-area frequency-control Plant A."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import numpy as np

from .bess_capability import BESSParameters, BESSState, BESSStepResult, step_bess
from .sg_governor_turbine import SGParameters, SGState, step_sg


@dataclass(frozen=True, slots=True)
class AreaParameters:
    inertia_s: float = 5.0
    damping_pu_power_per_pu_frequency: float = 1.0
    sg: SGParameters = field(default_factory=SGParameters)
    bess: BESSParameters = field(default_factory=BESSParameters)


@dataclass(frozen=True, slots=True)
class PlantAParameters:
    nominal_frequency_hz: float = 50.0
    system_base_mw: float = 1000.0
    tie_coefficient_pu_per_rad: float = 0.07
    upper_control_period_s: float = 2.0
    area1: AreaParameters = field(default_factory=AreaParameters)
    area2: AreaParameters = field(default_factory=lambda: AreaParameters(inertia_s=4.5))


@dataclass(frozen=True, slots=True)
class PlantAState:
    omega: np.ndarray
    tie_pu: float
    sg: tuple[SGState, SGState]
    bess: tuple[BESSState, BESSState]

    @classmethod
    def equilibrium(cls, params: PlantAParameters, soc: float = 0.5) -> "PlantAState":
        return cls(
            omega=np.zeros(2, dtype=float), tie_pu=0.0,
            sg=(SGState(), SGState()),
            bess=(
                BESSState(energy_mwh=soc * params.area1.bess.energy_mwh),
                BESSState(energy_mwh=soc * params.area2.bess.energy_mwh),
            ),
        )


@dataclass(frozen=True, slots=True)
class CapabilityRegime:
    availability: tuple[float, float] = (1.0, 1.0)
    headroom_fraction: tuple[float, float] = (1.0, 1.0)
    ramp_fraction: tuple[float, float] = (1.0, 1.0)
    delay_s: tuple[float, float] = (0.0, 0.0)


class PlantATwoArea:
    """Discrete co-simulation; commands are held between 2/4 s updates."""

    def __init__(self, params: PlantAParameters | None = None, dt_s: float = 0.01) -> None:
        self.params = PlantAParameters() if params is None else params
        if dt_s <= 0:
            raise ValueError("dt_s must be positive")
        self.dt_s = float(dt_s)

    def ace(self, state: PlantAState) -> np.ndarray:
        p = self.params
        b1 = p.area1.damping_pu_power_per_pu_frequency + 1 / p.area1.sg.droop_pu_frequency_per_pu_power
        b2 = p.area2.damping_pu_power_per_pu_frequency + 1 / p.area2.sg.droop_pu_frequency_per_pu_power
        return np.array([b1 * state.omega[0] + state.tie_pu, b2 * state.omega[1] - state.tie_pu])

    def initial_rocof_hz_s(self, load_step_pu: tuple[float, float]) -> np.ndarray:
        return self.params.nominal_frequency_hz * np.array([
            -load_step_pu[0] / (2 * self.params.area1.inertia_s),
            -load_step_pu[1] / (2 * self.params.area2.inertia_s),
        ])

    def step(
        self, state: PlantAState, command: np.ndarray, load_pu: np.ndarray,
        regime: CapabilityRegime | None = None,
    ) -> tuple[PlantAState, tuple[BESSStepResult, BESSStepResult]]:
        """Advance [ug1, ub1, ug2, ub2]; no hidden quantity is returned to a controller."""
        command = np.asarray(command, dtype=float)
        load_pu = np.asarray(load_pu, dtype=float)
        if command.shape != (4,) or load_pu.shape != (2,):
            raise ValueError("command must have 4 and load 2 elements")
        r = CapabilityRegime() if regime is None else regime
        areas = (self.params.area1, self.params.area2)
        sg_next: list[SGState] = []
        bess_next: list[BESSState] = []
        bresults: list[BESSStepResult] = []
        for i, area in enumerate(areas):
            sg_next.append(step_sg(state.sg[i], area.sg, state.omega[i], command[2*i], self.dt_s))
            br = step_bess(
                state.bess[i], area.bess, state.omega[i], command[2*i+1], self.dt_s,
                availability=r.availability[i], headroom_fraction=r.headroom_fraction[i],
                ramp_fraction=r.ramp_fraction[i],
            )
            bresults.append(br)
            bess_next.append(br.state)
        omega_dot = np.empty(2)
        omega_dot[0] = (sg_next[0].mechanical_pu + bess_next[0].power_pu - load_pu[0]
                        - self.params.area1.damping_pu_power_per_pu_frequency * state.omega[0] - state.tie_pu) / (2*self.params.area1.inertia_s)
        omega_dot[1] = (sg_next[1].mechanical_pu + bess_next[1].power_pu - load_pu[1]
                        - self.params.area2.damping_pu_power_per_pu_frequency * state.omega[1] + state.tie_pu) / (2*self.params.area2.inertia_s)
        tie_dot = 2 * math.pi * self.params.nominal_frequency_hz * self.params.tie_coefficient_pu_per_rad * (state.omega[0] - state.omega[1])
        next_state = PlantAState(
            omega=state.omega + self.dt_s * omega_dot,
            tie_pu=state.tie_pu + self.dt_s * tie_dot,
            sg=(sg_next[0], sg_next[1]), bess=(bess_next[0], bess_next[1]),
        )
        return next_state, (bresults[0], bresults[1])

    def observation(self, state: PlantAState, issued_command: np.ndarray) -> np.ndarray:
        """Only measurable signals; true load/regime/energy are excluded."""
        ace = self.ace(state)
        return np.array([
            *(self.params.nominal_frequency_hz * state.omega), *ace, state.tie_pu,
            state.sg[0].mechanical_pu, state.sg[1].mechanical_pu,
            state.bess[0].power_pu, state.bess[1].power_pu, *np.asarray(issued_command),
        ])
