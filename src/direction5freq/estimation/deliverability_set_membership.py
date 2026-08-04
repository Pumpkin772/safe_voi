"""Causal model-feasible deliverability sets for power, ramp and delay."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

from direction5freq.models.capability_contract import CapabilityContract


@dataclass(frozen=True, slots=True)
class DeliverabilityFeasibleSetSnapshot:
    contract_power_pu: np.ndarray
    contract_ramp_pu_per_s: np.ndarray
    performance_power_pu: np.ndarray
    performance_ramp_pu_per_s: np.ndarray
    power_capability_interval_pu: np.ndarray
    ramp_capability_interval_pu_per_s: np.ndarray
    delay_candidates_s: np.ndarray
    feasible_delay_mask: np.ndarray
    delay_interval_s: np.ndarray
    parameter_bounds_ab: np.ndarray
    one_step_delivered_power_interval_pu: np.ndarray
    excitation_sufficient: np.ndarray
    feasible_set_empty: np.ndarray
    change_reset: np.ndarray
    model_residual_bound_pu: float
    samples: int


class DeliverabilitySetMembership:
    """Maintain non-falsified `(a,b,delay)` models on a registered outer grid.

    Each grid point represents a cell whose prediction error is inflated by the
    registered residual bound.  A point is retained only if every post-reset
    transition is compatible with

    `p[k+1] = a p[k] + b u[k-delay] + e[k]`, `|e[k]| <= epsilon`.

    Power/ramp evidence is not promoted to hard safety.  It only constructs a
    revocable performance envelope and resets to the contract floor when the
    accumulated model set becomes empty after an abrupt change.
    """

    def __init__(
        self,
        contract: CapabilityContract,
        dt_s: float,
        *,
        window_samples: int = 96,
        delay_grid_s: tuple[float, ...] | None = None,
        residual_bound_pu: float = 0.003,
        physical_power_max_pu: float = 0.10,
        physical_ramp_max_pu_per_s: float = 0.10,
    ) -> None:
        self.contract = contract
        self.dt_s = float(dt_s)
        if self.dt_s <= 0:
            raise ValueError("dt_s must be positive")
        if delay_grid_s is None:
            maximum = max(contract.maximum_delay_s)
            delay_grid_s = tuple(np.linspace(0.0, maximum, 7))
        self.delay_grid = np.asarray(delay_grid_s, dtype=float)
        if np.any(np.diff(self.delay_grid) <= 0) or np.any(self.delay_grid < 0):
            raise ValueError("delay grid must be strictly increasing and nonnegative")
        self.residual_bound = float(residual_bound_pu)
        self.physical_power_max = float(physical_power_max_pu)
        self.physical_ramp_max = float(physical_ramp_max_pu_per_s)
        self.window_samples = int(max(window_samples, 8))
        self.a_grid = np.linspace(0.0, 1.0, 41)
        self.b_grid = np.linspace(0.0, 1.50, 51)
        self._a_mesh, self._b_mesh = np.meshgrid(self.a_grid, self.b_grid, indexing="ij")
        self._time: deque[float] = deque(maxlen=self.window_samples)
        self._command: deque[np.ndarray] = deque(maxlen=self.window_samples)
        self._actual: deque[np.ndarray] = deque(maxlen=self.window_samples)
        self._feasible = np.ones(
            (2, len(self.delay_grid), len(self.a_grid), len(self.b_grid)), dtype=bool
        )
        self._inconsistent_counts = np.zeros(2, dtype=int)
        self._performance_power = np.asarray(contract.upper_power_pu, dtype=float).copy()
        self._performance_ramp = np.asarray(contract.ramp_up_pu_per_s, dtype=float).copy()

    def _refresh_performance_witness(self, area: int) -> None:
        """Publish only a currently witnessed, readily revocable envelope.

        A historical peak is not a capability guarantee: after an unannounced
        transition it can remain above the new deliverability for an arbitrary
        detection interval. Promotion therefore requires six consecutive
        same-direction, high-request samples whose delivered magnitude has
        reached a near-steady plateau. The witness expires immediately when
        any condition is lost. This envelope is allocation evidence only; the
        independent contract remains the hard robust floor.
        """

        contract_power = float(self.contract.upper_power_pu[area])
        contract_ramp = float(self.contract.ramp_up_pu_per_s[area])
        self._performance_power[area] = contract_power
        self._performance_ramp[area] = contract_ramp
        witness_samples = 6
        if len(self._time) < witness_samples:
            return
        commands = np.asarray(self._command, dtype=float)[-witness_samples:, area]
        actual = np.asarray(self._actual, dtype=float)[-witness_samples:, area]
        command_sign = np.sign(commands)
        if (
            np.any(np.abs(commands) < 0.045)
            or np.any(command_sign == 0.0)
            or not np.all(command_sign == command_sign[-1])
            or not np.all(np.sign(actual) == command_sign[-1])
        ):
            return
        delivered = np.abs(actual)
        # A changing pipeline/ramp transient is not a power-capability witness.
        if float(np.ptp(delivered[-4:])) > 0.0045:
            return
        lower_power = float(np.min(delivered[-4:]) - self.residual_bound)
        if lower_power > contract_power:
            self._performance_power[area] = min(lower_power, self.physical_power_max)

        observed_ramps = np.abs(np.diff(actual)) / self.dt_s
        active = observed_ramps[
            observed_ramps > contract_ramp + self.residual_bound / self.dt_s
        ]
        if active.size:
            lower_ramp = float(np.min(active) - self.residual_bound / self.dt_s)
            self._performance_ramp[area] = min(
                max(contract_ramp, lower_ramp), self.physical_ramp_max
            )

    def _reset_area(self, area: int) -> None:
        self._feasible[area] = True
        self._inconsistent_counts[area] = 0
        self._performance_power[area] = float(self.contract.upper_power_pu[area])
        self._performance_ramp[area] = float(self.contract.ramp_up_pu_per_s[area])

    def _interpolated_command(self, query_time: float, area: int) -> float:
        time = np.asarray(self._time, dtype=float)
        command = np.asarray(self._command, dtype=float)[:, area]
        return float(np.interp(query_time, time, command, left=command[0], right=command[-1]))

    def update(
        self,
        time_s: float,
        requested_total_power_pu: np.ndarray,
        actual_poi_power_pu: np.ndarray,
    ) -> DeliverabilityFeasibleSetSnapshot:
        command = np.asarray(requested_total_power_pu, dtype=float)
        actual = np.asarray(actual_poi_power_pu, dtype=float)
        if command.shape != (2,) or actual.shape != (2,):
            raise ValueError("set-membership estimator requires two-area command and actual vectors")
        if self._time and time_s <= self._time[-1]:
            raise ValueError("timestamps must increase")
        previous_time = self._time[-1] if self._time else None
        previous_actual = self._actual[-1].copy() if self._actual else None
        self._time.append(float(time_s))
        self._command.append(command.copy())
        self._actual.append(actual.copy())
        reset = np.zeros(2, dtype=bool)
        if previous_time is not None and previous_actual is not None:
            transition_time = float(previous_time)
            for area in range(2):
                for delay_index, delay_s in enumerate(self.delay_grid):
                    delayed_command = self._interpolated_command(transition_time - float(delay_s), area)
                    predicted = self._a_mesh * previous_actual[area] + self._b_mesh * delayed_command
                    # Grid-cell and measurement/model residual inflation.
                    grid_inflation = (
                        0.5 * (self.a_grid[1] - self.a_grid[0]) * abs(previous_actual[area])
                        + 0.5 * (self.b_grid[1] - self.b_grid[0]) * abs(delayed_command)
                    )
                    compatible = np.abs(actual[area] - predicted) <= self.residual_bound + grid_inflation
                    self._feasible[area, delay_index] &= compatible
                any_model = bool(self._feasible[area].any())
                self._inconsistent_counts[area] = 0 if any_model else self._inconsistent_counts[area] + 1
                if self._inconsistent_counts[area] >= 2:
                    self._reset_area(area)
                    reset[area] = True

            command_history = np.asarray(self._command)
            excitation = (
                np.ptp(command_history, axis=0) >= 0.035
            ) & (np.max(np.abs(command_history), axis=0) >= 0.045)
            for area in range(2):
                if excitation[area] and not reset[area]:
                    self._refresh_performance_witness(area)
                else:
                    self._performance_power[area] = float(self.contract.upper_power_pu[area])
                    self._performance_ramp[area] = float(self.contract.ramp_up_pu_per_s[area])
        command_history = np.asarray(self._command)
        excitation = (
            (np.ptp(command_history, axis=0) >= 0.035)
            & (np.max(np.abs(command_history), axis=0) >= 0.045)
        ) if len(command_history) >= 2 else np.zeros(2, dtype=bool)

        feasible_delay = self._feasible.reshape(2, len(self.delay_grid), -1).any(axis=2)
        empty = ~feasible_delay.any(axis=1)
        parameter_bounds = np.full((2, len(self.delay_grid), 4), np.nan)
        one_step = np.full((2, 2), np.nan)
        delay_interval = np.zeros((2, 2))
        for area in range(2):
            candidate_predictions: list[np.ndarray] = []
            for delay_index, delay_s in enumerate(self.delay_grid):
                mask = self._feasible[area, delay_index]
                if not mask.any():
                    continue
                a_values = self._a_mesh[mask]
                b_values = self._b_mesh[mask]
                parameter_bounds[area, delay_index] = (
                    float(a_values.min()), float(a_values.max()),
                    float(b_values.min()), float(b_values.max()),
                )
                delayed = self._interpolated_command(float(time_s - delay_s), area)
                candidate_predictions.append(a_values * actual[area] + b_values * delayed)
            if candidate_predictions:
                predictions = np.concatenate(candidate_predictions)
                one_step[area] = (
                    float(predictions.min() - self.residual_bound),
                    float(predictions.max() + self.residual_bound),
                )
                values = self.delay_grid[feasible_delay[area]]
                half_step = 0.5 * float(np.min(np.diff(self.delay_grid)))
                delay_interval[area] = (
                    max(0.0, float(values.min() - half_step)),
                    min(max(self.contract.maximum_delay_s), float(values.max() + half_step)),
                )
            else:
                one_step[area] = (-self.physical_power_max, self.physical_power_max)
                delay_interval[area] = (0.0, max(self.contract.maximum_delay_s))

        power_interval = np.c_[self._performance_power, np.full(2, self.physical_power_max)]
        ramp_interval = np.c_[self._performance_ramp, np.full(2, self.physical_ramp_max)]
        return DeliverabilityFeasibleSetSnapshot(
            contract_power_pu=np.asarray(self.contract.upper_power_pu, dtype=float),
            contract_ramp_pu_per_s=np.asarray(self.contract.ramp_up_pu_per_s, dtype=float),
            performance_power_pu=self._performance_power.copy(),
            performance_ramp_pu_per_s=self._performance_ramp.copy(),
            power_capability_interval_pu=power_interval,
            ramp_capability_interval_pu_per_s=ramp_interval,
            delay_candidates_s=self.delay_grid.copy(),
            feasible_delay_mask=feasible_delay,
            delay_interval_s=delay_interval,
            parameter_bounds_ab=parameter_bounds,
            one_step_delivered_power_interval_pu=one_step,
            excitation_sufficient=excitation,
            feasible_set_empty=empty,
            change_reset=reset,
            model_residual_bound_pu=self.residual_bound,
            samples=len(self._time),
        )


__all__ = ["DeliverabilityFeasibleSetSnapshot", "DeliverabilitySetMembership"]
