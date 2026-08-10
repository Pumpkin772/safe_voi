"""Active Capability Certification and Recourse MPC."""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from direction5freq.accr.capability_identification import (
    PassiveCapabilityIdentifier,
    PassiveCapabilitySnapshot,
)
from direction5freq.accr.probing import (
    CapabilityHypothesis,
    ProbeCandidate,
    candidate_models,
    filter_models,
)
from direction5freq.controllers.dcsv_cr_mpc import DCSVCRResult, DCSVContractRecourseMPC
from direction5freq.controllers.dcsv_mpc_final import DCSVInput
from direction5freq.models.plant_a_full import PlantAParameters, PublicObservation


@dataclass(frozen=True, slots=True)
class CapabilityCertificate:
    issued_time_s: float
    expiry_time_s: float
    power_lower_pu: np.ndarray
    ramp_lower_pu_per_s: np.ndarray
    maximum_delay_s: np.ndarray
    retained_model_count: int
    source: str

    def valid_at(self, time_s: float) -> bool:
        return bool(self.issued_time_s <= time_s <= self.expiry_time_s)


@dataclass(frozen=True, slots=True)
class ACCRDiagnostics:
    probe_active: bool
    probe_triggered: bool
    certificate_valid: bool
    certificate_revoked: bool
    attempted_optimization_calls: int
    solve_time_s: float
    restoration_used: bool
    fallback_used: bool
    mathematical_infeasibility: bool
    numerical_failure: bool
    shared_current_action_verified: bool
    surplus_loss_branch_verified: bool


@dataclass(frozen=True, slots=True)
class ACCRResult:
    proposed_action_pu: np.ndarray
    contract_component_pu: np.ndarray
    certified_component_pu: np.ndarray
    probe_component_pu: np.ndarray
    guaranteed_bess_command_pu: np.ndarray
    slow_reserve_request_pu: np.ndarray
    certificate: CapabilityCertificate | None
    core_result: DCSVCRResult
    diagnostics: ACCRDiagnostics


