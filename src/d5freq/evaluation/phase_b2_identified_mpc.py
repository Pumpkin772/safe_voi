"""Truth-regime identified linear MPC used only as Phase-B2 Oracle O1."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import time
from typing import Mapping, Sequence

import cvxpy as cp
import numpy as np
from numpy.typing import ArrayLike, NDArray
from sklearn.linear_model import Ridge

from d5freq.evaluation.phase_b2_exact_nmpc import ExactNMPCConfig
from d5freq.models.two_area_plant_b import (
    PlantBParameters,
    PlantBStateIndex,
    TwoAreaPlantB,
    UpperCommand,
)


FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class IdentifiedRegimeModel:
    regime_pair: tuple[str, str]
    state_matrix: FloatArray
    history_matrix: FloatArray
    action_matrix: FloatArray
    load_matrix: FloatArray
    affine_offset: FloatArray
    fit_sample_count: int
    validation_rmse: float
    validation_q95_abs_error: float
    validation_max_abs_error: float
    ridge_alpha: float
    development_seed: int

    def __post_init__(self) -> None:
        expected = {
            "state_matrix": (15, 15),
            "history_matrix": (15, 4),
            "action_matrix": (15, 4),
            "load_matrix": (15, 2),
            "affine_offset": (15,),
        }
        for name, shape in expected.items():
            value = np.asarray(getattr(self, name), dtype=np.float64)
            if value.shape != shape or not np.isfinite(value).all():
                raise ValueError(f"{name} must be finite with shape {shape}")
            object.__setattr__(self, name, value)
        if len(self.regime_pair) != 2:
            raise ValueError("regime_pair must contain two IDs")

    @property
    def key(self) -> str:
        return "__".join(self.regime_pair)

    def augmented_matrices(self) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray]:
        """Return 19-state matrices including two past IBR command blocks."""

        state = np.zeros((19, 19), dtype=np.float64)
        action = np.zeros((19, 4), dtype=np.float64)
        load = np.zeros((19, 2), dtype=np.float64)
        offset = np.zeros(19, dtype=np.float64)
        state[:15, :15] = self.state_matrix
        state[:15, 15:] = self.history_matrix
        action[:15] = self.action_matrix
        load[:15] = self.load_matrix
        offset[:15] = self.affine_offset
        # History is [area1_old, area2_old, area1_new, area2_new].
        state[15, 17] = 1.0
        state[16, 18] = 1.0
        action[17, 2] = 1.0
        action[18, 3] = 1.0
        return state, action, load, offset


@dataclass(frozen=True, slots=True)
class LinearOracleSolveRecord:
    oracle_level: str
    solver_status: str
    success: bool
    objective: float
    iterations: int
    kkt_residual_inf: float
    max_constraint_residual: float
    wall_time_s: float
    command: UpperCommand
    action_sequence: FloatArray
    predicted_state_nodes: FloatArray
    regime_pair: tuple[str, str]
    model_validation_rmse: float


def _past_source(
    area: int,
    source_block: int,
    actions: FloatArray,
    past_ibr: FloatArray,
    current_block: int,
) -> float:
    if source_block >= 0:
        return float(actions[2 + area, min(source_block, current_block)])
    return float(past_ibr[area, max(0, min(1, source_block + 2))])


def exact_block_transition(
    params: PlantBParameters,
    *,
    state: ArrayLike,
    action: ArrayLike,
    load_pu: ArrayLike,
    regime_pair: Sequence[str],
    past_ibr_commands_pu: ArrayLike,
    integration_step_s: float = 0.10,
) -> FloatArray:
    """Standalone expected block transition used only to generate dev data."""

    model = TwoAreaPlantB(params)
    current = model.validate_state(state).copy()
    command_values = np.asarray(action, dtype=np.float64)
    load = np.asarray(load_pu, dtype=np.float64)
    past = np.asarray(past_ibr_commands_pu, dtype=np.float64)
    regimes = tuple(str(value) for value in regime_pair)
    if command_values.shape != (4,) or load.shape != (2,) or past.shape != (2, 2):
        raise ValueError("invalid exact block-transition shapes")
    steps = round(params.upper_control_period_s / integration_step_s)
    for substep in range(steps):
        delivered: list[float] = []
        for area in (0, 1):
            regime = params.regimes[regimes[area]]
            source_time = substep * integration_step_s - regime.command_delay_s
            source_block = math.floor(
                (source_time + 1.0e-12) / params.upper_control_period_s
            )
            value = _past_source(area, source_block, command_values[:, None], past, 0)
            delivered.append((1.0 - regime.dropout_probability) * value)
        current = model.step(
            current,
            command=UpperCommand(
                sg_pu=(float(command_values[0]), float(command_values[1])),
                ibr_pu=(float(command_values[2]), float(command_values[3])),
            ),
            delayed_ibr_command_pu=delivered,
            load_disturbance_pu=load,
            regimes=tuple(params.regimes[value] for value in regimes),
            step_s=integration_step_s,
        )
    return current


def _sample_identification_row(
    params: PlantBParameters,
    rng: np.random.Generator,
    regime_pair: tuple[str, str],
) -> tuple[FloatArray, FloatArray]:
    model = TwoAreaPlantB(params)
    soc = rng.uniform(0.12, 0.88, size=2)
    availability = np.asarray(
        [
            np.clip(
                rng.normal(params.regimes[regime_pair[area]].availability_target, 0.15),
                0.02,
                1.0,
            )
            for area in (0, 1)
        ]
    )
    state = model.initial_state(soc=soc, availability=availability)
    state[[PlantBStateIndex.F1, PlantBStateIndex.F2]] = rng.uniform(-0.06, 0.06, size=2)
    state[PlantBStateIndex.PTIE12] = rng.uniform(-0.04, 0.04)
    for area, indices in enumerate(((1, 2, 7, 8), (4, 5, 11, 12))):
        pm, pv, z, pb = indices
        state[pm] = rng.uniform(
            -params.sg_capability.reserve_down_pu[area],
            params.sg_capability.reserve_up_pu[area],
        )
        state[pv] = rng.uniform(
            -params.sg_capability.reserve_down_pu[area],
            params.sg_capability.reserve_up_pu[area],
        )
        state[z] = rng.uniform(-params.bess[area].rating_pu, params.bess[area].rating_pu)
        state[pb] = rng.uniform(-params.bess[area].rating_pu, params.bess[area].rating_pu)
    state = model.project_state(state)
    action = np.asarray(
        (
            rng.uniform(-params.sg_capability.reserve_down_pu[0], params.sg_capability.reserve_up_pu[0]),
            rng.uniform(-params.sg_capability.reserve_down_pu[1], params.sg_capability.reserve_up_pu[1]),
            rng.uniform(-params.bess[0].rating_pu, params.bess[0].rating_pu),
            rng.uniform(-params.bess[1].rating_pu, params.bess[1].rating_pu),
        )
    )
    past = np.vstack(
        (
            rng.uniform(-params.bess[0].rating_pu, params.bess[0].rating_pu, size=2),
            rng.uniform(-params.bess[1].rating_pu, params.bess[1].rating_pu, size=2),
        )
    )
    load = rng.uniform(-0.08, 0.08, size=2)
    target = exact_block_transition(
        params,
        state=state,
        action=action,
        load_pu=load,
        regime_pair=regime_pair,
        past_ibr_commands_pu=past,
    )
    feature = np.concatenate((state, past.reshape(-1, order="F"), action, load))
    return feature, target


def fit_identified_regime_model(
    params: PlantBParameters,
    *,
    regime_pair: Sequence[str],
    sample_count: int = 400,
    development_seed: int = 700,
    ridge_alpha: float = 1.0e-6,
) -> IdentifiedRegimeModel:
    """Fit one offline model using development-only randomized transitions."""

    pair = tuple(str(value) for value in regime_pair)
    if len(pair) != 2 or any(value not in params.regimes for value in pair):
        raise ValueError("invalid identification regime pair")
    if sample_count < 100:
        raise ValueError("sample_count must be at least 100")
    rng = np.random.default_rng(int(development_seed))
    features = np.empty((sample_count, 25), dtype=np.float64)
    targets = np.empty((sample_count, 15), dtype=np.float64)
    for row in range(sample_count):
        features[row], targets[row] = _sample_identification_row(params, rng, pair)
    split = round(0.8 * sample_count)
    estimator = Ridge(alpha=float(ridge_alpha), fit_intercept=True)
    estimator.fit(features[:split], targets[:split])
    prediction = estimator.predict(features[split:])
    error = prediction - targets[split:]
    coefficient = np.asarray(estimator.coef_, dtype=np.float64)
    return IdentifiedRegimeModel(
        regime_pair=pair,  # type: ignore[arg-type]
        state_matrix=coefficient[:, :15],
        history_matrix=coefficient[:, 15:19],
        action_matrix=coefficient[:, 19:23],
        load_matrix=coefficient[:, 23:25],
        affine_offset=np.asarray(estimator.intercept_, dtype=np.float64),
        fit_sample_count=split,
        validation_rmse=float(np.sqrt(np.mean(error**2))),
        validation_q95_abs_error=float(np.quantile(np.abs(error), 0.95)),
        validation_max_abs_error=float(np.max(np.abs(error))),
        ridge_alpha=float(ridge_alpha),
        development_seed=int(development_seed),
    )


def save_identified_model(model: IdentifiedRegimeModel, path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        destination,
        regime_pair=np.asarray(model.regime_pair),
        state_matrix=model.state_matrix,
        history_matrix=model.history_matrix,
        action_matrix=model.action_matrix,
        load_matrix=model.load_matrix,
        affine_offset=model.affine_offset,
        fit_sample_count=np.asarray(model.fit_sample_count),
        validation_rmse=np.asarray(model.validation_rmse),
        validation_q95_abs_error=np.asarray(model.validation_q95_abs_error),
        validation_max_abs_error=np.asarray(model.validation_max_abs_error),
        ridge_alpha=np.asarray(model.ridge_alpha),
        development_seed=np.asarray(model.development_seed),
    )
    return destination


def load_identified_model(path: str | Path) -> IdentifiedRegimeModel:
    with np.load(Path(path), allow_pickle=False) as payload:
        return IdentifiedRegimeModel(
            regime_pair=tuple(str(value) for value in payload["regime_pair"]),  # type: ignore[arg-type]
            state_matrix=payload["state_matrix"],
            history_matrix=payload["history_matrix"],
            action_matrix=payload["action_matrix"],
            load_matrix=payload["load_matrix"],
            affine_offset=payload["affine_offset"],
            fit_sample_count=int(payload["fit_sample_count"]),
            validation_rmse=float(payload["validation_rmse"]),
            validation_q95_abs_error=float(payload["validation_q95_abs_error"]),
            validation_max_abs_error=float(payload["validation_max_abs_error"]),
            ridge_alpha=float(payload["ridge_alpha"]),
            development_seed=int(payload["development_seed"]),
        )


class TruthRegimeIdentifiedMPC:
    """O1 linear MPC; truth label and full state are evaluation-only inputs."""

    evaluation_only = True
    uses_true_regime = True
    uses_true_internal_state = True
    uses_future_load = False
    uses_future_regime = False
    global_optimality_claim = False

    def __init__(
        self,
        params: PlantBParameters,
        models: Mapping[tuple[str, str], IdentifiedRegimeModel],
        *,
        config: ExactNMPCConfig | None = None,
    ) -> None:
        self.params = params
        self.models = dict(models)
        self.config = ExactNMPCConfig() if config is None else config

    def solve(
        self,
        state: ArrayLike,
        *,
        regime_pair: Sequence[str],
        current_load_pu: ArrayLike,
        previous_command: UpperCommand | None = None,
        past_ibr_commands_pu: ArrayLike | None = None,
    ) -> LinearOracleSolveRecord:
        pair = tuple(str(value) for value in regime_pair)
        if pair not in self.models:
            raise KeyError(f"no O1 identified model for {pair}")
        model = self.models[pair]
        state_values = TwoAreaPlantB(self.params).validate_state(state)
        load = np.asarray(current_load_pu, dtype=np.float64)
        past = (
            np.zeros((2, 2), dtype=np.float64)
            if past_ibr_commands_pu is None
            else np.asarray(past_ibr_commands_pu, dtype=np.float64)
        )
        if load.shape != (2,) or past.shape != (2, 2):
            raise ValueError("invalid O1 load/history shapes")
        previous = UpperCommand() if previous_command is None else previous_command
        previous_action = np.asarray((*previous.sg_pu, *previous.ibr_pu))
        augmented_initial = np.concatenate((state_values, past.reshape(-1, order="F")))
        state_matrix, action_matrix, load_matrix, offset = model.augmented_matrices()
        number = self.config.number_of_control_blocks
        x = cp.Variable((19, number + 1), name="o1_state")
        u = cp.Variable((4, number), name="o1_action")
        constraints: list[cp.Constraint] = [x[:, 0] == augmented_initial]
        objective: cp.Expression = 0.0
        for block in range(number):
            constraints.append(
                x[:, block + 1]
                == state_matrix @ x[:, block]
                + action_matrix @ u[:, block]
                + load_matrix @ load
                + offset
            )
            prior = previous_action if block == 0 else u[:, block - 1]
            delta = u[:, block] - prior
            frequency = x[[0, 3], block]
            tie = x[6, block]
            ace = cp.hstack(
                (
                    self.params.areas[0].ace_bias_pu_per_hz * frequency[0] + tie,
                    self.params.areas[1].ace_bias_pu_per_hz * frequency[1] - tie,
                )
            )
            objective += self.config.command_interval_s * (
                self.config.q_frequency * cp.sum_squares(frequency)
                + self.config.q_ace * cp.sum_squares(ace)
                + self.config.q_tie_line * cp.square(tie)
                + self.config.r_sg * cp.sum_squares(u[:2, block])
                + self.config.r_ibr * cp.sum_squares(u[2:, block])
            )
            objective += self.config.s_sg * cp.sum_squares(delta[:2])
            objective += self.config.s_ibr * cp.sum_squares(delta[2:])
            constraints.extend(
                (
                    u[0, block] >= -self.params.sg_capability.reserve_down_pu[0],
                    u[0, block] <= self.params.sg_capability.reserve_up_pu[0],
                    u[1, block] >= -self.params.sg_capability.reserve_down_pu[1],
                    u[1, block] <= self.params.sg_capability.reserve_up_pu[1],
                    u[2, block] >= -self.params.bess[0].rating_pu,
                    u[2, block] <= self.params.bess[0].rating_pu,
                    u[3, block] >= -self.params.bess[1].rating_pu,
                    u[3, block] <= self.params.bess[1].rating_pu,
                    cp.abs(delta[2]) <= self.config.ibr_command_delta_bound_pu,
                    cp.abs(delta[3]) <= self.config.ibr_command_delta_bound_pu,
                )
            )
        terminal_frequency = x[[0, 3], number]
        terminal_tie = x[6, number]
        terminal_ace = cp.hstack(
            (
                self.params.areas[0].ace_bias_pu_per_hz * terminal_frequency[0]
                + terminal_tie,
                self.params.areas[1].ace_bias_pu_per_hz * terminal_frequency[1]
                - terminal_tie,
            )
        )
        objective += self.config.terminal_multiplier * (
            self.config.q_frequency * cp.sum_squares(terminal_frequency)
            + self.config.q_ace * cp.sum_squares(terminal_ace)
            + self.config.q_tie_line * cp.square(terminal_tie)
            + self.config.r_sg * cp.sum_squares(u[:2, -1])
            + self.config.r_ibr * cp.sum_squares(u[2:, -1])
        )
        constraints.extend(
            (
                cp.abs(x[0, :]) <= self.config.frequency_bound_hz,
                cp.abs(x[3, :]) <= self.config.frequency_bound_hz,
                cp.abs(x[6, :]) <= self.config.tie_line_bound_pu,
            )
        )
        problem = cp.Problem(cp.Minimize(objective), constraints)
        started = time.perf_counter()
        try:
            problem.solve(
                solver="CLARABEL",
                tol_gap_abs=1.0e-7,
                tol_feas=1.0e-7,
                tol_gap_rel=1.0e-7,
                max_iter=1000,
                verbose=False,
            )
        except Exception:
            problem.solve(solver="OSQP", eps_abs=1.0e-6, eps_rel=1.0e-6, max_iter=20_000)
        wall_time = time.perf_counter() - started
        success = problem.status in {cp.OPTIMAL, cp.OPTIMAL_INACCURATE}
        if success and x.value is not None and u.value is not None:
            state_nodes = np.asarray(x.value[:15], dtype=np.float64)
            action_sequence = np.asarray(u.value, dtype=np.float64)
            first = action_sequence[:, 0]
            command = UpperCommand(
                sg_pu=(float(first[0]), float(first[1])),
                ibr_pu=(float(first[2]), float(first[3])),
            )
            dynamic_residual = 0.0
            augmented = np.asarray(x.value, dtype=np.float64)
            for block in range(number):
                residual = augmented[:, block + 1] - (
                    state_matrix @ augmented[:, block]
                    + action_matrix @ action_sequence[:, block]
                    + load_matrix @ load
                    + offset
                )
                dynamic_residual = max(dynamic_residual, float(np.max(np.abs(residual))))
        else:
            state_nodes = np.full((15, number + 1), np.nan)
            action_sequence = np.full((4, number), np.nan)
            command = UpperCommand()
            dynamic_residual = math.inf
        stats = problem.solver_stats
        iterations = int(stats.num_iters) if stats.num_iters is not None else -1
        kkt = math.nan
        extra = getattr(stats, "extra_stats", None)
        info = getattr(extra, "info", None)
        if info is not None:
            primal = float(getattr(info, "prim_res", math.nan))
            dual = float(getattr(info, "dual_res", math.nan))
            kkt = max(primal, dual)
        elif success:
            kkt = dynamic_residual
        return LinearOracleSolveRecord(
            oracle_level="O1",
            solver_status=str(problem.status),
            success=success,
            objective=float(problem.value) if problem.value is not None else math.inf,
            iterations=iterations,
            kkt_residual_inf=kkt,
            max_constraint_residual=dynamic_residual,
            wall_time_s=wall_time,
            command=command,
            action_sequence=action_sequence,
            predicted_state_nodes=state_nodes,
            regime_pair=pair,  # type: ignore[arg-type]
            model_validation_rmse=model.validation_rmse,
        )


def write_identified_model_manifest(
    models: Mapping[str, IdentifiedRegimeModel], destination: str | Path
) -> Path:
    payload = {
        "schema_version": "d5freq.phase_b2.identified_models.v1",
        "development_only": True,
        "models": {
            key: {
                "regime_pair": list(model.regime_pair),
                "fit_sample_count": model.fit_sample_count,
                "validation_rmse": model.validation_rmse,
                "validation_q95_abs_error": model.validation_q95_abs_error,
                "validation_max_abs_error": model.validation_max_abs_error,
                "ridge_alpha": model.ridge_alpha,
                "development_seed": model.development_seed,
            }
            for key, model in sorted(models.items())
        },
    }
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


__all__ = [
    "IdentifiedRegimeModel",
    "LinearOracleSolveRecord",
    "TruthRegimeIdentifiedMPC",
    "exact_block_transition",
    "fit_identified_regime_model",
    "load_identified_model",
    "save_identified_model",
    "write_identified_model_manifest",
]
