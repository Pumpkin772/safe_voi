"""Nested robust-safe and registered-distribution value accounting."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class NestedValueInputs:
    """Complete paired costs for one causal state and capability set.

    Arrays use hypothesis-by-event axes.  ``probe_total_cost`` already includes
    the full probe-window counterfactual and posterior recourse, rather than an
    L1 proxy.  Probe safety is a hard all-hypothesis condition.
    """

    contract_cost: np.ndarray
    perfect_information_cost: np.ndarray
    probe_total_cost: np.ndarray
    event_probability: np.ndarray
    probe_safe_for_hypothesis: np.ndarray
    probe_ids: tuple[str, ...]
    capability_aggregation: str = "worst_case"
    hypothesis_probability: np.ndarray | None = None

    def validated(self) -> "NestedValueInputs":
        contract = np.asarray(self.contract_cost, dtype=float)
        perfect = np.asarray(self.perfect_information_cost, dtype=float)
        probe = np.asarray(self.probe_total_cost, dtype=float)
        event_probability = np.asarray(self.event_probability, dtype=float)
        safe = np.asarray(self.probe_safe_for_hypothesis, dtype=bool)
        if contract.ndim != 2 or perfect.shape != contract.shape:
            raise ValueError("contract and perfect-information costs must be H-by-E")
        if probe.shape != (len(self.probe_ids), *contract.shape):
            raise ValueError("probe total cost must be P-by-H-by-E")
        if safe.shape != (len(self.probe_ids), contract.shape[0]):
            raise ValueError("probe safety must be P-by-H")
        if event_probability.shape != (contract.shape[1],):
            raise ValueError("event probability length mismatch")
        arrays = (contract, perfect, probe, event_probability)
        if any(not np.all(np.isfinite(value)) for value in arrays):
            raise ValueError("costs and probabilities must be finite")
        if np.any(event_probability < 0.0):
            raise ValueError("probabilities must be nonnegative")
        if not np.isclose(event_probability.sum(), 1.0):
            raise ValueError("event probabilities must sum to one")
        if self.capability_aggregation not in {"worst_case", "bayesian"}:
            raise ValueError("capability aggregation must be worst_case or bayesian")
        hypothesis_probability = None
        if self.capability_aggregation == "bayesian":
            if self.hypothesis_probability is None:
                raise ValueError("Bayesian capability value needs an evidence-based prior")
            hypothesis_probability = np.asarray(self.hypothesis_probability, dtype=float)
            if hypothesis_probability.shape != (contract.shape[0],):
                raise ValueError("hypothesis probability length mismatch")
            if not np.all(np.isfinite(hypothesis_probability)) or np.any(hypothesis_probability < 0.0):
                raise ValueError("hypothesis probabilities must be finite and nonnegative")
            if not np.isclose(hypothesis_probability.sum(), 1.0):
                raise ValueError("hypothesis probabilities must sum to one")
        object.__setattr__(self, "contract_cost", contract)
        object.__setattr__(self, "perfect_information_cost", perfect)
        object.__setattr__(self, "probe_total_cost", probe)
        object.__setattr__(self, "hypothesis_probability", hypothesis_probability)
        object.__setattr__(self, "event_probability", event_probability)
        object.__setattr__(self, "probe_safe_for_hypothesis", safe)
        return self


@dataclass(frozen=True)
class NestedValueResult:
    contract_expected_cost: float
    perfect_information_expected_cost: float
    perfect_information_value: float
    perfect_information_value_by_hypothesis: tuple[float, ...]
    probe_expected_cost: dict[str, float]
    probe_net_value: dict[str, float]
    probe_net_value_by_hypothesis: dict[str, tuple[float, ...]]
    safe_probe_ids: tuple[str, ...]
    selected_probe_id: str | None
    selected_net_value: float
    region: str


def evaluate_nested_value(
    inputs: NestedValueInputs,
    positive_margin: float = 0.0,
) -> NestedValueResult:
    data = inputs.validated()
    contract_by_hypothesis = data.contract_cost @ data.event_probability
    perfect_by_hypothesis = data.perfect_information_cost @ data.event_probability
    probe_by_hypothesis = np.einsum("phe,e->ph", data.probe_total_cost, data.event_probability)
    if data.capability_aggregation == "worst_case":
        contract = float(np.max(contract_by_hypothesis))
        perfect = float(np.max(perfect_by_hypothesis))
        perfect_value = float(np.min(contract_by_hypothesis - perfect_by_hypothesis))
    else:
        probability = data.hypothesis_probability
        assert probability is not None
        contract = float(probability @ contract_by_hypothesis)
        perfect = float(probability @ perfect_by_hypothesis)
        perfect_value = contract - perfect
    safe_mask = np.all(data.probe_safe_for_hypothesis, axis=1)
    probe_cost: dict[str, float] = {}
    probe_value: dict[str, float] = {}
    probe_value_by_hypothesis: dict[str, tuple[float, ...]] = {}
    for probe_index, probe_id in enumerate(data.probe_ids):
        branch_value = contract_by_hypothesis - probe_by_hypothesis[probe_index]
        if data.capability_aggregation == "worst_case":
            cost = float(np.max(probe_by_hypothesis[probe_index]))
            value = float(np.min(branch_value))
        else:
            probability = data.hypothesis_probability
            assert probability is not None
            cost = float(probability @ probe_by_hypothesis[probe_index])
            value = contract - cost
        probe_cost[probe_id] = cost
        probe_value[probe_id] = value
        probe_value_by_hypothesis[probe_id] = tuple(float(item) for item in branch_value)

    safe_ids = tuple(
        probe_id for probe_id, safe in zip(data.probe_ids, safe_mask, strict=True) if safe
    )
    positive = [
        probe_id for probe_id in safe_ids if probe_value[probe_id] > positive_margin
    ]
    selected = max(positive, key=probe_value.__getitem__) if positive else None
    selected_value = probe_value[selected] if selected is not None else 0.0
    return NestedValueResult(
        contract_expected_cost=contract,
        perfect_information_expected_cost=perfect,
        perfect_information_value=perfect_value,
        perfect_information_value_by_hypothesis=tuple(
            float(item) for item in contract_by_hypothesis - perfect_by_hypothesis
        ),
        probe_expected_cost=probe_cost,
        probe_net_value=probe_value,
        probe_net_value_by_hypothesis=probe_value_by_hypothesis,
        safe_probe_ids=safe_ids,
        selected_probe_id=selected,
        selected_net_value=selected_value,
        region="POSITIVE_VALUE" if selected is not None else "ZERO_VALUE",
    )
