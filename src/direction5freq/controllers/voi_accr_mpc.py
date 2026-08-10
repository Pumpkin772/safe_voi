"""Direction5 VOI-ACCR-MPC selected at the M1 integrated prototype Gate.

The controller wraps the frozen contract rolling MPC, applies probes around
that MPC's current allocation, and never receives evaluation-side capability
or load truth.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import inspect
import textwrap
from types import SimpleNamespace

import numpy as np

from direction5freq.accr.accr_mpc import (
    ACCRDiagnostics,
    ACCRResult,
    ActiveCapabilityCertificationRecourseMPC,
    CapabilityCertificate,
)
from direction5freq.accr.capability_identification import PassiveCapabilityIdentifier
from direction5freq.accr.probing import CapabilityHypothesis, ProbeCandidate
from direction5freq.controllers.contract_robust_mpc import ContractOnlyRollingRobustMPC
from direction5freq.controllers import dcsv_mpc_final as dcsv_module
from direction5freq.models.capability_contract import CapabilityContract


@dataclass(frozen=True, slots=True)
class VOIProbeDecision:
    worthwhile: bool
    decision_relevance_pu: float
    oracle_gap_proxy: float
    gross_value: float
    predicted_probe_cost: float
    net_value: float
    candidate_count: int
    predicted_diameter_reduction: float
    reason: str


def weighted_contract_mpc_class(
    *, ace_weight: float, tie_weight: float, frequency_weight: float,
    bess_effort_weight: float, sg_effort_weight: float,
):
    """Build a development-only weighted copy of the audited rolling QP."""
    source = textwrap.dedent(
        inspect.getsource(dcsv_module.DisturbanceCapabilitySeparatedViabilityMPC._solve)
    )
    source = source.replace(
        "objective += 30.0 * cp.sum_squares(ace) + 12.0 * cp.sum_squares(x[vertex][0:2, k])",
        f"objective += {float(ace_weight)!r} * cp.sum_squares(ace) + "
        f"{float(frequency_weight)!r} * cp.sum_squares(x[vertex][0:2, k]) + "
        f"{float(tie_weight)!r} * cp.square(x[vertex][2, k])",
    )
    source = source.replace(
        "objective += 0.05 * cp.sum_squares(u) + 0.20 * cp.sum_squares(u[:, 1:] - u[:, :-1])",
        f"objective += {float(sg_effort_weight)!r} * cp.sum_squares(u[[0, 2], :]) + "
        f"{float(bess_effort_weight)!r} * cp.sum_squares(u[[1, 3], :]) + "
        "0.20 * cp.sum_squares(u[:, 1:] - u[:, :-1])",
    )
    source = source.replace(
        "objective += 0.035 * cp.sum_squares(u[[1, 3], :])",
        "objective += 0.0 * cp.sum_squares(u[[1, 3], :])",
    )
    namespace: dict = {}
    exec(source, vars(dcsv_module), namespace)

    class WeightedContractMPC(ContractOnlyRollingRobustMPC):
        _solve = namespace["_solve"]

    return WeightedContractMPC


class VOIActiveCapabilityCertificationRecourseMPC(
    ActiveCapabilityCertificationRecourseMPC
):
    """Contract-equivalent abstention plus one active probe per change epoch."""

    name = "voi_accr_mpc"

    def __init__(
        self,
        period_s: float,
        horizon_steps: int,
        parameters,
        *,
        probe_id: str = "biphasic_2",
        probe_amplitude_pu: float = 0.0025,
        probe_sequence: tuple[float, ...] = (1.0, -1.0),
        certificate_validity_s: float = 40.0,
        cooldown_s: float = 60.0,
        voi_margin: float = 0.0025,
        action_relevance_norm: float = 0.0025,
        minimum_oracle_gap: float = 0.01,
        minimum_ace_for_probe: float = 0.0,
        estimator_window_s: float = 24.0,
        active_filter_residual_bound_pu: float = 0.0015,
        passive_renewal: bool = False,
        physical_dt_s: float = 0.05,
        delivered_branch_weight: float = 0.05,
        ace_weight: float = 35.0,
        tie_weight: float = 10.0,
        frequency_weight: float = 15.0,
        bess_effort_weight: float = 0.001,
        sg_effort_weight: float = 0.10,
        trigger_time_s: float = 60.0,
        certificate_confirmation_s: float | None = None,
        latch_abstention: bool = False,
    ) -> None:
        super().__init__(
            period_s,
            horizon_steps,
            parameters,
            probe_amplitude_pu=probe_amplitude_pu,
            probe_sequence=probe_sequence,
            certificate_validity_s=certificate_validity_s,
            active_filter_residual_bound_pu=active_filter_residual_bound_pu,
            physical_dt_s=physical_dt_s,
            probe_base_bess_pu=None,
            probe_preload_s=0.0,
            delivered_branch_weight=delivered_branch_weight,
        )
        self.probe = ProbeCandidate(
            probe_id, float(probe_amplitude_pu), np.asarray(probe_sequence, dtype=float)
        )
        self.identifier = PassiveCapabilityIdentifier(
            parameters.bess.contract,
            self.physical_dt_s,
            window_s=float(estimator_window_s),
            residual_bound_pu=float(active_filter_residual_bound_pu),
        )
        self.models = [
            CapabilityHypothesis(float(power), float(ramp), float(delay))
            for power in (0.045, 0.050, 0.065, 0.080)
            for ramp in (0.025, 0.040, 0.055, 0.060)
            for delay in (0.20, 0.80, 1.50)
        ]
        self.retained_models = list(self.models)
        # The registered contract remains the hard fallback.  A finite active
        # certificate temporarily replaces the rolling MPC capability set;
        # unlike the withdrawn DCSV-CR integration, it is not simultaneously
        # assumed to disappear inside every prediction horizon.
        self.registered_contract = parameters.bess.contract
        weighted_class = weighted_contract_mpc_class(
            ace_weight=ace_weight,
            tie_weight=tie_weight,
            frequency_weight=frequency_weight,
            bess_effort_weight=bess_effort_weight,
            sg_effort_weight=sg_effort_weight,
        )
        self.core = weighted_class(
            period_s, horizon_steps, parameters
        )
        self.cooldown_s = float(cooldown_s)
        self.passive_renewal_enabled = bool(passive_renewal)
        self.passive_renewals = 0
        self.voi_margin = float(voi_margin)
        self.action_relevance_norm = float(action_relevance_norm)
        self.minimum_oracle_gap = float(minimum_oracle_gap)
        self.minimum_ace_for_probe = float(minimum_ace_for_probe)
        self.trigger_time_s = float(trigger_time_s)
        self.change_epoch = 0
        self.probed_epoch = -1
        self.last_probe_end_s = -np.inf
        self.last_decision = VOIProbeDecision(
            False, 0.0, 0.0, 0.0, 0.0, 0.0, len(self.models), 0.0, "NOT_EVALUATED"
        )
        self.decision_calls = 0
        self.worthwhile_calls = 0
        self.abstention_calls = 0
        self._last_reset_s = -np.inf
        self._command_history: list[tuple[float, np.ndarray, np.ndarray]] = []
        self._models_before_probe = len(self.models)
        self.candidate_diameter_reduction = 0.0
        self.candidate_diameter_reductions: list[float] = []
        self.passive_candidate_reductions: list[float] = []
        self._demand_active_since_s: float | None = None
        self._abstain_until_demand_clears = False
        self.latch_abstention = bool(latch_abstention)
        self._last_voi_solver_attempts = 0
        self._last_voi_solve_time_s = 0.0
        self.maximum_unmetered_responsibility_jump_pu = 0.0
        self.probe_aborts_on_change = 0
        self._pending_session: dict | None = None
        self.certificate_confirmation_s = (
            self.period_s + max(model.delay_s for model in self.models)
            if certificate_confirmation_s is None
            else max(0.0, float(certificate_confirmation_s))
        )

    def _contract_interval(self):
        if self.latest_snapshot is None:
            raise RuntimeError("observe must be called before propose")
        interval = self.latest_snapshot.interval_set
        contract = self.parameters.bess.contract
        return replace(
            interval,
            performance_power_pu=np.asarray(contract.upper_power_pu, dtype=float),
            performance_ramp_pu_per_s=np.asarray(
                contract.ramp_up_pu_per_s, dtype=float
            ),
            delay_interval_s=np.c_[
                np.zeros(2), np.asarray(contract.maximum_delay_s, dtype=float)
            ],
        )

    def _effective_interval(self, observation):
        interval = self._contract_interval()
        if self.certificate is None or not self.certificate.valid_at(observation.time_s):
            return interval
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

    @staticmethod
    def _diameter(models: list[CapabilityHypothesis]) -> float:
        """Registered A3 normalized diameter (power/ramp/delay = .30/.20/.50)."""
        if len(models) <= 1:
            return 0.0
        power = np.ptp([model.power_pu for model in models]) / 0.035
        ramp = np.ptp([model.ramp_pu_per_s for model in models]) / 0.035
        delay = np.ptp([model.delay_s for model in models]) / 1.30
        return float(0.30 * power + 0.20 * ramp + 0.50 * delay)

    def _predicted_partition_reduction(self, base_power_pu: float) -> float:
        """Conservative output-cluster reduction before a probe is issued."""
        probe = self.probe
        duration = len(probe.sequence_pu) * self.period_s + 1.75
        sample_time = np.arange(0.0, duration + self.physical_dt_s / 2, self.physical_dt_s)
        signatures = []
        for model in self.retained_models:
            power = float(base_power_pu)
            trace = []
            for time_s in sample_time:
                delayed_t = time_s - model.delay_s
                index = int(delayed_t // self.period_s) if delayed_t >= 0.0 else -1
                q = (
                    float(probe.sequence_pu[index])
                    if 0 <= index < len(probe.sequence_pu)
                    else 0.0
                )
                target = float(np.clip(base_power_pu + q, -model.power_pu, model.power_pu))
                rate = float(
                    np.clip(
                        (target - power) / 0.15,
                        -model.ramp_pu_per_s,
                        model.ramp_pu_per_s,
                    )
                )
                power += self.physical_dt_s * rate
                trace.append(power)
            signatures.append(np.asarray(trace))
        if not signatures:
            return 0.0
        parent = self._diameter(self.retained_models)
        if parent <= 0.0:
            return 0.0
        # Build connected output-overlap components under twice the residual
        # radius.  The largest child is the worst possible posterior partition.
        count = len(signatures)
        adjacency = np.eye(count, dtype=bool)
        tolerance = 2.0 * self.active_filter_residual_bound_pu
        for i in range(count):
            for j in range(i + 1, count):
                if float(np.max(np.abs(signatures[i] - signatures[j]))) <= tolerance:
                    adjacency[i, j] = adjacency[j, i] = True
        unseen = set(range(count))
        children: list[list[CapabilityHypothesis]] = []
        while unseen:
            stack = [unseen.pop()]
            component = []
            while stack:
                node = stack.pop(); component.append(node)
                linked = {other for other in unseen if adjacency[node, other]}
                unseen -= linked; stack.extend(linked)
            children.append([self.retained_models[index] for index in component])
        worst = max(self._diameter(child) for child in children)
        return float(np.clip(1.0 - worst / parent, 0.0, 1.0))

    def _apply_causal_passive_filter(self) -> None:
        """Intersect hypotheses only with currently witnessed causal evidence."""
        if self.latest_snapshot is None or self._session is not None:
            return
        candidate = self.latest_snapshot.candidate_set
        excited = np.asarray(candidate.excitation_sufficient, dtype=bool)
        if not bool(np.any(excited)):
            return
        power_floor = float(np.max(candidate.performance_power_pu[excited]))
        ramp_floor = float(np.max(candidate.performance_ramp_pu_per_s[excited]))
        delay_low = float(np.max(candidate.delay_interval_s[excited, 0]))
        delay_high = float(np.min(candidate.delay_interval_s[excited, 1]))
        retained = [
            model for model in self.retained_models
            if model.power_pu + 1e-12 >= power_floor
            and model.ramp_pu_per_s + 1e-12 >= ramp_floor
            and model.delay_s + 1e-12 >= delay_low
            and model.delay_s <= delay_high + 1e-12
        ]
        if retained and len(retained) < len(self.retained_models):
            before = self._diameter(self.retained_models)
            after = self._diameter(retained)
            self.passive_candidate_reductions.append(
                0.0 if before <= 0.0 else float(np.clip(1.0 - after / before, 0.0, 1.0))
            )
            self.retained_models = retained

    def _candidate_action_relevance(self, inputs, base_action: np.ndarray) -> float:
        """Solve representative candidate MPCs using causal public state only."""
        totals = np.asarray((
            base_action[0] + base_action[1], base_action[2] + base_action[3]
        ))
        if float(np.max(np.abs(totals))) < 0.025:
            self._last_voi_solver_attempts = 0
            self._last_voi_solve_time_s = 0.0
            return 0.0
        powers = [min(model.power_pu for model in self.retained_models),
                  max(model.power_pu for model in self.retained_models)]
        ramps = [min(model.ramp_pu_per_s for model in self.retained_models),
                 max(model.ramp_pu_per_s for model in self.retained_models)]
        delays = [min(model.delay_s for model in self.retained_models),
                  max(model.delay_s for model in self.retained_models)]
        representatives = (
            (powers[0], ramps[0], delays[1]),
            (powers[1], ramps[0], delays[0]),
            (powers[0], ramps[1], delays[0]),
            (powers[1], ramps[1], delays[0]),
        )
        original_contract = self.core.contract
        original_bridge = self.core._bridge_remaining_s
        actions = []
        attempts = 0
        solve_time = 0.0
        try:
            for power, ramp, delay in representatives:
                self.core._bridge_remaining_s = original_bridge
                self.core.contract = CapabilityContract(
                    lower_power_pu=(-power, -power),
                    upper_power_pu=(power, power),
                    ramp_down_pu_per_s=(ramp, ramp),
                    ramp_up_pu_per_s=(ramp, ramp),
                    maximum_delay_s=(delay, delay),
                )
                candidate = self.core.propose(inputs)
                attempts += 2 if (
                    candidate.diagnostics.restoration_used
                    or candidate.diagnostics.fallback_used
                ) else 1
                solve_time += float(candidate.diagnostics.solve_time_s)
                if not candidate.diagnostics.fallback_used:
                    actions.append(candidate.proposed_action_pu)
        finally:
            self.core.contract = original_contract
            self.core._bridge_remaining_s = original_bridge
        self._last_voi_solver_attempts = attempts
        self._last_voi_solve_time_s = solve_time
        if not actions:
            return 0.0
        return float(max(np.linalg.norm(action - base_action) for action in actions))

    def _voi_decision(self, inputs, core) -> VOIProbeDecision:
        observation = inputs.observation
        totals = np.asarray((
            core.proposed_action_pu[0] + core.proposed_action_pu[1],
            core.proposed_action_pu[2] + core.proposed_action_pu[3],
        ))
        demand = float(np.max(np.abs(totals)))
        if demand < 0.025:
            self._abstain_until_demand_clears = False
        inactive_reason = None
        if self._session is not None:
            inactive_reason = "ACTIVE_PROBE_IN_PROGRESS"
        elif self._pending_session is not None:
            inactive_reason = "PENDING_CERTIFICATE_CONFIRMATION"
        elif self.certificate is not None and self.certificate.valid_at(observation.time_s):
            inactive_reason = "CERTIFICATE_VALID"
        elif self.probed_epoch >= self.change_epoch:
            inactive_reason = "ALREADY_PROBED_THIS_CHANGE_EPOCH"
        elif observation.time_s < self.trigger_time_s:
            inactive_reason = "OBSERVER_WARMUP"
        elif inputs.domain.domain != "SUSTAINABLE":
            inactive_reason = "DOMAIN_NOT_SUSTAINABLE"
        elif observation.time_s - self._last_reset_s < self.cooldown_s:
            inactive_reason = "CHANGE_RESET_COOLDOWN"
        elif (
            self.latch_abstention
            and self._abstain_until_demand_clears
            and demand >= 0.025
        ):
            inactive_reason = "ABSTAINED_FOR_CURRENT_DEMAND_EPISODE"
        elif core.diagnostics.fallback_used:
            inactive_reason = "CORE_FALLBACK_ACTIVE"
        elif core.diagnostics.mathematical_infeasibility:
            inactive_reason = "CORE_MATHEMATICALLY_INFEASIBLE"
        elif core.diagnostics.numerical_failure:
            inactive_reason = "CORE_NUMERICAL_FAILURE"
        elif not np.all(
            (observation.measured_soc >= 0.25)
            & (observation.measured_soc <= 0.75)
        ):
            inactive_reason = "SOC_PROBE_MARGIN_UNAVAILABLE"
        if inactive_reason is not None:
            self._last_voi_solver_attempts = 0
            self._last_voi_solve_time_s = 0.0
            return VOIProbeDecision(
                False, 0.0, 0.0, 0.0, 0.0, 0.0,
                len(self.retained_models), 0.0, inactive_reason,
            )
        contract_power = float(self.parameters.bess.contract.upper_power_pu[0])
        area = int(np.argmax(np.abs(totals)))
        base = float(core.proposed_action_pu[1 if area == 0 else 3])
        demand = abs(float(totals[area]))
        sg_column, bess_column = (0, 1) if area == 0 else (2, 3)
        q_low = max(
            float(core.proposed_action_pu[sg_column] - self.parameters.valve_upper_pu[area]),
            float(-self.parameters.bess.rating_pu - core.proposed_action_pu[bess_column]),
        )
        q_high = min(
            float(core.proposed_action_pu[sg_column] - self.parameters.valve_lower_pu[area]),
            float(self.parameters.bess.rating_pu - core.proposed_action_pu[bess_column]),
        )
        required_probe_margin = float(np.max(np.abs(self.probe.sequence_pu)))
        if q_low > -required_probe_margin + 1e-12 or q_high < required_probe_margin - 1e-12:
            self._last_voi_solver_attempts = 0
            self._last_voi_solve_time_s = 0.0
            return VOIProbeDecision(
                False, 0.0, 0.0, 0.0, 0.0, 0.0,
                len(self.retained_models), 0.0, "INSUFFICIENT_ALLOCATION_MARGIN",
            )
        relevance = self._candidate_action_relevance(inputs, core.proposed_action_pu)
        oracle_gap_proxy = float(relevance / max(demand, contract_power, 1e-9))
        partition_reduction = self._predicted_partition_reduction(base)
        ace_level = float(np.sum(np.abs(observation.ace_pu)))
        gross = float(
            relevance
            * self.certificate_validity_s
            * (0.5 + 4.0 * ace_level)
            * partition_reduction
        )
        probe_l1 = float(np.sum(np.abs(self.probe.sequence_pu))) * self.period_s
        predicted_cost = float(probe_l1 * (0.25 + 4.0 * ace_level))
        net = gross - predicted_cost
        if relevance < self.action_relevance_norm:
            reason = "NOT_DECISION_RELEVANT"
        elif oracle_gap_proxy < self.minimum_oracle_gap:
            reason = "ORACLE_GAP_PROXY_TOO_SMALL"
        elif partition_reduction < 0.25:
            reason = "CANDIDATES_NOT_DISTINGUISHABLE"
        elif ace_level < self.minimum_ace_for_probe:
            reason = "INSUFFICIENT_CONTROL_BURDEN"
        elif net <= self.voi_margin:
            reason = "NONPOSITIVE_NET_VOI"
        else:
            reason = "POSITIVE_NET_VOI"
        return VOIProbeDecision(
            reason == "POSITIVE_NET_VOI",
            relevance,
            oracle_gap_proxy,
            gross,
            predicted_cost,
            net,
            len(self.retained_models),
            partition_reduction,
            reason,
        )

    def _simulate_trace(self, model: CapabilityHypothesis, session: dict) -> np.ndarray:
        time = np.asarray(session["time"], dtype=float)
        command = np.asarray(session["sfr"], dtype=float)
        pfr = np.asarray(session["pfr"], dtype=float)
        measured = np.asarray(session["actual"], dtype=float)
        area = int(session["area"])
        predicted = np.empty(len(time), dtype=float)
        power = float(measured[0, area])
        predicted[0] = power
        for index in range(1, len(time)):
            delayed = float(
                np.interp(
                    time[index] - model.delay_s,
                    time,
                    command[:, area],
                    left=command[0, area],
                    right=command[-1, area],
                )
            )
            target = float(np.clip(pfr[index, area] + delayed, -model.power_pu, model.power_pu))
            dt_s = float(time[index] - time[index - 1])
            rate = float(
                np.clip(
                    (target - power) / 0.15,
                    -model.ramp_pu_per_s,
                    model.ramp_pu_per_s,
                )
            )
            power += dt_s * rate
            power = min(power, target) if target >= predicted[index - 1] else max(power, target)
            predicted[index] = power
        return predicted

    def _finish_probe(self, observation) -> None:
        session = self._session
        if session is None or len(session["time"]) < 2:
            return
        self._pending_session = session
        self._pending_session["confirmation_time_s"] = float(
            observation.time_s + self.certificate_confirmation_s
        )
        self._session = None
        self.last_probe_end_s = float(observation.time_s)
        if self.certificate_confirmation_s <= 1e-12:
            self._finalize_pending_certificate(observation)

    def _finalize_pending_certificate(self, observation) -> None:
        session = self._pending_session
        if session is None or len(session["time"]) < 2:
            return
        measured = np.asarray(session["actual"], dtype=float)[:, int(session["area"])]
        retained = []
        models_before = list(session["models_before"])
        for model in models_before:
            predicted = self._simulate_trace(model, session)
            # Skip the first actuator transient and retain an outer residual
            # radius.  Empty posteriors are never promoted to certificates.
            skip = max(1, int(round(0.25 / self.physical_dt_s)))
            residual = float(np.max(np.abs(predicted[skip:] - measured[skip:])))
            if residual <= self.active_filter_residual_bound_pu:
                retained.append(model)
        before = self._diameter(models_before)
        after = self._diameter(retained)
        self.candidate_diameter_reduction = (
            0.0 if before <= 0.0 or not retained
            else float(np.clip(1.0 - after / before, 0.0, 1.0))
        )
        self.candidate_diameter_reductions.append(self.candidate_diameter_reduction)
        if retained:
            self.retained_models = retained
            self._certificate_from_models(retained, observation.time_s, "SAFE_ACTIVE_VOI_PROBE")
        self._pending_session = None

    def observe(self, observation) -> None:
        omega = observation.frequency_deviation_hz / self.parameters.nominal_frequency_hz
        pfr = -self.parameters.bess.pfr_gain_pu_power_per_pu_frequency * omega
        requested = pfr + observation.issued_command_pu[[1, 3]]
        self.latest_snapshot = self.identifier.update(
            observation.time_s, requested, observation.bess_actual_power_pu
        )
        if (
            self.passive_renewal_enabled
            and self.certificate is not None
            and self.certificate.valid_at(observation.time_s)
            and self.certificate.expiry_time_s - observation.time_s <= self.physical_dt_s + 1e-10
        ):
            passive = self.latest_snapshot.candidate_set
            if bool(
                np.all(passive.excitation_sufficient)
                and np.all(passive.performance_power_pu + 1e-12 >= self.certificate.power_lower_pu)
                and np.all(passive.performance_ramp_pu_per_s + 1e-12 >= self.certificate.ramp_lower_pu_per_s)
                and np.all(passive.delay_interval_s[:, 1] <= self.certificate.maximum_delay_s + 1e-12)
            ):
                self.certificate = replace(
                    self.certificate,
                    issued_time_s=float(observation.time_s),
                    expiry_time_s=float(observation.time_s + self.certificate_validity_s),
                    source="CAUSAL_PASSIVE_RENEWAL",
                )
                self.certificate_issues += 1
                self.passive_renewals += 1
        reset = bool(self.latest_snapshot.candidate_set.change_reset.any())
        if reset:
            if self._session is not None:
                self._session = None
                self.last_probe_end_s = float(observation.time_s)
                self.probe_aborts_on_change += 1
            if self._pending_session is not None:
                self._pending_session = None
                self.probe_aborts_on_change += 1
            self.retained_models = list(self.models)
            if observation.time_s - self._last_reset_s > self.cooldown_s:
                self.change_epoch += 1
                self._last_reset_s = float(observation.time_s)
        elif not reset:
            self._apply_causal_passive_filter()
        self._revoke_if_needed(observation)
        self._command_history.append((
            float(observation.time_s),
            observation.issued_command_pu[[1, 3]].copy(),
            pfr.copy(),
        ))
        if len(self._command_history) > int(round(4.0 / self.physical_dt_s)) + 8:
            self._command_history.pop(0)
        if self._session is None:
            if self._pending_session is None:
                return
            self._pending_session["time"].append(float(observation.time_s))
            self._pending_session["sfr"].append(
                observation.issued_command_pu[[1, 3]].copy()
            )
            self._pending_session["pfr"].append(pfr.copy())
            self._pending_session["actual"].append(
                observation.bess_actual_power_pu.copy()
            )
            if observation.time_s + 1e-10 >= float(
                self._pending_session["confirmation_time_s"]
            ):
                self._finalize_pending_certificate(observation)
            return
        self._session["time"].append(float(observation.time_s))
        self._session["sfr"].append(observation.issued_command_pu[[1, 3]].copy())
        self._session["pfr"].append(pfr.copy())
        self._session["actual"].append(observation.bess_actual_power_pu.copy())
        elapsed = observation.time_s - float(self._session["start_time_s"])
        end = len(self.probe.sequence_pu) * self.period_s + 1.75
        if elapsed + 1e-10 >= end:
            self._finish_probe(observation)

    def propose(self, inputs) -> ACCRResult:
        observation = inputs.observation
        if self.certificate is not None and self.certificate.valid_at(observation.time_s):
            power = tuple(float(value) for value in self.certificate.power_lower_pu)
            ramp = tuple(float(value) for value in self.certificate.ramp_lower_pu_per_s)
            delay = tuple(float(value) for value in self.certificate.maximum_delay_s)
            self.core.contract = CapabilityContract(
                lower_power_pu=tuple(-value for value in power),
                upper_power_pu=power,
                ramp_down_pu_per_s=ramp,
                ramp_up_pu_per_s=ramp,
                maximum_delay_s=delay,
            )
        else:
            self.core.contract = self.registered_contract
        raw_core = self.core.propose(inputs)
        attempts = 2 if (
            raw_core.diagnostics.restoration_used
            or raw_core.diagnostics.fallback_used
        ) else 1
        diagnostic_values = asdict(raw_core.diagnostics)
        diagnostic_values["attempted_optimization_calls"] = attempts
        core = replace(raw_core, diagnostics=SimpleNamespace(**diagnostic_values))
        action = core.proposed_action_pu.copy()
        contract_optimal_action = action.copy()
        probe_component = np.zeros(4)
        triggered = False

        self.decision_calls += 1
        decision = self._voi_decision(inputs, core)
        core.diagnostics.attempted_optimization_calls += self._last_voi_solver_attempts
        core.diagnostics.solve_time_s += self._last_voi_solve_time_s
        self.last_decision = decision
        self.worthwhile_calls += int(decision.worthwhile)
        current_totals = np.asarray((
            core.proposed_action_pu[0] + core.proposed_action_pu[1],
            core.proposed_action_pu[2] + core.proposed_action_pu[3],
        ))
        evaluated_abstention_reasons = {
            "NOT_DECISION_RELEVANT", "ORACLE_GAP_PROXY_TOO_SMALL",
            "CANDIDATES_NOT_DISTINGUISHABLE", "NONPOSITIVE_NET_VOI",
        }
        if (
            self.latch_abstention
            and float(np.max(np.abs(current_totals))) >= 0.025
            and float(np.sum(np.abs(observation.ace_pu))) >= self.minimum_ace_for_probe
            and decision.reason in evaluated_abstention_reasons
        ):
            self._abstain_until_demand_clears = True
        if decision.worthwhile:
            if self._demand_active_since_s is None:
                self._demand_active_since_s = float(observation.time_s)
        else:
            self._demand_active_since_s = None
        demand_persistence_s = (
            0.0 if self._demand_active_since_s is None
            else float(observation.time_s - self._demand_active_since_s)
        )

        eligible = bool(
            decision.worthwhile
            and self._session is None
            and self.certificate is None
            and observation.time_s >= self.trigger_time_s
            and inputs.domain.domain == "SUSTAINABLE"
            and not core.diagnostics.fallback_used
            and self.probed_epoch < self.change_epoch
            and observation.time_s - self.last_probe_end_s >= self.cooldown_s
            and observation.time_s - self._last_reset_s >= self.cooldown_s
            # Candidate-MPC relevance and the positive net-VoI test are the
            # registered trigger; no additional unregistered one-period delay.
            and demand_persistence_s >= 0.0
            and np.all((observation.measured_soc >= 0.25) & (observation.measured_soc <= 0.75))
        )
        if eligible:
            totals = np.asarray((action[0] + action[1], action[2] + action[3]))
            area = int(np.argmax(np.abs(totals)))
            sign = 1.0 if totals[area] >= 0.0 else -1.0
            self._session = {
                "start_time_s": float(observation.time_s),
                "area": area,
                "sign": sign,
                "time": [float(observation.time_s)],
                "sfr": [observation.issued_command_pu[[1, 3]].copy()],
                "pfr": [(-self.parameters.bess.pfr_gain_pu_power_per_pu_frequency
                         * observation.frequency_deviation_hz
                         / self.parameters.nominal_frequency_hz).copy()],
                "actual": [observation.bess_actual_power_pu.copy()],
                "models_before": list(self.retained_models),
            }
            self.probed_epoch = self.change_epoch
            self.probe_triggers += 1
            triggered = True

        if self._session is not None:
            session = self._session
            elapsed = observation.time_s - float(session["start_time_s"])
            index = int(elapsed // self.period_s)
            q = 0.0
            if 0 <= index < len(self.probe.sequence_pu):
                q = float(session["sign"] * self.probe.sequence_pu[index])
            area = int(session["area"])
            sg_column, bess_column = (0, 1) if area == 0 else (2, 3)
            sg_low = float(self.parameters.valve_lower_pu[area])
            sg_high = float(self.parameters.valve_upper_pu[area])
            bess_rating = float(self.parameters.bess.rating_pu)
            q_low = max(action[sg_column] - sg_high, -bess_rating - action[bess_column])
            q_high = min(action[sg_column] - sg_low, bess_rating - action[bess_column])
            q = float(np.clip(q, q_low, q_high))
            action[sg_column] -= q
            action[bess_column] += q
            probe_component[sg_column] = -q
            probe_component[bess_column] = q
        else:
            self.abstention_calls += 1

        guaranteed = np.clip(
            core.proposed_action_pu[[1, 3]],
            np.asarray(self.registered_contract.lower_power_pu),
            np.asarray(self.registered_contract.upper_power_pu),
        )
        certified_component = np.zeros(4)
        certified_component[[1, 3]] = core.proposed_action_pu[[1, 3]] - guaranteed
        contract_component = action - certified_component - probe_component
        overlay_residual = float(np.max(np.abs(
            (action - contract_optimal_action) - probe_component
        )))
        self.maximum_unmetered_responsibility_jump_pu = max(
            self.maximum_unmetered_responsibility_jump_pu, overlay_residual
        )
        if overlay_residual > 1e-12:
            raise RuntimeError("probe overlay contains an unmetered responsibility jump")
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
            shared_current_action_verified=True,
            surplus_loss_branch_verified=False,
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
        self.core.commit(result.proposed_action_pu, measured_actual_bess_pu)
        self.last_action = result.proposed_action_pu.copy()
        self.last_guaranteed = result.guaranteed_bess_command_pu.copy()


__all__ = [
    "VOIActiveCapabilityCertificationRecourseMPC", "VOIProbeDecision",
    "weighted_contract_mpc_class",
]
