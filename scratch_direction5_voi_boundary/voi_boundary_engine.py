"""Exact finite-candidate VoI boundary engine for the Direction5 scratch study.

The engine deliberately lives outside the active package until the B1 evidence
milestone.  It implements the equations in
``research/direction5_voi_boundary_final/02_COMPLETE_MATHEMATICAL_DERIVATION.md``
for a registered finite outer approximation of hidden BESS power, ramp, and
delay.  The ordinary optimization receives only the candidate set, measured
state, measured POI power, measured SoC, and the persistent load estimate.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from itertools import product
from functools import lru_cache
from math import exp
from time import perf_counter
from typing import Iterable, Sequence

import cvxpy as cp
import numpy as np
from scipy.signal import cont2discrete

from direction5freq.estimation.grid_load_observer import LoadObserverInput
from direction5freq.models.plant_a_full import PlantAFull, PlantAParameters


@dataclass(frozen=True, slots=True)
class ObjectiveScales:
    frequency_hz: float = 0.20
    ace_pu: float = 0.08
    tie_pu: float = 0.04
    sg_move_pu: float = 0.03
    bess_move_pu: float = 0.03


@dataclass(frozen=True, slots=True)
class BoundaryPoint:
    point_id: str
    period_s: float
    sg_tension: str
    load_magnitude_pu: float
    power_spread_pu: float
    ramp_spread_pu_per_s: float
    delay_spread_s: float
    noise_std_pu: float
    soc: float
    tie_loading_pu: float
    objective: str = "balanced"
    nominal_frequency_hz: float = 50.0


@dataclass(frozen=True, slots=True)
class CapabilityModel:
    model_id: str
    power_pu: float
    ramp_pu_per_s: float
    delay_s: float


@dataclass(frozen=True, slots=True)
class Probe:
    probe_id: str
    duration_s: float
    amplitude_pu: float
    shape: str
    area: int
    sign: int
    sequence_pu: tuple[float, ...]
    sg_compensation: bool = True


@dataclass(slots=True)
class PolicySolution:
    status: str
    objective: float
    sg_command: np.ndarray
    bess_command: np.ndarray
    states: dict[str, np.ndarray]
    bess_power: dict[str, np.ndarray]
    solve_time_s: float
    solver: str


@dataclass(slots=True)
class FixedPrefix:
    safe: bool
    reason: str
    states: dict[str, np.ndarray]
    bess_power: dict[str, np.ndarray]
    energy_mwh: dict[str, np.ndarray]
    prefix_cost: dict[str, float]
    sg_command: np.ndarray
    bess_command: np.ndarray


@dataclass(slots=True)
class RollingPrefix:
    safe: bool
    reason: str
    terminal_state: dict[str, np.ndarray]
    terminal_power: dict[str, np.ndarray]
    terminal_energy_mwh: dict[str, np.ndarray]
    previous_sg_command: dict[str, np.ndarray]
    previous_bess_command: dict[str, np.ndarray]
    load_observer: dict[str, object]
    prefix_cost: dict[str, float]
    solver_attempts: int
    solver_failures: int


@dataclass(slots=True)
class ProbeValue:
    probe_id: str
    safe: bool
    reason: str
    possible_posteriors: tuple[tuple[str, ...], ...]
    maximum_posterior_size: int
    mean_posterior_reduction: float
    upper_value: float
    exact_value: float
    probe_counterfactual_cost: float
    worst_post_probe_cost: float
    observation_intervals: dict[str, tuple[float, float]]
    solver_attempts: int
    solver_failures: int


@dataclass(slots=True)
class AcquisitionInformationValue:
    """Pure information value after an identical causal acquisition prefix."""

    safe: bool
    reason: str
    branch_value: dict[str, float]
    low_branch_value: float
    high_branch_value: float
    break_even_high_probability: float | None
    weakly_dominates_without_prior: bool
    exploit_recourse_cost: dict[str, float]
    posterior_recourse_cost: dict[str, float]
    solver_attempts: int
    solver_failures: int
    continuation_path_count: int
    continuation_steps: int


@dataclass(slots=True)
class OptimisticContinuationScreen:
    """Causal future-opportunity screen evaluated on public contract paths."""

    safe: bool
    reason: str
    maximum_value_gap: float
    maximum_path_index: int | None
    maximum_anchor_time_s: float | None
    anchor_values: tuple[float, ...]
    solver_attempts: int
    solver_failures: int
    path_count: int
    anchor_count: int


@dataclass(slots=True)
class BoundaryResult:
    point: BoundaryPoint
    candidate_models: tuple[CapabilityModel, ...]
    robust_cost: float
    perfect_information_cost: float
    perfect_information_value: float
    heuristic_value: float
    maximum_safe_probe_upper_value: float
    maximum_exact_probe_value: float
    region: str
    selected_probe_id: str | None
    no_probe_reason: str | None
    registered_probe_count: int
    safe_probe_count: int
    evaluated_probe_count: int
    all_safe_probes_evaluated: bool
    probes: tuple[ProbeValue, ...]
    solver_attempts: int
    solver_failures: int
    elapsed_s: float

    def summary(self) -> dict[str, object]:
        row = asdict(self.point)
        row.update(
            candidate_count=len(self.candidate_models),
            robust_cost=self.robust_cost,
            perfect_information_cost=self.perfect_information_cost,
            perfect_information_value=self.perfect_information_value,
            heuristic_value=self.heuristic_value,
            maximum_safe_probe_upper_value=self.maximum_safe_probe_upper_value,
            maximum_exact_probe_value=self.maximum_exact_probe_value,
            region=self.region,
            selected_probe_id=self.selected_probe_id,
            no_probe_reason=self.no_probe_reason,
            registered_probe_count=self.registered_probe_count,
            safe_probe_count=self.safe_probe_count,
            evaluated_probe_count=self.evaluated_probe_count,
            all_safe_probes_evaluated=self.all_safe_probes_evaluated,
            solver_attempts=self.solver_attempts,
            solver_failures=self.solver_failures,
            elapsed_s=self.elapsed_s,
        )
        return row


SHAPES: dict[str, tuple[float, ...]] = {
    "biphasic": (1.0, -1.0),
    "plateau_reverse": (1.0, 1.0, -1.0, -1.0),
    "staircase": (0.5, 1.0, 0.0, -1.0, -0.5),
    "prbs": (1.0, -1.0, -1.0, 1.0, -1.0, 1.0),
}


def objective_scales(name: str) -> ObjectiveScales:
    if name == "balanced":
        return ObjectiveScales()
    if name == "regional_responsibility":
        return ObjectiveScales(ace_pu=0.05, tie_pu=0.025)
    if name == "resource_economy":
        return ObjectiveScales(sg_move_pu=0.02, bess_move_pu=0.04)
    if name == "grid_service":
        return ObjectiveScales(
            frequency_hz=0.20, ace_pu=0.05, tie_pu=0.025,
            sg_move_pu=0.03, bess_move_pu=0.03,
        )
    if name == "sg_conserving_4":
        return ObjectiveScales(
            frequency_hz=0.20, ace_pu=0.05, tie_pu=0.025,
            sg_move_pu=0.02, bess_move_pu=0.04,
        )
    if name == "sg_conserving_16":
        return ObjectiveScales(
            frequency_hz=0.20, ace_pu=0.05, tie_pu=0.025,
            sg_move_pu=0.015, bess_move_pu=0.06,
        )
    if name == "sg_conserving_64":
        return ObjectiveScales(
            frequency_hz=0.20, ace_pu=0.05, tie_pu=0.025,
            sg_move_pu=0.01, bess_move_pu=0.08,
        )
    raise ValueError(f"unknown objective preference: {name}")


def plant_parameters(tension: str, nominal_frequency_hz: float = 50.0) -> PlantAParameters:
    base = PlantAParameters(nominal_frequency_hz=float(nominal_frequency_hz))
    if tension == "low":
        return base
    if tension == "medium":
        return PlantAParameters(
            nominal_frequency_hz=float(nominal_frequency_hz),
            valve_upper_pu=(0.125, 0.125),
            sg_power_upper_pu=(0.105, 0.105),
            grc_up_pu_per_s=(0.0105, 0.0105),
        )
    if tension == "high":
        return PlantAParameters(
            nominal_frequency_hz=float(nominal_frequency_hz),
            valve_upper_pu=(0.105, 0.105),
            sg_power_upper_pu=(0.090, 0.090),
            grc_up_pu_per_s=(0.009, 0.009),
        )
    raise ValueError(f"unknown SG tension: {tension}")


def candidate_models(point: BoundaryPoint) -> tuple[CapabilityModel, ...]:
    """Return the complete registered finite power/ramp/delay vertex set."""

    contract_power = 0.045
    contract_ramp = 0.025
    maximum_delay = 1.50
    powers = sorted({contract_power, min(0.080, contract_power + point.power_spread_pu)})
    ramps = sorted({contract_ramp, min(0.060, contract_ramp + point.ramp_spread_pu_per_s)})
    delays = sorted({maximum_delay, max(0.20, maximum_delay - point.delay_spread_s)})
    models = []
    for index, (power_cap, ramp_cap, delay) in enumerate(product(powers, ramps, delays)):
        models.append(
            CapabilityModel(
                model_id=f"M{index:02d}_P{power_cap:.4f}_R{ramp_cap:.4f}_D{delay:.3f}",
                power_pu=float(power_cap),
                ramp_pu_per_s=float(ramp_cap),
                delay_s=float(delay),
            )
        )
    return tuple(models)


def normalized_probe_sequence(shape: Sequence[float], steps: int) -> np.ndarray | None:
    if steps < 2:
        return None
    original = np.asarray(shape, dtype=float)
    source = np.linspace(0.0, 1.0, len(original))
    target = np.linspace(0.0, 1.0, steps)
    sequence = np.interp(target, source, original)
    sequence -= np.mean(sequence)
    maximum = np.max(np.abs(sequence))
    if maximum <= 1e-12:
        return None
    sequence /= maximum
    # The discrete allocation integral is exactly zero at either control period.
    sequence[-1] -= np.sum(sequence)
    maximum = np.max(np.abs(sequence))
    sequence /= maximum
    if abs(float(np.sum(sequence))) > 1e-12:
        raise RuntimeError("probe normalization failed to preserve allocation neutrality")
    return sequence


def probe_library(point: BoundaryPoint) -> tuple[Probe, ...]:
    unique: dict[tuple[float, ...], Probe] = {}
    for duration in (4.0, 8.0, 12.0):
        steps = int(round(duration / point.period_s))
        if abs(steps * point.period_s - duration) > 1e-9:
            continue
        for shape_name, shape in SHAPES.items():
            normalized = normalized_probe_sequence(shape, steps)
            if normalized is None:
                continue
            for amplitude in (0.00125, 0.0025, 0.00375, 0.0050, 0.0075):
                for area in (0, 1):
                    for sign in (-1, 1):
                        sequence = tuple(float(v * amplitude * sign) for v in normalized)
                        key = (float(duration), float(amplitude), float(area), *np.round(sequence, 12))
                        unique.setdefault(
                            key,
                            Probe(
                                probe_id=(
                                    f"{shape_name}_{duration:g}s_A{area + 1}_"
                                    f"{('p' if sign > 0 else 'n')}_{amplitude:.5f}"
                                ),
                                duration_s=duration,
                                amplitude_pu=amplitude,
                                shape=shape_name,
                                area=area,
                                sign=sign,
                                sequence_pu=sequence,
                            ),
                        )
    return tuple(unique.values())


def _discrete_grid(parameters: PlantAParameters, period_s: float) -> tuple[np.ndarray, np.ndarray]:
    full_a, full_b, _, full_e = PlantAFull(parameters).linear_continuous_model_separate()
    a = full_a[:7, :7]
    # Actual POI power is an explicit known grid input, separate from issued command.
    input_matrix = np.column_stack((full_b[:7, [0, 2]], full_a[:7, 7:9], full_e[:7]))
    ad, bd, _, _, _ = cont2discrete(
        (a, input_matrix, np.eye(7), np.zeros((7, 6))), period_s, method="zoh"
    )
    return np.asarray(ad), np.asarray(bd)


def initial_state(point: BoundaryPoint) -> np.ndarray:
    state = np.zeros(7)
    state[2] = point.tie_loading_pu
    return state


def load_vector(point: BoundaryPoint) -> np.ndarray:
    # Area imbalance makes ACE and tie-line regulation genuinely different objectives.
    return np.array((point.load_magnitude_pu, 0.65 * point.load_magnitude_pu))


def _stage_cost(
    state: cp.Expression | np.ndarray,
    sg: cp.Expression | np.ndarray,
    bess_command: cp.Expression | np.ndarray,
    previous_sg: cp.Expression | np.ndarray,
    previous_bess: cp.Expression | np.ndarray,
    scales: ObjectiveScales,
    period_s: float,
    nominal_frequency_hz: float,
) -> cp.Expression:
    omega = state[:2]
    tie = state[2]
    ace = cp.hstack((21.0 * omega[0] + tie, 21.0 * omega[1] - tie))
    frequency_hz = nominal_frequency_hz * omega
    return period_s * (
        cp.sum_squares(frequency_hz / scales.frequency_hz)
        + cp.sum_squares(ace / scales.ace_pu)
        + cp.square(tie / scales.tie_pu)
        + cp.sum_squares((sg - previous_sg) / scales.sg_move_pu)
        + cp.sum_squares((bess_command - previous_bess) / scales.bess_move_pu)
    )


def _numeric_stage_cost(
    state: np.ndarray,
    sg: np.ndarray,
    bess_command: np.ndarray,
    previous_sg: np.ndarray,
    previous_bess: np.ndarray,
    scales: ObjectiveScales,
    period_s: float,
    nominal_frequency_hz: float,
) -> float:
    omega = state[:2]
    tie = state[2]
    ace = np.array((21.0 * omega[0] + tie, 21.0 * omega[1] - tie))
    frequency_hz = nominal_frequency_hz * omega
    return float(period_s * (
        np.sum(np.square(frequency_hz / scales.frequency_hz))
        + np.sum(np.square(ace / scales.ace_pu))
        + np.square(tie / scales.tie_pu)
        + np.sum(np.square((sg - previous_sg) / scales.sg_move_pu))
        + np.sum(np.square((bess_command - previous_bess) / scales.bess_move_pu))
    ))


def solve_policy(
    point: BoundaryPoint,
    models: Sequence[CapabilityModel],
    *,
    horizon_steps: int,
    initial_grid_state: np.ndarray,
    initial_bess_power: np.ndarray | None = None,
    previous_sg_command: np.ndarray | None = None,
    previous_bess_command: np.ndarray | None = None,
    initial_energy_mwh: np.ndarray | None = None,
    load_forecast_pu: np.ndarray | None = None,
    scales: ObjectiveScales | None = None,
) -> PolicySolution:
    """Solve the common-sequence robust MPC for exactly the supplied posterior."""

    if horizon_steps <= 0:
        return PolicySolution(
            "optimal", 0.0, np.zeros((2, 0)), np.zeros((2, 0)), {}, {}, 0.0, "NONE"
        )
    if not models:
        raise ValueError("posterior model set cannot be empty")
    policy_scales = objective_scales(point.objective) if scales is None else scales
    parameters = plant_parameters(point.sg_tension, point.nominal_frequency_hz)
    ad, bd = _discrete_grid(parameters, point.period_s)
    load = (
        load_vector(point)
        if load_forecast_pu is None
        else np.asarray(load_forecast_pu, dtype=float)
    )
    if load.shape != (2,) or not np.all(np.isfinite(load)):
        raise ValueError("load forecast must contain two finite causal area loads")
    p0 = np.zeros(2) if initial_bess_power is None else np.asarray(initial_bess_power, dtype=float)
    prior_sg = np.zeros(2) if previous_sg_command is None else np.asarray(previous_sg_command, dtype=float)
    prior_bess = np.zeros(2) if previous_bess_command is None else np.asarray(previous_bess_command, dtype=float)
    energy0 = (
        np.full(2, parameters.bess.energy_mwh * point.soc)
        if initial_energy_mwh is None
        else np.asarray(initial_energy_mwh, dtype=float)
    )

    sg = cp.Variable((2, horizon_steps), name="sg")
    bess_command = cp.Variable((2, horizon_steps), name="bess_command")
    worst_cost = cp.Variable(name="worst_cost")
    constraints: list[cp.Constraint] = [
        sg >= np.asarray(parameters.valve_lower_pu)[:, None],
        sg <= np.asarray(parameters.valve_upper_pu)[:, None],
        bess_command >= -parameters.bess.rating_pu,
        bess_command <= parameters.bess.rating_pu,
        worst_cost >= 0.0,
    ]
    states: dict[str, cp.Variable] = {}
    powers: dict[str, cp.Variable] = {}
    model_costs: dict[str, cp.Expression] = {}
    alpha = exp(-point.period_s / parameters.bess.actuator_time_constant_s)
    for model in models:
        x = cp.Variable((7, horizon_steps + 1), name=f"x_{model.model_id}")
        p = cp.Variable((2, horizon_steps + 1), name=f"p_{model.model_id}")
        states[model.model_id] = x
        powers[model.model_id] = p
        constraints.extend((x[:, 0] == initial_grid_state, p[:, 0] == p0))
        cost: cp.Expression = 0.0
        throughput: cp.Expression = 0.0
        for step in range(horizon_steps):
            previous_bess = prior_bess if step == 0 else bess_command[:, step - 1]
            delay_fraction = min(max(model.delay_s / point.period_s, 0.0), 1.0)
            delayed = (1.0 - delay_fraction) * bess_command[:, step] + delay_fraction * previous_bess
            next_power = alpha * p[:, step] + (1.0 - alpha) * delayed
            constraints.extend((
                p[:, step + 1] == next_power,
                p[:, step + 1] <= model.power_pu,
                p[:, step + 1] >= -model.power_pu,
                p[:, step + 1] - p[:, step] <= model.ramp_pu_per_s * point.period_s,
                p[:, step + 1] - p[:, step] >= -model.ramp_pu_per_s * point.period_s,
                x[:, step + 1] == ad @ x[:, step] + bd @ cp.hstack((
                    sg[:, step], p[:, step + 1], load
                )),
                x[3:5, step + 1] >= np.asarray(parameters.valve_lower_pu),
                x[3:5, step + 1] <= np.asarray(parameters.valve_upper_pu),
                x[5:7, step + 1] >= np.asarray(parameters.sg_power_lower_pu),
                x[5:7, step + 1] <= np.asarray(parameters.sg_power_upper_pu),
                cp.abs(point.nominal_frequency_hz * x[:2, step + 1]) <= 1.0,
                cp.abs(x[2, step + 1]) <= 0.12,
            ))
            previous_sg = prior_sg if step == 0 else sg[:, step - 1]
            cost += _stage_cost(
                x[:, step + 1], sg[:, step], bess_command[:, step],
                previous_sg, previous_bess, policy_scales, point.period_s,
                point.nominal_frequency_hz,
            )
            throughput += cp.sum(cp.abs(p[:, step + 1]))
        # A conservative measured-SoC energy margin covers charge or discharge.
        available_energy = float(np.min(np.minimum(
            energy0 - parameters.bess.soc_min * parameters.bess.energy_mwh,
            parameters.bess.soc_max * parameters.bess.energy_mwh - energy0,
        )))
        constraints.append(
            throughput * point.period_s * parameters.system_base_mva
            / (3600.0 * min(parameters.bess.eta_charge, parameters.bess.eta_discharge))
            <= available_energy
        )
        cost += 2.0 * _stage_cost(
            x[:, horizon_steps], sg[:, horizon_steps - 1], bess_command[:, horizon_steps - 1],
            sg[:, horizon_steps - 1], bess_command[:, horizon_steps - 1],
            policy_scales, point.period_s, point.nominal_frequency_hz,
        )
        model_costs[model.model_id] = cost
        constraints.append(worst_cost >= cost)

    problem = cp.Problem(cp.Minimize(worst_cost), constraints)
    started = perf_counter()
    solver = "CLARABEL"
    try:
        problem.solve(
            solver=cp.CLARABEL,
            verbose=False,
            tol_gap_abs=1e-9,
            tol_gap_rel=1e-9,
            tol_feas=1e-9,
            max_iter=600,
        )
    except cp.error.SolverError:
        solver = "SCS"
        problem.solve(solver=cp.SCS, verbose=False, eps=1e-6, max_iters=40_000)
    elapsed = perf_counter() - started
    valid = problem.status in {cp.OPTIMAL, cp.OPTIMAL_INACCURATE}
    return PolicySolution(
        status=str(problem.status),
        objective=float(problem.value) if valid else float("inf"),
        sg_command=np.asarray(sg.value) if valid else np.empty((2, 0)),
        bess_command=np.asarray(bess_command.value) if valid else np.empty((2, 0)),
        states={key: np.asarray(value.value) for key, value in states.items()} if valid else {},
        bess_power={key: np.asarray(value.value) for key, value in powers.items()} if valid else {},
        solve_time_s=elapsed,
        solver=solver,
    )


def _fixed_prefix(
    point: BoundaryPoint,
    models: Sequence[CapabilityModel],
    baseline: PolicySolution,
    probe: Probe,
    scales: ObjectiveScales,
    *,
    initial_grid_state: np.ndarray | None = None,
    initial_bess_power: np.ndarray | None = None,
    previous_sg_command: np.ndarray | None = None,
    previous_bess_command: np.ndarray | None = None,
    initial_energy_mwh: np.ndarray | None = None,
    load_forecast_pu: np.ndarray | None = None,
) -> FixedPrefix:
    parameters = plant_parameters(point.sg_tension, point.nominal_frequency_hz)
    ad, bd = _discrete_grid(parameters, point.period_s)
    load = (
        load_vector(point)
        if load_forecast_pu is None
        else np.asarray(load_forecast_pu, dtype=float)
    )
    steps = len(probe.sequence_pu)
    if steps > baseline.sg_command.shape[1]:
        return FixedPrefix(False, "PROBE_LONGER_THAN_HORIZON", {}, {}, {}, {}, np.empty((0, 0)), np.empty((0, 0)))
    sg = baseline.sg_command[:, :steps].copy()
    bess = baseline.bess_command[:, :steps].copy()
    q = np.asarray(probe.sequence_pu)
    if probe.sg_compensation:
        sg[probe.area] -= q
    bess[probe.area] += q
    if np.any(sg < np.asarray(parameters.valve_lower_pu)[:, None] - 1e-10) or np.any(
        sg > np.asarray(parameters.valve_upper_pu)[:, None] + 1e-10
    ):
        return FixedPrefix(False, "SG_COMMAND_MARGIN", {}, {}, {}, {}, sg, bess)
    if np.any(np.abs(bess) > parameters.bess.rating_pu + 1e-10):
        return FixedPrefix(False, "BESS_COMMAND_RATING", {}, {}, {}, {}, sg, bess)

    states: dict[str, np.ndarray] = {}
    powers: dict[str, np.ndarray] = {}
    energies: dict[str, np.ndarray] = {}
    costs: dict[str, float] = {}
    alpha = exp(-point.period_s / parameters.bess.actuator_time_constant_s)
    for model in models:
        x = np.zeros((7, steps + 1))
        x[:, 0] = (
            initial_state(point)
            if initial_grid_state is None
            else np.asarray(initial_grid_state, dtype=float)
        )
        p = np.zeros((2, steps + 1))
        if initial_bess_power is not None:
            p[:, 0] = np.asarray(initial_bess_power, dtype=float)
        energy = np.zeros((2, steps + 1))
        energy[:, 0] = (
            parameters.bess.energy_mwh * point.soc
            if initial_energy_mwh is None
            else np.asarray(initial_energy_mwh, dtype=float)
        )
        cost = 0.0
        previous_sg = (
            np.zeros(2)
            if previous_sg_command is None
            else np.asarray(previous_sg_command, dtype=float).copy()
        )
        previous_bess = (
            np.zeros(2)
            if previous_bess_command is None
            else np.asarray(previous_bess_command, dtype=float).copy()
        )
        for step in range(steps):
            fraction = min(max(model.delay_s / point.period_s, 0.0), 1.0)
            delayed = (1.0 - fraction) * bess[:, step] + fraction * previous_bess
            target = alpha * p[:, step] + (1.0 - alpha) * delayed
            target = np.clip(target, -model.power_pu, model.power_pu)
            delta = np.clip(
                target - p[:, step],
                -model.ramp_pu_per_s * point.period_s,
                model.ramp_pu_per_s * point.period_s,
            )
            p[:, step + 1] = p[:, step] + delta
            average = 0.5 * (p[:, step] + p[:, step + 1])
            loss_adjusted = np.where(
                average >= 0.0,
                average / parameters.bess.eta_discharge,
                average * parameters.bess.eta_charge,
            )
            energy[:, step + 1] = (
                energy[:, step] - point.period_s * parameters.system_base_mva * loss_adjusted / 3600.0
            )
            x[:, step + 1] = ad @ x[:, step] + bd @ np.r_[sg[:, step], p[:, step + 1], load]
            cost += _numeric_stage_cost(
                x[:, step + 1], sg[:, step], bess[:, step],
                previous_sg, previous_bess, scales, point.period_s,
                point.nominal_frequency_hz,
            )
            previous_sg = sg[:, step]; previous_bess = bess[:, step]
        safe = bool(
            np.max(np.abs(point.nominal_frequency_hz * x[:2])) <= 1.0 + 1e-10
            and np.max(np.abs(x[2])) <= 0.12 + 1e-10
            and np.all(x[3:5] >= np.asarray(parameters.valve_lower_pu)[:, None] - 1e-10)
            and np.all(x[3:5] <= np.asarray(parameters.valve_upper_pu)[:, None] + 1e-10)
            and np.all(x[5:7] >= np.asarray(parameters.sg_power_lower_pu)[:, None] - 1e-10)
            and np.all(x[5:7] <= np.asarray(parameters.sg_power_upper_pu)[:, None] + 1e-10)
            and np.all(energy >= parameters.bess.soc_min * parameters.bess.energy_mwh - 1e-10)
            and np.all(energy <= parameters.bess.soc_max * parameters.bess.energy_mwh + 1e-10)
        )
        if not safe:
            return FixedPrefix(False, f"PHYSICAL_TUBE_{model.model_id}", {}, {}, {}, {}, sg, bess)
        states[model.model_id] = x
        powers[model.model_id] = p
        energies[model.model_id] = energy
        costs[model.model_id] = float(cost)
    return FixedPrefix(True, "SAFE", states, powers, energies, costs, sg, bess)


def _physical_limits_hold(
    point: BoundaryPoint,
    parameters: PlantAParameters,
    state: np.ndarray,
    energy_mwh: np.ndarray,
) -> bool:
    return bool(
        np.max(np.abs(point.nominal_frequency_hz * state[:2])) <= 1.0 + 1e-10
        and abs(float(state[2])) <= 0.12 + 1e-10
        and np.all(state[3:5] >= np.asarray(parameters.valve_lower_pu) - 1e-10)
        and np.all(state[3:5] <= np.asarray(parameters.valve_upper_pu) + 1e-10)
        and np.all(state[5:7] >= np.asarray(parameters.sg_power_lower_pu) - 1e-10)
        and np.all(state[5:7] <= np.asarray(parameters.sg_power_upper_pu) + 1e-10)
        and np.all(energy_mwh >= parameters.bess.soc_min * parameters.bess.energy_mwh - 1e-10)
        and np.all(energy_mwh <= parameters.bess.soc_max * parameters.bess.energy_mwh + 1e-10)
    )


def _propagate_truth_interval(
    point: BoundaryPoint,
    truth: CapabilityModel,
    state: np.ndarray,
    power: np.ndarray,
    energy_mwh: np.ndarray,
    sg_command: np.ndarray,
    bess_command: np.ndarray,
    previous_bess_command: np.ndarray,
    load_pu: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, bool]:
    """Propagate one control interval on the public 0.2 s evidence grid."""

    parameters = plant_parameters(point.sg_tension, point.nominal_frequency_hz)
    substeps = int(round(point.period_s / 0.2))
    step_s = point.period_s / substeps
    ad, bd = _discrete_grid(parameters, step_s)
    alpha = exp(-step_s / parameters.bess.actuator_time_constant_s)
    value = np.asarray(state, dtype=float).copy()
    actual = np.asarray(power, dtype=float).copy()
    energy = np.asarray(energy_mwh, dtype=float).copy()
    for substep in range(substeps):
        elapsed_s = (substep + 1) * step_s
        delayed = (
            previous_bess_command
            if elapsed_s <= truth.delay_s + 1e-12
            else bess_command
        )
        target = np.clip(
            alpha * actual + (1.0 - alpha) * delayed,
            -truth.power_pu,
            truth.power_pu,
        )
        delta = np.clip(
            target - actual,
            -truth.ramp_pu_per_s * step_s,
            truth.ramp_pu_per_s * step_s,
        )
        next_actual = actual + delta
        average = 0.5 * (actual + next_actual)
        loss_adjusted = np.where(
            average >= 0.0,
            average / parameters.bess.eta_discharge,
            average * parameters.bess.eta_charge,
        )
        energy -= (
            step_s * parameters.system_base_mva * loss_adjusted / 3600.0
        )
        actual = next_actual
        value = ad @ value + bd @ np.r_[sg_command, actual, load_pu]
        if not _physical_limits_hold(point, parameters, value, energy):
            return value, actual, energy, False
    return value, actual, energy, True


def _rolling_acquisition_prefix(
    point: BoundaryPoint,
    models: Sequence[CapabilityModel],
    baseline: PolicySolution,
    probe: Probe,
    *,
    horizon_steps: int,
    scales: ObjectiveScales,
    initial_grid_state: np.ndarray,
    initial_bess_power: np.ndarray,
    previous_sg_command: np.ndarray,
    previous_bess_command: np.ndarray,
    initial_energy_mwh: np.ndarray,
    load_forecast_pu: np.ndarray,
    current_time_s: float,
    load_observer: object,
) -> RollingPrefix:
    """Recompute contract-set MPC at every pre-certificate control instant."""

    parameters = plant_parameters(point.sg_tension, point.nominal_frequency_hz)
    terminal_state: dict[str, np.ndarray] = {}
    terminal_power: dict[str, np.ndarray] = {}
    terminal_energy: dict[str, np.ndarray] = {}
    previous_sg: dict[str, np.ndarray] = {}
    previous_bess: dict[str, np.ndarray] = {}
    observers: dict[str, object] = {}
    prefix_cost: dict[str, float] = {}
    attempts = 0
    failures = 0
    for truth in models:
        state = np.asarray(initial_grid_state, dtype=float).copy()
        power = np.asarray(initial_bess_power, dtype=float).copy()
        energy = np.asarray(initial_energy_mwh, dtype=float).copy()
        prior_sg = np.asarray(previous_sg_command, dtype=float).copy()
        prior_bess = np.asarray(previous_bess_command, dtype=float).copy()
        observer = deepcopy(load_observer)
        load_estimate = np.asarray(load_forecast_pu, dtype=float).copy()
        cost = 0.0
        for step, surplus in enumerate(probe.sequence_pu):
            solution = baseline if step == 0 else solve_policy(
                point,
                models,
                horizon_steps=horizon_steps,
                initial_grid_state=state,
                initial_bess_power=power,
                previous_sg_command=prior_sg,
                previous_bess_command=prior_bess,
                initial_energy_mwh=energy,
                load_forecast_pu=load_estimate,
                scales=scales,
            )
            if step > 0:
                attempts += 1
            if not np.isfinite(solution.objective):
                failures += 1
                return RollingPrefix(
                    False, f"PREFIX_SOLVE_{truth.model_id}", {}, {}, {}, {}, {}, {}, {},
                    attempts, failures,
                )
            sg = solution.sg_command[:, 0].copy()
            bess = solution.bess_command[:, 0].copy()
            bess[probe.area] += float(surplus)
            if (
                np.any(sg < np.asarray(parameters.valve_lower_pu) - 1e-10)
                or np.any(sg > np.asarray(parameters.valve_upper_pu) + 1e-10)
                or np.any(np.abs(bess) > parameters.bess.rating_pu + 1e-10)
            ):
                return RollingPrefix(
                    False, f"PREFIX_COMMAND_{truth.model_id}", {}, {}, {}, {}, {}, {}, {},
                    attempts, failures,
                )
            next_state, next_power, next_energy, safe = _propagate_truth_interval(
                point, truth, state, power, energy, sg, bess, prior_bess,
                load_estimate,
            )
            if not safe:
                return RollingPrefix(
                    False, f"PREFIX_PHYSICAL_{truth.model_id}", {}, {}, {}, {}, {}, {}, {},
                    attempts, failures,
                )
            cost += _numeric_stage_cost(
                next_state, sg, bess, prior_sg, prior_bess, scales,
                point.period_s, point.nominal_frequency_hz,
            )
            state = next_state
            power = next_power
            energy = next_energy
            prior_sg = sg
            prior_bess = bess
            load_estimate = observer.update(LoadObserverInput(
                current_time_s + (step + 1) * point.period_s,
                point.nominal_frequency_hz * state[:2],
                float(state[2]),
                state[5:7],
                power,
                np.zeros(2),
            )).load_pu
        terminal_state[truth.model_id] = state
        terminal_power[truth.model_id] = power
        terminal_energy[truth.model_id] = energy
        previous_sg[truth.model_id] = prior_sg
        previous_bess[truth.model_id] = prior_bess
        observers[truth.model_id] = observer
        prefix_cost[truth.model_id] = float(cost)
    return RollingPrefix(
        True, "SAFE", terminal_state, terminal_power, terminal_energy,
        previous_sg, previous_bess, observers, prefix_cost, attempts, failures,
    )


def _rolling_continuation_cost(
    point: BoundaryPoint,
    truth: CapabilityModel,
    policy_models: Sequence[CapabilityModel],
    *,
    horizon_steps: int,
    scales: ObjectiveScales,
    initial_grid_state: np.ndarray,
    initial_bess_power: np.ndarray,
    initial_energy_mwh: np.ndarray,
    previous_sg_command: np.ndarray,
    previous_bess_command: np.ndarray,
    load_path_pu: np.ndarray,
    current_time_s: float,
    load_observer: object,
) -> tuple[float, int, int, bool]:
    state = np.asarray(initial_grid_state, dtype=float).copy()
    power = np.asarray(initial_bess_power, dtype=float).copy()
    energy = np.asarray(initial_energy_mwh, dtype=float).copy()
    prior_sg = np.asarray(previous_sg_command, dtype=float).copy()
    prior_bess = np.asarray(previous_bess_command, dtype=float).copy()
    observer = deepcopy(load_observer)
    load_estimate = np.asarray(observer._load, dtype=float).copy()
    cost = 0.0
    attempts = 0
    failures = 0
    for step, load in enumerate(np.asarray(load_path_pu, dtype=float)):
        solution = solve_policy(
            point,
            policy_models,
            horizon_steps=horizon_steps,
            initial_grid_state=state,
            initial_bess_power=power,
            previous_sg_command=prior_sg,
            previous_bess_command=prior_bess,
            initial_energy_mwh=energy,
            load_forecast_pu=load_estimate,
            scales=scales,
        )
        attempts += 1
        if not np.isfinite(solution.objective):
            failures += 1
            return float("inf"), attempts, failures, False
        sg = solution.sg_command[:, 0]
        bess = solution.bess_command[:, 0]
        next_state, next_power, next_energy, safe = _propagate_truth_interval(
            point, truth, state, power, energy, sg, bess, prior_bess, load,
        )
        if not safe:
            return float("inf"), attempts, failures, False
        cost += _numeric_stage_cost(
            next_state, sg, bess, prior_sg, prior_bess, scales,
            point.period_s, point.nominal_frequency_hz,
        )
        state = next_state
        power = next_power
        energy = next_energy
        prior_sg = np.asarray(sg, dtype=float).copy()
        prior_bess = np.asarray(bess, dtype=float).copy()
        load_estimate = observer.update(LoadObserverInput(
            current_time_s + (step + 1) * point.period_s,
            point.nominal_frequency_hz * state[:2],
            float(state[2]),
            state[5:7],
            power,
            np.zeros(2),
        )).load_pu
    return float(cost), attempts, failures, True


def evaluate_optimistic_continuation_screen(
    point: BoundaryPoint,
    models: Sequence[CapabilityModel],
    baseline: PolicySolution,
    *,
    horizon_steps: int,
    scales: ObjectiveScales,
    initial_grid_state: np.ndarray,
    initial_bess_power: np.ndarray,
    previous_sg_command: np.ndarray,
    previous_bess_command: np.ndarray,
    initial_energy_mwh: np.ndarray,
    load_forecast_pu: np.ndarray,
    continuation_load_paths_pu: np.ndarray,
    current_time_s: float,
    load_observer: object,
    prefix_steps: int = 3,
    anchor_stride_steps: int = 4,
    high_power_threshold_pu: float = 0.045,
) -> OptimisticContinuationScreen:
    """Find future full-vs-high value opportunities on public contract paths.

    The propagation model is the registered contract floor (minimum power and
    ramp, maximum delay), never the episode's hidden capability.  The screen is
    intentionally optimistic: a positive gap at any registered path/anchor is
    enough to send the state to the exact acquisition-matched calculation.
    """

    paths = np.asarray(continuation_load_paths_pu, dtype=float)
    if paths.ndim != 3 or paths.shape[2] != 2:
        raise ValueError("screen load paths must be path-by-time-by-area")
    if prefix_steps < 0 or anchor_stride_steps <= 0:
        raise ValueError("screen prefix and anchor stride must be nonnegative")
    high_models = tuple(
        model for model in models
        if model.power_pu > high_power_threshold_pu + 1e-10
    )
    if not high_models or paths.shape[1] <= prefix_steps:
        return OptimisticContinuationScreen(
            True, "NO_SCREEN_OPPORTUNITY", 0.0, None, None, (), 0, 0,
            int(paths.shape[0]), 0,
        )

    minimum_power = min(model.power_pu for model in models)
    minimum_ramp = min(
        model.ramp_pu_per_s for model in models
        if abs(model.power_pu - minimum_power) <= 1e-10
    )
    floor_models = [
        model for model in models
        if abs(model.power_pu - minimum_power) <= 1e-10
        and abs(model.ramp_pu_per_s - minimum_ramp) <= 1e-10
    ]
    public_model = max(floor_models, key=lambda model: model.delay_s)

    attempts = 0
    failures = 0
    maximum_gap = 0.0
    maximum_path: int | None = None
    maximum_time: float | None = None
    anchor_values: list[float] = []
    anchor_count = 0
    for path_index, path in enumerate(paths):
        state = np.asarray(initial_grid_state, dtype=float).copy()
        power = np.asarray(initial_bess_power, dtype=float).copy()
        energy = np.asarray(initial_energy_mwh, dtype=float).copy()
        prior_sg = np.asarray(previous_sg_command, dtype=float).copy()
        prior_bess = np.asarray(previous_bess_command, dtype=float).copy()
        observer = deepcopy(load_observer)
        load_estimate = np.asarray(load_forecast_pu, dtype=float).copy()
        for step, physical_load in enumerate(path):
            full_solution = baseline if step == 0 else solve_policy(
                point,
                models,
                horizon_steps=horizon_steps,
                initial_grid_state=state,
                initial_bess_power=power,
                previous_sg_command=prior_sg,
                previous_bess_command=prior_bess,
                initial_energy_mwh=energy,
                load_forecast_pu=load_estimate,
                scales=scales,
            )
            if step > 0:
                attempts += 1
            if not np.isfinite(full_solution.objective):
                failures += 1
                return OptimisticContinuationScreen(
                    False, "FULL_SET_SCREEN_SOLVE_FAILURE", float("inf"),
                    None, None, tuple(anchor_values), attempts, failures,
                    int(paths.shape[0]), anchor_count,
                )

            if step >= prefix_steps and (
                (step - prefix_steps) % anchor_stride_steps == 0
            ):
                high_solution = solve_policy(
                    point,
                    high_models,
                    horizon_steps=horizon_steps,
                    initial_grid_state=state,
                    initial_bess_power=power,
                    previous_sg_command=prior_sg,
                    previous_bess_command=prior_bess,
                    initial_energy_mwh=energy,
                    load_forecast_pu=load_estimate,
                    scales=scales,
                )
                attempts += 1
                anchor_count += 1
                if not np.isfinite(high_solution.objective):
                    failures += 1
                    return OptimisticContinuationScreen(
                        False, "HIGH_SET_SCREEN_SOLVE_FAILURE", float("inf"),
                        None, None, tuple(anchor_values), attempts, failures,
                        int(paths.shape[0]), anchor_count,
                    )
                gap = max(
                    0.0,
                    float(full_solution.objective - high_solution.objective),
                )
                anchor_values.append(gap)
                if gap > maximum_gap:
                    maximum_gap = gap
                    maximum_path = path_index
                    maximum_time = (
                        float(current_time_s) + step * point.period_s
                    )

            sg = full_solution.sg_command[:, 0]
            bess = full_solution.bess_command[:, 0]
            next_state, next_power, next_energy, safe = (
                _propagate_truth_interval(
                    point, public_model, state, power, energy, sg, bess,
                    prior_bess, physical_load,
                )
            )
            if not safe:
                return OptimisticContinuationScreen(
                    False, "PUBLIC_SCREEN_PROPAGATION_INCONCLUSIVE",
                    float("inf"), None, None, tuple(anchor_values), attempts,
                    failures, int(paths.shape[0]), anchor_count,
                )
            state = next_state
            power = next_power
            energy = next_energy
            prior_sg = np.asarray(sg, dtype=float).copy()
            prior_bess = np.asarray(bess, dtype=float).copy()
            load_estimate = observer.update(LoadObserverInput(
                current_time_s + (step + 1) * point.period_s,
                point.nominal_frequency_hz * state[:2],
                float(state[2]),
                state[5:7],
                power,
                np.zeros(2),
            )).load_pu

    return OptimisticContinuationScreen(
        True,
        "FUTURE_OPPORTUNITY" if maximum_gap > 0.0 else "NO_FUTURE_OPPORTUNITY",
        float(maximum_gap),
        maximum_path,
        maximum_time,
        tuple(anchor_values),
        attempts,
        failures,
        int(paths.shape[0]),
        anchor_count,
    )


def evaluate_acquisition_information_value(
    point: BoundaryPoint,
    models: Sequence[CapabilityModel],
    baseline: PolicySolution,
    probe: Probe,
    *,
    horizon_steps: int,
    scales: ObjectiveScales,
    initial_grid_state: np.ndarray,
    initial_bess_power: np.ndarray,
    previous_sg_command: np.ndarray,
    previous_bess_command: np.ndarray,
    initial_energy_mwh: np.ndarray,
    load_forecast_pu: np.ndarray,
    continuation_load_paths_pu: np.ndarray | None = None,
    current_time_s: float = 0.0,
    load_observer: object | None = None,
    high_power_threshold_pu: float = 0.045,
    numerical_margin: float = 1e-7,
) -> AcquisitionInformationValue:
    """Compare exploit and posterior recourse after the same surplus prefix.

    This matches the current one-window estimator: a high-power observation
    enables the high-power candidate subset, while a low-power or ambiguous
    observation retains the complete contract set. Ramp and delay remain
    robust within either power branch. Values are computed separately for
    every hidden candidate, so no capability prior is read by the controller.
    """

    if load_observer is None:
        raise ValueError("a causal warmed load observer is required")
    prefix = _rolling_acquisition_prefix(
        point,
        models,
        baseline,
        probe,
        horizon_steps=horizon_steps,
        scales=scales,
        initial_grid_state=initial_grid_state,
        initial_bess_power=initial_bess_power,
        previous_sg_command=previous_sg_command,
        previous_bess_command=previous_bess_command,
        initial_energy_mwh=initial_energy_mwh,
        load_forecast_pu=load_forecast_pu,
        current_time_s=current_time_s,
        load_observer=load_observer,
    )
    if not prefix.safe:
        return AcquisitionInformationValue(
            False, prefix.reason, {}, -float("inf"), -float("inf"), None,
            False, {}, {}, prefix.solver_attempts, prefix.solver_failures, 0, 0,
        )

    high_models = tuple(
        model for model in models
        if model.power_pu > high_power_threshold_pu + 1e-10
    )
    if not high_models:
        return AcquisitionInformationValue(
            True, "NO_HIGH_POWER_HYPOTHESIS", {}, 0.0, 0.0, None,
            False, {}, {}, prefix.solver_attempts, prefix.solver_failures, 0, 0,
        )

    if continuation_load_paths_pu is None:
        remaining = max(horizon_steps - len(probe.sequence_pu), 0)
        load_paths = np.tile(
            np.asarray(load_forecast_pu, dtype=float), (1, remaining, 1)
        )
    else:
        load_paths = np.asarray(continuation_load_paths_pu, dtype=float)
    if load_paths.ndim != 3 or load_paths.shape[2] != 2:
        raise ValueError("continuation load paths must be path-by-time-by-area")
    if load_paths.shape[1] == 0:
        return AcquisitionInformationValue(
            True, "NO_POSTERIOR_RECOURSE_TIME", {}, 0.0, 0.0, None,
            False, {}, {}, prefix.solver_attempts, prefix.solver_failures,
            int(load_paths.shape[0]), 0,
        )

    attempts = prefix.solver_attempts
    failures = prefix.solver_failures
    branch_value: dict[str, float] = {}
    exploit_cost: dict[str, float] = {}
    posterior_cost: dict[str, float] = {}
    for truth in models:
        if truth.power_pu <= high_power_threshold_pu + 1e-10:
            branch_value[truth.model_id] = 0.0
            exploit_cost[truth.model_id] = 0.0
            posterior_cost[truth.model_id] = 0.0
            continue
        exploit_path_costs = []
        posterior_path_costs = []
        branch_safe = True
        for path in load_paths:
            common = dict(
                horizon_steps=horizon_steps,
                scales=scales,
                initial_grid_state=prefix.terminal_state[truth.model_id],
                initial_bess_power=prefix.terminal_power[truth.model_id],
                initial_energy_mwh=prefix.terminal_energy_mwh[truth.model_id],
                previous_sg_command=prefix.previous_sg_command[truth.model_id],
                previous_bess_command=prefix.previous_bess_command[truth.model_id],
                load_path_pu=path,
                current_time_s=current_time_s + probe.duration_s,
                load_observer=prefix.load_observer[truth.model_id],
            )
            exploit_value, used, failed, exploit_safe = _rolling_continuation_cost(
                point, truth, models, **common
            )
            attempts += used
            failures += failed
            posterior_value, used, failed, posterior_safe = (
                _rolling_continuation_cost(
                    point, truth, high_models, **common
                )
            )
            attempts += used
            failures += failed
            branch_safe = bool(branch_safe and exploit_safe and posterior_safe)
            exploit_path_costs.append(exploit_value)
            posterior_path_costs.append(posterior_value)
        if not branch_safe:
            continue
        exploit_cost[truth.model_id] = float(np.mean(exploit_path_costs))
        posterior_cost[truth.model_id] = float(np.mean(posterior_path_costs))
        branch_value[truth.model_id] = float(
            np.mean(np.asarray(exploit_path_costs) - posterior_path_costs)
        )

    if len(branch_value) != len(models):
        return AcquisitionInformationValue(
            False, "RECOURSE_SOLVE_FAILURE", branch_value,
            -float("inf"), -float("inf"), None, False,
            exploit_cost, posterior_cost, attempts, failures,
            int(load_paths.shape[0]), int(load_paths.shape[1]),
        )

    low_values = [
        branch_value[model.model_id] for model in models
        if model.power_pu <= high_power_threshold_pu + 1e-10
    ]
    high_values = [
        branch_value[model.model_id] for model in models
        if model.power_pu > high_power_threshold_pu + 1e-10
    ]
    low_value = float(min(low_values))
    high_value = float(min(high_values))
    slope = high_value - low_value
    break_even = None
    if slope > numerical_margin:
        break_even = float(np.clip(-low_value / slope, 0.0, 1.0))
    weak_dominance = bool(
        low_value >= -numerical_margin
        and high_value >= -numerical_margin
        and max(low_value, high_value) > numerical_margin
    )
    return AcquisitionInformationValue(
        True,
        "POSITIVE_PURE_INFORMATION_VALUE" if weak_dominance
        else "NONPOSITIVE_OR_BRANCH_ADVERSE_INFORMATION_VALUE",
        branch_value,
        low_value,
        high_value,
        break_even,
        weak_dominance,
        exploit_cost,
        posterior_cost,
        attempts,
        failures,
        int(load_paths.shape[0]),
        int(load_paths.shape[1]),
    )


def observation_intervals(
    point: BoundaryPoint,
    models: Sequence[CapabilityModel],
    prefix: FixedPrefix,
    probe: Probe,
) -> dict[str, tuple[float, float]]:
    q = np.asarray(probe.sequence_pu)
    weights = q / max(np.sum(np.abs(q)), 1e-12)
    intervals: dict[str, tuple[float, float]] = {}
    # A bounded matched-filter statistic keeps the tube partition exactly enumerable.
    radius = 2.576 * point.noise_std_pu + 2.5e-4
    for model in models:
        trace = prefix.bess_power[model.model_id][probe.area, 1:]
        center = float(np.dot(weights, trace))
        intervals[model.model_id] = (center - radius, center + radius)
    return intervals


def enumerate_possible_posteriors(
    intervals: dict[str, tuple[float, float]],
) -> tuple[tuple[str, ...], ...]:
    endpoints = sorted({value for interval in intervals.values() for value in interval})
    samples = set(endpoints)
    samples.update((left + right) / 2.0 for left, right in zip(endpoints[:-1], endpoints[1:]))
    posteriors = {
        tuple(sorted(model_id for model_id, (lower, upper) in intervals.items() if lower - 1e-12 <= y <= upper + 1e-12))
        for y in samples
    }
    posteriors.discard(())
    return tuple(sorted(posteriors, key=lambda item: (len(item), item)))


def _probe_separation_score(
    point: BoundaryPoint,
    models: Sequence[CapabilityModel],
    prefix: FixedPrefix,
    probe: Probe,
) -> float:
    intervals = observation_intervals(point, models, prefix, probe)
    posteriors = enumerate_possible_posteriors(intervals)
    if not posteriors:
        return -float("inf")
    reduction = 1.0 - np.mean([len(item) for item in posteriors]) / len(models)
    command_cost = point.period_s * np.sum(np.abs(probe.sequence_pu))
    return float(reduction - 8.0 * command_cost)


def evaluate_probe(
    point: BoundaryPoint,
    models: Sequence[CapabilityModel],
    baseline: PolicySolution,
    probe: Probe,
    *,
    horizon_steps: int,
    scales: ObjectiveScales,
) -> ProbeValue:
    prefix = _fixed_prefix(point, models, baseline, probe, scales)
    if not prefix.safe:
        return ProbeValue(
            probe.probe_id, False, prefix.reason, (), len(models), 0.0,
            -float("inf"), -float("inf"), float("inf"), float("inf"), {}, 0, 0,
        )
    intervals = observation_intervals(point, models, prefix, probe)
    posteriors = enumerate_possible_posteriors(intervals)
    model_lookup = {model.model_id: model for model in models}
    remaining = horizon_steps - len(probe.sequence_pu)
    attempts = 0; failures = 0
    exact_worst = -float("inf")
    clairvoyant_worst = -float("inf")
    for truth in models:
        reachable = [
            posterior for posterior in posteriors
            if truth.model_id in posterior
            and max(intervals[truth.model_id][0], max(intervals[item][0] for item in posterior))
            <= min(intervals[truth.model_id][1], min(intervals[item][1] for item in posterior)) + 1e-12
        ]
        if not reachable:
            reachable = [(truth.model_id,)]
        terminal_state = prefix.states[truth.model_id][:, -1]
        terminal_power = prefix.bess_power[truth.model_id][:, -1]
        terminal_energy = prefix.energy_mwh[truth.model_id][:, -1]
        previous_sg = prefix.sg_command[:, -1]
        previous_bess = prefix.bess_command[:, -1]
        if remaining <= 0:
            exact_worst = max(exact_worst, prefix.prefix_cost[truth.model_id])
            clairvoyant_worst = max(clairvoyant_worst, prefix.prefix_cost[truth.model_id])
            continue
        singleton = solve_policy(
            point, (truth,), horizon_steps=remaining,
            initial_grid_state=terminal_state,
            initial_bess_power=terminal_power,
            previous_sg_command=previous_sg,
            previous_bess_command=previous_bess,
            initial_energy_mwh=terminal_energy,
            scales=scales,
        )
        attempts += 1
        if not np.isfinite(singleton.objective):
            failures += 1
        clairvoyant_worst = max(
            clairvoyant_worst, prefix.prefix_cost[truth.model_id] + singleton.objective
        )
        for posterior in reachable:
            recourse = solve_policy(
                point, tuple(model_lookup[item] for item in posterior),
                horizon_steps=remaining,
                initial_grid_state=terminal_state,
                initial_bess_power=terminal_power,
                previous_sg_command=previous_sg,
                previous_bess_command=previous_bess,
                initial_energy_mwh=terminal_energy,
                scales=scales,
            )
            attempts += 1
            if not np.isfinite(recourse.objective):
                failures += 1
            exact_worst = max(
                exact_worst, prefix.prefix_cost[truth.model_id] + recourse.objective
            )
    upper_value = float(baseline.objective - clairvoyant_worst)
    exact_value = float(baseline.objective - exact_worst)
    no_probe_prefix = {
        model.model_id: _fixed_prefix(
            point, (model,), baseline,
            Probe(
                "zero", probe.duration_s, 0.0, "zero", probe.area, 1,
                tuple(0.0 for _ in probe.sequence_pu),
            ), scales,
        ).prefix_cost.get(model.model_id, 0.0)
        for model in models
    }
    probe_increment = max(
        prefix.prefix_cost[model.model_id] - no_probe_prefix[model.model_id]
        for model in models
    )
    reduction = 1.0 - np.mean([len(item) for item in posteriors]) / len(models)
    return ProbeValue(
        probe_id=probe.probe_id,
        safe=True,
        reason="POSITIVE_NET_VALUE" if exact_value > 1e-8 else "NONPOSITIVE_NET_VALUE",
        possible_posteriors=posteriors,
        maximum_posterior_size=max(map(len, posteriors)),
        mean_posterior_reduction=float(reduction),
        upper_value=upper_value,
        exact_value=exact_value,
        probe_counterfactual_cost=float(probe_increment),
        worst_post_probe_cost=float(exact_worst),
        observation_intervals=intervals,
        solver_attempts=attempts,
        solver_failures=failures,
    )


def evaluate_probe_upper(
    point: BoundaryPoint,
    models: Sequence[CapabilityModel],
    baseline: PolicySolution,
    probe: Probe,
    *,
    horizon_steps: int,
    scales: ObjectiveScales,
) -> ProbeValue:
    """Compute the perfect-post-probe upper value without posterior recourse solves."""

    prefix = _fixed_prefix(point, models, baseline, probe, scales)
    if not prefix.safe:
        return ProbeValue(
            probe.probe_id, False, prefix.reason, (), len(models), 0.0,
            -float("inf"), float("nan"), float("inf"), float("inf"), {}, 0, 0,
        )
    intervals = observation_intervals(point, models, prefix, probe)
    posteriors = enumerate_possible_posteriors(intervals)
    remaining = horizon_steps - len(probe.sequence_pu)
    attempts = 0; failures = 0; clairvoyant_worst = -float("inf")
    for truth in models:
        if remaining <= 0:
            cost = prefix.prefix_cost[truth.model_id]
        else:
            singleton = solve_policy(
                point, (truth,), horizon_steps=remaining,
                initial_grid_state=prefix.states[truth.model_id][:, -1],
                initial_bess_power=prefix.bess_power[truth.model_id][:, -1],
                previous_sg_command=prefix.sg_command[:, -1],
                previous_bess_command=prefix.bess_command[:, -1],
                initial_energy_mwh=prefix.energy_mwh[truth.model_id][:, -1],
                scales=scales,
            )
            attempts += 1
            failures += int(not np.isfinite(singleton.objective))
            cost = prefix.prefix_cost[truth.model_id] + singleton.objective
        clairvoyant_worst = max(clairvoyant_worst, cost)
    upper_value = float(baseline.objective - clairvoyant_worst)
    reduction = 1.0 - np.mean([len(item) for item in posteriors]) / len(models)
    return ProbeValue(
        probe_id=probe.probe_id,
        safe=True,
        reason="UPPER_VALUE_POSITIVE" if upper_value > 1e-8 else "UPPER_VALUE_NONPOSITIVE",
        possible_posteriors=posteriors,
        maximum_posterior_size=max(map(len, posteriors)),
        mean_posterior_reduction=float(reduction),
        upper_value=upper_value,
        exact_value=float("nan"),
        probe_counterfactual_cost=float("nan"),
        worst_post_probe_cost=float(clairvoyant_worst),
        observation_intervals=intervals,
        solver_attempts=attempts,
        solver_failures=failures,
    )


def evaluate_probe_strong_convexity_upper(
    point: BoundaryPoint,
    models: Sequence[CapabilityModel],
    baseline: PolicySolution,
    singleton_solutions: Sequence[PolicySolution],
    probe: Probe,
    *,
    horizon_steps: int,
    scales: ObjectiveScales,
) -> ProbeValue:
    """Rigorous no-solve upper bound from the registered move-cost curvature.

    For a horizon command vector, the move penalty is ``a ||D u||^2`` with
    fixed previous action.  Its strong-convexity modulus gives
    ``J(u)-J(u*) >= a lambda_min(D.T D) ||u-u*||^2``.  Restricting the distance
    to the fixed probe prefix only weakens the lower cost bound and therefore
    preserves a valid upper bound on probe value.
    """

    prefix = _fixed_prefix(point, models, baseline, probe, scales)
    if not prefix.safe:
        return ProbeValue(
            probe.probe_id, False, prefix.reason, (), len(models), 0.0,
            -float("inf"), float("nan"), float("inf"), float("inf"), {}, 0, 0,
        )
    intervals = observation_intervals(point, models, prefix, probe)
    posteriors = enumerate_possible_posteriors(intervals)
    prefix_steps = len(probe.sequence_pu)
    lower_costs = []
    for model, solution in zip(models, singleton_solutions):
        schur, indices = _prefix_recourse_schur(
            point, model, horizon_steps, scales, prefix_steps
        )
        difference = np.r_[
            (prefix.sg_command - solution.sg_command[:, :prefix_steps]).reshape(-1),
            (prefix.bess_command - solution.bess_command[:, :prefix_steps]).reshape(-1),
        ]
        lower_costs.append(
            solution.objective + float(difference @ schur @ difference)
        )
    lower_post_probe_cost = float(max(lower_costs))
    upper_value = float(baseline.objective - lower_post_probe_cost)
    reduction = 1.0 - np.mean([len(item) for item in posteriors]) / len(models)
    return ProbeValue(
        probe_id=probe.probe_id,
        safe=True,
        reason=(
            "QUADRATIC_RECOURSE_UPPER_POSITIVE"
            if upper_value > 1e-8 else "QUADRATIC_RECOURSE_UPPER_NONPOSITIVE"
        ),
        possible_posteriors=posteriors,
        maximum_posterior_size=max(map(len, posteriors)),
        mean_posterior_reduction=float(reduction),
        upper_value=upper_value,
        exact_value=float("nan"),
        probe_counterfactual_cost=float("nan"),
        worst_post_probe_cost=lower_post_probe_cost,
        observation_intervals=intervals,
        solver_attempts=0,
        solver_failures=0,
    )


@lru_cache(maxsize=4096)
def _quadratic_command_hessian(
    point: BoundaryPoint,
    model: CapabilityModel,
    horizon_steps: int,
    scales: ObjectiveScales,
) -> np.ndarray:
    """Reduced quadratic cost matrix in [SG area-major, BESS area-major]."""

    parameters = plant_parameters(point.sg_tension, point.nominal_frequency_hz)
    ad, bd = _discrete_grid(parameters, point.period_s)
    dimension = 4 * horizon_steps

    def selector(offset: int, step: int) -> np.ndarray:
        matrix = np.zeros((2, dimension))
        matrix[0, offset + step] = 1.0
        matrix[1, offset + horizon_steps + step] = 1.0
        return matrix

    ace = np.zeros((2, 7)); ace[0, 0] = 21.0; ace[0, 2] = 1.0
    ace[1, 1] = 21.0; ace[1, 2] = -1.0
    frequency = np.zeros((2, 7)); frequency[0, 0] = point.nominal_frequency_hz
    frequency[1, 1] = point.nominal_frequency_hz
    tie = np.zeros((1, 7)); tie[0, 2] = 1.0
    state_weight = (
        frequency.T @ frequency / scales.frequency_hz ** 2
        + ace.T @ ace / scales.ace_pu ** 2
        + tie.T @ tie / scales.tie_pu ** 2
    )
    hessian = np.zeros((dimension, dimension))
    p_map = np.zeros((2, dimension)); x_map = np.zeros((7, dimension))
    alpha = exp(-point.period_s / parameters.bess.actuator_time_constant_s)
    delay_fraction = min(max(model.delay_s / point.period_s, 0.0), 1.0)
    last_x_map = x_map
    for step in range(horizon_steps):
        sg_map = selector(0, step)
        bess_map = selector(2 * horizon_steps, step)
        previous_bess_map = (
            np.zeros_like(bess_map)
            if step == 0 else selector(2 * horizon_steps, step - 1)
        )
        delayed_map = (
            (1.0 - delay_fraction) * bess_map
            + delay_fraction * previous_bess_map
        )
        p_map = alpha * p_map + (1.0 - alpha) * delayed_map
        x_map = ad @ x_map + bd[:, :2] @ sg_map + bd[:, 2:4] @ p_map
        hessian += point.period_s * x_map.T @ state_weight @ x_map
        previous_sg_map = (
            np.zeros_like(sg_map) if step == 0 else selector(0, step - 1)
        )
        hessian += (
            point.period_s / scales.sg_move_pu ** 2
            * (sg_map - previous_sg_map).T @ (sg_map - previous_sg_map)
        )
        hessian += (
            point.period_s / scales.bess_move_pu ** 2
            * (bess_map - previous_bess_map).T @ (bess_map - previous_bess_map)
        )
        last_x_map = x_map
    hessian += 2.0 * point.period_s * last_x_map.T @ state_weight @ last_x_map
    return 0.5 * (hessian + hessian.T)


@lru_cache(maxsize=8192)
def _prefix_recourse_schur(
    point: BoundaryPoint,
    model: CapabilityModel,
    horizon_steps: int,
    scales: ObjectiveScales,
    prefix_steps: int,
) -> tuple[np.ndarray, tuple[int, ...]]:
    hessian = _quadratic_command_hessian(point, model, horizon_steps, scales)
    prefix = tuple(
        list(range(0, prefix_steps))
        + list(range(horizon_steps, horizon_steps + prefix_steps))
        + list(range(2 * horizon_steps, 2 * horizon_steps + prefix_steps))
        + list(range(3 * horizon_steps, 3 * horizon_steps + prefix_steps))
    )
    tail = tuple(index for index in range(4 * horizon_steps) if index not in prefix)
    haa = hessian[np.ix_(prefix, prefix)]
    if not tail:
        return haa, prefix
    hab = hessian[np.ix_(prefix, tail)]
    hbb = hessian[np.ix_(tail, tail)]
    schur = haa - hab @ np.linalg.solve(hbb, hab.T)
    return 0.5 * (schur + schur.T), prefix


def evaluate_boundary_point(
    point: BoundaryPoint,
    *,
    physical_horizon_s: float = 24.0,
    exact_probe_limit: int | None = 8,
    upper_only: bool = False,
    strong_convexity_upper_only: bool = False,
    scales: ObjectiveScales | None = None,
) -> BoundaryResult:
    started = perf_counter()
    selected_scales = objective_scales(point.objective) if scales is None else scales
    models = candidate_models(point)
    horizon_steps = int(round(physical_horizon_s / point.period_s))
    if horizon_steps < 3:
        raise ValueError("physical horizon must contain at least three control steps")
    x0 = initial_state(point)
    robust = solve_policy(
        point, models, horizon_steps=horizon_steps, initial_grid_state=x0,
        scales=selected_scales,
    )
    attempts = 1; failures = int(not np.isfinite(robust.objective))
    singleton_solutions = []
    for model in models:
        solution = solve_policy(
            point, (model,), horizon_steps=horizon_steps,
            initial_grid_state=x0, scales=selected_scales,
        )
        attempts += 1
        failures += int(not np.isfinite(solution.objective))
        singleton_solutions.append(solution)
    perfect_cost = float(max(solution.objective for solution in singleton_solutions))
    perfect_value = float(robust.objective - perfect_cost)

    # The predecessor proxy is retained only for exact-vs-heuristic comparison.
    first_actions = []
    for solution in singleton_solutions:
        first_actions.append(solution.bess_command[:, 0])
    relevance = float(np.max(np.ptp(np.asarray(first_actions), axis=0)))
    ace_level = float(np.sum(np.abs(np.array((point.tie_loading_pu, -point.tie_loading_pu)))))
    heuristic_value = float(
        relevance * physical_horizon_s * (0.5 + 4.0 * ace_level)
        - 0.0025 * 2.0 * point.period_s * (0.25 + 4.0 * ace_level)
    )

    registered_probes = probe_library(point)
    ranked: list[tuple[float, Probe, FixedPrefix]] = []
    for probe in registered_probes:
        prefix = _fixed_prefix(point, models, robust, probe, selected_scales)
        if prefix.safe:
            ranked.append((
                _probe_separation_score(point, models, prefix, probe), probe, prefix
            ))
    ranked.sort(key=lambda item: item[0], reverse=True)
    selected_ranked = ranked if exact_probe_limit is None else ranked[:exact_probe_limit]
    probe_values = []
    for _, probe, _ in selected_ranked:
        if strong_convexity_upper_only:
            result = evaluate_probe_strong_convexity_upper(
                point, models, robust, singleton_solutions, probe,
                horizon_steps=horizon_steps, scales=selected_scales,
            )
        else:
            evaluator = evaluate_probe_upper if upper_only else evaluate_probe
            result = evaluator(
                point, models, robust, probe,
                horizon_steps=horizon_steps, scales=selected_scales,
            )
        probe_values.append(result)
        attempts += result.solver_attempts
        failures += result.solver_failures

    safe_values = [item for item in probe_values if item.safe]
    maximum_upper = max((item.upper_value for item in safe_values), default=-float("inf"))
    exact_values = [item.exact_value for item in safe_values if np.isfinite(item.exact_value)]
    maximum_exact = max(exact_values, default=float("nan"))
    selected = max(
        (item for item in safe_values if np.isfinite(item.exact_value)),
        key=lambda item: item.exact_value,
        default=None,
    )
    all_safe_evaluated = len(selected_ranked) == len(ranked)
    if failures:
        region = "UNCLASSIFIED_SOLVER"
        no_probe_reason = "SOLVER_FAILURE"
    elif np.isfinite(maximum_exact) and maximum_exact > 1e-8:
        region = "POSITIVE_VALUE"
        no_probe_reason = None
    elif perfect_value <= 1e-8:
        region = "ZERO_VALUE_PROVED"
        no_probe_reason = "REGISTERED_PERFECT_INFORMATION_VALUE_NONPOSITIVE"
    elif not ranked:
        region = "ZERO_VALUE_PROVED"
        no_probe_reason = "NO_REGISTERED_SAFE_PROBE"
    elif all_safe_evaluated and maximum_upper <= 1e-8:
        region = "ZERO_VALUE_PROVED"
        no_probe_reason = "MAXIMUM_SAFE_PROBE_UPPER_VALUE_NONPOSITIVE"
    else:
        region = "ZERO_VALUE_OBSERVED_NOT_PROVED"
        no_probe_reason = (
            "UNEVALUATED_SAFE_PROBES_REMAIN"
            if not all_safe_evaluated
            else "SAFE_PROBE_UPPER_BOUND_POSITIVE"
        )
    return BoundaryResult(
        point=point,
        candidate_models=models,
        robust_cost=float(robust.objective),
        perfect_information_cost=perfect_cost,
        perfect_information_value=perfect_value,
        heuristic_value=heuristic_value,
        maximum_safe_probe_upper_value=float(maximum_upper),
        maximum_exact_probe_value=float(maximum_exact),
        region=region,
        selected_probe_id=(
            None if selected is None or not np.isfinite(maximum_exact) or maximum_exact <= 1e-8
            else selected.probe_id
        ),
        no_probe_reason=no_probe_reason,
        registered_probe_count=len(registered_probes),
        safe_probe_count=len(ranked),
        evaluated_probe_count=len(selected_ranked),
        all_safe_probes_evaluated=all_safe_evaluated,
        probes=tuple(probe_values),
        solver_attempts=attempts,
        solver_failures=failures,
        elapsed_s=perf_counter() - started,
    )


__all__ = [
    "AcquisitionInformationValue", "BoundaryPoint", "BoundaryResult",
    "CapabilityModel", "ObjectiveScales",
    "OptimisticContinuationScreen", "PolicySolution", "Probe", "ProbeValue",
    "candidate_models",
    "enumerate_possible_posteriors", "evaluate_acquisition_information_value",
    "evaluate_optimistic_continuation_screen",
    "evaluate_boundary_point", "evaluate_probe",
    "evaluate_probe_upper",
    "evaluate_probe_strong_convexity_upper",
    "normalized_probe_sequence", "observation_intervals", "probe_library",
    "objective_scales", "solve_policy",
]
