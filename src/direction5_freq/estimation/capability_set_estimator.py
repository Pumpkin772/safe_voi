"""Causal command-to-actual BESS capability-set estimator."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class CapabilitySetEstimate:
    power_discharge_interval_pu: np.ndarray
    power_charge_interval_pu: np.ndarray
    ramp_up_interval_pu_per_s: np.ndarray
    ramp_down_interval_pu_per_s: np.ndarray
    delay_interval_s: np.ndarray
    energy_available_interval_mwh: np.ndarray
    availability_interval: np.ndarray
    excitation_sufficient: np.ndarray
    update_reason: str


class CapabilitySetEstimator:
    """Maintain conservative parameter intervals using public command/POI data.

    The estimator never reads capability truth. With no excitation, intervals
    remain wide. A persistent command-to-actual mismatch expands lower bounds
    before collecting new evidence, preventing stale pre-change capability from
    being treated as a guarantee after an unannounced derating.
    """

    def __init__(
        self,
        sample_time_s: float,
        rating_pu: float = 0.10,
        maximum_ramp_pu_per_s: float = 0.08,
        maximum_delay_s: float = 2.0,
        maximum_energy_available_mwh: float = 20.0,
        nominal_frequency_hz: float = 50.0,
        pfr_gain: float = 2.5,
    ) -> None:
        self.sample_time_s = float(sample_time_s)
        self.rating = float(rating_pu)
        self.maximum_ramp = float(maximum_ramp_pu_per_s)
        self.maximum_delay = float(maximum_delay_s)
        self.maximum_energy = float(maximum_energy_available_mwh)
        self.nominal_frequency_hz = float(nominal_frequency_hz)
        self.pfr_gain = float(pfr_gain)
        self.reset()

    def reset(self) -> None:
        self.power_discharge_lower = np.zeros(2)
        self.power_charge_lower = np.zeros(2)
        self.ramp_up_lower = np.zeros(2)
        self.ramp_down_lower = np.zeros(2)
        self.delay_lower = np.zeros(2)
        self.delay_upper = np.full(2, self.maximum_delay)
        self.energy_used = np.zeros(2)
        self.initial_soc: np.ndarray | None = None
        self.previous_actual = np.zeros(2)
        self.previous_request = np.zeros(2)
        self.previous_time: float | None = None
        self.mismatch_duration = np.zeros(2)
        self.excitation_count = np.zeros(2, dtype=int)
        history_samples = max(int(np.ceil(24.0 / self.sample_time_s)), 64)
        self.request_history: deque[np.ndarray] = deque(maxlen=history_samples)
        self.actual_history: deque[np.ndarray] = deque(maxlen=history_samples)

    def _update_delay_model_set(self) -> np.ndarray:
        """Update delay bounds from a causal command/output model set.

        A single response threshold is unsafe when PFR is superimposed on SFR:
        a response belonging to an earlier command can otherwise be assigned to
        a newer command.  Here every admissible delay is scored over the same
        history after fitting only a static gain and bias.  The retained set is
        deliberately enlarged for actuator lag and sampling uncertainty.  If
        the public I/O does not identify delay, the registered physical interval
        is kept rather than reporting a false contraction.
        """

        identifiable = np.zeros(2, dtype=bool)
        if len(self.request_history) < max(12, int(np.ceil(8.0 / self.sample_time_s))):
            return identifiable
        request = np.asarray(self.request_history, dtype=float)
        actual = np.asarray(self.actual_history, dtype=float)
        maximum_lag = int(np.floor(self.maximum_delay / self.sample_time_s + 1e-9))
        for area in range(2):
            command_steps = np.abs(np.diff(request[:, area])) >= 0.015
            if np.count_nonzero(command_steps) < 3:
                self.delay_lower[area] = 0.0
                self.delay_upper[area] = self.maximum_delay
                continue
            output_span = float(np.ptp(actual[:, area]))
            if output_span < 0.004:
                self.delay_lower[area] = 0.0
                self.delay_upper[area] = self.maximum_delay
                continue
            delays: list[float] = []
            errors: list[float] = []
            for lag in range(maximum_lag + 1):
                if lag:
                    x = request[:-lag, area]
                    y = actual[lag:, area]
                else:
                    x = request[:, area]
                    y = actual[:, area]
                if x.size < 24 or float(np.ptp(x)) < 0.015:
                    continue
                design = np.c_[x, np.ones_like(x)]
                gain, bias = np.linalg.lstsq(design, y, rcond=None)[0]
                if not (0.0 <= gain <= 1.5):
                    continue
                residual = y - (gain * x + bias)
                delays.append(lag * self.sample_time_s)
                errors.append(float(np.sqrt(np.mean(residual**2))))
            if not errors:
                self.delay_lower[area] = 0.0
                self.delay_upper[area] = self.maximum_delay
                continue
            error = np.asarray(errors)
            candidate_delay = np.asarray(delays)
            tolerance = max(0.003, 0.20 * output_span)
            retained = candidate_delay[error <= float(np.min(error)) + tolerance]
            if retained.size == 0:
                self.delay_lower[area] = 0.0
                self.delay_upper[area] = self.maximum_delay
                continue
            # The physical channel is followed by a 0.15 s actuator and sampled
            # at 0.05 s.  A 0.40 s outer allowance also covers the registered
            # jitter/noise range without using capability truth.
            lower = max(0.0, float(np.min(retained)) - 0.40)
            upper = min(self.maximum_delay, float(np.max(retained)) + 0.40)
            if upper - lower >= 0.90 * self.maximum_delay:
                self.delay_lower[area] = 0.0
                self.delay_upper[area] = self.maximum_delay
                continue
            self.delay_lower[area] = lower
            self.delay_upper[area] = upper
            identifiable[area] = True
        return identifiable

    def update(
        self,
        time_s: float,
        issued_bess_command_pu: np.ndarray,
        actual_bess_power_pu: np.ndarray,
        frequency_deviation_hz: np.ndarray,
        soc: np.ndarray,
    ) -> CapabilitySetEstimate:
        command = np.asarray(issued_bess_command_pu, dtype=float)
        actual = np.asarray(actual_bess_power_pu, dtype=float)
        frequency = np.asarray(frequency_deviation_hz, dtype=float)
        soc_value = np.asarray(soc, dtype=float)
        if any(value.shape != (2,) for value in (command, actual, frequency, soc_value)):
            raise ValueError("capability estimator inputs must contain two areas")
        pfr = -self.pfr_gain * frequency / self.nominal_frequency_hz
        request = command + pfr
        if self.initial_soc is None:
            self.initial_soc = soc_value.copy()
        dt = (
            self.sample_time_s
            if self.previous_time is None
            else max(float(time_s) - self.previous_time, 1e-9)
        )
        ramp = (actual - self.previous_actual) / dt
        changed = np.abs(request - self.previous_request) >= 0.004
        for area in range(2):
            if changed[area]:
                self.excitation_count[area] += 1
            mismatch = abs(request[area] - actual[area]) > 0.012 and abs(request[area]) > 0.015
            self.mismatch_duration[area] = (
                self.mismatch_duration[area] + dt if mismatch else 0.0
            )
            if self.mismatch_duration[area] > self.maximum_delay + 0.30:
                # Change alarm: stale pre-change witnessed lower bounds are no
                # longer guarantees. Expansion precedes any new contraction.
                self.power_discharge_lower[area] = max(actual[area], 0.0)
                self.power_charge_lower[area] = max(-actual[area], 0.0)
                self.ramp_up_lower[area] = max(ramp[area], 0.0)
                self.ramp_down_lower[area] = max(-ramp[area], 0.0)
                self.delay_lower[area] = 0.0
                self.delay_upper[area] = self.maximum_delay
                self.mismatch_duration[area] = 0.0
        self.power_discharge_lower = np.maximum(
            self.power_discharge_lower, np.maximum(actual, 0.0)
        )
        self.power_charge_lower = np.maximum(
            self.power_charge_lower, np.maximum(-actual, 0.0)
        )
        self.ramp_up_lower = np.maximum(self.ramp_up_lower, np.maximum(ramp, 0.0))
        self.ramp_down_lower = np.maximum(
            self.ramp_down_lower, np.maximum(-ramp, 0.0)
        )
        self.energy_used = np.maximum(
            self.energy_used, np.abs(soc_value - self.initial_soc) * 50.0
        )
        self.request_history.append(request.copy())
        self.actual_history.append(actual.copy())
        delay_identifiable = self._update_delay_model_set()
        self.previous_actual = actual.copy()
        self.previous_request = request.copy()
        self.previous_time = float(time_s)
        excited = self.excitation_count >= 2
        return CapabilitySetEstimate(
            power_discharge_interval_pu=np.c_[
                self.power_discharge_lower, np.full(2, self.rating)
            ],
            power_charge_interval_pu=np.c_[
                self.power_charge_lower, np.full(2, self.rating)
            ],
            ramp_up_interval_pu_per_s=np.c_[
                self.ramp_up_lower, np.full(2, self.maximum_ramp)
            ],
            ramp_down_interval_pu_per_s=np.c_[
                self.ramp_down_lower, np.full(2, self.maximum_ramp)
            ],
            delay_interval_s=np.c_[self.delay_lower, self.delay_upper],
            energy_available_interval_mwh=np.c_[
                np.minimum(self.energy_used, self.maximum_energy),
                np.full(2, self.maximum_energy),
            ],
            availability_interval=np.c_[np.zeros(2), np.ones(2)],
            excitation_sufficient=excited.copy(),
            update_reason=(
                "set_updated_from_public_io"
                if np.any(excited)
                else (
                    "delay_structurally_unidentifiable_hold_wide"
                    if not np.any(delay_identifiable)
                    else "insufficient_excitation_hold_wide"
                )
            ),
        )
