"""Selected Phase-E branch R: capability-set robust tube MPC."""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from direction1freq.controllers.ace_pi_aw import ACEPIAntiWindup, design_stable_pi
from direction1freq.controllers.nominal_mpc import FiniteHorizonMPC, MPCDiagnostics
from direction1freq.models.plant_a_v2 import PublicObservationV2, TwoAreaPlantAV2
from direction1freq.optimization.terminal_backup import SGTerminalBackupSet
from direction1freq.optimization.tube_propagation import (
    ReachableTubeCertificate, finite_horizon_reachable_tube,
)


@dataclass(frozen=True, slots=True)
class RobustTubeMPCDiagnostics:
    mpc: MPCDiagnostics
    tube_spectral_radius: float
    maximum_frequency_tightening_hz: float
    maximum_input_tightening_pu: float
    terminal_backup_predicted: bool
    used_fallback: bool
    fallback_reason: str

    @property
    def solved(self) -> bool:
        return self.mpc.solved and not self.used_fallback

    @property
    def solver_status(self) -> str:
        return self.mpc.solver_status

    @property
    def primal_residual(self) -> float:
        return self.mpc.primal_residual

    @property
    def dual_residual(self) -> float:
        return self.mpc.dual_residual

    @property
    def solve_time_s(self) -> float:
        return self.mpc.solve_time_s

    @property
    def iterations(self) -> int:
        return self.mpc.iterations


class CapabilitySetRobustTubeMPC:
    """No-label branch-R controller over the preregistered global set."""

    # Phase E used ``optimizer.solve`` here.  F2 replaces that eager-commit
    # call with propose/select/commit while retaining this frozen audit marker.

    selected_branch = "R"

    def __init__(self, period_s: float = 4.0, horizon: int = 5) -> None:
        self.period_s = float(period_s)
        self.horizon = int(horizon)
        probe = FiniteHorizonMPC(period_s, horizon)
        self.tube: ReachableTubeCertificate = finite_horizon_reachable_tube(
            probe.ad, probe.bd, horizon
        )
        frequency_margin = min(0.12, 50.0 * float(np.max(self.tube.state_radii[:2])))
        ace_margin = min(0.04, float(np.max(np.abs(probe.c_ace) @ self.tube.state_radii)))
        tie_margin = min(0.03, float(np.max(self.tube.state_radii[2])))
        self.optimizer = FiniteHorizonMPC(
            period_s, horizon, nominal_delay_s=min(2.0, period_s - 1e-6),
            # Total BESS PFR+SFR is constrained robustly at every action.  The
            # measured actuator state may begin outside the componentwise
            # intersection of mutually exclusive capability vertices and
            # cannot be projected instantaneously; do not create a false QP
            # infeasibility by imposing that intersection on x_b.
            reference_weight=8.0, resource_constraint_start_stage=horizon + 1,
            frequency_limit_hz=0.80 - frequency_margin,
            ace_limit_pu=0.30 - ace_margin, tie_limit_pu=0.15 - tie_margin,
            secondary_solver="CLARABEL",
        )
        kp, ki, _ = design_stable_pi(TwoAreaPlantAV2(), period_s)
        self.reference = ACEPIAntiWindup(period_s, kp, ki, sg_fraction=0.70)
        self.backup = ACEPIAntiWindup(period_s, kp, ki, sg_fraction=1.0)
        self.terminal_set = SGTerminalBackupSet()
        self.certified_bess_limit = 0.030
        self.certified_bess_ramp_pu_s = 0.012
        self.maximum_frequency_tightening_hz = frequency_margin
        self.maximum_input_tightening_pu = float(np.max(self.tube.input_radii))
        self._consecutive_backup_count = 0

    def reset(self) -> None:
        self.optimizer.reset(); self.reference.reset(); self.backup.reset()
        self._consecutive_backup_count = 0

    def update(
        self, observation: PublicObservationV2, estimated_state: np.ndarray,
        causal_load_estimate: np.ndarray, sg_reserve_pu: float,
        force_solver_failure: bool = False,
    ) -> tuple[np.ndarray, RobustTubeMPCDiagnostics]:
        reference, _ = self.reference.update(observation)
        reference[[0, 2]] = np.clip(reference[[0, 2]], -sg_reserve_pu, sg_reserve_pu)
        input_margin = np.max(self.tube.input_radii, axis=1)
        sg_limit = max(0.005, sg_reserve_pu - max(input_margin[0], input_margin[2]))
        bess_limit = max(0.005, self.certified_bess_limit - max(input_margin[1], input_margin[3]))
        lower = np.array([-sg_limit, -bess_limit, -sg_limit, -bess_limit])
        upper = -lower
        action, diagnostic = self.optimizer.propose(
            estimated_state, causal_load_estimate, lower, upper,
            np.array([-bess_limit, -bess_limit]), np.array([bess_limit, bess_limit]),
            np.array([
                min(0.04, 2.0 * sg_limit),
                min(self.certified_bess_ramp_pu_s * self.period_s, 2.0 * bess_limit),
                min(0.04, 2.0 * sg_limit),
                min(self.certified_bess_ramp_pu_s * self.period_s, 2.0 * bess_limit),
            ]),
            delay_s=self.optimizer.nominal_delay_s, action_reference=reference,
        )
        if force_solver_failure:
            diagnostic = replace(
                diagnostic, solved=False, solver_status="forced_timeout_test",
                fallback_reason="forced_timeout_test",
            )
        terminal_ok = bool(
            diagnostic.solved
            and self.terminal_set.contains(
                diagnostic.predicted_states[:, -1], self.optimizer.c_ace
            )
        )
        used_fallback = bool(not diagnostic.solved or not terminal_ok)
        reason = diagnostic.fallback_reason
        if diagnostic.solved and not terminal_ok:
            reason = "predicted_terminal_outside_sg_backup_set"
        if used_fallback:
            action, _ = self.backup.update(observation)
            action[[0, 2]] = np.clip(action[[0, 2]], -sg_reserve_pu, sg_reserve_pu)
            action[[1, 3]] = 0.0
        self.optimizer.commit_applied_action(action)
        self._consecutive_backup_count = (
            self._consecutive_backup_count + 1 if used_fallback else 0
        )
        diagnostic = replace(
            diagnostic,
            terminal_reject=bool(diagnostic.solved and not terminal_ok),
            backup_used=used_fallback,
            applied_action_pu=action.copy(),
            history_match=bool(
                np.allclose(
                    diagnostic.previous_applied_action,
                    diagnostic.previous_model_action,
                    atol=1e-12,
                )
            ),
            consecutive_backup_count=self._consecutive_backup_count,
        )
        return action, RobustTubeMPCDiagnostics(
            diagnostic, self.tube.closed_loop_spectral_radius,
            self.maximum_frequency_tightening_hz, self.maximum_input_tightening_pu,
            terminal_ok, used_fallback, reason,
        )
