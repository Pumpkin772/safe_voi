"""Conditional one-cycle surplus-loss recourse certificate."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from direction5freq.controllers.dcsv_cr_mpc import DCSVCRResult, DCSVContractRecourseMPC


@dataclass(frozen=True, slots=True)
class SurplusLossRecourseCertificate:
    period_s: float
    horizon_steps: int
    reaction_delay_s: float
    maximum_surplus_loss_pu: np.ndarray
    available_sg_recourse_pu: np.ndarray
    available_slow_reserve_recourse_pu: np.ndarray
    recourse_margin_pu: np.ndarray
    loss_branch_frequency_margin_pu: float
    loss_branch_ace_margin_pu: float
    loss_branch_tie_margin_pu: float
    certified: bool
    claim_level: str


def compute_surplus_loss_recourse_certificate(
    controller: DCSVContractRecourseMPC,
    result: DCSVCRResult,
) -> SurplusLossRecourseCertificate:
    horizon = result.predicted_surplus_bess_sequence_pu.shape[1]
    loss = result.predicted_state_sequence[1]
    maximum_loss = np.max(np.abs(result.predicted_surplus_bess_sequence_pu), axis=1)
    future_steps = max(horizon - 1, 0)
    sg_headroom = np.asarray(controller.plant.parameters.sg_power_upper_pu) - np.abs(
        result.predicted_input_sequence[1, [0, 2], 0]
    )
    available_sg = np.minimum(
        np.maximum(sg_headroom, 0.0), 0.04 * controller.period_s * future_steps
    )
    reserve_headroom = np.asarray(controller.plant.parameters.slow_reserve.upper_pu) - np.abs(
        result.predicted_slow_reserve_sequence_pu[1, :, 0]
    )
    available_reserve = np.minimum(
        np.maximum(reserve_headroom, 0.0),
        np.asarray(controller.plant.parameters.slow_reserve.ramp_up_pu_per_s)
        * controller.period_s * future_steps,
    )
    margin = available_sg + available_reserve - maximum_loss
    frequency_margin = float(0.030 - np.max(np.abs(loss[:, 0:2, 1:])))
    ace_values = np.stack([
        controller.ace_matrix @ loss[vertex] for vertex in range(loss.shape[0])
    ])
    ace_margin = float(0.45 - np.max(np.abs(ace_values[..., 1:])))
    tie_margin = float(0.12 - np.max(np.abs(loss[:, 2, 1:])))
    certified = bool(
        result.surplus_loss_branch_verified
        and result.shared_current_action_verified
        and np.all(margin >= -1e-9)
        and min(frequency_margin, ace_margin, tie_margin) >= -1e-7
        and not result.diagnostics.fallback_used
    )
    return SurplusLossRecourseCertificate(
        period_s=controller.period_s,
        horizon_steps=horizon,
        reaction_delay_s=controller.period_s,
        maximum_surplus_loss_pu=maximum_loss,
        available_sg_recourse_pu=available_sg,
        available_slow_reserve_recourse_pu=available_reserve,
        recourse_margin_pu=margin,
        loss_branch_frequency_margin_pu=frequency_margin,
        loss_branch_ace_margin_pu=ace_margin,
        loss_branch_tie_margin_pu=tie_margin,
        certified=certified,
        claim_level=(
            "CONDITIONAL_ONE_CYCLE_SURPLUS_LOSS_RECOURSE"
            if certified else "NO_SURPLUS_LOSS_RECOURSE_CERTIFICATE"
        ),
    )


__all__ = [
    "SurplusLossRecourseCertificate",
    "compute_surplus_loss_recourse_certificate",
]
