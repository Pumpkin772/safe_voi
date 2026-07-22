"""Frozen Phase-6 closed-loop experiment protocol and scenario builders.

This module intentionally lives below :mod:`d5freq.evaluation`: it parses
simulator-private mode schedules and must never be imported by a controller.
The resulting :class:`~d5freq.simulation.hybrid_simulator.Scenario` is passed
only to :class:`~d5freq.simulation.hybrid_simulator.HiddenModeFrequencySimulator`.
Controllers continue to receive only :class:`d5freq.interfaces.Measurement`.

The parser is deliberately closed-world.  Unknown or missing fields, method
IDs, scenario IDs, seed ranges, time bases, or preregistered selection rules
are rejected instead of being silently ignored.  This turns
``configs/experiments.yaml`` into an auditable preregistration rather than a
loosely interpreted collection of defaults.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any

from d5freq.simulation.disturbances import LoadDisturbanceSpec, LoadEvent
from d5freq.simulation.hybrid_simulator import Scenario
from d5freq.simulation.mode_schedules import ModeSwitch, PiecewiseConstantModeSchedule
from d5freq.utils.config import load_yaml


EXPERIMENT_PROTOCOL_SCHEMA_VERSION = "d5freq.closed_loop_experiments.v3"

FROZEN_METHOD_IDS: tuple[str, ...] = (
    "B0",
    "B1",
    "B2",
    "B3",
    "B4",
    "P",
    "no-worst",
    "no-OOD",
    "no-tightening",
    "fixed-K4-unlabeled",
    "labeled-library",
    "no-transition-prior",
)

FROZEN_SCENARIO_IDS: tuple[str, ...] = (
    "S0_nominal_stochastic",
    "S1_step_pos_002",
    "S1_step_neg_002",
    "S1_step_pos_004",
    "S1_step_neg_004",
    "S1_step_pos_006",
    "S1_step_neg_006",
    "S1_step_pos_008",
    "S1_step_neg_008",
    "S2_sluggish_switch_050",
    "S2_sluggish_switch_060",
    "S2_sluggish_switch_090",
    "S3_derated_coincident",
    "S4_unavailable_coincident",
    "S5_multi_switch_stochastic",
    "S6_sluggish_coincident_low_noise",
    "S6_sluggish_coincident_medium_noise",
    "S6_sluggish_coincident_high_noise",
    "S7_ood_asymmetric_limit",
    "S8_ood_time_varying_delay",
    "S9_compound_unavailable_double_step",
)

_FROZEN_FAMILY_COUNTS: Mapping[str, int] = MappingProxyType(
    {"S0": 1, "S1": 8, "S2": 3, "S3": 1, "S4": 1,
     "S5": 1, "S6": 3, "S7": 1, "S8": 1, "S9": 1}
)
_FROZEN_OBJECTIVES: tuple[str, ...] = (
    "minimize_catastrophic_failure_rate",
    "minimize_mean_frequency_iae_hz_s",
    "minimize_q95_max_abs_frequency_deviation_hz",
    "minimize_mean_solver_wall_time_s",
)
_KNOWN_MODES = frozenset({"nominal", "sluggish", "derated", "unavailable"})
_OOD_MODES = frozenset({"asymmetric_limit", "time_varying_delay"})


def _as_mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{context} must be a mapping")
    if not all(isinstance(key, str) for key in value):
        raise TypeError(f"{context} keys must be strings")
    return value  # type: ignore[return-value]


def _exact_keys(
    value: object,
    expected: set[str] | frozenset[str],
    context: str,
) -> Mapping[str, object]:
    mapping = _as_mapping(value, context)
    actual = set(mapping)
    missing = expected - actual
    unknown = actual - expected
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append(f"missing={sorted(missing)!r}")
        if unknown:
            details.append(f"unknown={sorted(unknown)!r}")
        raise ValueError(f"{context} violates the closed schema: {', '.join(details)}")
    return mapping


def _as_sequence(value: object, context: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{context} must be a sequence")
    return value


def _string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{context} must be a non-empty string")
    if value != value.strip():
        raise ValueError(f"{context} must not have leading or trailing whitespace")
    return value


def _boolean(value: object, context: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{context} must be a boolean")
    return value


def _integer(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{context} must be an integer")
    return value


def _finite(value: object, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{context} must be a real scalar")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{context} must be finite")
    return result


def _require_equal(actual: object, expected: object, context: str) -> None:
    if actual != expected:
        raise ValueError(f"{context} is frozen at {expected!r}, got {actual!r}")


@dataclass(frozen=True, slots=True)
class ExperimentTimebase:
    """Numerical horizon and integration rates frozen for final experiments."""

    episode_duration_s: float
    control_period_s: float
    integration_step_s: float

    def __post_init__(self) -> None:
        for name in (
            "episode_duration_s",
            "control_period_s",
            "integration_step_s",
        ):
            value = _finite(getattr(self, name), name)
            if value <= 0.0:
                raise ValueError(f"{name} must be positive")
            object.__setattr__(self, name, value)
        if self.integration_step_s > self.control_period_s:
            raise ValueError("integration_step_s must not exceed control_period_s")
        ratio = self.control_period_s / self.integration_step_s
        if not math.isclose(ratio, round(ratio), rel_tol=0.0, abs_tol=1.0e-12):
            raise ValueError("control_period_s must be an integer integration-step multiple")


@dataclass(frozen=True, slots=True)
class SeedSet:
    """A frozen contiguous inclusive seed interval."""

    name: str
    start: int
    stop_inclusive: int
    count: int

    def __post_init__(self) -> None:
        name = _string(self.name, "seed-set name")
        start = _integer(self.start, f"seed_sets.{name}.start")
        stop = _integer(self.stop_inclusive, f"seed_sets.{name}.stop_inclusive")
        count = _integer(self.count, f"seed_sets.{name}.count")
        if start < 0 or stop < start or count <= 0:
            raise ValueError(f"seed set {name!r} has an invalid interval")
        if stop - start + 1 != count:
            raise ValueError(f"seed set {name!r} count does not match its interval")
        object.__setattr__(self, "name", name)

    @property
    def values(self) -> tuple[int, ...]:
        return tuple(range(self.start, self.stop_inclusive + 1))


@dataclass(frozen=True, slots=True)
class NoiseProfile:
    """Controller-visible measurement noise magnitudes in per unit."""

    name: str
    omega_std_pu: float
    power_std_pu: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _string(self.name, "noise-profile name"))
        for field_name in ("omega_std_pu", "power_std_pu"):
            value = _finite(getattr(self, field_name), field_name)
            if value < 0.0:
                raise ValueError(f"{field_name} must be non-negative")
            object.__setattr__(self, field_name, value)


@dataclass(frozen=True, slots=True)
class MethodDefinition:
    """One frozen baseline, proposed method, or ablation definition."""

    method_id: str
    output_slug: str
    role: str
    truth_access: str
    definition: str

    def __post_init__(self) -> None:
        for field_name in (
            "method_id",
            "output_slug",
            "role",
            "truth_access",
            "definition",
        ):
            object.__setattr__(
                self,
                field_name,
                _string(getattr(self, field_name), f"method.{field_name}"),
            )
        if self.role not in {"baseline", "proposed", "ablation", "evaluation_upper_bound"}:
            raise ValueError(f"unknown method role {self.role!r}")
        if self.truth_access not in {
            "none",
            "evaluation_oracle_only",
            "training_labels_only",
        }:
            raise ValueError(f"unknown method truth_access {self.truth_access!r}")


@dataclass(frozen=True, slots=True)
class StochasticLoadDefinition:
    """Seeded sampled-load recipe for a scenario variant."""

    enabled: bool
    sample_period_s: float
    white_std_pu: float
    random_walk_step_std_pu: float

    def __post_init__(self) -> None:
        _boolean(self.enabled, "stochastic.enabled")
        period = _finite(self.sample_period_s, "stochastic.sample_period_s")
        white = _finite(self.white_std_pu, "stochastic.white_std_pu")
        walk = _finite(
            self.random_walk_step_std_pu,
            "stochastic.random_walk_step_std_pu",
        )
        if period <= 0.0 or white < 0.0 or walk < 0.0:
            raise ValueError("stochastic load periods/std values are invalid")
        if not self.enabled and (white != 0.0 or walk != 0.0):
            raise ValueError("disabled stochastic load must have exactly zero std values")
        if self.enabled and white == 0.0 and walk == 0.0:
            raise ValueError("enabled stochastic load must contain nonzero noise")
        object.__setattr__(self, "sample_period_s", period)
        object.__setattr__(self, "white_std_pu", white)
        object.__setattr__(self, "random_walk_step_std_pu", walk)


@dataclass(frozen=True, slots=True)
class ScenarioVariantDefinition:
    """A concrete, uniquely named simulator-private scenario variant."""

    scenario_id: str
    family: str
    variant: str
    description: str
    truth_class: str
    noise_profile: str
    final_seed_set: str
    load_events: tuple[LoadEvent, ...]
    stochastic_load: StochasticLoadDefinition
    mode_schedule: PiecewiseConstantModeSchedule

    def __post_init__(self) -> None:
        for field_name in (
            "scenario_id",
            "family",
            "variant",
            "description",
            "truth_class",
            "noise_profile",
            "final_seed_set",
        ):
            object.__setattr__(
                self,
                field_name,
                _string(getattr(self, field_name), f"scenario.{field_name}"),
            )
        if self.truth_class not in {"known", "ood", "extreme_known"}:
            raise ValueError(f"unknown truth_class {self.truth_class!r}")
        object.__setattr__(self, "load_events", tuple(self.load_events))
        if not all(isinstance(event, LoadEvent) for event in self.load_events):
            raise TypeError("load_events must contain LoadEvent instances")
        if not isinstance(self.stochastic_load, StochasticLoadDefinition):
            raise TypeError("stochastic_load must be StochasticLoadDefinition")
        if not isinstance(self.mode_schedule, PiecewiseConstantModeSchedule):
            raise TypeError("mode_schedule must be PiecewiseConstantModeSchedule")

    def build_scenario(
        self,
        *,
        timebase: ExperimentTimebase,
        noise: NoiseProfile,
    ) -> Scenario:
        """Build the simulator recipe without exposing it to a controller."""

        if noise.name != self.noise_profile:
            raise ValueError("noise profile does not match this scenario variant")
        stochastic = self.stochastic_load
        disturbance = LoadDisturbanceSpec(
            events=self.load_events,
            sample_period_s=stochastic.sample_period_s,
            white_noise_std_pu=stochastic.white_std_pu if stochastic.enabled else 0.0,
            random_walk_step_std_pu=(
                stochastic.random_walk_step_std_pu if stochastic.enabled else 0.0
            ),
        )
        return Scenario(
            mode_schedule=self.mode_schedule,
            duration_s=timebase.episode_duration_s,
            disturbance=disturbance,
            name=self.scenario_id,
            omega_measurement_std_pu=noise.omega_std_pu,
            power_measurement_std_pu=noise.power_std_pu,
        )


@dataclass(frozen=True, slots=True)
class TuningSelectionRule:
    """Preregistered deterministic validation-only candidate selection."""

    split: str
    seed_set: str
    one_global_configuration_for_all_final_scenarios: bool
    final_test_feedback_forbidden: bool
    ordered_objectives: tuple[str, ...]
    deterministic_tie_breaker: str
    selection_record_required: bool
    selection_record_must_precede_final_ledger: bool


@dataclass(frozen=True, slots=True)
class ExperimentProtocol:
    """Validated immutable Phase-6 experiment protocol."""

    schema_version: str
    revision: str
    timebase: ExperimentTimebase
    retain_failed_episodes: bool
    seed_sets: Mapping[str, SeedSet]
    data_splits: Mapping[str, str]
    tuning_selection: TuningSelectionRule
    methods: tuple[MethodDefinition, ...]
    noise_profiles: Mapping[str, NoiseProfile]
    scenario_variants: tuple[ScenarioVariantDefinition, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "seed_sets", MappingProxyType(dict(self.seed_sets)))
        object.__setattr__(self, "data_splits", MappingProxyType(dict(self.data_splits)))
        object.__setattr__(
            self, "noise_profiles", MappingProxyType(dict(self.noise_profiles))
        )
        object.__setattr__(self, "methods", tuple(self.methods))
        object.__setattr__(self, "scenario_variants", tuple(self.scenario_variants))

    @property
    def methods_by_id(self) -> Mapping[str, MethodDefinition]:
        return MappingProxyType({method.method_id: method for method in self.methods})

    @property
    def scenarios_by_id(self) -> Mapping[str, ScenarioVariantDefinition]:
        return MappingProxyType(
            {scenario.scenario_id: scenario for scenario in self.scenario_variants}
        )

    @property
    def full_final_episode_count(self) -> int:
        """Return the frozen method-by-variant-by-seed final-run count."""

        seed_count = sum(
            self.seed_sets[scenario.final_seed_set].count
            for scenario in self.scenario_variants
        )
        return len(self.methods) * seed_count

    def build_scenario(self, scenario_id: str) -> Scenario:
        """Return one concrete simulator-private scenario by stable ID."""

        try:
            definition = self.scenarios_by_id[scenario_id]
        except KeyError as exc:
            raise KeyError(f"unknown frozen scenario_id {scenario_id!r}") from exc
        noise = self.noise_profiles[definition.noise_profile]
        return definition.build_scenario(timebase=self.timebase, noise=noise)

    def seeds_for(self, scenario_id: str, stage: str) -> tuple[int, ...]:
        """Return the preregistered smoke, tuning, or final seeds."""

        if stage == "smoke":
            seed_name = "smoke"
        elif stage == "tuning":
            seed_name = "tuning"
        elif stage == "final":
            try:
                seed_name = self.scenarios_by_id[scenario_id].final_seed_set
            except KeyError as exc:
                raise KeyError(f"unknown frozen scenario_id {scenario_id!r}") from exc
        else:
            raise ValueError("stage must be one of 'smoke', 'tuning', or 'final'")
        return self.seed_sets[seed_name].values


def _parse_seed_sets(value: object) -> Mapping[str, SeedSet]:
    expected = {"smoke", "tuning", "final_known", "final_ood_extreme"}
    mapping = _exact_keys(value, expected, "seed_sets")
    result: dict[str, SeedSet] = {}
    for name in ("smoke", "tuning", "final_known", "final_ood_extreme"):
        row = _exact_keys(
            mapping[name], {"start", "stop_inclusive", "count"}, f"seed_sets.{name}"
        )
        result[name] = SeedSet(
            name=name,
            start=_integer(row["start"], f"seed_sets.{name}.start"),
            stop_inclusive=_integer(
                row["stop_inclusive"], f"seed_sets.{name}.stop_inclusive"
            ),
            count=_integer(row["count"], f"seed_sets.{name}.count"),
        )
    expected_values = {
        "smoke": (0, 1),
        "tuning": tuple(range(100, 110)),
        "final_known": tuple(range(1000, 1030)),
        "final_ood_extreme": tuple(range(1000, 1050)),
    }
    for name, values in expected_values.items():
        _require_equal(result[name].values, values, f"seed_sets.{name}")
    return MappingProxyType(result)


def _parse_methods(value: object) -> tuple[MethodDefinition, ...]:
    rows = _as_sequence(value, "methods")
    result: list[MethodDefinition] = []
    expected_keys = {"method_id", "output_slug", "role", "truth_access", "definition"}
    for index, raw_row in enumerate(rows):
        row = _exact_keys(raw_row, expected_keys, f"methods[{index}]")
        result.append(
            MethodDefinition(
                method_id=_string(row["method_id"], f"methods[{index}].method_id"),
                output_slug=_string(row["output_slug"], f"methods[{index}].output_slug"),
                role=_string(row["role"], f"methods[{index}].role"),
                truth_access=_string(
                    row["truth_access"], f"methods[{index}].truth_access"
                ),
                definition=_string(row["definition"], f"methods[{index}].definition"),
            )
        )
    ids = tuple(method.method_id for method in result)
    _require_equal(ids, FROZEN_METHOD_IDS, "methods method_id order")
    slugs = tuple(method.output_slug for method in result)
    if len(set(slugs)) != len(slugs):
        raise ValueError("method output_slug values must be unique")
    for method in result:
        if method.method_id == "B4":
            _require_equal(
                method.truth_access,
                "evaluation_oracle_only",
                "methods.B4.truth_access",
            )
        elif method.method_id == "labeled-library":
            _require_equal(
                method.truth_access,
                "training_labels_only",
                "methods.labeled-library.truth_access",
            )
        else:
            _require_equal(method.truth_access, "none", f"methods.{method.method_id}.truth_access")
    return tuple(result)


def _parse_noise_profiles(value: object) -> Mapping[str, NoiseProfile]:
    mapping = _exact_keys(value, {"low", "medium", "high"}, "noise_profiles")
    result: dict[str, NoiseProfile] = {}
    for name in ("low", "medium", "high"):
        row = _exact_keys(
            mapping[name], {"omega_std_pu", "power_std_pu"}, f"noise_profiles.{name}"
        )
        result[name] = NoiseProfile(
            name=name,
            omega_std_pu=_finite(
                row["omega_std_pu"], f"noise_profiles.{name}.omega_std_pu"
            ),
            power_std_pu=_finite(
                row["power_std_pu"], f"noise_profiles.{name}.power_std_pu"
            ),
        )
    expected = {
        "low": (1.0e-5, 2.0e-4),
        "medium": (3.0e-5, 2.0e-4),
        "high": (1.0e-4, 1.0e-3),
    }
    for name, pair in expected.items():
        _require_equal(
            (result[name].omega_std_pu, result[name].power_std_pu),
            pair,
            f"noise_profiles.{name}",
        )
    return MappingProxyType(result)


def _parse_event(value: object, context: str, duration_s: float) -> LoadEvent:
    row = _exact_keys(
        value, {"start_time_s", "magnitude_pu", "end_time_s"}, context
    )
    start = _finite(row["start_time_s"], f"{context}.start_time_s")
    magnitude = _finite(row["magnitude_pu"], f"{context}.magnitude_pu")
    raw_end = row["end_time_s"]
    end = None if raw_end is None else _finite(raw_end, f"{context}.end_time_s")
    if start >= duration_s or (end is not None and end > duration_s):
        raise ValueError(f"{context} lies outside the episode")
    return LoadEvent(start_time_s=start, magnitude_pu=magnitude, end_time_s=end)


def _parse_stochastic(value: object, context: str) -> StochasticLoadDefinition:
    row = _exact_keys(
        value,
        {
            "enabled",
            "sample_period_s",
            "white_std_pu",
            "random_walk_step_std_pu",
        },
        context,
    )
    return StochasticLoadDefinition(
        enabled=_boolean(row["enabled"], f"{context}.enabled"),
        sample_period_s=_finite(row["sample_period_s"], f"{context}.sample_period_s"),
        white_std_pu=_finite(row["white_std_pu"], f"{context}.white_std_pu"),
        random_walk_step_std_pu=_finite(
            row["random_walk_step_std_pu"],
            f"{context}.random_walk_step_std_pu",
        ),
    )


def _parse_mode_schedule(
    value: object, context: str, duration_s: float
) -> PiecewiseConstantModeSchedule:
    row = _exact_keys(value, {"initial", "switches"}, context)
    initial = _string(row["initial"], f"{context}.initial")
    switches: list[ModeSwitch] = []
    for index, raw_switch in enumerate(_as_sequence(row["switches"], f"{context}.switches")):
        switch_row = _exact_keys(
            raw_switch, {"time_s", "mode"}, f"{context}.switches[{index}]"
        )
        time_s = _finite(
            switch_row["time_s"], f"{context}.switches[{index}].time_s"
        )
        if time_s >= duration_s:
            raise ValueError(f"{context}.switches[{index}] lies outside the episode")
        switches.append(
            ModeSwitch(
                time_s=time_s,
                mode=_string(
                    switch_row["mode"], f"{context}.switches[{index}].mode"
                ),
            )
        )
    return PiecewiseConstantModeSchedule(initial, tuple(switches))


def _parse_scenarios(
    value: object, timebase: ExperimentTimebase
) -> tuple[ScenarioVariantDefinition, ...]:
    rows = _as_sequence(value, "scenario_variants")
    expected_keys = {
        "scenario_id",
        "family",
        "variant",
        "description",
        "truth_class",
        "noise_profile",
        "final_seed_set",
        "load",
        "mode",
    }
    result: list[ScenarioVariantDefinition] = []
    for index, raw_row in enumerate(rows):
        context = f"scenario_variants[{index}]"
        row = _exact_keys(raw_row, expected_keys, context)
        load = _exact_keys(row["load"], {"events", "stochastic"}, f"{context}.load")
        events = tuple(
            _parse_event(event, f"{context}.load.events[{event_index}]", timebase.episode_duration_s)
            for event_index, event in enumerate(
                _as_sequence(load["events"], f"{context}.load.events")
            )
        )
        result.append(
            ScenarioVariantDefinition(
                scenario_id=_string(row["scenario_id"], f"{context}.scenario_id"),
                family=_string(row["family"], f"{context}.family"),
                variant=_string(row["variant"], f"{context}.variant"),
                description=_string(row["description"], f"{context}.description"),
                truth_class=_string(row["truth_class"], f"{context}.truth_class"),
                noise_profile=_string(row["noise_profile"], f"{context}.noise_profile"),
                final_seed_set=_string(row["final_seed_set"], f"{context}.final_seed_set"),
                load_events=events,
                stochastic_load=_parse_stochastic(
                    load["stochastic"], f"{context}.load.stochastic"
                ),
                mode_schedule=_parse_mode_schedule(
                    row["mode"], f"{context}.mode", timebase.episode_duration_s
                ),
            )
        )
    ids = tuple(scenario.scenario_id for scenario in result)
    _require_equal(ids, FROZEN_SCENARIO_IDS, "scenario_variants scenario_id order")
    if len({(row.family, row.variant) for row in result}) != len(result):
        raise ValueError("family/variant pairs must be unique")
    family_counts = Counter(row.family for row in result)
    _require_equal(dict(family_counts), dict(_FROZEN_FAMILY_COUNTS), "scenario family counts")
    return tuple(result)


def _event_signature(row: ScenarioVariantDefinition) -> tuple[tuple[float, float], ...]:
    return tuple((event.start_time_s, event.magnitude_pu) for event in row.load_events)


def _switch_signature(row: ScenarioVariantDefinition) -> tuple[tuple[float, str], ...]:
    return tuple((switch.time_s, switch.mode) for switch in row.mode_schedule.switches)


def _validate_frozen_scenario_matrix(
    scenarios: tuple[ScenarioVariantDefinition, ...],
) -> None:
    by_id = {row.scenario_id: row for row in scenarios}

    s0 = by_id["S0_nominal_stochastic"]
    _require_equal(_event_signature(s0), (), "S0 load events")
    _require_equal(_switch_signature(s0), (), "S0 mode switches")
    _require_equal(s0.mode_schedule.initial_mode, "nominal", "S0 initial mode")
    _require_equal(s0.stochastic_load.enabled, True, "S0 stochastic load")
    _require_equal(
        (
            s0.stochastic_load.sample_period_s,
            s0.stochastic_load.white_std_pu,
            s0.stochastic_load.random_walk_step_std_pu,
        ),
        (0.5, 1.0e-3, 7.071067811865475e-5),
        "S0 stochastic recipe",
    )

    expected_s1 = {
        "S1_step_pos_002": 0.02,
        "S1_step_neg_002": -0.02,
        "S1_step_pos_004": 0.04,
        "S1_step_neg_004": -0.04,
        "S1_step_pos_006": 0.06,
        "S1_step_neg_006": -0.06,
        "S1_step_pos_008": 0.08,
        "S1_step_neg_008": -0.08,
    }
    for scenario_id, magnitude in expected_s1.items():
        row = by_id[scenario_id]
        _require_equal(_event_signature(row), ((60.0, magnitude),), f"{scenario_id} load")
        _require_equal(_switch_signature(row), (), f"{scenario_id} switches")

    for scenario_id, switch_time in (
        ("S2_sluggish_switch_050", 50.0),
        ("S2_sluggish_switch_060", 60.0),
        ("S2_sluggish_switch_090", 90.0),
    ):
        row = by_id[scenario_id]
        _require_equal(_event_signature(row), ((60.0, 0.06),), f"{scenario_id} load")
        _require_equal(
            _switch_signature(row), ((switch_time, "sluggish"),), f"{scenario_id} switch"
        )

    for scenario_id, mode in (
        ("S3_derated_coincident", "derated"),
        ("S4_unavailable_coincident", "unavailable"),
    ):
        row = by_id[scenario_id]
        _require_equal(_event_signature(row), ((60.0, 0.06),), f"{scenario_id} load")
        _require_equal(_switch_signature(row), ((60.0, mode),), f"{scenario_id} switch")

    s5 = by_id["S5_multi_switch_stochastic"]
    _require_equal(_event_signature(s5), (), "S5 deterministic events")
    _require_equal(
        _switch_signature(s5),
        ((45.0, "sluggish"), (90.0, "derated"), (135.0, "nominal")),
        "S5 switches",
    )
    _require_equal(s5.stochastic_load.enabled, True, "S5 stochastic load")

    for suffix, noise_name in (
        ("low_noise", "low"),
        ("medium_noise", "medium"),
        ("high_noise", "high"),
    ):
        row = by_id[f"S6_sluggish_coincident_{suffix}"]
        _require_equal(_event_signature(row), ((60.0, 0.06),), f"S6 {suffix} load")
        _require_equal(
            _switch_signature(row), ((60.0, "sluggish"),), f"S6 {suffix} switch"
        )
        _require_equal(row.noise_profile, noise_name, f"S6 {suffix} noise")

    s7 = by_id["S7_ood_asymmetric_limit"]
    _require_equal(_event_signature(s7), ((60.0, 0.06),), "S7 load")
    _require_equal(_switch_signature(s7), ((90.0, "asymmetric_limit"),), "S7 switch")
    s8 = by_id["S8_ood_time_varying_delay"]
    _require_equal(_event_signature(s8), ((60.0, 0.06),), "S8 load")
    _require_equal(
        _switch_signature(s8), ((90.0, "time_varying_delay"),), "S8 switch"
    )
    s9 = by_id["S9_compound_unavailable_double_step"]
    _require_equal(_event_signature(s9), ((60.0, 0.08), (90.0, -0.04)), "S9 load")
    _require_equal(_switch_signature(s9), ((60.0, "unavailable"),), "S9 switch")

    for row in scenarios:
        all_modes = set(row.mode_schedule.modes)
        expected_seed_set = (
            "final_ood_extreme" if row.family in {"S7", "S8", "S9"} else "final_known"
        )
        _require_equal(row.final_seed_set, expected_seed_set, f"{row.scenario_id} seed set")
        if row.family in {"S7", "S8"}:
            _require_equal(row.truth_class, "ood", f"{row.scenario_id} truth class")
            if not (all_modes & _OOD_MODES):
                raise ValueError(f"{row.scenario_id} must contain an OOD mode")
        else:
            expected_class = "extreme_known" if row.family == "S9" else "known"
            _require_equal(row.truth_class, expected_class, f"{row.scenario_id} truth class")
            if not all_modes <= _KNOWN_MODES:
                raise ValueError(f"{row.scenario_id} contains an undeclared known mode")


def parse_experiment_protocol(payload: Mapping[str, Any]) -> ExperimentProtocol:
    """Parse and fully validate the frozen Phase-6 protocol mapping."""

    root = _exact_keys(
        payload,
        {
            "schema_version",
            "protocol_status",
            "truth_access",
            "timebase",
            "execution_policy",
            "seed_sets",
            "data_splits",
            "tuning_selection",
            "methods",
            "noise_profiles",
            "scenario_variants",
        },
        "experiment protocol",
    )
    schema_version = _string(root["schema_version"], "schema_version")
    _require_equal(
        schema_version, EXPERIMENT_PROTOCOL_SCHEMA_VERSION, "schema_version"
    )
    _require_equal(
        _string(root["truth_access"], "truth_access"),
        "simulator_and_evaluation_only",
        "truth_access",
    )

    status = _exact_keys(
        root["protocol_status"],
        {"frozen", "frozen_before_final_test", "phase", "revision"},
        "protocol_status",
    )
    _require_equal(_boolean(status["frozen"], "protocol_status.frozen"), True, "protocol_status.frozen")
    _require_equal(
        _boolean(
            status["frozen_before_final_test"],
            "protocol_status.frozen_before_final_test",
        ),
        True,
        "protocol_status.frozen_before_final_test",
    )
    _require_equal(_integer(status["phase"], "protocol_status.phase"), 6, "protocol_status.phase")
    revision = _string(status["revision"], "protocol_status.revision")

    time_raw = _exact_keys(
        root["timebase"],
        {"episode_duration_s", "control_period_s", "integration_step_s"},
        "timebase",
    )
    timebase = ExperimentTimebase(
        episode_duration_s=_finite(time_raw["episode_duration_s"], "timebase.episode_duration_s"),
        control_period_s=_finite(time_raw["control_period_s"], "timebase.control_period_s"),
        integration_step_s=_finite(time_raw["integration_step_s"], "timebase.integration_step_s"),
    )
    _require_equal(
        (
            timebase.episode_duration_s,
            timebase.control_period_s,
            timebase.integration_step_s,
        ),
        (180.0, 0.5, 0.02),
        "timebase",
    )

    execution = _exact_keys(
        root["execution_policy"],
        {
            "retain_failed_episodes",
            "record_run_completed_separately_from_scientific_success",
            "full_matrix_success_storage",
            "incomplete_failure_trace_storage",
            "failure_trace_point_limit",
            "failure_trace_interval_limit",
            "selected_trajectory_export_policy",
            "selected_trajectory_format",
            "tuning_and_final_worker_processes",
            "solver_threads_per_episode",
            "final_test_is_read_only_after_first_run",
            "controller_receives_truth",
        },
        "execution_policy",
    )
    for key in (
        "retain_failed_episodes",
        "record_run_completed_separately_from_scientific_success",
        "final_test_is_read_only_after_first_run",
    ):
        _require_equal(_boolean(execution[key], f"execution_policy.{key}"), True, f"execution_policy.{key}")
    _require_equal(
        _boolean(execution["controller_receives_truth"], "execution_policy.controller_receives_truth"),
        False,
        "execution_policy.controller_receives_truth",
    )
    _require_equal(
        _string(
            execution["full_matrix_success_storage"],
            "execution_policy.full_matrix_success_storage",
        ),
        "per_episode_metrics_and_compact_audit_only",
        "execution_policy.full_matrix_success_storage",
    )
    _require_equal(
        _string(
            execution["incomplete_failure_trace_storage"],
            "execution_policy.incomplete_failure_trace_storage",
        ),
        "bounded_strict_json",
        "execution_policy.incomplete_failure_trace_storage",
    )
    _require_equal(
        _integer(
            execution["failure_trace_point_limit"],
            "execution_policy.failure_trace_point_limit",
        ),
        2001,
        "execution_policy.failure_trace_point_limit",
    )
    _require_equal(
        _integer(
            execution["failure_trace_interval_limit"],
            "execution_policy.failure_trace_interval_limit",
        ),
        401,
        "execution_policy.failure_trace_interval_limit",
    )
    _require_equal(
        _string(
            execution["selected_trajectory_export_policy"],
            "execution_policy.selected_trajectory_export_policy",
        ),
        "deterministic_post_final_replay",
        "execution_policy.selected_trajectory_export_policy",
    )
    _require_equal(
        _string(
            execution["selected_trajectory_format"],
            "execution_policy.selected_trajectory_format",
        ),
        "parquet_zstd",
        "execution_policy.selected_trajectory_format",
    )
    _require_equal(
        _integer(
            execution["tuning_and_final_worker_processes"],
            "execution_policy.tuning_and_final_worker_processes",
        ),
        4,
        "execution_policy.tuning_and_final_worker_processes",
    )
    _require_equal(
        _integer(
            execution["solver_threads_per_episode"],
            "execution_policy.solver_threads_per_episode",
        ),
        1,
        "execution_policy.solver_threads_per_episode",
    )

    seed_sets = _parse_seed_sets(root["seed_sets"])

    split_keys = (
        "split_unit",
        "identification_train",
        "identification_validation",
        "ood_calibration",
        "closed_loop_validation",
        "closed_loop_test",
        "ood_test",
    )
    split_raw = _exact_keys(root["data_splits"], set(split_keys), "data_splits")
    data_splits = {key: _string(split_raw[key], f"data_splits.{key}") for key in split_keys}
    _require_equal(data_splits["split_unit"], "trajectory", "data_splits.split_unit")

    tuning_raw = _exact_keys(
        root["tuning_selection"],
        {
            "split",
            "seed_set",
            "one_global_configuration_for_all_final_scenarios",
            "final_test_feedback_forbidden",
            "ordered_objectives",
            "deterministic_tie_breaker",
            "selection_record_required",
            "selection_record_must_precede_final_ledger",
        },
        "tuning_selection",
    )
    objectives = tuple(
        _string(value, f"tuning_selection.ordered_objectives[{index}]")
        for index, value in enumerate(
            _as_sequence(tuning_raw["ordered_objectives"], "tuning_selection.ordered_objectives")
        )
    )
    _require_equal(objectives, _FROZEN_OBJECTIVES, "tuning_selection.ordered_objectives")
    tuning = TuningSelectionRule(
        split=_string(tuning_raw["split"], "tuning_selection.split"),
        seed_set=_string(tuning_raw["seed_set"], "tuning_selection.seed_set"),
        one_global_configuration_for_all_final_scenarios=_boolean(
            tuning_raw["one_global_configuration_for_all_final_scenarios"],
            "tuning_selection.one_global_configuration_for_all_final_scenarios",
        ),
        final_test_feedback_forbidden=_boolean(
            tuning_raw["final_test_feedback_forbidden"],
            "tuning_selection.final_test_feedback_forbidden",
        ),
        ordered_objectives=objectives,
        deterministic_tie_breaker=_string(
            tuning_raw["deterministic_tie_breaker"],
            "tuning_selection.deterministic_tie_breaker",
        ),
        selection_record_required=_boolean(
            tuning_raw["selection_record_required"],
            "tuning_selection.selection_record_required",
        ),
        selection_record_must_precede_final_ledger=_boolean(
            tuning_raw["selection_record_must_precede_final_ledger"],
            "tuning_selection.selection_record_must_precede_final_ledger",
        ),
    )
    _require_equal(tuning.split, "closed_loop_validation", "tuning_selection.split")
    _require_equal(tuning.seed_set, "tuning", "tuning_selection.seed_set")
    _require_equal(
        tuning.deterministic_tie_breaker,
        "lexicographically_smallest_resolved_config_sha256",
        "tuning_selection.deterministic_tie_breaker",
    )
    for key, value in (
        ("one_global_configuration_for_all_final_scenarios", tuning.one_global_configuration_for_all_final_scenarios),
        ("final_test_feedback_forbidden", tuning.final_test_feedback_forbidden),
        ("selection_record_required", tuning.selection_record_required),
        ("selection_record_must_precede_final_ledger", tuning.selection_record_must_precede_final_ledger),
    ):
        _require_equal(value, True, f"tuning_selection.{key}")

    methods = _parse_methods(root["methods"])
    noise_profiles = _parse_noise_profiles(root["noise_profiles"])
    scenarios = _parse_scenarios(root["scenario_variants"], timebase)
    _validate_frozen_scenario_matrix(scenarios)
    for scenario in scenarios:
        if scenario.noise_profile not in noise_profiles:
            raise ValueError(f"{scenario.scenario_id} references an unknown noise profile")
        if scenario.final_seed_set not in seed_sets:
            raise ValueError(f"{scenario.scenario_id} references an unknown seed set")

    return ExperimentProtocol(
        schema_version=schema_version,
        revision=revision,
        timebase=timebase,
        retain_failed_episodes=True,
        seed_sets=seed_sets,
        data_splits=MappingProxyType(data_splits),
        tuning_selection=tuning,
        methods=methods,
        noise_profiles=noise_profiles,
        scenario_variants=scenarios,
    )


def load_experiment_protocol(path: str | Path) -> ExperimentProtocol:
    """Load ``experiments.yaml`` and enforce the complete closed schema."""

    return parse_experiment_protocol(load_yaml(path))


def build_closed_loop_scenario(
    protocol: ExperimentProtocol, scenario_id: str
) -> Scenario:
    """Small functional wrapper used by experiment runners."""

    if not isinstance(protocol, ExperimentProtocol):
        raise TypeError("protocol must be an ExperimentProtocol")
    return protocol.build_scenario(scenario_id)


__all__ = [
    "EXPERIMENT_PROTOCOL_SCHEMA_VERSION",
    "FROZEN_METHOD_IDS",
    "FROZEN_SCENARIO_IDS",
    "ExperimentProtocol",
    "ExperimentTimebase",
    "MethodDefinition",
    "NoiseProfile",
    "ScenarioVariantDefinition",
    "SeedSet",
    "StochasticLoadDefinition",
    "TuningSelectionRule",
    "build_closed_loop_scenario",
    "load_experiment_protocol",
    "parse_experiment_protocol",
]
