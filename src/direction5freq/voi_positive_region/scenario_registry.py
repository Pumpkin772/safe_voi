"""Preregistered, causally separated scenarios for the positive-region rebuild."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

import numpy as np


class StudySplit(str, Enum):
    DEVELOPMENT = "development"
    VALIDATION = "validation"
    FINAL = "final"
    NORMAL1H = "normal1h"


SEED_RANGES: dict[StudySplit, range] = {
    StudySplit.DEVELOPMENT: range(8100, 8300),
    StudySplit.VALIDATION: range(9100, 9300),
    StudySplit.FINAL: range(10100, 10300),
    StudySplit.NORMAL1H: range(11100, 11106),
}


@dataclass(frozen=True)
class ControllerScenarioContext:
    """Information that an ordinary online controller may use.

    The context exposes a distributional event rate, not the realized event
    time, sign, area, capability, or mode.
    """

    period_s: float
    rolling_horizon_s: float
    information_validity_horizon_s: float
    episode_duration_s: float
    measured_initial_soc: float
    public_event_count: int
    public_event_time_window_s: tuple[float, float]


@dataclass(frozen=True)
class ScenarioSpec:
    scenario_id: str
    split: StudySplit
    seed: int
    plant: str
    known_ood: str
    period_s: float
    rolling_horizon_s: float
    information_validity_horizon_s: float
    episode_duration_s: float
    warmup_s: float
    initial_soc: float
    capability_transition_time_s: float
    load_event_time_s: float
    load_magnitude_pu: float
    load_sign: int
    load_area: str
    true_power_pu: float
    true_ramp_pu_per_s: float
    true_delay_s: float
    measurement_noise_std_pu: float

    def __post_init__(self) -> None:
        if self.seed not in SEED_RANGES[self.split]:
            raise ValueError(f"seed {self.seed} is outside split {self.split.value}")
        if self.plant not in {"plant_a_full_nonlinear", "plant_b_native_andes"}:
            raise ValueError("unregistered plant")
        if self.known_ood not in {"known", "ood"}:
            raise ValueError("known_ood must be known or ood")
        if self.period_s not in {2.0, 4.0}:
            raise ValueError("control period must be 2 or 4 s")
        if not 90.0 <= self.capability_transition_time_s <= 150.0:
            raise ValueError("capability transition outside registered window")
        if not 210.0 <= self.load_event_time_s <= 390.0:
            raise ValueError("load event outside registered window")
        if self.load_event_time_s <= self.capability_transition_time_s:
            raise ValueError("load event must follow the hidden capability transition")
        if self.load_sign not in {-1, 1}:
            raise ValueError("load sign must be -1 or 1")
        if self.load_area not in {"area0", "area1", "both"}:
            raise ValueError("unregistered load area")

    def controller_context(self) -> ControllerScenarioContext:
        """Return a truth-free public view for the ordinary controller."""

        return ControllerScenarioContext(
            period_s=self.period_s,
            rolling_horizon_s=self.rolling_horizon_s,
            information_validity_horizon_s=self.information_validity_horizon_s,
            episode_duration_s=self.episode_duration_s,
            measured_initial_soc=self.initial_soc,
            public_event_count=1,
            public_event_time_window_s=(210.0, 390.0),
        )

    def evaluation_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["split"] = self.split.value
        return record


def _rng(seed_sequence: np.random.SeedSequence) -> np.random.Generator:
    return np.random.default_rng(seed_sequence)


def generate_scenario(split: StudySplit, seed: int) -> ScenarioSpec:
    """Generate one registered scenario using independent random streams.

    Separate child streams prevent the hidden capability and future load event
    from becoming coupled merely because they were drawn consecutively.
    """

    if seed not in SEED_RANGES[split]:
        raise ValueError(f"seed {seed} is outside the {split.value} firewall")
    streams = np.random.SeedSequence(seed).spawn(7)
    timing_capability = _rng(streams[0])
    timing_load = _rng(streams[1])
    load = _rng(streams[2])
    capability = _rng(streams[3])
    state = _rng(streams[4])
    design = _rng(streams[5])
    noise = _rng(streams[6])

    period_s = float(design.choice((2.0, 4.0)))
    rolling_horizon_s = float(design.choice((24.0, 32.0)))
    validity_s = float(design.choice((120.0, 180.0, 240.0, 300.0)))
    known = bool(design.integers(0, 2))
    if split is StudySplit.DEVELOPMENT:
        plant = "plant_a_full_nonlinear"
    else:
        plant = (
            "plant_a_full_nonlinear"
            if int(design.integers(0, 3)) != 0
            else "plant_b_native_andes"
        )

    if known:
        power = float(capability.choice((0.045, 0.060, 0.080)))
        ramp = float(capability.choice((0.025, 0.035, 0.050)))
        delay = float(capability.choice((0.2, 1.0, 1.5)))
    else:
        power = float(capability.uniform(0.047, 0.078))
        ramp = float(capability.uniform(0.027, 0.048))
        delay = float(capability.uniform(0.3, 1.4))

    return ScenarioSpec(
        scenario_id=f"D5PVR_{split.value.upper()}_{seed}",
        split=split,
        seed=seed,
        plant=plant,
        known_ood="known" if known else "ood",
        period_s=period_s,
        rolling_horizon_s=rolling_horizon_s,
        information_validity_horizon_s=validity_s,
        episode_duration_s=3600.0 if split is StudySplit.NORMAL1H else 720.0,
        warmup_s=60.0,
        initial_soc=float(state.uniform(0.35, 0.65)),
        capability_transition_time_s=float(timing_capability.uniform(90.0, 150.0)),
        load_event_time_s=float(timing_load.uniform(210.0, 390.0)),
        load_magnitude_pu=float(load.uniform(0.025, 0.070)),
        load_sign=int(load.choice((-1, 1))),
        load_area=str(load.choice(("area0", "area1", "both"))),
        true_power_pu=power,
        true_ramp_pu_per_s=ramp,
        true_delay_s=delay,
        measurement_noise_std_pu=float(noise.uniform(0.0002, 0.0015)),
    )


def generate_scenarios(split: StudySplit, count: int | None = None) -> list[ScenarioSpec]:
    seeds = SEED_RANGES[split]
    requested = len(seeds) if count is None else count
    if requested < 1 or requested > len(seeds):
        raise ValueError("count outside registered split size")
    return [generate_scenario(split, seed) for seed in list(seeds)[:requested]]
