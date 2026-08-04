"""Evaluation-only true-capability rolling MPC for materiality bounds."""

from __future__ import annotations

from dataclasses import replace

from direction5freq.models.capability_contract import (
    CapabilityContract,
    CapabilityRealization,
)

from .dcsv_mpc_final import DCSVInput, DCSVResult, RollingContractMPC


class TrueCapabilityOracleMPC(RollingContractMPC):
    """A fair rolling upper bound that alone may read current evaluation truth.

    The plant model, horizon, objective, state constraints, measured-SoC energy,
    delay pipeline and solver are identical to the contract-only MPC.  Only the
    command-to-actual capability set is replaced by the current true set.  This
    class is never a deployable-controller candidate.
    """

    name = "true_capability_oracle_mpc"
    evaluation_only = True

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.registered_contract = self.contract

    @staticmethod
    def _truth_contract(truth: CapabilityRealization) -> CapabilityContract:
        return CapabilityContract(
            lower_power_pu=tuple(float(value) for value in truth.lower_power_pu),
            upper_power_pu=tuple(float(value) for value in truth.upper_power_pu),
            ramp_down_pu_per_s=tuple(float(value) for value in truth.ramp_down_pu_per_s),
            ramp_up_pu_per_s=tuple(float(value) for value in truth.ramp_up_pu_per_s),
            maximum_delay_s=tuple(float(value) for value in truth.delay_s),
        )

    def propose_with_evaluation_truth(
        self,
        inputs: DCSVInput,
        truth: CapabilityRealization,
    ) -> DCSVResult:
        self.contract = self._truth_contract(truth)
        return super().propose(inputs)

    def propose(self, inputs: DCSVInput) -> DCSVResult:  # pragma: no cover - safety boundary
        raise RuntimeError(
            "TrueCapabilityOracleMPC is evaluation-only; use "
            "propose_with_evaluation_truth"
        )


__all__ = ["TrueCapabilityOracleMPC"]

