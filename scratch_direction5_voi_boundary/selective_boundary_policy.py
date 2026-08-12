"""Causal selective probe decision built from a frozen exact boundary map."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd


FEATURES = (
    "load_magnitude_pu", "power_spread_pu", "ramp_spread_pu_per_s",
    "delay_spread_s", "noise_std_pu", "soc", "tie_loading_pu",
)
FEATURE_RANGES = np.array((0.060, 0.035, 0.035, 1.3, 0.0015, 0.40, 0.04))


@dataclass(frozen=True, slots=True)
class CausalBoundaryFeatures:
    period_s: float
    sg_tension: str
    objective: str
    load_magnitude_pu: float
    power_spread_pu: float
    ramp_spread_pu_per_s: float
    delay_spread_s: float
    noise_std_pu: float
    soc: float
    tie_loading_pu: float


@dataclass(frozen=True, slots=True)
class BoundaryDecision:
    worthwhile: bool
    reason: str
    predicted_net_value: float
    selected_point_id: str | None
    selected_probe_id: str | None
    neighbor_point_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConservativeCapability:
    retained_model_ids: tuple[str, ...]
    power_floor_pu: float
    ramp_floor_pu_per_s: float
    maximum_delay_s: float
    valid_until_s: float


class FrozenBoundaryLookup:
    """A conservative lookup: all nearest neighbours must be exact-positive."""

    def __init__(self, map_csv: Path, detail_root: Path, neighbors: int = 5) -> None:
        self.frame = pd.read_csv(map_csv)
        self.detail_root = Path(detail_root)
        self.neighbors = int(neighbors)
        if self.neighbors <= 0:
            raise ValueError("neighbors must be positive")
        region_column = "final_region" if "final_region" in self.frame else "region"
        self.has_positive_region = bool(
            self.frame[region_column].astype(str).eq("POSITIVE_VALUE").any()
        )

    @staticmethod
    def _vector(values) -> np.ndarray:
        return np.asarray([float(getattr(values, name)) for name in FEATURES]) / FEATURE_RANGES

    def decide(self, features: CausalBoundaryFeatures) -> BoundaryDecision:
        if not self.has_positive_region:
            return BoundaryDecision(False, "FROZEN_MAP_HAS_NO_POSITIVE_REGION", 0.0, None, None, ())
        compatible = self.frame.loc[
            np.isclose(self.frame.period_s, features.period_s)
            & self.frame.sg_tension.eq(features.sg_tension)
            & self.frame.objective.eq(features.objective)
            & self.frame.solver_failures.eq(0)
        ].copy()
        if compatible.empty:
            return BoundaryDecision(False, "NO_COMPATIBLE_BOUNDARY_POINTS", 0.0, None, None, ())
        target = self._vector(features)
        values = compatible.loc[:, FEATURES].astype(float).to_numpy() / FEATURE_RANGES
        compatible["distance"] = np.linalg.norm(values - target, axis=1)
        nearest = compatible.nsmallest(min(self.neighbors, len(compatible)), "distance")
        ids = tuple(nearest.point_id.astype(str))
        if len(nearest) < self.neighbors:
            return BoundaryDecision(False, "INSUFFICIENT_LOCAL_BOUNDARY_DENSITY", 0.0, None, None, ids)
        if not nearest.region.eq("POSITIVE_VALUE").all():
            return BoundaryDecision(False, "LOCAL_REGION_NOT_UNIFORMLY_POSITIVE", 0.0, None, None, ids)
        lower_value = float(nearest.maximum_exact_probe_value.min())
        if lower_value <= 0.0:
            return BoundaryDecision(False, "NONPOSITIVE_LOCAL_VALUE_LOWER_BOUND", lower_value, None, None, ids)
        selected = nearest.iloc[0]
        return BoundaryDecision(
            True, "POSITIVE_EXACT_LOCAL_REGION", lower_value,
            str(selected.point_id), str(selected.selected_probe_id), ids,
        )

    def detail(self, point_id: str) -> dict:
        return json.loads((self.detail_root / f"{point_id}.json").read_text(encoding="utf-8"))


class SelectiveProbeScheduler:
    """Overlay a frozen probe; abstention returns the exact base array unchanged."""

    def __init__(self, lookup: FrozenBoundaryLookup, certificate_validity_s: float = 24.0) -> None:
        self.lookup = lookup
        self.certificate_validity_s = float(certificate_validity_s)
        self.decision: BoundaryDecision | None = None
        self._probe: dict | None = None
        self._sequence = np.empty(0)
        self._index = 0
        self._issued_base: list[float] = []
        self._actual_trace: list[float] = []
        self._last_epoch: int | None = None

    @property
    def active(self) -> bool:
        return self._index < len(self._sequence)

    def consider(
        self,
        features: CausalBoundaryFeatures,
        *,
        causal_change_epoch: int,
        decision_relevant: bool,
    ) -> BoundaryDecision:
        if not decision_relevant:
            self.decision = BoundaryDecision(False, "NOT_DECISION_RELEVANT", 0.0, None, None, ())
            return self.decision
        if self._last_epoch == causal_change_epoch:
            self.decision = BoundaryDecision(False, "EPOCH_ALREADY_CONSIDERED", 0.0, None, None, ())
            return self.decision
        self._last_epoch = int(causal_change_epoch)
        self.decision = self.lookup.decide(features)
        if not self.decision.worthwhile:
            self._probe = None; self._sequence = np.empty(0); self._index = 0
            return self.decision
        detail = self.lookup.detail(str(self.decision.selected_point_id))
        matching = [
            item for item in detail["probes"]
            if item["probe_id"] == self.decision.selected_probe_id
        ]
        if len(matching) != 1:
            raise RuntimeError("selected exact probe is absent from frozen point detail")
        self._probe = matching[0]
        # Sequence is reconstructed from its physical definition stored in the ID/detail.
        # The detailed engine output is augmented with this field when the map is frozen.
        self._sequence = np.asarray(self._probe["sequence_pu"], dtype=float)
        self._index = 0; self._issued_base.clear(); self._actual_trace.clear()
        return self.decision

    def overlay(self, base_action: np.ndarray) -> np.ndarray:
        base = np.asarray(base_action, dtype=float)
        if not self.active:
            # No allocation, copying, clipping, or re-solving occurs in the zero region.
            return base_action
        area = int(self._probe["area"])
        q = float(self._sequence[self._index])
        action = base.copy()
        sg_index, bess_index = ((0, 1) if area == 0 else (2, 3))
        action[sg_index] -= q; action[bess_index] += q
        self._issued_base.append(float(base[bess_index]))
        self._index += 1
        return action

    def observe_actual_poi(self, actual_bess_power_pu: Sequence[float]) -> None:
        if self._probe is None or len(self._actual_trace) >= len(self._sequence):
            return
        area = int(self._probe["area"])
        self._actual_trace.append(float(actual_bess_power_pu[area]))

    def finish(self, now_s: float, candidate_models: Sequence[dict]) -> ConservativeCapability | None:
        if self._probe is None or len(self._actual_trace) != len(self._sequence):
            return None
        weights = self._sequence / max(np.sum(np.abs(self._sequence)), 1e-12)
        statistic = float(np.dot(weights, np.asarray(self._actual_trace)))
        retained = tuple(sorted(
            model_id for model_id, interval in self._probe["observation_intervals"].items()
            if float(interval[0]) - 1e-12 <= statistic <= float(interval[1]) + 1e-12
        ))
        if not retained:
            return None
        lookup = {str(item["model_id"]): item for item in candidate_models}
        selected = [lookup[item] for item in retained]
        return ConservativeCapability(
            retained_model_ids=retained,
            power_floor_pu=float(min(item["power_pu"] for item in selected)),
            ramp_floor_pu_per_s=float(min(item["ramp_pu_per_s"] for item in selected)),
            maximum_delay_s=float(max(item["delay_s"] for item in selected)),
            valid_until_s=float(now_s + self.certificate_validity_s),
        )


__all__ = [
    "BoundaryDecision", "CausalBoundaryFeatures", "ConservativeCapability",
    "FrozenBoundaryLookup", "SelectiveProbeScheduler",
]