class ActiveCapabilityCertificationRecourseMPC:
    """True rolling contract-recourse MPC with finite active certificates."""

    name = "accr_mpc"
    is_true_rolling_mpc = True
    ordinary_controller = True

    def __init__(
        self,
        period_s: float,
        horizon_steps: int,
        parameters: PlantAParameters,
        *,
        probe_amplitude_pu: float = 0.0025,
        probe_sequence: tuple[float, ...] = (0.5, 1.0, 0.0, -1.0, -0.5),
        certificate_validity_s: float = 40.0,
        trigger_minimum_bess_pu: float = 0.0,
        active_filter_residual_bound_pu: float = 0.0015,
        physical_dt_s: float = 0.05,
    ) -> None:
        self.period_s = float(period_s)
        self.parameters = parameters
        self.core = DCSVContractRecourseMPC(period_s, horizon_steps, parameters)
        self.physical_dt_s = float(physical_dt_s)
        self.identifier = PassiveCapabilityIdentifier(
            parameters.bess.contract, self.physical_dt_s
        )
        self.probe = ProbeCandidate("staircase_5", probe_amplitude_pu, np.asarray(probe_sequence))
        self.certificate_validity_s = float(certificate_validity_s)
        self.trigger_minimum_bess_pu = float(trigger_minimum_bess_pu)
        self.active_filter_residual_bound_pu = float(active_filter_residual_bound_pu)
        self.models = candidate_models({
            "power_candidates_pu": [0.045, 0.050, 0.065, 0.080],
            "ramp_candidates_pu_per_s": [0.025, 0.040, 0.060],
            "delay_candidates_s": [0.20, 0.80, 1.50],
        })
        self.latest_snapshot: PassiveCapabilitySnapshot | None = None
        self.certificate: CapabilityCertificate | None = None
        self.last_action = np.zeros(4)
        self.last_guaranteed = np.zeros(2)
        self._session: dict | None = None
        self.probe_triggers = 0
        self.certificate_issues = 0
        self.certificate_revocations = 0
        self._certificate_revoked_since_last_propose = False

    def _certificate_from_models(
        self, retained: list[CapabilityHypothesis], now_s: float, source: str
    ) -> CapabilityCertificate | None:
        if not retained:
            return None
        certificate = CapabilityCertificate(
            issued_time_s=float(now_s),
            expiry_time_s=float(now_s + self.certificate_validity_s),
            power_lower_pu=np.full(2, min(model.power_pu for model in retained)),
            ramp_lower_pu_per_s=np.full(2, min(model.ramp_pu_per_s for model in retained)),
            maximum_delay_s=np.full(2, max(model.delay_s for model in retained)),
            retained_model_count=len(retained),
            source=source,
        )
        self.certificate = certificate
        self.certificate_issues += 1
        return certificate

    def accept_public_candidate_set(
        self, retained: list[CapabilityHypothesis], now_s: float
    ) -> CapabilityCertificate | None:
        """Install an estimator-produced candidate set; no truth argument exists."""
        return self._certificate_from_models(retained, now_s, "CAUSAL_SET_MEMBERSHIP")

    def _revoke_if_needed(self, observation: PublicObservation) -> bool:
        revoked = False
        if self.certificate is not None and not self.certificate.valid_at(observation.time_s):
            self.certificate = None; revoked = True
        if (
            self.latest_snapshot is not None
            and self.latest_snapshot.candidate_set.change_reset.any()
            and self.certificate is not None
        ):
            self.certificate = None; revoked = True
        if revoked:
            self.certificate_revocations += 1
            self._certificate_revoked_since_last_propose = True
        return revoked

    def observe(self, observation: PublicObservation) -> None:
        omega = observation.frequency_deviation_hz / self.parameters.nominal_frequency_hz
        pfr = -self.parameters.bess.pfr_gain_pu_power_per_pu_frequency * omega
        requested = pfr + observation.issued_command_pu[[1, 3]]
        self.latest_snapshot = self.identifier.update(
            observation.time_s, requested, observation.bess_actual_power_pu
        )
        self._revoke_if_needed(observation)
        if self._session is None:
            return
        session = self._session
        elapsed = observation.time_s - session["start_time_s"]
        area = session["area"]
        signed_sfr_actual = session["sign"] * (
            observation.bess_actual_power_pu[area] - pfr[area]
        )
        if elapsed >= 0.0:
            session["measured"].append(float(signed_sfr_actual))
        end = len(self.probe.sequence_pu) * self.period_s + max(m.delay_s for m in self.models) + 0.5
        if elapsed + 1e-10 < end:
            return
        measured = np.asarray(session["measured"], dtype=float)
        retained = filter_models(
            self.models, measured, self.probe,
            period_s=self.period_s, dt_s=self.physical_dt_s,
            base_power_pu=abs(float(session["base_bess_pu"])),
            residual_bound_pu=self.active_filter_residual_bound_pu,
        )
        self._certificate_from_models(retained, observation.time_s, "SAFE_ACTIVE_PROBE")
        self._session = None

    def _effective_interval(self, observation: PublicObservation):
        if self.latest_snapshot is None:
            raise RuntimeError("observe must be called before propose")
        interval = self.latest_snapshot.interval_set
        if self.certificate is None or not self.certificate.valid_at(observation.time_s):
            return replace(
                interval,
                performance_power_pu=np.asarray(self.parameters.bess.contract.upper_power_pu),
                performance_ramp_pu_per_s=np.asarray(self.parameters.bess.contract.ramp_up_pu_per_s),
            )
        return replace(
            interval,
            performance_power_pu=np.maximum(
                np.asarray(self.parameters.bess.contract.upper_power_pu),
                self.certificate.power_lower_pu,
            ),
            performance_ramp_pu_per_s=np.maximum(
                np.asarray(self.parameters.bess.contract.ramp_up_pu_per_s),
                self.certificate.ramp_lower_pu_per_s,
            ),
            delay_interval_s=np.c_[np.zeros(2), self.certificate.maximum_delay_s],
        )

    def propose(self, inputs: DCSVInput) -> ACCRResult:
        observation = inputs.observation
        interval = self._effective_interval(observation)
        core_inputs = replace(inputs, deliverability_set=interval)
        core = self.core.propose(core_inputs)
        action = core.proposed_action_pu.copy()
        probe_component = np.zeros(4)
        triggered = False
        pfr = (
            -self.parameters.bess.pfr_gain_pu_power_per_pu_frequency
            * observation.frequency_deviation_hz
            / self.parameters.nominal_frequency_hz
        )

        can_trigger = bool(
            self._session is None
            and self.certificate is None
            and observation.time_s >= 60.0
            and inputs.domain.domain == "SUSTAINABLE"
            and not core.diagnostics.fallback_used
            and np.max(np.abs(core.guaranteed_bess_command_pu)) >= self.trigger_minimum_bess_pu
            and np.all((observation.measured_soc >= 0.25) & (observation.measured_soc <= 0.75))
        )
        if can_trigger:
            area = int(np.argmax(np.abs(core.guaranteed_bess_command_pu)))
            sign = 1.0 if core.guaranteed_bess_command_pu[area] >= 0.0 else -1.0
            self._session = {
                "start_time_s": observation.time_s, "area": area, "sign": sign,
                "base_bess_pu": float(core.guaranteed_bess_command_pu[area]),
                "base_guaranteed_bess_pu": float(core.guaranteed_bess_command_pu[area]),
                "measured": [float(sign * (
                    observation.bess_actual_power_pu[area] - pfr[area]
                ))],
            }
            self.probe_triggers += 1; triggered = True

        if self._session is not None:
            session = self._session
            elapsed = observation.time_s - session["start_time_s"]
            index = int(max(elapsed, 0.0) // self.period_s)
            q = 0.0
            if 0 <= index < len(self.probe.sequence_pu):
                q = float(session["sign"] * self.probe.sequence_pu[index])
            area = int(session["area"])
            sg_column, bess_column = (0, 1) if area == 0 else (2, 3)
            total = float(action[sg_column] + action[bess_column])
            action[bess_column] = float(session["base_bess_pu"] + q)
            action[sg_column] = total - action[bess_column]
            probe_component[sg_column] = -q
            probe_component[bess_column] = q

        guaranteed = core.guaranteed_bess_command_pu.copy()
        certified_component = np.zeros(4)
        certified_component[[1, 3]] = core.surplus_bess_command_pu
        if self._session is not None:
            area = int(self._session["area"])
            guaranteed[area] = float(self._session["base_guaranteed_bess_pu"])
            certified_component[1 if area == 0 else 3] = (
                float(self._session["base_bess_pu"]) - guaranteed[area]
            )
        contract_component = action - certified_component - probe_component
        if not np.allclose(
            contract_component + certified_component + probe_component,
            action,
            rtol=0.0,
            atol=1e-12,
        ):
            raise RuntimeError("ACCR command components do not reconstruct the issued action")
        revoked = self._certificate_revoked_since_last_propose
        self._certificate_revoked_since_last_propose = False
        diagnostics = ACCRDiagnostics(
            probe_active=self._session is not None,
            probe_triggered=triggered,
            certificate_valid=self.certificate is not None and self.certificate.valid_at(observation.time_s),
            certificate_revoked=revoked,
            attempted_optimization_calls=core.diagnostics.attempted_optimization_calls,
            solve_time_s=core.diagnostics.solve_time_s,
            restoration_used=core.diagnostics.restoration_used,
            fallback_used=core.diagnostics.fallback_used,
            mathematical_infeasibility=core.diagnostics.mathematical_infeasibility,
            numerical_failure=core.diagnostics.numerical_failure,
            shared_current_action_verified=core.shared_current_action_verified,
            surplus_loss_branch_verified=core.surplus_loss_branch_verified,
        )
        return ACCRResult(
            proposed_action_pu=action,
            contract_component_pu=contract_component,
            certified_component_pu=certified_component,
            probe_component_pu=probe_component,
            guaranteed_bess_command_pu=guaranteed,
            slow_reserve_request_pu=core.slow_reserve_request_pu,
            certificate=self.certificate,
            core_result=core,
            diagnostics=diagnostics,
        )

    def commit(self, result: ACCRResult, measured_actual_bess_pu: np.ndarray) -> None:
        """Commit the action actually applied, including probe and supervision."""
        self.core.commit(
            result.proposed_action_pu,
            measured_actual_bess_pu,
            result.guaranteed_bess_command_pu,
        )
        self.last_action = result.proposed_action_pu.copy()
        self.last_guaranteed = result.guaranteed_bess_command_pu.copy()


__all__ = [
    "ACCRDiagnostics", "ACCRResult", "ActiveCapabilityCertificationRecourseMPC",
    "CapabilityCertificate",
]
