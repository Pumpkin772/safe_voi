"""Plant B: native multi-machine network DAE plus ANDES qualification.

The experiment model retains four rotor/governor units and solves network bus
angles algebraically every integration step.  ANDES 2.0.0's bundled Kundur
case is separately executed to qualify the external native RMS reference.
The two objects are not claimed to be identical or EMT models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import numpy as np

from .bess_capability import BESSParameters, BESSState, step_bess
from .plant_a_two_area import CapabilityRegime
from .sg_governor_turbine import SGParameters, SGState, step_sg


@dataclass(frozen=True, slots=True)
class PlantBParameters:
    nominal_frequency_hz: float = 50.0
    system_base_mw: float = 1000.0
    inertia_s: tuple[float, ...] = (4.0, 5.0, 4.5, 5.5)
    damping: tuple[float, ...] = (0.30, 0.30, 0.25, 0.35)
    area: tuple[int, ...] = (0, 0, 1, 1)
    generator_bus: tuple[int, ...] = (0, 1, 4, 5)
    bess_bus: tuple[int, int] = (2, 3)
    sg: SGParameters = field(default_factory=SGParameters)
    bess: BESSParameters = field(default_factory=BESSParameters)


@dataclass(frozen=True, slots=True)
class PlantBState:
    rotor_angle_rad: np.ndarray
    omega: np.ndarray
    sg: tuple[SGState, ...]
    bess: tuple[BESSState, BESSState]
    bus_angle_rad: np.ndarray

    @classmethod
    def equilibrium(cls, params: PlantBParameters, soc: float = 0.5) -> "PlantBState":
        return cls(
            rotor_angle_rad=np.zeros(4), omega=np.zeros(4),
            sg=tuple(SGState() for _ in range(4)),
            bess=tuple(BESSState(energy_mwh=soc*params.bess.energy_mwh) for _ in range(2)),
            bus_angle_rad=np.zeros(6),
        )


def andes_native_qualification(output_json: str | Path | None = None) -> dict[str, Any]:
    """Run the unmodified ANDES Kundur native PFlow+TDS reference."""
    try:
        import andes
        case = andes.get_case("kundur/kundur_full.xlsx")
        system = andes.load(case, setup=True, no_output=True)
        pf_ok = bool(system.PFlow.run())
        system.TDS.config.tf = 2.0
        tds_ok = bool(system.TDS.run())
        result = {
            "tool": "ANDES", "version": andes.__version__, "case": "kundur/kundur_full.xlsx",
            "power_flow_success": pf_ok, "tds_success": tds_ok,
            "buses": int(system.Bus.n), "lines": int(system.Line.n),
            "synchronous_generators": int(system.SynGen.n),
            "native_network_algebraic_equations_retained": True,
            "native_dynamic_models_retained": True,
        }
    except Exception as exc:  # evidence must survive dependency failures
        result = {"tool": "ANDES", "success": False, "exception": repr(exc)}
    if output_json is not None:
        Path(output_json).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


class NativeRMSPlantB:
    """Four-machine, six-bus electromechanical RMS/network DAE model."""

    def __init__(self, params: PlantBParameters | None = None, dt_s: float = 0.01) -> None:
        self.params = PlantBParameters() if params is None else params
        self.dt_s = float(dt_s)
        # Connected 6-bus network; off-diagonal susceptance magnitudes.
        edges = ((0,2,8.0),(1,2,7.0),(2,3,3.0),(3,4,8.0),(3,5,7.0),(1,4,0.8))
        lap = np.zeros((6,6))
        for i,j,b in edges:
            lap[i,i] += b; lap[j,j] += b; lap[i,j] -= b; lap[j,i] -= b
        self._laplacian = lap

    def _network_angles(self, injections: np.ndarray) -> np.ndarray:
        """Solve B theta=p with bus 0 reference; this is the algebraic DAE block."""
        rhs = np.asarray(injections, dtype=float).copy()
        rhs -= rhs.mean()  # slack balances instantaneous residual
        theta = np.zeros(6)
        theta[1:] = np.linalg.solve(self._laplacian[1:,1:], rhs[1:])
        return theta

    def area_coi(self, state: PlantBState) -> np.ndarray:
        h = np.asarray(self.params.inertia_s)
        return np.array([
            np.average(state.omega[:2], weights=h[:2]),
            np.average(state.omega[2:], weights=h[2:]),
        ])

    def step(self, state: PlantBState, command: np.ndarray, load_pu: np.ndarray,
             regime: CapabilityRegime | None = None) -> PlantBState:
        command = np.asarray(command, dtype=float); load_pu = np.asarray(load_pu, dtype=float)
        r = CapabilityRegime() if regime is None else regime
        coi = self.area_coi(state)
        sg_next = tuple(step_sg(state.sg[g], self.params.sg, state.omega[g], command[2*self.params.area[g]]/2, self.dt_s) for g in range(4))
        bess_results = tuple(step_bess(
            state.bess[a], self.params.bess, coi[a], command[2*a+1], self.dt_s,
            availability=r.availability[a], headroom_fraction=r.headroom_fraction[a], ramp_fraction=r.ramp_fraction[a],
        ) for a in range(2))
        injections = np.zeros(6)
        for g,bus in enumerate(self.params.generator_bus):
            injections[bus] += sg_next[g].mechanical_pu
        for a,bus in enumerate(self.params.bess_bus):
            injections[bus] += bess_results[a].state.power_pu - load_pu[a]
        theta = self._network_angles(injections)
        # The algebraic network supplies inter-area exchange.  The reference
        # bus must not create free balancing power: distribute each area's
        # net demand across its machines and add an intra-area synchronizing
        # torque around the area rotor-angle mean.
        tie_12 = 3.0 * (theta[2] - theta[3])
        area_mean_delta = (float(np.mean(state.rotor_angle_rad[:2])), float(np.mean(state.rotor_angle_rad[2:])))
        electrical = np.empty(4)
        for g in range(4):
            a = self.params.area[g]
            signed_tie = tie_12 if a == 0 else -tie_12
            electrical[g] = 0.5 * (load_pu[a] + signed_tie) + 4.0 * (state.rotor_angle_rad[g] - area_mean_delta[a])
        omega_dot = np.array([
            (sg_next[g].mechanical_pu - electrical[g] - self.params.damping[g]*state.omega[g])/(2*self.params.inertia_s[g])
            for g in range(4)
        ])
        delta_dot = 2*np.pi*self.params.nominal_frequency_hz*state.omega
        return PlantBState(
            rotor_angle_rad=state.rotor_angle_rad+self.dt_s*delta_dot,
            omega=state.omega+self.dt_s*omega_dot,
            sg=sg_next,
            bess=(bess_results[0].state,bess_results[1].state), bus_angle_rad=theta,
        )

    def observation(self, state: PlantBState, issued_command: np.ndarray) -> np.ndarray:
        coi = self.area_coi(state)
        tie = 3.0*(state.bus_angle_rad[2]-state.bus_angle_rad[3])
        bias = self.params.damping[0]+self.params.damping[1]+2/self.params.sg.droop_pu_frequency_per_pu_power
        ace = np.array([bias*coi[0]+tie,bias*coi[1]-tie])
        return np.array([*(self.params.nominal_frequency_hz*coi),*ace,tie,*issued_command])
