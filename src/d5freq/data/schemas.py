"""Public and private schemas for safe identification trajectories.

The public trajectory schema is deliberately narrow.  Simulator truth such as
the hidden mode and generation seeds lives in :class:`PrivateTrajectoryMetadata`
and is serialized to a separate private evaluation file by the generator.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Integral, Real
import re

import numpy as np
from numpy.typing import ArrayLike, NDArray
import pandas as pd


FloatArray = NDArray[np.float64]

PUBLIC_SAMPLE_COLUMNS = (
    "trajectory_id",
    "time_s",
    "u_ibr_pu",
    "omega_pu",
    "p_ibr_pu",
)
PUBLIC_SPLIT_COLUMNS = ("trajectory_id", "split", "sha256")
SPLIT_NAMES = ("train", "validation", "ood_calibration", "test")
EXCITATION_FAMILIES = ("prbs", "band_limited", "multisine", "steps")

_OPAQUE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


def _finite(value: float, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real scalar")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


def _positive(value: float, name: str) -> float:
    normalized = _finite(value, name)
    if normalized <= 0.0:
        raise ValueError(f"{name} must be positive")
    return normalized


def _nonnegative(value: float, name: str) -> float:
    normalized = _finite(value, name)
    if normalized < 0.0:
        raise ValueError(f"{name} must be non-negative")
    return normalized


def _positive_integer(value: int, name: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise TypeError(f"{name} must be an integer")
    normalized = int(value)
    if normalized <= 0:
        raise ValueError(f"{name} must be positive")
    return normalized


def _opaque_id(value: str, name: str) -> str:
    if not isinstance(value, str) or _OPAQUE_ID_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} must be a 32-character lowercase hexadecimal ID")
    return value


def _readonly_vector(values: ArrayLike, name: str) -> FloatArray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must contain only finite values")
    result = np.ascontiguousarray(array).copy()
    result.setflags(write=False)
    return result


@dataclass(frozen=True, slots=True)
class SplitCounts:
    """Trajectory counts per hidden-safe public split, for each truth mode."""

    train: int
    validation: int
    ood_calibration: int
    test: int

    def __post_init__(self) -> None:
        for name in SPLIT_NAMES:
            value = getattr(self, name)
            if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
                raise TypeError(f"split count {name} must be an integer")
            normalized = int(value)
            if normalized < 0:
                raise ValueError(f"split count {name} must be non-negative")
            object.__setattr__(self, name, normalized)
        if self.train == 0:
            raise ValueError("the train split must contain at least one trajectory")

    @property
    def total(self) -> int:
        return sum(getattr(self, name) for name in SPLIT_NAMES)

    def as_dict(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in SPLIT_NAMES}

    @classmethod
    def from_mapping(cls, values: object) -> "SplitCounts":
        if not isinstance(values, dict):
            try:
                values = dict(values)  # type: ignore[arg-type]
            except (TypeError, ValueError) as exc:
                raise TypeError("split_counts_per_mode must be a mapping") from exc
        unknown = set(values) - set(SPLIT_NAMES)
        missing = set(SPLIT_NAMES) - set(values)
        if unknown or missing:
            raise ValueError(
                "split_counts_per_mode must contain exactly "
                f"{SPLIT_NAMES}; missing={sorted(missing)}, unknown={sorted(unknown)}"
            )
        return cls(**{name: values[name] for name in SPLIT_NAMES})


@dataclass(frozen=True, slots=True)
class IdentificationGenerationConfig:
    """Validated settings for the independent hidden-mode IBR test bench."""

    master_seed: int
    trajectories_per_mode: int
    trajectory_duration_s: float
    control_period_s: float
    integration_step_s: float
    f0_hz: float
    command_abs_limit_pu: float
    command_rate_limit_pu_per_s: float
    frequency_abs_limit_hz: float
    power_measurement_noise_std_pu: float
    minimum_command_std_pu: float
    minimum_frequency_std_hz: float
    maximum_regression_condition_number: float
    split_counts_per_mode: SplitCounts

    def __post_init__(self) -> None:
        if isinstance(self.master_seed, (bool, np.bool_)) or not isinstance(
            self.master_seed, Integral
        ):
            raise TypeError("master_seed must be a non-negative integer")
        master_seed = int(self.master_seed)
        if master_seed < 0:
            raise ValueError("master_seed must be non-negative")
        object.__setattr__(self, "master_seed", master_seed)

        count = _positive_integer(self.trajectories_per_mode, "trajectories_per_mode")
        object.__setattr__(self, "trajectories_per_mode", count)
        for name in (
            "trajectory_duration_s",
            "control_period_s",
            "integration_step_s",
            "f0_hz",
            "command_abs_limit_pu",
            "command_rate_limit_pu_per_s",
            "frequency_abs_limit_hz",
            "minimum_command_std_pu",
            "minimum_frequency_std_hz",
            "maximum_regression_condition_number",
        ):
            object.__setattr__(self, name, _positive(getattr(self, name), name))
        object.__setattr__(
            self,
            "power_measurement_noise_std_pu",
            _nonnegative(
                self.power_measurement_noise_std_pu,
                "power_measurement_noise_std_pu",
            ),
        )
        if self.integration_step_s > self.control_period_s:
            raise ValueError("integration_step_s must not exceed control_period_s")
        interval_count = self.trajectory_duration_s / self.control_period_s
        rounded = round(interval_count)
        if rounded < 3 or not math.isclose(
            interval_count, rounded, rel_tol=0.0, abs_tol=1.0e-10
        ):
            raise ValueError(
                "trajectory_duration_s must be an integer multiple of "
                "control_period_s and provide at least four samples"
            )
        if self.maximum_regression_condition_number <= 1.0:
            raise ValueError("maximum_regression_condition_number must exceed one")
        if not isinstance(self.split_counts_per_mode, SplitCounts):
            raise TypeError("split_counts_per_mode must be a SplitCounts instance")
        if self.split_counts_per_mode.total != count:
            raise ValueError(
                "split_counts_per_mode must sum to trajectories_per_mode"
            )

    @property
    def sample_count(self) -> int:
        return round(self.trajectory_duration_s / self.control_period_s) + 1


@dataclass(frozen=True, slots=True)
class ExcitationSignals:
    """One paired, control-period ZOH command/frequency excitation."""

    family: str
    time_s: ArrayLike
    u_ibr_pu: ArrayLike
    omega_pu: ArrayLike

    def __post_init__(self) -> None:
        if self.family not in EXCITATION_FAMILIES:
            raise ValueError(f"unknown excitation family: {self.family!r}")
        time = _readonly_vector(self.time_s, "time_s")
        command = _readonly_vector(self.u_ibr_pu, "u_ibr_pu")
        omega = _readonly_vector(self.omega_pu, "omega_pu")
        if len(time) < 4:
            raise ValueError("an excitation must contain at least four samples")
        if not (len(time) == len(command) == len(omega)):
            raise ValueError("excitation arrays must have identical lengths")
        if not math.isclose(float(time[0]), 0.0, rel_tol=0.0, abs_tol=1.0e-12):
            raise ValueError("excitation time must begin at zero")
        if np.any(np.diff(time) <= 0.0):
            raise ValueError("excitation time must be strictly increasing")
        object.__setattr__(self, "time_s", time)
        object.__setattr__(self, "u_ibr_pu", command)
        object.__setattr__(self, "omega_pu", omega)


@dataclass(frozen=True, slots=True)
class IdentificationTrajectory:
    """A controller-visible, truth-free identification trajectory.

    This class intentionally has no mode, seed, family, pair, or private
    metadata attributes.  Its dataframe representation is restricted to
    :data:`PUBLIC_SAMPLE_COLUMNS`.
    """

    trajectory_id: str
    time_s: ArrayLike
    u_ibr_pu: ArrayLike
    omega_pu: ArrayLike
    p_ibr_pu: ArrayLike

    def __post_init__(self) -> None:
        trajectory_id = _opaque_id(self.trajectory_id, "trajectory_id")
        arrays = {
            name: _readonly_vector(getattr(self, name), name)
            for name in ("time_s", "u_ibr_pu", "omega_pu", "p_ibr_pu")
        }
        lengths = {len(array) for array in arrays.values()}
        if len(lengths) != 1 or next(iter(lengths)) < 4:
            raise ValueError(
                "trajectory arrays must have one common length of at least four"
            )
        time = arrays["time_s"]
        if not math.isclose(float(time[0]), 0.0, rel_tol=0.0, abs_tol=1.0e-12):
            raise ValueError("trajectory time must begin at zero")
        differences = np.diff(time)
        if np.any(differences <= 0.0) or not np.allclose(
            differences, differences[0], rtol=0.0, atol=1.0e-10
        ):
            raise ValueError("trajectory samples must be strictly and uniformly spaced")
        object.__setattr__(self, "trajectory_id", trajectory_id)
        for name, array in arrays.items():
            object.__setattr__(self, name, array)

    @property
    def control_period_s(self) -> float:
        return float(self.time_s[1] - self.time_s[0])

    def to_frame(self) -> pd.DataFrame:
        """Return a new dataframe containing exactly the public whitelist."""

        sample_count = len(self.time_s)
        frame = pd.DataFrame(
            {
                "trajectory_id": np.repeat(self.trajectory_id, sample_count),
                "time_s": self.time_s,
                "u_ibr_pu": self.u_ibr_pu,
                "omega_pu": self.omega_pu,
                "p_ibr_pu": self.p_ibr_pu,
            },
            columns=PUBLIC_SAMPLE_COLUMNS,
        )
        return frame

    @classmethod
    def from_frame(cls, frame: pd.DataFrame) -> "IdentificationTrajectory":
        """Validate and load a dataframe with no non-whitelisted columns."""

        if tuple(frame.columns) != PUBLIC_SAMPLE_COLUMNS:
            raise ValueError(
                "public trajectory columns must exactly match "
                f"{PUBLIC_SAMPLE_COLUMNS}"
            )
        identifiers = frame["trajectory_id"].drop_duplicates().tolist()
        if len(identifiers) != 1:
            raise ValueError("a public trajectory file must contain exactly one ID")
        return cls(
            trajectory_id=str(identifiers[0]),
            time_s=frame["time_s"].to_numpy(dtype=float),
            u_ibr_pu=frame["u_ibr_pu"].to_numpy(dtype=float),
            omega_pu=frame["omega_pu"].to_numpy(dtype=float),
            p_ibr_pu=frame["p_ibr_pu"].to_numpy(dtype=float),
        )


@dataclass(frozen=True, slots=True)
class PrivateTrajectoryMetadata:
    """Evaluation-only truth record stored outside the public data tree."""

    trajectory_id: str
    mode_name_eval_only: str
    trajectory_seed_eval_only: int
    excitation_pair_id_eval_only: str
    excitation_family_eval_only: str
    split: str
    excitation_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "trajectory_id", _opaque_id(self.trajectory_id, "trajectory_id")
        )
        object.__setattr__(
            self,
            "excitation_pair_id_eval_only",
            _opaque_id(
                self.excitation_pair_id_eval_only,
                "excitation_pair_id_eval_only",
            ),
        )
        if not isinstance(self.mode_name_eval_only, str) or not self.mode_name_eval_only:
            raise ValueError("mode_name_eval_only must be a non-empty string")
        if isinstance(self.trajectory_seed_eval_only, (bool, np.bool_)) or not isinstance(
            self.trajectory_seed_eval_only, Integral
        ):
            raise TypeError("trajectory_seed_eval_only must be an integer")
        seed = int(self.trajectory_seed_eval_only)
        if seed < 0:
            raise ValueError("trajectory_seed_eval_only must be non-negative")
        object.__setattr__(self, "trajectory_seed_eval_only", seed)
        if self.excitation_family_eval_only not in EXCITATION_FAMILIES:
            raise ValueError("invalid excitation_family_eval_only")
        if self.split not in SPLIT_NAMES:
            raise ValueError("invalid split")
        if re.fullmatch(r"[0-9a-f]{64}", self.excitation_sha256) is None:
            raise ValueError("excitation_sha256 must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class TrajectoryAudit:
    """Safety and excitation-quality evidence for one public trajectory."""

    trajectory_id: str
    max_abs_command_pu: float
    max_abs_command_rate_pu_per_s: float
    max_abs_frequency_hz: float
    command_std_pu: float
    frequency_std_hz: float
    regression_condition_number: float
    command_amplitude_safe: bool
    command_rate_safe: bool
    frequency_safe: bool
    command_excitation_sufficient: bool
    frequency_excitation_sufficient: bool
    regression_conditioning_safe: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "trajectory_id", _opaque_id(self.trajectory_id, "trajectory_id")
        )

    @property
    def passed(self) -> bool:
        return all(
            (
                self.command_amplitude_safe,
                self.command_rate_safe,
                self.frequency_safe,
                self.command_excitation_sufficient,
                self.frequency_excitation_sufficient,
                self.regression_conditioning_safe,
            )
        )


__all__ = [
    "EXCITATION_FAMILIES",
    "ExcitationSignals",
    "FloatArray",
    "IdentificationGenerationConfig",
    "IdentificationTrajectory",
    "PUBLIC_SAMPLE_COLUMNS",
    "PUBLIC_SPLIT_COLUMNS",
    "PrivateTrajectoryMetadata",
    "SPLIT_NAMES",
    "SplitCounts",
    "TrajectoryAudit",
]
