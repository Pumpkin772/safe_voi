"""True rolling MPC baselines sharing the registered physical formulation."""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from .dcsv_mpc import DCSVInput, DisturbanceCapabilitySeparatedViabilityMPC


class NominalOffsetFreeMPC(DisturbanceCapabilitySeparatedViabilityMPC):
    method_name = "nominal_offset_free_mpc"

    def _delay_points(self, data: DCSVInput) -> np.ndarray:
        return np.array([min(0.20, self.period_s - 1e-5)])

    def _guaranteed_limits(self, data: DCSVInput) -> tuple[np.ndarray, ...]:
        return (
            np.full(2, 0.10),
            np.full(2, 0.10),
            np.full(2, 0.08),
            np.full(2, 0.08),
            np.full(2, 20.0),
        )


class RLSAdaptiveMPC(DisturbanceCapabilitySeparatedViabilityMPC):
    method_name = "rls_adaptive_mpc"

    def _delay_points(self, data: DCSVInput) -> np.ndarray:
        midpoint = float(np.mean(data.delay_interval_s))
        return np.array([min(max(midpoint, 0.0), self.period_s - 1e-5)])


class ContractRobustMPC(DisturbanceCapabilitySeparatedViabilityMPC):
    method_name = "contract_robust_mpc"

    def _delay_points(self, data: DCSVInput) -> np.ndarray:
        upper = min(1.60, self.period_s - 1e-5)
        return np.array([0.20, upper])

    def _guaranteed_limits(self, data: DCSVInput) -> tuple[np.ndarray, ...]:
        return (
            np.full(2, 0.035),
            np.full(2, 0.035),
            np.full(2, 0.012),
            np.full(2, 0.012),
            np.full(2, 0.80),
        )


@dataclass(frozen=True, slots=True)
class OracleCapability:
    power_discharge_pu: np.ndarray
    power_charge_pu: np.ndarray
    ramp_up_pu_per_s: np.ndarray
    ramp_down_pu_per_s: np.ndarray
    delay_s: np.ndarray
    energy_available_mwh: np.ndarray
    availability: np.ndarray


class TrueCapabilityOracleMPC(DisturbanceCapabilitySeparatedViabilityMPC):
    """Evaluation-only upper bound; never exposed to an ordinary controller."""

    method_name = "true_capability_oracle_mpc"
    evaluation_only = True

    def control_with_evaluation_truth(self, data: DCSVInput, truth: OracleCapability):
        oracle_input = replace(
            data,
            power_discharge_guaranteed_pu=np.asarray(truth.power_discharge_pu),
            power_charge_guaranteed_pu=np.asarray(truth.power_charge_pu),
            ramp_up_guaranteed_pu_per_s=np.asarray(truth.ramp_up_pu_per_s),
            ramp_down_guaranteed_pu_per_s=np.asarray(truth.ramp_down_pu_per_s),
            delay_interval_s=np.c_[truth.delay_s, truth.delay_s],
            energy_available_guaranteed_mwh=np.asarray(truth.energy_available_mwh),
            availability_interval=np.c_[truth.availability, truth.availability],
        )
        return super().control(oracle_input)

    def control(self, data: DCSVInput):  # pragma: no cover - explicit safety boundary
        raise RuntimeError("evaluation truth must be supplied through control_with_evaluation_truth")
