"""Recomputation of DCSV-CR finite-horizon contract-branch constraints."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from direction5freq.controllers.dcsv_cr_mpc import DCSVCRResult, DCSVContractRecourseMPC
from direction5freq.controllers.dcsv_mpc_final import DCSVInput


@dataclass(frozen=True, slots=True)
class ContractBranchCertificate:
    period_s: float
    horizon_steps: int
    dense_delay_points: int
    maximum_guaranteed_power_violation_pu: float
    maximum_guaranteed_ramp_violation_pu: float
    maximum_physical_power_violation_pu: float
    maximum_physical_ramp_violation_pu: float
    maximum_energy_violation_mwh: float
    maximum_frequency_violation_pu: float
    maximum_ace_violation_pu: float
    maximum_tie_violation_pu: float
    contract_containment_assumed: bool
    registered_model_error_assumed: bool
    measured_soc_assumed_correct: bool
    finite_horizon_certified: bool
    claim_level: str


def _delayed(
    sequence: np.ndarray,
    step: int,
    delay_s: float,
    period_s: float,
    area: int,
    history: list[np.ndarray],
) -> float:
    delay_steps = max(delay_s / period_s, 0.0)
    whole = int(np.floor(delay_steps))
    fraction = delay_steps - whole

    def sample(index: int) -> float:
        if index >= 0:
            return float(sequence[area, index])
        return float(history[max(-len(history), index)][area])

    newest = step - whole
    return (1.0 - fraction) * sample(newest) + fraction * sample(newest - 1)


def compute_contract_branch_certificate(
    controller: DCSVContractRecourseMPC,
    inputs: DCSVInput,
    result: DCSVCRResult,
    *,
    dense_delay_points: int = 31,
    contract_containment_assumed: bool = True,
    registered_model_error_assumed: bool = True,
    measured_soc_assumed_correct: bool = True,
) -> ContractBranchCertificate:
    """Replay every branch over a dense registered delay grid.

    This certificate is deliberately conditional.  It verifies the exact
    finite optimized sequence and does not promote that check to global or
    native-DAE recursive feasibility.
    """

    guaranteed = np.asarray(result.predicted_guaranteed_bess_sequence_pu)
    surplus = np.asarray(result.predicted_surplus_bess_sequence_pu)
    horizon = guaranteed.shape[1]
    contract = controller.contract
    upper = np.asarray(contract.upper_power_pu)[:, None]
    lower = np.asarray(contract.lower_power_pu)[:, None]
    power_violation = max(
        float(np.max(guaranteed - upper)), float(np.max(lower - guaranteed)), 0.0
    )
    previous_g = np.asarray(controller._guaranteed_history[-1])
    ramp_up = np.asarray(contract.ramp_up_pu_per_s)
    ramp_down = np.asarray(contract.ramp_down_pu_per_s)
    ramp_violation = 0.0
    for k in range(horizon):
        prior = previous_g if k == 0 else guaranteed[:, k - 1]
        ramp_violation = max(
            ramp_violation,
            float(np.max(guaranteed[:, k] - prior - ramp_up * controller.period_s)),
            float(np.max(prior - guaranteed[:, k] - ramp_down * controller.period_s)),
        )

    x0 = controller._state_from_observation(inputs.observation)
    energy0 = inputs.observation.measured_soc * controller.plant.parameters.bess.energy_mwh
    g_history = list(controller._guaranteed_history)
    s_history = list(controller._surplus_history)
    maximum = {
        "physical_power": 0.0,
        "physical_ramp": 0.0,
        "energy": 0.0,
        "frequency": 0.0,
        "ace": 0.0,
        "tie": 0.0,
    }
    delay_grid = np.linspace(0.0, max(contract.maximum_delay_s), dense_delay_points)
    rating = controller.plant.parameters.bess.rating_pu
    e_min = controller.plant.parameters.bess.soc_min * controller.plant.parameters.bess.energy_mwh
    e_max = controller.plant.parameters.bess.soc_max * controller.plant.parameters.bess.energy_mwh
    energy_factor = controller.period_s * controller.plant.parameters.system_base_mva / 3600.0
    for branch_index, branch in enumerate(controller.tree.branches):
        for delay_s in delay_grid:
            state = x0.copy()
            stored_energy = energy0.copy()
            previous_pb = np.asarray(inputs.observation.bess_actual_power_pu).copy()
            for k in range(horizon):
                delivered_g = np.array([
                    _delayed(guaranteed, k, float(delay_s), controller.period_s, area, g_history)
                    for area in range(2)
                ])
                delivered_s = np.array([
                    _delayed(
                        surplus,
                        k,
                        float(delay_s + branch.extra_surplus_delay_s),
                        controller.period_s,
                        area,
                        s_history,
                    ) for area in range(2)
                ])
                actual_bess = delivered_g + branch.surplus_delivery_fraction * delivered_s
                sg = result.predicted_input_sequence[branch_index, [0, 2], k]
                effective = np.array((sg[0], actual_bess[0], sg[1], actual_bess[1]))
                reserve = result.predicted_slow_reserve_sequence_pu[branch_index, :, k]
                state = (
                    controller.ad @ state + controller.bd @ effective
                    + controller.ed @ inputs.load_estimate_pu + controller.rd @ reserve
                )
                pb = state[7:9]
                maximum["physical_power"] = max(
                    maximum["physical_power"], float(np.max(np.abs(pb) - rating))
                )
                maximum["physical_ramp"] = max(
                    maximum["physical_ramp"],
                    float(np.max(np.abs(pb - previous_pb) - 0.10 * controller.period_s)),
                )
                stored_energy += np.where(
                    pb >= 0.0,
                    -energy_factor * pb / controller.plant.parameters.bess.eta_discharge,
                    -energy_factor * pb * controller.plant.parameters.bess.eta_charge,
                )
                maximum["energy"] = max(
                    maximum["energy"],
                    float(np.max(e_min - stored_energy)),
                    float(np.max(stored_energy - e_max)),
                )
                maximum["frequency"] = max(
                    maximum["frequency"], float(np.max(np.abs(state[0:2]) - 0.030))
                )
                maximum["ace"] = max(
                    maximum["ace"],
                    float(np.max(np.abs(controller.ace_matrix @ state) - 0.45)),
                )
                maximum["tie"] = max(
                    maximum["tie"], float(abs(state[2]) - 0.12)
                )
                previous_pb = pb.copy()
    maximum = {name: max(value, 0.0) for name, value in maximum.items()}
    assumptions = (
        contract_containment_assumed
        and registered_model_error_assumed
        and measured_soc_assumed_correct
    )
    certified = bool(
        assumptions
        and max(power_violation, ramp_violation, *maximum.values()) <= 1e-6
        and result.surplus_loss_branch_verified
        and result.shared_current_action_verified
        and not result.diagnostics.fallback_used
    )
    return ContractBranchCertificate(
        period_s=controller.period_s,
        horizon_steps=horizon,
        dense_delay_points=int(dense_delay_points),
        maximum_guaranteed_power_violation_pu=max(power_violation, 0.0),
        maximum_guaranteed_ramp_violation_pu=max(ramp_violation, 0.0),
        maximum_physical_power_violation_pu=maximum["physical_power"],
        maximum_physical_ramp_violation_pu=maximum["physical_ramp"],
        maximum_energy_violation_mwh=maximum["energy"],
        maximum_frequency_violation_pu=maximum["frequency"],
        maximum_ace_violation_pu=maximum["ace"],
        maximum_tie_violation_pu=maximum["tie"],
        contract_containment_assumed=contract_containment_assumed,
        registered_model_error_assumed=registered_model_error_assumed,
        measured_soc_assumed_correct=measured_soc_assumed_correct,
        finite_horizon_certified=certified,
        claim_level=(
            "CONDITIONAL_FINITE_HORIZON_CONTRACT_BRANCH"
            if certified else "NO_CONTRACT_BRANCH_CERTIFICATE"
        ),
    )


__all__ = ["ContractBranchCertificate", "compute_contract_branch_certificate"]
