"""Two-area supplementary-frequency Plant B with physical BESS limits.

The upper layer commands supplementary SG and IBR power. Local governor
droop and optional local IBR droop remain fixed inside the plant. Hidden BESS
regimes, SoC, headroom causes, delays, and internal states are simulator truth
and are intentionally absent from :class:`PlantBObservation`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import math
from numbers import Real
from typing import Any, Mapping, Sequence

import numpy as np
from numpy.typing import ArrayLike, NDArray


FloatArray = NDArray[np.float64]


STATE_NAMES = (
    "frequency_area_1_hz",
    "mechanical_power_area_1_pu",
    "valve_power_area_1_pu",
    "frequency_area_2_hz",
    "mechanical_power_area_2_pu",
    "valve_power_area_2_pu",
    "tie_line_1_to_2_pu",
    "bess_command_state_area_1_pu",
    "bess_power_area_1_pu",
    "bess_soc_area_1",
    "bess_availability_area_1",
    "bess_command_state_area_2_pu",
    "bess_power_area_2_pu",
    "bess_soc_area_2",
    "bess_availability_area_2",
)
STATE_SIZE = len(STATE_NAMES)


class PlantBStateIndex(IntEnum):
    F1 = 0
    PM1 = 1
    PV1 = 2
    F2 = 3
    PM2 = 4
    PV2 = 5
    PTIE12 = 6
    Z1 = 7
    PB1 = 8
    SOC1 = 9
    A1 = 10
    Z2 = 11
    PB2 = 12
    SOC2 = 13
    A2 = 14


AREA_STATE_INDICES = (
    (
        PlantBStateIndex.F1,
        PlantBStateIndex.PM1,
        PlantBStateIndex.PV1,
        PlantBStateIndex.Z1,
        PlantBStateIndex.PB1,
        PlantBStateIndex.SOC1,
        PlantBStateIndex.A1,
    ),
    (
        PlantBStateIndex.F2,
        PlantBStateIndex.PM2,
        PlantBStateIndex.PV2,
        PlantBStateIndex.Z2,
        PlantBStateIndex.PB2,
        PlantBStateIndex.SOC2,
        PlantBStateIndex.A2,
    ),
)


def _finite(value: object, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _positive(value: object, name: str, *, allow_zero: bool = False) -> float:
    number = _finite(value, name)
    if number < 0.0 or (not allow_zero and number == 0.0):
        qualifier = "non-negative" if allow_zero else "strictly positive"
        raise ValueError(f"{name} must be {qualifier}")
    return number


@dataclass(frozen=True, slots=True)
class AreaFrequencyParams:
    area_id: str
    inertia_pu_s_per_hz: float
    load_damping_pu_per_hz: float
    turbine_time_constant_s: float
    governor_time_constant_s: float
    droop_hz_per_pu: float
    ace_bias_pu_per_hz: float

    def __post_init__(self) -> None:
        if not self.area_id:
            raise ValueError("area_id must not be empty")
        for name in (
            "inertia_pu_s_per_hz",
            "turbine_time_constant_s",
            "governor_time_constant_s",
            "droop_hz_per_pu",
            "ace_bias_pu_per_hz",
        ):
            object.__setattr__(self, name, _positive(getattr(self, name), name))
        object.__setattr__(
            self,
            "load_damping_pu_per_hz",
            _positive(
                self.load_damping_pu_per_hz,
                "load_damping_pu_per_hz",
                allow_zero=True,
            ),
        )


@dataclass(frozen=True, slots=True)
class SGCapability:
    reserve_up_pu: tuple[float, float]
    reserve_down_pu: tuple[float, float]
    grc_up_pu_per_s: tuple[float, float]
    grc_down_pu_per_s: tuple[float, float]

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            values = tuple(_positive(value, name) for value in getattr(self, name))
            if len(values) != 2:
                raise ValueError(f"{name} must contain two areas")
            object.__setattr__(self, name, values)

    def engineering_units(self, system_base_mw: float) -> dict[str, tuple[float, float]]:
        base = _positive(system_base_mw, "system_base_mw")
        return {
            "grc_up_pu_per_min": tuple(value * 60.0 for value in self.grc_up_pu_per_s),
            "grc_down_pu_per_min": tuple(
                value * 60.0 for value in self.grc_down_pu_per_s
            ),
            "grc_up_mw_per_min": tuple(
                value * 60.0 * base for value in self.grc_up_pu_per_s
            ),
            "grc_down_mw_per_min": tuple(
                value * 60.0 * base for value in self.grc_down_pu_per_s
            ),
            "reserve_up_mw": tuple(value * base for value in self.reserve_up_pu),
            "reserve_down_mw": tuple(
                value * base for value in self.reserve_down_pu
            ),
        }


@dataclass(frozen=True, slots=True)
class BESSPhysicalParams:
    area_id: str
    system_base_mw: float
    rating_mw: float
    energy_mwh: float
    base_power_mw: float
    reactive_power_mvar: float
    voltage_pu: float
    current_limit_pu_on_system_base: float
    soc_min: float
    soc_max: float
    eta_charge: float
    eta_discharge: float
    sustainable_horizon_s: float
    local_droop_pu_per_hz: float
    nominal_command_time_constant_s: float
    nominal_power_time_constant_s: float
    nominal_ramp_up_pu_per_s: float
    nominal_ramp_down_pu_per_s: float

    def __post_init__(self) -> None:
        if not self.area_id:
            raise ValueError("area_id must not be empty")
        for name in (
            "system_base_mw",
            "rating_mw",
            "energy_mwh",
            "voltage_pu",
            "current_limit_pu_on_system_base",
            "sustainable_horizon_s",
            "nominal_command_time_constant_s",
            "nominal_power_time_constant_s",
            "nominal_ramp_up_pu_per_s",
            "nominal_ramp_down_pu_per_s",
        ):
            object.__setattr__(self, name, _positive(getattr(self, name), name))
        for name in (
            "base_power_mw",
            "reactive_power_mvar",
            "soc_min",
            "soc_max",
            "eta_charge",
            "eta_discharge",
            "local_droop_pu_per_hz",
        ):
            object.__setattr__(self, name, _finite(getattr(self, name), name))
        if not 0.0 <= self.soc_min < self.soc_max <= 1.0:
            raise ValueError("SoC bounds must satisfy 0 <= min < max <= 1")
        if not 0.0 < self.eta_charge <= 1.0 or not 0.0 < self.eta_discharge <= 1.0:
            raise ValueError("charge/discharge efficiency must be in (0, 1]")
        if self.local_droop_pu_per_hz < 0.0:
            raise ValueError("local droop gain must be non-negative")
        if abs(self.base_power_mw) > self.rating_mw:
            raise ValueError("base power must lie inside the BESS rating")

    @property
    def rating_pu(self) -> float:
        return self.rating_mw / self.system_base_mw

    @property
    def base_power_pu(self) -> float:
        return self.base_power_mw / self.system_base_mw

    @property
    def reactive_power_pu(self) -> float:
        return self.reactive_power_mvar / self.system_base_mw

    def raw_headroom(self, soc: float) -> tuple[float, float]:
        """Return physical upward (discharge) and downward headroom in pu."""

        state = float(np.clip(_finite(soc, "soc"), self.soc_min, self.soc_max))
        apparent = math.sqrt(
            max(
                (self.voltage_pu * self.current_limit_pu_on_system_base) ** 2
                - self.reactive_power_pu**2,
                0.0,
            )
        )
        upward_energy = (
            3600.0
            * self.energy_mwh
            * self.eta_discharge
            * (state - self.soc_min)
            / (self.system_base_mw * self.sustainable_horizon_s)
        )
        downward_energy = (
            3600.0
            * self.energy_mwh
            * (self.soc_max - state)
            / (
                self.system_base_mw
                * self.sustainable_horizon_s
                * self.eta_charge
            )
        )
        upward = min(
            self.rating_pu - self.base_power_pu,
            apparent - self.base_power_pu,
            upward_energy,
        )
        downward = min(
            self.rating_pu + self.base_power_pu,
            apparent + self.base_power_pu,
            downward_energy,
        )
        return max(upward, 0.0), max(downward, 0.0)


@dataclass(frozen=True, slots=True)
class IBRRegimeParams:
    regime_id: str
    central_service_enabled: bool
    command_efficiency: float
    command_time_constant_multiplier: float
    power_time_constant_multiplier: float
    command_delay_s: float
    dropout_probability: float
    availability_target: float
    availability_time_constant_s: float
    headroom_up_multiplier: float
    headroom_down_multiplier: float
    ramp_up_multiplier: float
    ramp_down_multiplier: float

    def __post_init__(self) -> None:
        if not self.regime_id:
            raise ValueError("regime_id must not be empty")
        for name in (
            "command_efficiency",
            "command_delay_s",
            "availability_target",
            "headroom_up_multiplier",
            "headroom_down_multiplier",
        ):
            value = _positive(getattr(self, name), name, allow_zero=True)
            object.__setattr__(self, name, value)
        for name in (
            "command_time_constant_multiplier",
            "power_time_constant_multiplier",
            "availability_time_constant_s",
            "ramp_up_multiplier",
            "ramp_down_multiplier",
        ):
            object.__setattr__(self, name, _positive(getattr(self, name), name))
        probability = _finite(self.dropout_probability, "dropout_probability")
        if not 0.0 <= probability <= 1.0:
            raise ValueError("dropout_probability must be in [0, 1]")
        object.__setattr__(self, "dropout_probability", probability)
        if self.availability_target > 1.0:
            raise ValueError("availability_target must not exceed one")


@dataclass(frozen=True, slots=True)
class PlantBParameters:
    system_base_mw: float
    nominal_frequency_hz: float
    integration_step_s: float
    upper_control_period_s: float
    tie_synchronizing_coefficient_pu_per_rad: float
    areas: tuple[AreaFrequencyParams, AreaFrequencyParams]
    sg_capability: SGCapability
    bess: tuple[BESSPhysicalParams, BESSPhysicalParams]
    regimes: Mapping[str, IBRRegimeParams]

    def __post_init__(self) -> None:
        for name in (
            "system_base_mw",
            "nominal_frequency_hz",
            "integration_step_s",
            "upper_control_period_s",
            "tie_synchronizing_coefficient_pu_per_rad",
        ):
            object.__setattr__(self, name, _positive(getattr(self, name), name))
        if len(self.areas) != 2 or len(self.bess) != 2:
            raise ValueError("Plant B requires exactly two areas and two BESS resources")
        steps = self.upper_control_period_s / self.integration_step_s
        if not math.isclose(steps, round(steps), rel_tol=0.0, abs_tol=1.0e-12):
            raise ValueError("upper control period must contain an integer number of steps")
        if not self.regimes:
            raise ValueError("at least one IBR regime is required")


@dataclass(frozen=True, slots=True)
class UpperCommand:
    sg_pu: tuple[float, float] = (0.0, 0.0)
    ibr_pu: tuple[float, float] = (0.0, 0.0)

    def __post_init__(self) -> None:
        for name in ("sg_pu", "ibr_pu"):
            values = tuple(_finite(value, name) for value in getattr(self, name))
            if len(values) != 2:
                raise ValueError(f"{name} must contain two area commands")
            object.__setattr__(self, name, values)


@dataclass(frozen=True, slots=True)
class PlantBObservation:
    time_s: float
    frequency_hz: tuple[float, float]
    tie_line_1_to_2_pu: float
    ace_pu: tuple[float, float]
    bess_poi_power_pu: tuple[float, float]
    sg_mechanical_power_pu: tuple[float, float]
    issued_sg_command_pu: tuple[float, float]
    issued_ibr_command_pu: tuple[float, float]

    def as_array(self) -> FloatArray:
        return np.asarray(
            (
                *self.frequency_hz,
                self.tie_line_1_to_2_pu,
                *self.ace_pu,
                *self.bess_poi_power_pu,
                *self.sg_mechanical_power_pu,
                *self.issued_sg_command_pu,
                *self.issued_ibr_command_pu,
            ),
            dtype=np.float64,
        )


class TwoAreaPlantB:
    """Stateless exact nonlinear dynamics and RK4 integrator for Plant B."""

    state_names = STATE_NAMES
    state_size = STATE_SIZE

    def __init__(self, params: PlantBParameters) -> None:
        if not isinstance(params, PlantBParameters):
            raise TypeError("params must be PlantBParameters")
        self.params = params

    def initial_state(
        self,
        *,
        soc: Sequence[float] = (0.50, 0.50),
        availability: Sequence[float] = (1.0, 1.0),
    ) -> FloatArray:
        if len(soc) != 2 or len(availability) != 2:
            raise ValueError("soc and availability require two values")
        state = np.zeros(STATE_SIZE, dtype=np.float64)
        for area, indices in enumerate(AREA_STATE_INDICES):
            _, _, _, _, pb, soc_index, a_index = indices
            physical = self.params.bess[area]
            state[pb] = physical.base_power_pu
            state[soc_index] = float(np.clip(soc[area], physical.soc_min, physical.soc_max))
            state[a_index] = float(np.clip(availability[area], 0.0, 1.0))
        return state

    def validate_state(self, state: ArrayLike) -> FloatArray:
        values = np.asarray(state, dtype=np.float64)
        if values.shape != (STATE_SIZE,):
            raise ValueError(f"state must have shape ({STATE_SIZE},)")
        if not np.isfinite(values).all():
            raise ValueError("state must be finite")
        return values

    def ace(self, state: ArrayLike) -> tuple[float, float]:
        values = self.validate_state(state)
        tie = float(values[PlantBStateIndex.PTIE12])
        return (
            self.params.areas[0].ace_bias_pu_per_hz
            * float(values[PlantBStateIndex.F1])
            + tie,
            self.params.areas[1].ace_bias_pu_per_hz
            * float(values[PlantBStateIndex.F2])
            - tie,
        )

    def headroom(
        self,
        state: ArrayLike,
        *,
        area: int,
        regime: IBRRegimeParams,
    ) -> tuple[float, float]:
        values = self.validate_state(state)
        if area not in (0, 1):
            raise ValueError("area must be 0 or 1")
        *_, soc_index, a_index = AREA_STATE_INDICES[area]
        upward, downward = self.params.bess[area].raw_headroom(values[soc_index])
        availability = float(np.clip(values[a_index], 0.0, 1.0))
        if not regime.central_service_enabled:
            return 0.0, 0.0
        return (
            availability * regime.headroom_up_multiplier * upward,
            availability * regime.headroom_down_multiplier * downward,
        )

    def derivative(
        self,
        state: ArrayLike,
        *,
        command: UpperCommand,
        delayed_ibr_command_pu: Sequence[float],
        load_disturbance_pu: Sequence[float],
        regimes: Sequence[IBRRegimeParams],
    ) -> FloatArray:
        values = self.validate_state(state)
        if len(delayed_ibr_command_pu) != 2 or len(load_disturbance_pu) != 2:
            raise ValueError("delayed commands and loads require two values")
        if len(regimes) != 2:
            raise ValueError("two current regimes are required")
        derivative = np.zeros(STATE_SIZE, dtype=np.float64)
        tie = float(values[PlantBStateIndex.PTIE12])
        frequencies = (
            float(values[PlantBStateIndex.F1]),
            float(values[PlantBStateIndex.F2]),
        )
        for area, indices in enumerate(AREA_STATE_INDICES):
            frequency_index, pm_index, pv_index, z_index, pb_index, soc_index, a_index = indices
            area_params = self.params.areas[area]
            physical = self.params.bess[area]
            regime = regimes[area]
            frequency = float(values[frequency_index])
            pm = float(values[pm_index])
            pv = float(values[pv_index])
            z_command = float(values[z_index])
            pb = float(values[pb_index])
            availability = float(np.clip(values[a_index], 0.0, 1.0))
            tie_export = tie if area == 0 else -tie
            derivative[frequency_index] = (
                -area_params.load_damping_pu_per_hz * frequency
                + pm
                + pb
                - float(load_disturbance_pu[area])
                - tie_export
            ) / area_params.inertia_pu_s_per_hz
            raw_pm_rate = (-pm + pv) / area_params.turbine_time_constant_s
            derivative[pm_index] = float(
                np.clip(
                    raw_pm_rate,
                    -self.params.sg_capability.grc_down_pu_per_s[area],
                    self.params.sg_capability.grc_up_pu_per_s[area],
                )
            )
            derivative[pv_index] = (
                -pv
                - frequency / area_params.droop_hz_per_pu
                + command.sg_pu[area]
            ) / area_params.governor_time_constant_s
            central_target = (
                regime.command_efficiency * float(delayed_ibr_command_pu[area])
                if regime.central_service_enabled
                else 0.0
            )
            command_tau = (
                physical.nominal_command_time_constant_s
                * regime.command_time_constant_multiplier
            )
            derivative[z_index] = (-z_command + central_target) / command_tau
            head_up, head_down = self.headroom(values, area=area, regime=regime)
            central_power = float(np.clip(z_command, -head_down, head_up))
            local_power = -physical.local_droop_pu_per_hz * frequency
            p_reference = float(
                np.clip(
                    physical.base_power_pu + local_power + central_power,
                    -physical.rating_pu,
                    physical.rating_pu,
                )
            )
            raw_pb_rate = (
                p_reference - pb
            ) / (physical.nominal_power_time_constant_s * regime.power_time_constant_multiplier)
            derivative[pb_index] = float(
                np.clip(
                    raw_pb_rate,
                    -physical.nominal_ramp_down_pu_per_s * regime.ramp_down_multiplier,
                    physical.nominal_ramp_up_pu_per_s * regime.ramp_up_multiplier,
                )
            )
            relative_power = pb - physical.base_power_pu
            if relative_power >= 0.0:
                energy_term = relative_power / physical.eta_discharge
            else:
                energy_term = physical.eta_charge * relative_power
            derivative[soc_index] = -(
                physical.system_base_mw / (3600.0 * physical.energy_mwh)
            ) * energy_term
            derivative[a_index] = (
                regime.availability_target - availability
            ) / regime.availability_time_constant_s
        derivative[PlantBStateIndex.PTIE12] = (
            2.0
            * math.pi
            * self.params.tie_synchronizing_coefficient_pu_per_rad
            * (frequencies[0] - frequencies[1])
        )
        return derivative

    def project_state(self, state: ArrayLike) -> FloatArray:
        output = self.validate_state(state).copy()
        for area, indices in enumerate(AREA_STATE_INDICES):
            _, pm_index, pv_index, _, pb_index, soc_index, a_index = indices
            physical = self.params.bess[area]
            output[pm_index] = np.clip(
                output[pm_index],
                -self.params.sg_capability.reserve_down_pu[area],
                self.params.sg_capability.reserve_up_pu[area],
            )
            output[pv_index] = np.clip(
                output[pv_index],
                -self.params.sg_capability.reserve_down_pu[area],
                self.params.sg_capability.reserve_up_pu[area],
            )
            output[pb_index] = np.clip(
                output[pb_index], -physical.rating_pu, physical.rating_pu
            )
            output[soc_index] = np.clip(
                output[soc_index], physical.soc_min, physical.soc_max
            )
            output[a_index] = np.clip(output[a_index], 0.0, 1.0)
        return output

    def step(
        self,
        state: ArrayLike,
        *,
        command: UpperCommand,
        delayed_ibr_command_pu: Sequence[float],
        load_disturbance_pu: Sequence[float],
        regimes: Sequence[IBRRegimeParams],
        step_s: float | None = None,
    ) -> FloatArray:
        values = self.validate_state(state)
        dt = self.params.integration_step_s if step_s is None else _positive(step_s, "step_s")
        arguments = {
            "command": command,
            "delayed_ibr_command_pu": delayed_ibr_command_pu,
            "load_disturbance_pu": load_disturbance_pu,
            "regimes": regimes,
        }
        k1 = self.derivative(values, **arguments)
        k2 = self.derivative(self.project_state(values + 0.5 * dt * k1), **arguments)
        k3 = self.derivative(self.project_state(values + 0.5 * dt * k2), **arguments)
        k4 = self.derivative(self.project_state(values + dt * k3), **arguments)
        return self.project_state(values + (dt / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4))


class TwoAreaPlantBSimulator:
    """Stateful simulator with command delay/dropout and hidden truth state."""

    def __init__(
        self,
        model: TwoAreaPlantB,
        *,
        initial_state: ArrayLike | None = None,
        initial_regime_ids: Sequence[str] = (
            "nominal_available",
            "nominal_available",
        ),
        random_seed: int = 0,
    ) -> None:
        self.model = model
        self.state = (
            model.initial_state()
            if initial_state is None
            else model.project_state(initial_state)
        )
        self.time_s = 0.0
        self._rng = np.random.default_rng(int(random_seed))
        self._regime_ids = self._validate_regime_ids(initial_regime_ids)
        self._issued = UpperCommand()
        self._delivered_history: list[list[tuple[float, float]]] = [
            [(0.0, 0.0)],
            [(0.0, 0.0)],
        ]
        self._last_delivered = [0.0, 0.0]

    def _validate_regime_ids(self, regime_ids: Sequence[str]) -> tuple[str, str]:
        if len(regime_ids) != 2:
            raise ValueError("two regime IDs are required")
        normalized = tuple(str(value) for value in regime_ids)
        missing = [value for value in normalized if value not in self.model.params.regimes]
        if missing:
            raise KeyError(f"unknown Plant-B regimes: {missing}")
        return normalized  # type: ignore[return-value]

    @property
    def regime_ids_evaluation_only(self) -> tuple[str, str]:
        return self._regime_ids

    def set_regimes(self, regime_ids: Sequence[str]) -> None:
        """Change hidden regimes without resetting any physical state."""

        self._regime_ids = self._validate_regime_ids(regime_ids)

    def issue_command(self, command: UpperCommand) -> None:
        if not isinstance(command, UpperCommand):
            raise TypeError("command must be UpperCommand")
        self._issued = command
        for area, regime_id in enumerate(self._regime_ids):
            regime = self.model.params.regimes[regime_id]
            delivered = self._last_delivered[area]
            if not regime.central_service_enabled:
                delivered = 0.0
            elif self._rng.random() >= regime.dropout_probability:
                delivered = command.ibr_pu[area]
            self._last_delivered[area] = delivered
            self._delivered_history[area].append((self.time_s, delivered))

    def _delayed_command(self, area: int, delay_s: float) -> float:
        target = self.time_s - delay_s
        history = self._delivered_history[area]
        selected = 0.0
        for timestamp, value in history:
            if timestamp > target + 1.0e-12:
                break
            selected = value
        return selected

    def observation(self) -> PlantBObservation:
        ace = self.model.ace(self.state)
        return PlantBObservation(
            time_s=self.time_s,
            frequency_hz=(
                float(self.state[PlantBStateIndex.F1]),
                float(self.state[PlantBStateIndex.F2]),
            ),
            tie_line_1_to_2_pu=float(self.state[PlantBStateIndex.PTIE12]),
            ace_pu=ace,
            bess_poi_power_pu=(
                float(self.state[PlantBStateIndex.PB1]),
                float(self.state[PlantBStateIndex.PB2]),
            ),
            sg_mechanical_power_pu=(
                float(self.state[PlantBStateIndex.PM1]),
                float(self.state[PlantBStateIndex.PM2]),
            ),
            issued_sg_command_pu=self._issued.sg_pu,
            issued_ibr_command_pu=self._issued.ibr_pu,
        )

    def advance(self, load_disturbance_pu: Sequence[float]) -> PlantBObservation:
        regimes = tuple(
            self.model.params.regimes[regime_id] for regime_id in self._regime_ids
        )
        delayed = tuple(
            self._delayed_command(area, regimes[area].command_delay_s)
            for area in (0, 1)
        )
        self.state = self.model.step(
            self.state,
            command=self._issued,
            delayed_ibr_command_pu=delayed,
            load_disturbance_pu=load_disturbance_pu,
            regimes=regimes,
        )
        self.time_s += self.model.params.integration_step_s
        return self.observation()

    def evaluation_truth_snapshot(self) -> dict[str, Any]:
        headroom = [
            self.model.headroom(
                self.state,
                area=area,
                regime=self.model.params.regimes[self._regime_ids[area]],
            )
            for area in (0, 1)
        ]
        return {
            "time_s": self.time_s,
            "regime_ids": self._regime_ids,
            "soc": (
                float(self.state[PlantBStateIndex.SOC1]),
                float(self.state[PlantBStateIndex.SOC2]),
            ),
            "availability": (
                float(self.state[PlantBStateIndex.A1]),
                float(self.state[PlantBStateIndex.A2]),
            ),
            "headroom_up_down_pu": headroom,
        }


def plant_b_parameters_from_config(
    payload: Mapping[str, Any],
    *,
    sg_level: str,
    upper_control_period_s: float | None = None,
) -> PlantBParameters:
    if payload.get("schema_version") != "d5freq.phase_b2.plant_b.v1":
        raise ValueError("unexpected Plant-B config schema")
    base = float(payload["system_base_mw"])
    areas = tuple(AreaFrequencyParams(**dict(row)) for row in payload["areas"])
    if len(areas) != 2:
        raise ValueError("Plant-B config must define two areas")
    capability_payload = dict(payload["sg_capability_levels"][sg_level])
    capability = SGCapability(
        **{name: tuple(values) for name, values in capability_payload.items()}
    )
    bess = tuple(
        BESSPhysicalParams(system_base_mw=base, **dict(row)) for row in payload["bess"]
    )
    regimes = {
        str(name): IBRRegimeParams(regime_id=str(name), **dict(values))
        for name, values in payload["regimes"].items()
    }
    period = (
        float(payload["default_upper_control_period_s"])
        if upper_control_period_s is None
        else float(upper_control_period_s)
    )
    candidates = tuple(float(value) for value in payload["upper_control_period_candidates_s"])
    if period not in candidates:
        raise ValueError("upper control period is not a registered candidate")
    return PlantBParameters(
        system_base_mw=base,
        nominal_frequency_hz=float(payload["nominal_frequency_hz"]),
        integration_step_s=float(payload["integration_step_s"]),
        upper_control_period_s=period,
        tie_synchronizing_coefficient_pu_per_rad=float(
            payload["tie_synchronizing_coefficient_pu_per_rad"]
        ),
        areas=areas,  # type: ignore[arg-type]
        sg_capability=capability,
        bess=bess,  # type: ignore[arg-type]
        regimes=regimes,
    )


__all__ = [
    "AREA_STATE_INDICES",
    "STATE_NAMES",
    "STATE_SIZE",
    "AreaFrequencyParams",
    "BESSPhysicalParams",
    "IBRRegimeParams",
    "PlantBObservation",
    "PlantBParameters",
    "PlantBStateIndex",
    "SGCapability",
    "TwoAreaPlantB",
    "TwoAreaPlantBSimulator",
    "UpperCommand",
    "plant_b_parameters_from_config",
]
