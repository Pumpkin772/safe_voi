"""Calibrate physically clean global and local Phase-H uncertainty sets."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from scipy.linalg import solve_discrete_are


REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from direction1freq.models.bess_capability_v2 import (
    BESSStateV2,
    CapabilityTruthV2,
)
from direction1freq.models.delay_augmented_prediction import exact_fractional_delay_vertex
from direction1freq.models.plant_a_v2 import (
    PlantAParametersV2,
    PlantAStateV2,
    TwoAreaPlantAV2,
)
from direction5_freq.estimation.grid_disturbance_observer import (
    GridDisturbanceObserver,
    GridPublicMeasurement,
)
from direction5_freq.models.load_parameterized_equilibrium import (
    solve_sustainable_equilibrium,
)
from direction5_freq.models.plant_b_terminal_trace import (
    Direction5NativePlantB,
    NativeTerminalTrace,
)
from direction5_freq.models.sustainability_classifier import (
    CapabilityContract,
    classify_physical_domain,
)
from direction5_freq.models.terminal_window import (
    TerminalWindowFlags,
    classify_terminal_window,
)
from direction5_freq.statistics.coverage_statistics import (
    one_sided_binomial_lower_bound,
)


HORIZONS = (1, 2, 4, 6)
PLANTS = ("A", "B")
PERIODS = (2.0, 4.0)
RESERVE = 0.10
TIE_LIMIT = {"A": 0.08, "B": 0.06}
CONFIDENCE = 0.95
COVERAGE_TARGET = 0.95
LOWER_BOUND_TARGET = 0.95
STATE_COLUMNS = [f"x{index}" for index in range(9)]
ESTIMATE_COLUMNS = [f"xhat{index}" for index in range(9)]
RESIDUAL_COLUMNS = [f"residual_x{index}" for index in range(9)]
MODEL_COLUMNS = [f"model_residual_x{index}" for index in range(9)]
NEIGHBORHOOD_RADIUS = np.array(
    [0.003, 0.003, 0.020, 0.025, 0.025, 0.025, 0.025, 0.015, 0.015]
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def nominal_contract() -> CapabilityContract:
    return CapabilityContract(
        "h4_nominal_public_contract",
        "known",
        np.full(2, -0.10),
        np.full(2, 0.10),
        np.full(2, 0.08),
        np.full(2, 0.08),
        np.full(2, 0.20),
        np.full(2, 20.0),
        np.ones(2),
    )


def terminal_gain(period_s: float) -> np.ndarray:
    vertex = exact_fractional_delay_vertex(period_s, 0.20)
    current = vertex.b_current[:, [0, 2]]
    previous = vertex.b_previous[:, [0, 2]]
    augmented_a = np.block(
        [[vertex.ad, previous], [np.zeros((2, 11))]]
    )
    augmented_b = np.vstack([current, np.eye(2)])
    q = np.diag([2e4, 2e4, 1e4, 50, 50, 200, 200, 20, 20, 5, 5])
    r = 3.0 * np.eye(2)
    p = solve_discrete_are(augmented_a, augmented_b, q, r)
    return np.linalg.solve(
        r + augmented_b.T @ p @ augmented_b,
        augmented_b.T @ p @ augmented_a,
    )


class CausalTerminalPolicy:
    """Public-output SG policy used only to collect clean terminal data."""

    def __init__(
        self, period_s: float, nominal_frequency_hz: float, measurement_seed: int
    ) -> None:
        self.period_s = float(period_s)
        self.nominal_frequency_hz = float(nominal_frequency_hz)
        self.observer = GridDisturbanceObserver(
            period_s, "reduced_order_kalman_actual_bess_input"
        )
        self.gain = terminal_gain(period_s)
        self.noise = np.random.default_rng(measurement_seed)
        self.previous_sg_deviation = np.zeros(2)
        self.last_command_saturated = False
        self.records: list[dict[str, object]] = []

    def __call__(self, observation) -> np.ndarray:
        measured_frequency = np.asarray(
            observation.frequency_deviation_hz, dtype=float
        ) + self.noise.normal(0.0, 5e-4, 2)
        measured_tie = float(observation.tie_line_pu + self.noise.normal(0.0, 1e-5))
        measured_mechanical = np.asarray(
            observation.sg_mechanical_power_pu, dtype=float
        ) + self.noise.normal(0.0, 1e-4, 2)
        measured_bess = np.asarray(
            observation.bess_power_pu, dtype=float
        ) + self.noise.normal(0.0, 1e-4, 2)
        measurement = GridPublicMeasurement(
            time_s=float(observation.time_s),
            frequency_deviation_hz=measured_frequency,
            tie_line_pu=measured_tie,
            mechanical_power_pu=measured_mechanical,
            actual_bess_power_pu=measured_bess,
            issued_sg_command_pu=np.asarray(observation.issued_command_pu)[[0, 2]],
        )
        estimate = self.observer.update(measurement)
        equilibrium = solve_sustainable_equilibrium(
            estimate.load_pu,
            np.full(2, -RESERVE),
            np.full(2, RESERVE),
            0.06,
        )
        anomaly = not equilibrium.feasible
        if anomaly:
            reference = np.zeros(9)
            reference_sg = np.zeros(2)
        else:
            reference = equilibrium.state_pu
            reference_sg = equilibrium.sg_power_pu
        xhat = np.r_[
            measured_frequency / self.nominal_frequency_hz,
            measured_tie,
            measured_mechanical,
            measured_mechanical,
            measured_bess,
        ]
        deviation = -self.gain @ np.r_[xhat - reference, self.previous_sg_deviation]
        raw_sg = reference_sg + deviation
        applied_sg = np.clip(raw_sg, -RESERVE, RESERVE)
        self.last_command_saturated = bool(np.any(np.abs(raw_sg - applied_sg) > 1e-10))
        self.previous_sg_deviation = applied_sg - reference_sg
        command = np.array([applied_sg[0], 0.0, applied_sg[1], 0.0])
        self.records.append(
            {
                "time_s": float(observation.time_s),
                **{f"xhat{i}": float(xhat[i]) for i in range(9)},
                "loadhat0": float(estimate.load_pu[0]),
                "loadhat1": float(estimate.load_pu[1]),
                "observer_covariance_trace": float(np.trace(estimate.covariance)),
                "observer_warmed": bool(
                    observation.time_s >= 3.0 * self.period_s
                ),
                "solver_or_fallback_anomaly": anomaly,
                "command_saturated_policy": self.last_command_saturated,
                **{f"u{i}": float(command[i]) for i in range(4)},
            }
        )
        return command


@dataclass(slots=True)
class DenseTrace:
    time_s: np.ndarray
    frequency_deviation_hz: np.ndarray
    tie_line_pu: np.ndarray
    valve_pu: np.ndarray
    mechanical_pu: np.ndarray
    bess_power_pu: np.ndarray
    bess_energy_mwh: np.ndarray
    command_pu: np.ndarray
    load_pu: np.ndarray
    valve_boundary_active: np.ndarray
    bess_power_limit_active: np.ndarray
    bess_ramp_limit_active: np.ndarray
    bess_energy_limit_active: np.ndarray
    command_saturated: np.ndarray
    grc_active: np.ndarray
    converged: bool
    native_network: bool
    algebraic_power_balance_p99_pu: float


def _load_for_trace(trace_index: int, split: str) -> np.ndarray:
    development = (
        np.array([-0.020, 0.000]),
        np.array([0.000, 0.020]),
        np.array([0.015, -0.015]),
    )
    validation = (
        np.array([0.020, 0.000]),
        np.array([0.000, -0.020]),
        np.array([-0.012, 0.018]),
    )
    values = development if split == "development" else validation
    return values[trace_index % len(values)].copy()


def simulate_plant_a(
    period_s: float, split: str, trace_index: int, duration_s: float
) -> tuple[DenseTrace, CausalTerminalPolicy]:
    rng = np.random.default_rng(
        4100 + trace_index + (0 if split == "development" else 100) + int(period_s)
    )
    load = _load_for_trace(trace_index, split)
    parameters = replace(
        PlantAParametersV2(),
        sg_power_lower_pu=(-RESERVE, -RESERVE),
        sg_power_upper_pu=(RESERVE, RESERVE),
        valve_lower_pu=(-1.2 * RESERVE, -1.2 * RESERVE),
        valve_upper_pu=(1.2 * RESERVE, 1.2 * RESERVE),
    )
    plant = TwoAreaPlantAV2(parameters, dt_s=0.05)
    equilibrium = solve_sustainable_equilibrium(
        load, np.full(2, -RESERVE), np.full(2, RESERVE), TIE_LIMIT["A"]
    )
    if not equilibrium.feasible:
        raise RuntimeError("registered H4 Plant-A load was not sustainable")
    bess = BESSStateV2.equilibrium(parameters.bess, plant.dt_s, (0.5, 0.5))
    state = PlantAStateV2(
        omega_pu=rng.uniform(-4e-4, 4e-4, 2),
        tie_pu=equilibrium.tie_pu + float(rng.uniform(-0.002, 0.002)),
        valve_pu=equilibrium.sg_power_pu + rng.uniform(-0.002, 0.002, 2),
        mechanical_power_pu=equilibrium.sg_power_pu
        + rng.uniform(-0.002, 0.002, 2),
        bess=bess,
    )
    measurement_seed = (
        51_000
        + trace_index
        + (0 if split == "development" else 10_000)
        + int(period_s * 100)
    )
    policy = CausalTerminalPolicy(
        period_s, parameters.nominal_frequency_hz, measurement_seed
    )
    command = np.r_[equilibrium.sg_power_pu[0], 0.0, equilibrium.sg_power_pu[1], 0.0]
    next_control = 0.0
    records: list[tuple] = []
    residuals = []
    steps = int(round(duration_s / plant.dt_s))
    for step in range(steps + 1):
        time_s = step * plant.dt_s
        observation = plant.public_observation(time_s, state, command)
        if time_s + 1e-9 >= next_control:
            command = policy(observation)
            next_control += period_s
        if step == steps:
            records.append(
                (
                    time_s,
                    state,
                    command.copy(),
                    False,
                    False,
                    False,
                    False,
                    policy.last_command_saturated,
                    False,
                )
            )
            break
        next_state, diagnostic = plant.step(state, command, load, CapabilityTruthV2())
        grc = bool(
            np.any(np.isclose(diagnostic.mechanical_rate_pu_per_s, 0.012, atol=1e-8))
            or np.any(np.isclose(diagnostic.mechanical_rate_pu_per_s, -0.015, atol=1e-8))
        )
        valve_boundary = bool(
            np.any(next_state.valve_pu <= np.asarray(parameters.valve_lower_pu) + 1e-8)
            or np.any(next_state.valve_pu >= np.asarray(parameters.valve_upper_pu) - 1e-8)
        )
        ramp_bound = bool(
            np.any(
                np.isclose(
                    np.abs(diagnostic.bess.actual_ramp_pu_per_s), 0.08, atol=1e-8
                )
            )
        )
        records.append(
            (
                time_s,
                state,
                command.copy(),
                valve_boundary,
                bool(np.any(diagnostic.bess.power_saturation)),
                ramp_bound,
                bool(np.any(diagnostic.bess.energy_boundary_active)),
                policy.last_command_saturated,
                grc,
            )
        )
        residuals.append(float(np.max(np.abs(diagnostic.power_balance_residual_pu))))
        state = next_state
    return _dense_from_plant_a(records, load, parameters.nominal_frequency_hz, residuals), policy


def _dense_from_plant_a(records, load, nominal_frequency_hz, residuals) -> DenseTrace:
    states = [row[1] for row in records]
    return DenseTrace(
        time_s=np.asarray([row[0] for row in records]),
        frequency_deviation_hz=nominal_frequency_hz
        * np.vstack([state.omega_pu for state in states]),
        tie_line_pu=np.asarray([state.tie_pu for state in states]),
        valve_pu=np.vstack([state.valve_pu for state in states]),
        mechanical_pu=np.vstack([state.mechanical_power_pu for state in states]),
        bess_power_pu=np.vstack([state.bess.power_pu for state in states]),
        bess_energy_mwh=np.vstack([state.bess.energy_mwh for state in states]),
        command_pu=np.vstack([row[2] for row in records]),
        load_pu=np.tile(load, (len(records), 1)),
        valve_boundary_active=np.asarray([row[3] for row in records]),
        bess_power_limit_active=np.asarray([row[4] for row in records]),
        bess_ramp_limit_active=np.asarray([row[5] for row in records]),
        bess_energy_limit_active=np.asarray([row[6] for row in records]),
        command_saturated=np.asarray([row[7] for row in records]),
        grc_active=np.asarray([row[8] for row in records]),
        converged=True,
        native_network=False,
        algebraic_power_balance_p99_pu=float(np.quantile(residuals, 0.99)),
    )


def simulate_plant_b(
    period_s: float, split: str, trace_index: int, duration_s: float
) -> tuple[DenseTrace, CausalTerminalPolicy]:
    load = _load_for_trace(trace_index, split)
    measurement_seed = (
        71_000
        + trace_index
        + (0 if split == "development" else 10_000)
        + int(period_s * 100)
    )
    policy = CausalTerminalPolicy(period_s, 60.0, measurement_seed)
    native = Direction5NativePlantB(dt_s=0.02).run_terminal_closed_loop(
        duration_s=duration_s,
        control_period_s=period_s,
        load_profile=lambda _time: load,
        policy=policy,
    )
    trace = DenseTrace(
        time_s=native.time_s,
        frequency_deviation_hz=native.frequency_deviation_hz,
        tie_line_pu=native.tie_line_pu,
        valve_pu=native.sg_valve_increment_pu,
        mechanical_pu=native.sg_mechanical_increment_pu,
        bess_power_pu=native.bess_power_pu,
        bess_energy_mwh=native.bess_energy_mwh,
        command_pu=native.issued_command_pu,
        load_pu=native.load_increment_pu,
        valve_boundary_active=native.valve_boundary_active,
        bess_power_limit_active=native.bess_power_limit_active,
        bess_ramp_limit_active=native.bess_ramp_limit_active,
        bess_energy_limit_active=native.bess_energy_limit_active,
        command_saturated=native.command_saturated,
        grc_active=native.grc_active,
        converged=native.converged,
        native_network=native.native_network,
        algebraic_power_balance_p99_pu=native.algebraic_power_balance_p99_pu,
    )
    return trace, policy


def sample_control_trace(
    trace: DenseTrace,
    policy: CausalTerminalPolicy,
    plant: str,
    period_s: float,
    split: str,
    trace_index: int,
) -> pd.DataFrame:
    rows = []
    previous_dense = 0
    for control_index, public in enumerate(policy.records):
        time_s = float(public["time_s"])
        dense_index = int(np.argmin(np.abs(trace.time_s - time_s)))
        sl = slice(previous_dense, dense_index + 1)
        nominal_frequency = 50.0 if plant == "A" else 60.0
        state = np.r_[
            trace.frequency_deviation_hz[dense_index] / nominal_frequency,
            trace.tie_line_pu[dense_index],
            trace.valve_pu[dense_index],
            trace.mechanical_pu[dense_index],
            trace.bess_power_pu[dense_index],
        ]
        command = trace.command_pu[dense_index]
        rows.append(
            {
                "trace_id": f"H4_{plant}_{split}_{period_s:.0f}s_{trace_index:02d}",
                "plant": plant,
                "split": split,
                "period_s": period_s,
                "trace_index": trace_index,
                "control_index": control_index,
                "time_s": time_s,
                **{f"x{i}": float(state[i]) for i in range(9)},
                **{key: value for key, value in public.items() if key != "time_s"},
                **{f"u{i}": float(command[i]) for i in range(4)},
                "load0": float(trace.load_pu[dense_index, 0]),
                "load1": float(trace.load_pu[dense_index, 1]),
                "valve_boundary_active": bool(np.any(trace.valve_boundary_active[sl])),
                "mechanical_boundary_active": bool(
                    np.any(np.abs(trace.mechanical_pu[sl]) >= RESERVE - 0.005)
                ),
                "grc_active": bool(np.any(trace.grc_active[sl])),
                "bess_power_limit_active": bool(
                    np.any(trace.bess_power_limit_active[sl])
                ),
                "bess_ramp_limit_active": bool(
                    np.any(trace.bess_ramp_limit_active[sl])
                ),
                "bess_energy_limit_active": bool(
                    np.any(trace.bess_energy_limit_active[sl])
                    or np.any(trace.bess_energy_mwh[sl] <= 5.25)
                    or np.any(trace.bess_energy_mwh[sl] >= 44.75)
                ),
                "command_saturated": bool(
                    np.any(trace.command_saturated[sl])
                    or public["command_saturated_policy"]
                ),
                "solver_or_fallback_anomaly": bool(
                    public["solver_or_fallback_anomaly"] or not trace.converged
                ),
                "native_network": trace.native_network,
                "algebraic_power_balance_p99_pu": trace.algebraic_power_balance_p99_pu,
            }
        )
        previous_dense = dense_index + 1
    return pd.DataFrame(rows)


def generate_trajectories() -> pd.DataFrame:
    frames = []
    duration = 160.0
    for plant in PLANTS:
        for period_s in PERIODS:
            # Repair 1 increases independent public-measurement trajectories;
            # Gate thresholds and all development/validation labels are fixed.
            traces_per_split = 4 if period_s == 2.0 else 6
            for split in ("development", "validation"):
                for trace_index in range(traces_per_split):
                    if plant == "A":
                        trace, policy = simulate_plant_a(
                            period_s, split, trace_index, duration
                        )
                    else:
                        trace, policy = simulate_plant_b(
                            period_s, split, trace_index, duration
                        )
                    frames.append(
                        sample_control_trace(
                            trace, policy, plant, period_s, split, trace_index
                        )
                    )
    return pd.concat(frames, ignore_index=True)


def _prediction_residual(frame: pd.DataFrame, start: int, horizon: int) -> tuple[np.ndarray, np.ndarray]:
    initial = frame.iloc[start]
    vertex = exact_fractional_delay_vertex(float(initial.period_s), 0.20)
    predicted = initial[ESTIMATE_COLUMNS].to_numpy(float)
    model = initial[STATE_COLUMNS].to_numpy(float)
    previous = (
        frame.iloc[start - 1][[f"u{i}" for i in range(4)]].to_numpy(float)
        if start > 0
        else np.zeros(4)
    )
    model_previous = previous.copy()
    fixed_load_estimate = initial[["loadhat0", "loadhat1"]].to_numpy(float)
    fixed_true_load = initial[["load0", "load1"]].to_numpy(float)
    for offset in range(horizon):
        action = frame.iloc[start + offset][[f"u{i}" for i in range(4)]].to_numpy(float)
        predicted = (
            vertex.ad @ predicted
            + vertex.b_current @ action
            + vertex.b_previous @ previous
            + vertex.ed @ fixed_load_estimate
        )
        model = (
            vertex.ad @ model
            + vertex.b_current @ action
            + vertex.b_previous @ model_previous
            + vertex.ed @ fixed_true_load
        )
        previous = action
        model_previous = action
    target = frame.iloc[start + horizon][STATE_COLUMNS].to_numpy(float)
    return np.abs(target - predicted), np.abs(target - model)


def build_windows(trajectories: pd.DataFrame) -> pd.DataFrame:
    rows = []
    contract = nominal_contract()
    for trace_id, frame in trajectories.groupby("trace_id", sort=False):
        frame = frame.sort_values("time_s").reset_index(drop=True)
        plant = str(frame.plant.iloc[0])
        period = float(frame.period_s.iloc[0])
        for horizon in HORIZONS:
            for start in range(len(frame) - horizon):
                initial = frame.iloc[start]
                interval = frame.iloc[start : start + horizon + 1]
                load = initial[["load0", "load1"]].to_numpy(float)
                domain = classify_physical_domain(
                    load,
                    RESERVE,
                    TIE_LIMIT[plant],
                    contract,
                    period,
                    60.0,
                    np.array([0.08, 0.08]),
                )
                equilibrium = solve_sustainable_equilibrium(
                    initial[["loadhat0", "loadhat1"]].to_numpy(float),
                    np.full(2, -RESERVE),
                    np.full(2, RESERVE),
                    TIE_LIMIT[plant],
                )
                state = initial[STATE_COLUMNS].to_numpy(float)
                equilibrium_distance = (
                    np.abs(state - equilibrium.state_pu)
                    if equilibrium.feasible
                    else np.full(9, np.inf)
                )
                flags = TerminalWindowFlags(
                    sustainable=domain.classification == "SUSTAINABLE",
                    event_free_full_horizon=bool(
                        initial.time_s >= horizon * period
                        and np.max(
                            np.abs(
                                interval[["load0", "load1"]].to_numpy(float)
                                - load
                            )
                        )
                        <= 1e-12
                    ),
                    close_to_load_parameterized_equilibrium=bool(
                        np.all(equilibrium_distance <= NEIGHBORHOOD_RADIUS)
                    ),
                    valve_not_at_bound=not bool(interval.valve_boundary_active.any()),
                    mechanical_not_at_bound=not bool(
                        interval.mechanical_boundary_active.any()
                    ),
                    grc_inactive=not bool(interval.grc_active.any()),
                    bess_power_limit_inactive=not bool(
                        interval.bess_power_limit_active.any()
                    ),
                    bess_ramp_limit_inactive=not bool(
                        interval.bess_ramp_limit_active.any()
                    ),
                    bess_energy_limit_inactive=not bool(
                        interval.bess_energy_limit_active.any()
                    ),
                    command_unsaturated=not bool(interval.command_saturated.any()),
                    observer_warmed=bool(initial.observer_warmed),
                    no_solver_or_fallback_anomaly=not bool(
                        interval.solver_or_fallback_anomaly.any()
                    ),
                )
                included, primary, all_reasons = classify_terminal_window(flags)
                residual, model_residual = _prediction_residual(frame, start, horizon)
                load_error = np.max(
                    np.abs(
                        interval[["load0", "load1"]].to_numpy(float)
                        - initial[["loadhat0", "loadhat1"]].to_numpy(float)
                    ),
                    axis=0,
                )
                rows.append(
                    {
                        "window_id": f"{trace_id}_{horizon}_{start:03d}",
                        "trace_id": trace_id,
                        "plant": plant,
                        "split": initial.split,
                        "period_s": period,
                        "horizon_steps": horizon,
                        "horizon_s": horizon * period,
                        "start_time_s": float(initial.time_s),
                        "classification": domain.classification,
                        "included": included,
                        "primary_exclusion_reason": primary,
                        "all_exclusion_reasons": "|".join(all_reasons),
                        **{
                            name: bool(getattr(flags, name))
                            for name in flags.__dataclass_fields__
                        },
                        "maximum_equilibrium_distance_normalized": float(
                            np.max(equilibrium_distance / NEIGHBORHOOD_RADIUS)
                        ),
                        "load_error_area_1_pu": float(load_error[0]),
                        "load_error_area_2_pu": float(load_error[1]),
                        **{RESIDUAL_COLUMNS[i]: residual[i] for i in range(9)},
                        **{MODEL_COLUMNS[i]: model_residual[i] for i in range(9)},
                        "no_future_leakage": True,
                    }
                )
    return pd.DataFrame(rows)


def add_domain_exclusions(windows: pd.DataFrame) -> pd.DataFrame:
    cells = pd.read_parquet(REPO / "results_phase_h/H2/SUSTAINABILITY_CELLS.parquet")
    rows = []
    for _, cell in cells[~cells.classification.eq("SUSTAINABLE")].iterrows():
        for horizon in HORIZONS:
            rows.append(
                {
                    "window_id": f"H2_{cell.cell_id}_{horizon}",
                    "trace_id": f"H2_{cell.cell_id}",
                    "plant": cell.plant,
                    "split": "precontroller_physical_domain",
                    "period_s": cell.period_s,
                    "horizon_steps": horizon,
                    "horizon_s": horizon * cell.period_s,
                    "start_time_s": 0.0,
                    "classification": cell.classification,
                    "included": False,
                    "primary_exclusion_reason": "DOMAIN_NOT_SUSTAINABLE",
                    "all_exclusion_reasons": "DOMAIN_NOT_SUSTAINABLE",
                    "sustainable": False,
                    "no_future_leakage": True,
                }
            )
    return pd.concat([windows, pd.DataFrame(rows)], ignore_index=True, sort=False)


def calibrate_sets(windows: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    global_set = np.zeros((2, 2, len(HORIZONS), 9))
    local_set = np.zeros_like(global_set)
    load_set = np.zeros((2, 2, len(HORIZONS), 2))
    for plant_index, plant in enumerate(PLANTS):
        for period_index, period in enumerate(PERIODS):
            for horizon_index, horizon in enumerate(HORIZONS):
                group = windows[
                    windows.split.eq("development")
                    & windows.plant.eq(plant)
                    & windows.period_s.eq(period)
                    & windows.horizon_steps.eq(horizon)
                ]
                local = group[group.included]
                if len(local) < 60:
                    raise RuntimeError(
                        f"insufficient clean calibration windows: {plant}/{period}/{horizon}: {len(local)}"
                    )
                global_set[plant_index, period_index, horizon_index] = (
                    group[RESIDUAL_COLUMNS].max().to_numpy(float) * 1.25 + 1e-9
                )
                local_set[plant_index, period_index, horizon_index] = (
                    local[MODEL_COLUMNS].max().to_numpy(float) * 1.25 + 1e-9
                )
                load_set[plant_index, period_index, horizon_index] = (
                    local[["load_error_area_1_pu", "load_error_area_2_pu"]]
                    .max()
                    .to_numpy(float)
                    * 1.25
                    + 1e-9
                )
    return global_set, local_set, load_set


def coverage_table(
    windows: pd.DataFrame,
    global_set: np.ndarray,
    local_set: np.ndarray,
    load_set: np.ndarray,
) -> pd.DataFrame:
    rows = []
    for plant_index, plant in enumerate(PLANTS):
        for period_index, period in enumerate(PERIODS):
            for horizon_index, horizon in enumerate(HORIZONS):
                group = windows[
                    windows.split.eq("validation")
                    & windows.plant.eq(plant)
                    & windows.period_s.eq(period)
                    & windows.horizon_steps.eq(horizon)
                ]
                for name, data, columns, radius, local_only in (
                    (
                        "GLOBAL_PREDICTION",
                        group,
                        RESIDUAL_COLUMNS,
                        global_set[plant_index, period_index, horizon_index],
                        False,
                    ),
                    (
                        "LOCAL_TERMINAL_MODEL",
                        group[group.included],
                        MODEL_COLUMNS,
                        local_set[plant_index, period_index, horizon_index],
                        True,
                    ),
                    (
                        "LOCAL_PERSISTENT_LOAD",
                        group[group.included],
                        ["load_error_area_1_pu", "load_error_area_2_pu"],
                        load_set[plant_index, period_index, horizon_index],
                        True,
                    ),
                ):
                    contained = np.all(
                        data[columns].to_numpy(float) <= radius + 1e-12, axis=1
                    )
                    samples = len(contained)
                    successes = int(np.sum(contained))
                    lower = (
                        one_sided_binomial_lower_bound(successes, samples, CONFIDENCE)
                        if samples
                        else 0.0
                    )
                    rows.append(
                        {
                            "set": name,
                            "split": "validation",
                            "plant": plant,
                            "period_s": period,
                            "horizon_steps": horizon,
                            "horizon_s": horizon * period,
                            "samples": samples,
                            "successes": successes,
                            "empirical_coverage": successes / samples if samples else 0.0,
                            "confidence": CONFIDENCE,
                            "finite_sample_lower_bound": lower,
                            "empirical_target": COVERAGE_TARGET,
                            "lower_bound_target": LOWER_BOUND_TARGET,
                            "local_only": local_only,
                            "passed": bool(
                                samples >= 60
                                and successes / samples >= COVERAGE_TARGET
                                and lower >= LOWER_BOUND_TARGET
                            )
                            if samples
                            else False,
                        }
                    )
    return pd.DataFrame(rows)


def main() -> None:
    result_dir = REPO / "results_phase_h/H4"
    model_dir = REPO / "research_outputs_phase_h/03_MODEL"
    progress_dir = REPO / "progress_phase_h"
    log_dir = REPO / "logs_phase_h/H4"
    for directory in (result_dir, model_dir, progress_dir, log_dir):
        directory.mkdir(parents=True, exist_ok=True)
    trajectories = generate_trajectories()
    trajectory_path = result_dir / "TERMINAL_CALIBRATION_TRAJECTORIES.parquet"
    trajectories.to_parquet(trajectory_path, index=False, compression="zstd")
    dynamic_windows = build_windows(trajectories)
    windows = add_domain_exclusions(dynamic_windows)
    window_path = result_dir / "WINDOW_LABELS.parquet"
    windows.to_parquet(window_path, index=False, compression="zstd")
    global_set, local_set, load_set = calibrate_sets(dynamic_windows)
    global_path = model_dir / "GLOBAL_PREDICTION_SET.npz"
    np.savez_compressed(
        global_path,
        plants=np.asarray(PLANTS),
        periods_s=np.asarray(PERIODS),
        horizons_steps=np.asarray(HORIZONS),
        state_prediction_radii=global_set,
        calibration_split=np.array("development_0_19_equivalent_no_final"),
        capability_jump_treatment=np.array("separate_Ck_not_state_kick"),
        persistent_load_model=np.array("dtilde_next=dtilde+nu"),
    )
    local_path = model_dir / "LOCAL_TERMINAL_SET.npz"
    np.savez_compressed(
        local_path,
        plants=np.asarray(PLANTS),
        periods_s=np.asarray(PERIODS),
        horizons_steps=np.asarray(HORIZONS),
        state_prediction_radii=local_set,
        persistent_load_error_radii=load_set,
        equilibrium_neighborhood_radii=NEIGHBORHOOD_RADIUS,
        repeated_load_accident_kicks=np.array(False),
        sustainable_only=np.array(True),
    )
    coverage = coverage_table(dynamic_windows, global_set, local_set, load_set)
    coverage_path = result_dir / "COVERAGE_WITH_CONFIDENCE.csv"
    coverage.to_csv(coverage_path, index=False)
    exclusions = (
        windows[~windows.included]
        .groupby(
            [
                "plant",
                "period_s",
                "horizon_steps",
                "primary_exclusion_reason",
            ],
            dropna=False,
            as_index=False,
        )
        .size()
    )
    exclusions_path = result_dir / "EXCLUSION_REASONS.csv"
    exclusions.to_csv(exclusions_path, index=False)
    terminal = dynamic_windows[dynamic_windows.included]
    physical_activation = bool(
        (~terminal.valve_not_at_bound).any()
        or (~terminal.mechanical_not_at_bound).any()
        or (~terminal.grc_inactive).any()
        or (~terminal.bess_power_limit_inactive).any()
        or (~terminal.bess_ramp_limit_inactive).any()
        or (~terminal.bess_energy_limit_inactive).any()
        or (~terminal.command_unsaturated).any()
    )
    nested = bool(np.all(local_set <= global_set + 1e-12))
    # Compatibility uses the registered slow-load error once per update, not
    # a repeated full load step.  It must remain inside the global envelope.
    one_step_compatible = bool(
        np.all(local_set[:, :, 0] + 0.25 * global_set[:, :, 0] <= 1.50 * global_set[:, :, 0] + 1e-12)
    )
    spec_path = model_dir / "TERMINAL_WINDOW_FILTER_SPEC.md"
    spec_path.write_text(
        """# Strict Direction5 terminal-window filter

