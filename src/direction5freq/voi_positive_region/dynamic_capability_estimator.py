"""Window-level dynamic evidence for hidden BESS deliverability.

The estimator uses only issued SFR commands, measured frequency, and measured
actual POI power.  It never receives the realized power/ramp/delay parameters.
Candidate responses include the public local PFR law, SFR delay, total-power
clipping, ramp clipping, and the public actuator time constant.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, sqrt
from typing import Iterable

import numpy as np
from scipy.stats import chi2


@dataclass(frozen=True, slots=True)
class DynamicCapabilityCandidate:
    candidate_id: str
    power_pu: float
    ramp_pu_per_s: float
    delay_s: float


@dataclass(frozen=True, slots=True)
class DynamicEvidenceConfig:
    sample_period_s: float = 0.2
    internal_step_s: float = 0.02
    actuator_time_constant_s: float = 0.15
    pfr_gain_pu_power_per_pu_frequency: float = 2.5
    nominal_frequency_hz: float = 50.0
    contract_power_pu: float = 0.045
    excitation_margin_pu: float = 0.0015
    maximum_delay_s: float = 1.5
    settling_exclusion_s: float = 1.5
    post_action_response_s: float = 2.0
    measurement_noise_std_pu: float = 0.0015
    ar1_correlation: float = 0.2
    deterministic_residual_bound_pu: float = 0.0005
    familywise_false_optimism: float = 0.01
    maximum_windows: int = 2
    information_validity_s: float = 240.0

    def __post_init__(self) -> None:
        if self.sample_period_s <= 0.0 or self.internal_step_s <= 0.0:
            raise ValueError("sampling intervals must be positive")
        if self.measurement_noise_std_pu <= 0.0:
            raise ValueError("measurement noise must be positive")
        if not 0.0 <= self.ar1_correlation < 1.0:
            raise ValueError("AR(1) correlation must lie in [0, 1)")
        if not 0.0 < self.familywise_false_optimism < 1.0:
            raise ValueError("false-optimism probability must lie in (0, 1)")
        if self.maximum_windows < 1:
            raise ValueError("at least one evidence window is required")


@dataclass(frozen=True, slots=True)
class DynamicWindowResult:
    start_time_s: float
    end_time_s: float
    area: int
    direction: float
    raw_samples: int
    scored_samples: int
    window_alpha: float
    likelihood_radius: float
    retained_candidate_ids: tuple[str, ...]
    score_by_candidate: dict[str, float]


@dataclass(frozen=True, slots=True)
class _Sample:
    time_s: float
    issued_sfr_pu: np.ndarray
    actual_poi_pu: np.ndarray
    frequency_hz: np.ndarray


def _held_value(times: np.ndarray, values: np.ndarray, query_time_s: float) -> float:
    index = int(np.searchsorted(times, query_time_s, side="right") - 1)
    return float(values[max(index, 0)])


def simulate_candidate_response(
    times_s: np.ndarray,
    issued_sfr_pu: np.ndarray,
    frequency_hz: np.ndarray,
    initial_actual_power_pu: float,
    candidate: DynamicCapabilityCandidate,
    config: DynamicEvidenceConfig,
) -> np.ndarray:
    """Predict one candidate response on the supplied causal sample grid."""

    times = np.asarray(times_s, dtype=float)
    commands = np.asarray(issued_sfr_pu, dtype=float)
    frequency = np.asarray(frequency_hz, dtype=float)
    if times.ndim != 1 or commands.shape != times.shape or frequency.shape != times.shape:
        raise ValueError("times, command, and frequency must be aligned vectors")
    if len(times) < 1 or np.any(np.diff(times) <= 0.0):
        raise ValueError("sample times must be strictly increasing")

    prediction = np.empty(len(times), dtype=float)
    prediction[0] = float(initial_actual_power_pu)
    power = float(initial_actual_power_pu)
    for index in range(1, len(times)):
        left = float(times[index - 1])
        right = float(times[index])
        interval = right - left
        substeps = max(1, int(ceil(interval / config.internal_step_s)))
        step = interval / substeps
        for substep in range(substeps):
            time_s = left + (substep + 1) * step
            fraction = (time_s - left) / interval
            local_frequency_hz = (
                (1.0 - fraction) * frequency[index - 1]
                + fraction * frequency[index]
            )
            pfr = (
                -config.pfr_gain_pu_power_per_pu_frequency
                * local_frequency_hz
                / config.nominal_frequency_hz
            )
            delayed_sfr = _held_value(
                times,
                commands,
                time_s - candidate.delay_s,
            )
            target = float(np.clip(
                pfr + delayed_sfr,
                -candidate.power_pu,
                candidate.power_pu,
            ))
            raw_rate = (target - power) / config.actuator_time_constant_s
            rate = float(np.clip(
                raw_rate,
                -candidate.ramp_pu_per_s,
                candidate.ramp_pu_per_s,
            ))
            next_power = power + step * rate
            power = (
                min(next_power, target)
                if target >= power
                else max(next_power, target)
            )
        prediction[index] = power
    return prediction


def whitened_residual_score(
    residual: np.ndarray,
    config: DynamicEvidenceConfig,
) -> np.ndarray:
    """Return the bounded-residual AR(1)-whitened score along the last axis."""

    value = np.asarray(residual, dtype=float)
    if value.shape[-1] < 1:
        raise ValueError("at least one residual sample is required")
    rho = config.ar1_correlation
    sigma = config.measurement_noise_std_pu
    bound = config.deterministic_residual_bound_pu
    first = np.maximum(np.abs(value[..., 0]) - bound, 0.0) / sigma
    innovation = value[..., 1:] - rho * value[..., :-1]
    innovation_bound = bound * (1.0 + abs(rho))
    adjusted = np.maximum(np.abs(innovation) - innovation_bound, 0.0)
    innovation_sigma = sigma * sqrt(1.0 - rho * rho)
    return first * first + np.sum((adjusted / innovation_sigma) ** 2, axis=-1)


class DynamicCapabilityEstimator:
    """Intersect window-level likelihood sets over complete probe responses."""

    def __init__(
        self,
        candidates: Iterable[DynamicCapabilityCandidate],
        config: DynamicEvidenceConfig = DynamicEvidenceConfig(),
    ) -> None:
        self.config = config
        self.candidates = tuple(candidates)
        if not self.candidates:
            raise ValueError("candidate set cannot be empty")
        if len({item.candidate_id for item in self.candidates}) != len(self.candidates):
            raise ValueError("candidate identifiers must be unique")
        self._candidate_by_id = {item.candidate_id: item for item in self.candidates}
        self._retained = set(self._candidate_by_id)
        self._history: list[_Sample] = []
        self._window_start_s: float | None = None
        self._window_area: int | None = None
        self._window_direction = 0.0
        self._post_until_s: float | None = None
        self._first_evidence_s: float | None = None
        self._certified_at_s: float | None = None
        self._certified_until_s = -float("inf")
        self._model_inconsistent = False
        self.window_results: list[DynamicWindowResult] = []

    @property
    def retained_candidate_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._retained))

    @property
    def model_inconsistent(self) -> bool:
        return self._model_inconsistent

    @property
    def power_certificate_time_s(self) -> float | None:
        return self._certified_at_s

    @property
    def power_certified_until_s(self) -> float:
        return self._certified_until_s

    @property
    def high_capability_still_possible(self) -> bool:
        return any(
            self._candidate_by_id[candidate_id].power_pu
            > self.config.contract_power_pu + 1e-10
            for candidate_id in self._retained
        )

    def power_certified(self, time_s: float) -> bool:
        return bool(
            not self._model_inconsistent
            and self._retained
            and all(
                self._candidate_by_id[candidate_id].power_pu
                > self.config.contract_power_pu + 1e-10
                for candidate_id in self._retained
            )
            and time_s <= self._certified_until_s
        )

    def observe(
        self,
        time_s: float,
        issued_sfr_pu: np.ndarray,
        actual_poi_pu: np.ndarray,
        frequency_hz: np.ndarray,
    ) -> bool:
        issued = np.asarray(issued_sfr_pu, dtype=float)
        actual = np.asarray(actual_poi_pu, dtype=float)
        frequency = np.asarray(frequency_hz, dtype=float)
        if issued.shape != (2,) or actual.shape != (2,) or frequency.shape != (2,):
            raise ValueError("two-area command, POI power, and frequency are required")
        self._history.append(_Sample(
            float(time_s), issued.copy(), actual.copy(), frequency.copy()
        ))

        excess = np.abs(issued) - self.config.contract_power_pu
        area = int(np.argmax(excess))
        active = bool(excess[area] > self.config.excitation_margin_pu)
        if self._window_start_s is None and active and len(self.window_results) < self.config.maximum_windows:
            self._window_start_s = float(time_s)
            self._window_area = area
            self._window_direction = float(np.sign(issued[area]))
            self._post_until_s = None
            if self._first_evidence_s is None:
                self._first_evidence_s = float(time_s)
        elif self._window_start_s is not None:
            same_direction = bool(
                active
                and area == self._window_area
                and np.sign(issued[area]) == self._window_direction
            )
            if same_direction:
                self._post_until_s = None
            elif self._post_until_s is None:
                self._post_until_s = float(time_s) + self.config.post_action_response_s

        if (
            self._window_start_s is not None
            and self._post_until_s is not None
            and time_s + 1e-10 >= self._post_until_s
            and not active
        ):
            return self._finish_window(float(time_s))
        return False

    def _finish_window(self, end_time_s: float) -> bool:
        assert self._window_start_s is not None
        assert self._window_area is not None
        start = self._window_start_s
        area = self._window_area
        direction = self._window_direction
        history_start = start - self.config.maximum_delay_s - self.config.settling_exclusion_s
        samples = [
            sample for sample in self._history
            if history_start - 1e-10 <= sample.time_s <= end_time_s + 1e-10
        ]
        times = np.asarray([sample.time_s for sample in samples])
        issued = np.asarray([sample.issued_sfr_pu[area] for sample in samples])
        actual = np.asarray([sample.actual_poi_pu[area] for sample in samples])
        frequency = np.asarray([sample.frequency_hz[area] for sample in samples])
        score_mask = times >= start + self.config.settling_exclusion_s - 1e-10
        scores: dict[str, float] = {}
        for candidate in self.candidates:
            predicted = simulate_candidate_response(
                times,
                issued,
                frequency,
                actual[0],
                candidate,
                self.config,
            )
            scores[candidate.candidate_id] = self._whitened_score(
                actual[score_mask] - predicted[score_mask]
            )
        scored_samples = int(np.sum(score_mask))
        window_alpha = (
            self.config.familywise_false_optimism / self.config.maximum_windows
        )
        radius = float(chi2.ppf(1.0 - window_alpha, max(scored_samples, 1)))
        minimum = min(scores.values())
        window_retained = {
            candidate_id for candidate_id, score in scores.items()
            if score <= minimum + radius
        }
        self._retained.intersection_update(window_retained)
        if not self._retained:
            self._model_inconsistent = True
        self.window_results.append(DynamicWindowResult(
            start_time_s=start,
            end_time_s=end_time_s,
            area=area,
            direction=direction,
            raw_samples=len(samples),
            scored_samples=scored_samples,
            window_alpha=window_alpha,
            likelihood_radius=radius,
            retained_candidate_ids=self.retained_candidate_ids,
            score_by_candidate=scores,
        ))
        newly_certified = bool(
            self._certified_at_s is None
            and self._retained
            and not self._model_inconsistent
            and all(
                self._candidate_by_id[candidate_id].power_pu
                > self.config.contract_power_pu + 1e-10
                for candidate_id in self._retained
            )
        )
        if newly_certified:
            self._certified_at_s = end_time_s
            assert self._first_evidence_s is not None
            self._certified_until_s = (
                self._first_evidence_s + self.config.information_validity_s
            )
        self._window_start_s = None
        self._window_area = None
        self._window_direction = 0.0
        self._post_until_s = None
        return newly_certified

    def _whitened_score(self, residual: np.ndarray) -> float:
        value = np.asarray(residual, dtype=float)
        if not len(value):
            return float("inf")
        return float(whitened_residual_score(value, self.config))


__all__ = [
    "DynamicCapabilityCandidate",
    "DynamicCapabilityEstimator",
    "DynamicEvidenceConfig",
    "DynamicWindowResult",
    "simulate_candidate_response",
    "whitened_residual_score",
]
