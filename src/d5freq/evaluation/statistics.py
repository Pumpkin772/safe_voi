"""Episode-level summaries and paired statistical comparisons.

Every row is one statistical unit.  Failed rows and right-censored rows remain
in the input and in all audit counts; a numerical estimand may use only finite,
uncensored observations, but that conditional sample size is always reported.
No function in this module uses NumPy's global random state.  Randomized
procedures require an explicit seed and create a local ``Generator``.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Integral, Real
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray
import pandas as pd
from scipy.stats import binomtest


FloatArray = NDArray[np.float64]


def _rng_seed(value: object) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise TypeError("rng_seed must be an integer")
    seed = int(value)
    if seed < 0:
        raise ValueError("rng_seed must be non-negative")
    return seed


def _positive_resamples(value: object, name: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise TypeError(f"{name} must be an integer")
    normalized = int(value)
    if normalized <= 0:
        raise ValueError(f"{name} must be strictly positive")
    return normalized


def _confidence(value: object) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError("confidence_level must be a real number")
    normalized = float(value)
    if not math.isfinite(normalized) or not 0.0 < normalized < 1.0:
        raise ValueError("confidence_level must lie in (0, 1)")
    return normalized


def _require_columns(frame: pd.DataFrame, columns: tuple[str, ...]) -> None:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas DataFrame")
    missing = tuple(column for column in columns if column not in frame.columns)
    if missing:
        raise ValueError(f"dataframe is missing columns: {missing!r}")


def validate_episode_unit(
    frame: pd.DataFrame,
    *,
    episode_id_column: str = "run_id",
) -> None:
    """Require exactly one table row per attempted episode."""

    _require_columns(frame, (episode_id_column,))
    if frame[episode_id_column].isna().any():
        raise ValueError(f"{episode_id_column} cannot be missing")
    duplicated = frame[episode_id_column].duplicated(keep=False)
    if duplicated.any():
        values = frame.loc[duplicated, episode_id_column].tolist()
        raise ValueError(f"each episode must be one statistical row: {values!r}")


def _numeric_audit(series: pd.Series, name: str) -> tuple[FloatArray, NDArray[np.bool_], int, int]:
    missing = series.isna().to_numpy(dtype=np.bool_)
    try:
        numeric = pd.to_numeric(series, errors="raise").to_numpy(dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must contain only numeric or missing values") from exc
    finite = np.isfinite(numeric)
    nonfinite_count = int(np.count_nonzero(~finite & ~missing))
    missing_count = int(np.count_nonzero(missing))
    return numeric, finite, missing_count, nonfinite_count


def _boolean_series(series: pd.Series, name: str, *, allow_missing: bool) -> NDArray[np.bool_]:
    result = np.zeros(len(series), dtype=np.bool_)
    for index, raw in enumerate(series.tolist()):
        if pd.isna(raw):
            if allow_missing:
                continue
            raise ValueError(f"{name} cannot contain missing values")
        if not isinstance(raw, (bool, np.bool_)):
            raise TypeError(f"{name} must contain booleans")
        result[index] = bool(raw)
    return result


def _finite_strict(values: ArrayLike, name: str) -> FloatArray:
    raw = np.asarray(values)
    if np.iscomplexobj(raw):
        raise TypeError(f"{name} must be real-valued")
    array = np.asarray(raw, dtype=np.float64)
    if array.ndim != 1 or array.size == 0:
        raise ValueError(f"{name} must be a non-empty one-dimensional vector")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must contain only finite values")
    return array.copy()


@dataclass(frozen=True, slots=True)
class BootstrapCI:
    estimate: float
    lower: float
    upper: float
    confidence_level: float
    resamples: int
    episode_count: int

    def to_dict(self) -> dict[str, float | int]:
        return {
            "estimate": self.estimate,
            "lower": self.lower,
            "upper": self.upper,
            "confidence_level": self.confidence_level,
            "resamples": self.resamples,
            "episode_count": self.episode_count,
        }


def bootstrap_mean_ci(
    episode_values: ArrayLike,
    *,
    rng_seed: int,
    n_resamples: int = 10_000,
    confidence_level: float = 0.95,
) -> BootstrapCI:
    """Percentile CI by resampling complete episode units with replacement."""

    values = _finite_strict(episode_values, "episode_values")
    seed = _rng_seed(rng_seed)
    resamples = _positive_resamples(n_resamples, "n_resamples")
    confidence = _confidence(confidence_level)
    rng = np.random.default_rng(seed)
    distribution = np.empty(resamples, dtype=np.float64)
    chunk_size = 1024
    for start in range(0, resamples, chunk_size):
        stop = min(resamples, start + chunk_size)
        indices = rng.integers(0, values.size, size=(stop - start, values.size))
        distribution[start:stop] = np.mean(values[indices], axis=1)
    alpha = (1.0 - confidence) / 2.0
    return BootstrapCI(
        estimate=float(np.mean(values)),
        lower=float(np.quantile(distribution, alpha)),
        upper=float(np.quantile(distribution, 1.0 - alpha)),
        confidence_level=confidence,
        resamples=resamples,
        episode_count=int(values.size),
    )


def paired_bootstrap_mean_ci(
    paired_differences: ArrayLike,
    *,
    rng_seed: int,
    n_resamples: int = 10_000,
    confidence_level: float = 0.95,
) -> BootstrapCI:
    """Seed-paired bootstrap CI; each resampled unit is one paired seed."""

    return bootstrap_mean_ci(
        paired_differences,
        rng_seed=rng_seed,
        n_resamples=n_resamples,
        confidence_level=confidence_level,
    )


SUMMARY_COLUMNS: tuple[str, ...] = (
    "metric",
    "episode_count",
    "finite_count",
    "missing_count",
    "nonfinite_count",
    "run_incomplete_count",
    "scientific_failure_count",
    "censored_count",
    "mean",
    "median",
    "std",
    "q05",
    "q95",
    "ci95_low",
    "ci95_high",
    "bootstrap_resamples",
)


def _ordered_group_keys(frame: pd.DataFrame, columns: tuple[str, ...]) -> list[tuple[Any, ...]]:
    if not columns:
        return [()]
    keys: dict[tuple[Any, ...], None] = {}
    for values in frame.loc[:, columns].itertuples(index=False, name=None):
        if any(pd.isna(value) for value in values):
            raise ValueError("grouping columns cannot contain missing values")
        keys[tuple(values)] = None
    return sorted(
        keys,
        key=lambda values: tuple((type(value).__qualname__, repr(value)) for value in values),
    )


def _group_subset(
    frame: pd.DataFrame,
    columns: tuple[str, ...],
    key: tuple[Any, ...],
) -> pd.DataFrame:
    if not columns:
        return frame
    mask = np.ones(len(frame), dtype=np.bool_)
    for column, value in zip(columns, key, strict=True):
        mask &= frame[column].to_numpy() == value
    return frame.loc[mask]


def summarize_episode_metric(
    frame: pd.DataFrame,
    metric: str,
    *,
    group_columns: tuple[str, ...] = ("scenario_id", "method"),
    censor_column: str | None = None,
    rng_seed: int,
    n_resamples: int = 10_000,
    confidence_level: float = 0.95,
    episode_id_column: str = "run_id",
) -> pd.DataFrame:
    """Report mean/median/std/q05/q95 and episode-bootstrap confidence limits.

    Finite, uncensored values define the numerical estimand.  Missing,
    non-finite, failed, incomplete, and censored episode counts remain visible
    in adjacent audit columns.  A censored row carrying a finite delay is
    rejected because it would ambiguously mix censoring exposure with delay.
    """

    required = (episode_id_column, metric, *group_columns)
    if censor_column is not None:
        required += (censor_column,)
    _require_columns(frame, required)
    validate_episode_unit(frame, episode_id_column=episode_id_column)
    resamples = _positive_resamples(n_resamples, "n_resamples")
    confidence = _confidence(confidence_level)
    master_rng = np.random.default_rng(_rng_seed(rng_seed))
    rows: list[dict[str, Any]] = []
    for key in _ordered_group_keys(frame, group_columns):
        group = _group_subset(frame, group_columns, key)
        numeric, finite, missing_count, nonfinite_count = _numeric_audit(group[metric], metric)
        censored = np.zeros(len(group), dtype=np.bool_)
        if censor_column is not None:
            censored = _boolean_series(group[censor_column], censor_column, allow_missing=False)
            if np.any(censored & finite):
                raise ValueError("censored episodes must store delay as missing, not as a number")
        included = finite & ~censored
        values = numeric[included]
        run_incomplete = 0
        if "run_completed" in group.columns:
            run_incomplete = int(
                np.count_nonzero(~_boolean_series(group["run_completed"], "run_completed", allow_missing=False))
            )
        scientific_failure = 0
        if "scientific_success" in group.columns:
            scientific_failure = int(
                np.count_nonzero(
                    ~_boolean_series(group["scientific_success"], "scientific_success", allow_missing=False)
                )
            )
        ci_low: float | None = None
        ci_high: float | None = None
        if values.size:
            child_seed = int(master_rng.integers(0, np.iinfo(np.uint32).max, dtype=np.uint32))
            ci = bootstrap_mean_ci(
                values,
                rng_seed=child_seed,
                n_resamples=resamples,
                confidence_level=confidence,
            )
            ci_low, ci_high = ci.lower, ci.upper
        row = {column: value for column, value in zip(group_columns, key, strict=True)}
        row.update(
            metric=metric,
            episode_count=int(len(group)),
            finite_count=int(values.size),
            missing_count=missing_count,
            nonfinite_count=nonfinite_count,
            run_incomplete_count=run_incomplete,
            scientific_failure_count=scientific_failure,
            censored_count=int(np.count_nonzero(censored)),
            mean=None if values.size == 0 else float(np.mean(values)),
            median=None if values.size == 0 else float(np.median(values)),
            std=None if values.size < 2 else float(np.std(values, ddof=1)),
            q05=None if values.size == 0 else float(np.quantile(values, 0.05)),
            q95=None if values.size == 0 else float(np.quantile(values, 0.95)),
            ci95_low=ci_low,
            ci95_high=ci_high,
            bootstrap_resamples=resamples,
        )
        rows.append(row)
    return pd.DataFrame.from_records(rows, columns=(*group_columns, *SUMMARY_COLUMNS))


def pair_episode_rows(
    frame: pd.DataFrame,
    *,
    method: str,
    reference_method: str,
    pairing_columns: tuple[str, ...] = ("scenario_id", "seed"),
    method_column: str = "method",
) -> pd.DataFrame:
    """Outer-pair two methods while preserving unmatched and failed episodes."""

    _require_columns(frame, (method_column, *pairing_columns))
    selected = frame.loc[frame[method_column].isin((method, reference_method))].copy()
    for label, subset in selected.groupby(method_column, sort=False):
        duplicates = subset.duplicated(subset=list(pairing_columns), keep=False)
        if duplicates.any():
            keys = subset.loc[duplicates, list(pairing_columns)].to_dict("records")
            raise ValueError(f"method {label!r} has duplicate episode pairing keys: {keys!r}")
    method_rows = selected.loc[selected[method_column] == method].drop(columns=[method_column])
    reference_rows = selected.loc[selected[method_column] == reference_method].drop(columns=[method_column])
    paired = method_rows.merge(
        reference_rows,
        how="outer",
        on=list(pairing_columns),
        suffixes=("_method", "_reference"),
        indicator="pair_status",
        sort=True,
        validate="one_to_one",
    )
    paired.insert(len(pairing_columns), "method", method)
    paired.insert(len(pairing_columns) + 1, "reference_method", reference_method)
    return paired


@dataclass(frozen=True, slots=True)
class SignFlipResult:
    statistic: float
    pvalue: float
    paired_count: int
    permutation_count: int
    exact: bool

    def to_dict(self) -> dict[str, float | int | bool]:
        return {
            "statistic": self.statistic,
            "pvalue": self.pvalue,
            "paired_count": self.paired_count,
            "permutation_count": self.permutation_count,
            "exact": self.exact,
        }


def sign_flip_permutation_test(
    paired_differences: ArrayLike,
    *,
    rng_seed: int,
    n_resamples: int = 10_000,
) -> SignFlipResult:
    """Two-sided paired sign-flip test using exact enumeration when feasible."""

    differences = _finite_strict(paired_differences, "paired_differences")
    seed = _rng_seed(rng_seed)
    requested = _positive_resamples(n_resamples, "n_resamples")
    observed = abs(float(np.mean(differences)))
    tolerance = 1e-15 * max(1.0, observed)
    total_permutations = 1 << differences.size if differences.size < 63 else requested + 1
    exact = total_permutations <= requested
    extreme = 0
    if exact:
        for code in range(total_permutations):
            signs = np.fromiter(
                (1.0 if (code >> index) & 1 else -1.0 for index in range(differences.size)),
                dtype=np.float64,
                count=differences.size,
            )
            extreme += abs(float(np.mean(signs * differences))) + tolerance >= observed
        pvalue = extreme / total_permutations
        permutation_count = total_permutations
    else:
        rng = np.random.default_rng(seed)
        chunk_size = 1024
        for start in range(0, requested, chunk_size):
            count = min(chunk_size, requested - start)
            signs = 2.0 * rng.integers(0, 2, size=(count, differences.size)) - 1.0
            statistics = np.abs(np.mean(signs * differences, axis=1))
            extreme += int(np.count_nonzero(statistics + tolerance >= observed))
        pvalue = (extreme + 1.0) / (requested + 1.0)
        permutation_count = requested
    return SignFlipResult(
        statistic=observed,
        pvalue=float(pvalue),
        paired_count=int(differences.size),
        permutation_count=int(permutation_count),
        exact=exact,
    )


PAIRED_COMPARISON_COLUMNS: tuple[str, ...] = (
    "metric",
    "method",
    "reference_method",
    "method_episode_count",
    "reference_episode_count",
    "matched_pair_count",
    "finite_pair_count",
    "missing_pair_count",
    "censored_pair_count",
    "unmatched_method_count",
    "unmatched_reference_count",
    "mean_difference",
    "median_difference",
    "ci95_low",
    "ci95_high",
    "sign_flip_pvalue",
    "sign_flip_permutations",
    "bootstrap_resamples",
)


def paired_method_comparison(
    frame: pd.DataFrame,
    metric: str,
    *,
    method: str,
    reference_method: str,
    strata_columns: tuple[str, ...] = ("scenario_id",),
    seed_column: str = "seed",
    method_column: str = "method",
    censor_column: str | None = None,
    rng_seed: int,
    n_resamples: int = 10_000,
    confidence_level: float = 0.95,
    episode_id_column: str = "run_id",
) -> pd.DataFrame:
    """Compute method-minus-reference seed-paired differences by stratum."""

    required = (episode_id_column, metric, method_column, seed_column, *strata_columns)
    if censor_column is not None:
        required += (censor_column,)
    _require_columns(frame, required)
    validate_episode_unit(frame, episode_id_column=episode_id_column)
    selected = frame.loc[frame[method_column].isin((method, reference_method))]
    resamples = _positive_resamples(n_resamples, "n_resamples")
    confidence = _confidence(confidence_level)
    master_rng = np.random.default_rng(_rng_seed(rng_seed))
    rows: list[dict[str, Any]] = []
    for key in _ordered_group_keys(selected, strata_columns):
        group = _group_subset(selected, strata_columns, key)
        paired = pair_episode_rows(
            group,
            method=method,
            reference_method=reference_method,
            pairing_columns=(seed_column,),
            method_column=method_column,
        )
        both = paired["pair_status"].eq("both").to_numpy()
        method_values, method_finite, _, _ = _numeric_audit(
            paired[f"{metric}_method"], f"{metric}_method"
        )
        reference_values, reference_finite, _, _ = _numeric_audit(
            paired[f"{metric}_reference"], f"{metric}_reference"
        )
        censored_pair = np.zeros(len(paired), dtype=np.bool_)
        if censor_column is not None:
            for suffix in ("method", "reference"):
                column = f"{censor_column}_{suffix}"
                values = paired[column]
                present = ~values.isna().to_numpy()
                parsed = _boolean_series(values, column, allow_missing=True)
                censored_pair |= present & parsed
        finite_pair = both & method_finite & reference_finite & ~censored_pair
        differences = method_values[finite_pair] - reference_values[finite_pair]
        ci_low: float | None = None
        ci_high: float | None = None
        pvalue: float | None = None
        permutations = 0
        if differences.size:
            bootstrap_seed = int(master_rng.integers(0, np.iinfo(np.uint32).max, dtype=np.uint32))
            permutation_seed = int(master_rng.integers(0, np.iinfo(np.uint32).max, dtype=np.uint32))
            ci = paired_bootstrap_mean_ci(
                differences,
                rng_seed=bootstrap_seed,
                n_resamples=resamples,
                confidence_level=confidence,
            )
            test = sign_flip_permutation_test(
                differences,
                rng_seed=permutation_seed,
                n_resamples=resamples,
            )
            ci_low, ci_high = ci.lower, ci.upper
            pvalue = test.pvalue
            permutations = test.permutation_count
        row = {column: value for column, value in zip(strata_columns, key, strict=True)}
        row.update(
            metric=metric,
            method=method,
            reference_method=reference_method,
            method_episode_count=int(np.count_nonzero(paired["pair_status"].isin(("both", "left_only")))),
            reference_episode_count=int(np.count_nonzero(paired["pair_status"].isin(("both", "right_only")))),
            matched_pair_count=int(np.count_nonzero(both)),
            finite_pair_count=int(differences.size),
            missing_pair_count=int(np.count_nonzero(both & ~(method_finite & reference_finite))),
            censored_pair_count=int(np.count_nonzero(both & censored_pair)),
            unmatched_method_count=int(np.count_nonzero(paired["pair_status"].eq("left_only"))),
            unmatched_reference_count=int(np.count_nonzero(paired["pair_status"].eq("right_only"))),
            mean_difference=None if differences.size == 0 else float(np.mean(differences)),
            median_difference=None if differences.size == 0 else float(np.median(differences)),
            ci95_low=ci_low,
            ci95_high=ci_high,
            sign_flip_pvalue=pvalue,
            sign_flip_permutations=permutations,
            bootstrap_resamples=resamples,
        )
        rows.append(row)
    return pd.DataFrame.from_records(
        rows,
        columns=(*strata_columns, *PAIRED_COMPARISON_COLUMNS),
    )


@dataclass(frozen=True, slots=True)
class OracleRegretAttachment:
    table: pd.DataFrame
    pairing_audit: pd.DataFrame


def attach_oracle_regret(
    frame: pd.DataFrame,
    cost_column: str,
    *,
    oracle_method: str = "Oracle",
    output_column: str = "oracle_regret",
    pairing_columns: tuple[str, ...] = ("scenario_id", "seed"),
    method_column: str = "method",
    episode_id_column: str = "run_id",
) -> OracleRegretAttachment:
    """Attach cost-minus-Oracle only after an explicit one-to-one seed pairing.

    The returned table preserves input row count and order.  Missing Oracle
    partners or missing costs produce a missing regret plus an audit count;
    they are never replaced by zero.  Oracle rows receive zero only when their
    own cost is finite.
    """

    _require_columns(
        frame,
        (episode_id_column, cost_column, method_column, *pairing_columns),
    )
    validate_episode_unit(frame, episode_id_column=episode_id_column)
    for label, subset in frame.groupby(method_column, sort=False):
        duplicated = subset.duplicated(subset=list(pairing_columns), keep=False)
        if duplicated.any():
            raise ValueError(f"method {label!r} has duplicate Oracle pairing keys")
    oracle = frame.loc[frame[method_column] == oracle_method, [*pairing_columns, cost_column]].copy()
    oracle = oracle.rename(columns={cost_column: "_oracle_cost"})
    working = frame.copy()
    working["_row_order"] = np.arange(len(working), dtype=np.int64)
    working = working.merge(
        oracle,
        how="left",
        on=list(pairing_columns),
        sort=False,
        validate="many_to_one",
    )
    cost, cost_finite, _, _ = _numeric_audit(working[cost_column], cost_column)
    oracle_cost, oracle_finite, _, _ = _numeric_audit(working["_oracle_cost"], "_oracle_cost")
    paired_finite = cost_finite & oracle_finite
    regret = np.full(len(working), np.nan, dtype=np.float64)
    regret[paired_finite] = cost[paired_finite] - oracle_cost[paired_finite]
    working[output_column] = regret

    audit_rows: list[dict[str, Any]] = []
    for method_name in sorted(working[method_column].unique(), key=lambda value: repr(value)):
        mask = working[method_column].eq(method_name).to_numpy()
        has_oracle = mask & oracle_finite
        audit_rows.append(
            {
                "method": method_name,
                "episode_count": int(np.count_nonzero(mask)),
                "oracle_matched_count": int(np.count_nonzero(has_oracle)),
                "finite_regret_count": int(np.count_nonzero(mask & paired_finite)),
                "missing_oracle_count": int(np.count_nonzero(mask & ~oracle_finite)),
                "missing_cost_pair_count": int(np.count_nonzero(has_oracle & ~cost_finite)),
            }
        )
    working = working.sort_values("_row_order").drop(columns=["_row_order", "_oracle_cost"])
    working.index = frame.index
    audit = pd.DataFrame.from_records(
        audit_rows,
        columns=(
            "method",
            "episode_count",
            "oracle_matched_count",
            "finite_regret_count",
            "missing_oracle_count",
            "missing_cost_pair_count",
        ),
    )
    return OracleRegretAttachment(table=working, pairing_audit=audit)


@dataclass(frozen=True, slots=True)
class McNemarResult:
    paired_count: int
    missing_pair_count: int
    both_false: int
    first_false_second_true: int
    first_true_second_false: int
    both_true: int
    discordant_count: int
    pvalue: float

    def to_dict(self) -> dict[str, int | float]:
        return {
            "paired_count": self.paired_count,
            "missing_pair_count": self.missing_pair_count,
            "both_false": self.both_false,
            "first_false_second_true": self.first_false_second_true,
            "first_true_second_false": self.first_true_second_false,
            "both_true": self.both_true,
            "discordant_count": self.discordant_count,
            "pvalue": self.pvalue,
        }


def exact_mcnemar(first: ArrayLike, second: ArrayLike) -> McNemarResult:
    """Exact two-sided McNemar test with explicit missing-pair accounting."""

    first_raw = np.asarray(first, dtype=object)
    second_raw = np.asarray(second, dtype=object)
    if first_raw.ndim != 1 or second_raw.ndim != 1 or first_raw.size != second_raw.size:
        raise ValueError("first and second must be equal-length one-dimensional vectors")
    first_values: list[bool] = []
    second_values: list[bool] = []
    missing = 0
    for left, right in zip(first_raw.tolist(), second_raw.tolist(), strict=True):
        if pd.isna(left) or pd.isna(right):
            missing += 1
            continue
        if not isinstance(left, (bool, np.bool_)) or not isinstance(right, (bool, np.bool_)):
            raise TypeError("McNemar inputs must contain booleans or missing values")
        first_values.append(bool(left))
        second_values.append(bool(right))
    left = np.asarray(first_values, dtype=np.bool_)
    right = np.asarray(second_values, dtype=np.bool_)
    both_false = int(np.count_nonzero(~left & ~right))
    false_true = int(np.count_nonzero(~left & right))
    true_false = int(np.count_nonzero(left & ~right))
    both_true = int(np.count_nonzero(left & right))
    discordant = false_true + true_false
    pvalue = 1.0 if discordant == 0 else float(
        binomtest(false_true, discordant, p=0.5, alternative="two-sided").pvalue
    )
    return McNemarResult(
        paired_count=int(left.size),
        missing_pair_count=missing,
        both_false=both_false,
        first_false_second_true=false_true,
        first_true_second_false=true_false,
        both_true=both_true,
        discordant_count=discordant,
        pvalue=pvalue,
    )


@dataclass(frozen=True, slots=True)
class HolmResult:
    adjusted_pvalues: tuple[float | None, ...]
    rejected: tuple[bool | None, ...]
    alpha: float


def holm_adjust(pvalues: ArrayLike, *, alpha: float = 0.05) -> HolmResult:
    """Holm step-down adjustment; missing p-values remain missing in place."""

    threshold = float(alpha)
    if not math.isfinite(threshold) or not 0.0 < threshold < 1.0:
        raise ValueError("alpha must lie in (0, 1)")
    raw = np.asarray(pvalues, dtype=object)
    if raw.ndim != 1:
        raise ValueError("pvalues must be one-dimensional")
    normalized: list[float | None] = []
    for value in raw.tolist():
        if value is None or pd.isna(value):
            normalized.append(None)
            continue
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
            raise TypeError("pvalues must contain real numbers or missing values")
        number = float(value)
        if not math.isfinite(number) or not 0.0 <= number <= 1.0:
            raise ValueError("finite pvalues must lie in [0, 1]")
        normalized.append(number)
    valid = [index for index, value in enumerate(normalized) if value is not None]
    order = sorted(valid, key=lambda index: (normalized[index], index))
    adjusted: list[float | None] = [None] * len(normalized)
    running = 0.0
    count = len(order)
    for rank, index in enumerate(order):
        assert normalized[index] is not None
        candidate = min(1.0, (count - rank) * normalized[index])
        running = max(running, candidate)
        adjusted[index] = running
    rejected: tuple[bool | None, ...] = tuple(
        None if value is None else bool(value <= threshold) for value in adjusted
    )
    return HolmResult(tuple(adjusted), rejected, threshold)


def apply_holm(
    frame: pd.DataFrame,
    *,
    pvalue_column: str = "pvalue",
    adjusted_column: str = "pvalue_holm",
    rejected_column: str = "reject_holm",
    alpha: float = 0.05,
) -> pd.DataFrame:
    """Return a copy with stable, row-aligned Holm outputs."""

    _require_columns(frame, (pvalue_column,))
    result = holm_adjust(frame[pvalue_column].to_numpy(dtype=object), alpha=alpha)
    output = frame.copy()
    output[adjusted_column] = list(result.adjusted_pvalues)
    output[rejected_column] = list(result.rejected)
    return output


__all__ = [
    "BootstrapCI",
    "HolmResult",
    "McNemarResult",
    "OracleRegretAttachment",
    "PAIRED_COMPARISON_COLUMNS",
    "SUMMARY_COLUMNS",
    "SignFlipResult",
    "apply_holm",
    "attach_oracle_regret",
    "bootstrap_mean_ci",
    "exact_mcnemar",
    "holm_adjust",
    "pair_episode_rows",
    "paired_bootstrap_mean_ci",
    "paired_method_comparison",
    "sign_flip_permutation_test",
    "summarize_episode_metric",
    "validate_episode_unit",
]