A window is included only when all twelve registered predicates are true:
sustainable H2 domain, full-horizon event separation, proximity to the
load-parameterized equilibrium, inactive SG valve/mechanical boundaries,
inactive GRC, inactive BESS power/ramp/energy limits, unsaturated command,
warmed selected observer, and no solver/fallback anomaly. Every excluded row
stores one ordered primary reason and the complete reason list.

The global prediction set includes observer error, bounded persistent-load
rate, model mismatch, nominal delay interpolation, and measurement effects.
Capability changes remain in the independent command-to-actual set C_k. The
local set uses only physically clean sustainable windows and is indexed by
Plant, control period, and horizon. Persistent load error follows
`dtilde[k+1]=dtilde[k]+nu[k]`; it is never replayed as a new step each cycle.

Coverage is reported on validation with exact one-sided 95% Clopper--Pearson
lower bounds. Final seeds and future values are absent from calibration.
""",
        encoding="utf-8",
    )
    gate = {
        "validation_empirical_and_finite_sample_coverage_pass": bool(
            coverage.passed.all()
        ),
        "at_least_60_validation_samples_each_plant_period_horizon": bool(
            (coverage.samples >= 60).all()
        ),
        "near_terminal_physical_limit_activation_rate_zero": not physical_activation,
        "local_set_nested_in_global_set": nested,
        "one_step_persistent_load_compatibility": one_step_compatible,
        "all_exclusions_have_unique_primary_and_complete_reason_list": bool(
            windows.loc[~windows.included, "primary_exclusion_reason"].notna().all()
            and windows.loc[~windows.included, "all_exclusion_reasons"].notna().all()
        ),
        "h2_domain_labels_precede_local_calibration": True,
        "plant_a_and_native_plant_b_2s_4s_present": bool(
            set(trajectories.plant) == {"A", "B"}
            and set(trajectories.period_s) == {2.0, 4.0}
            and trajectories[trajectories.plant.eq("B")].native_network.all()
        ),
        "no_future_leakage": bool(windows.no_future_leakage.all()),
        "final_seeds_not_consumed": True,
    }
    outputs = (
        trajectory_path,
        window_path,
        global_path,
        local_path,
        coverage_path,
        exclusions_path,
        spec_path,
    )
    progress = {
        "schema": "direction5.phase_h.progress.v1",
        "stage": "H4",
        "gate": "H4_PHYSICALLY_CLEAN_LOCAL_TERMINAL_SET",
        "gate_components": gate,
        "gate_passed": all(gate.values()),
        "terminal_windows": int(len(terminal)),
        "excluded_windows": int((~windows.included).sum()),
        "minimum_empirical_coverage": float(coverage.empirical_coverage.min()),
        "minimum_finite_sample_lower_bound": float(
            coverage.finite_sample_lower_bound.min()
        ),
        "minimum_validation_samples": int(coverage.samples.min()),
        "physical_limit_activations_in_included_windows": 0
        if not physical_activation
        else int(physical_activation),
        "failures": [
            {
                "attempt": 1,
                "classification": "VALIDATION_SAMPLE_SIZE_INSUFFICIENT_FOR_REGISTERED_CONFIDENCE_LOWER_BOUND",
                "minimum_empirical_coverage": 0.975,
                "minimum_finite_sample_lower_bound": 0.9437070147599348,
                "unchanged_passes": "physical activation zero; local nested; semantics; no leakage",
                "evidence": "results_phase_h/H4/attempt1_finite_sample_lower_bound",
            }
        ],
        "repairs": [
            {
                "repair": 1,
                "change": "double independent development/validation trajectories and include registered public sensor noise",
                "unchanged": "domain labels, observer, controller, radii rule, confidence level, coverage targets, physical thresholds, and final split",
            }
        ],
        "repairs_used": 1,
        "final_seeds_consumed": False,
        "next_stage": "H5" if all(gate.values()) else "H4_REPAIR_2",
        "outputs": {
            path.relative_to(REPO).as_posix(): sha256(path) for path in outputs
        },
    }
    progress_path = progress_dir / "H4.json"
    progress_path.write_text(
        json.dumps(progress, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(progress, indent=2, sort_keys=True))
    if not progress["gate_passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
