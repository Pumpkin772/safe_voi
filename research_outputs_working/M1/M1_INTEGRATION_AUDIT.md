# Direction5 VOI-ACCR-MPC M1 integration audit

Status: `IN_PROGRESS_M1_NOT_YET_PASSED`

## Corrected integration defects

- The active overlay is applied as `u_b = u_b_contract + q` and
  `u_g = u_g_contract - q`; no fixed `+/-0.05 pu` BESS base remains in the
  development controller.
- Missing certificate is no longer a sufficient trigger. A probe requires a
  positive causal candidate-action relevance, positive net-VoI proxy,
  distinguishable candidate partition, sustainable-domain state, SoC margin,
  solver success, cooldown and one-probe-per-change-epoch eligibility.
- Zero-load ramp uncertainty no longer creates false relevance. Candidate MPCs
  are evaluated only after the current rolling contract action has material
  regulation demand.
- Certificate expiry/revocation returns the same rolling MPC to the registered
  contract. A change/reset starts a new epoch and blocks immediate reprobe.
- The certificate-mode MPC uses the finite-valid certificate during its stated
  validity interval. It does not simultaneously assume certified surplus is
  lost at every future step; an observed change revokes the certificate at the
  next causal update.
- All candidate action comparisons use public observations, measured SoC,
  issued commands and actual POI power. No ordinary-controller interface takes
  true capability, true load or a future event.
- Candidate-MPC calls used by the VoI gate are included in attempted solver-call
  and solve-time diagnostics.
- A VoI-positive decision is rejected unless the current contract-optimal SG
  and BESS allocation has enough two-sided headroom for the complete requested
  probe.  Predicted distinguishability therefore cannot rely on a probe that
  the command overlay would later clip.
- The finite hypothesis set is intersected with causal, sufficiently excited
  power/ramp/delay evidence.  Empty intersections are not treated as 100%
  diameter reduction and cannot create a certificate.
- Every new development invocation writes below a labeled run directory.  The
  earlier C00/C01 and W00--W02 failures remain intact rather than being
  overwritten by corrected reruns.
- The M1 decision now audits cumulative probe command cost, candidate-set
  diameter, each certificate issue against evaluation-side truth after the
  episode, and exact action equivalence on abstention cases.  Evaluation truth
  is not passed into the ordinary controller.

## Results retained so far

- Initial corrected-base screen: 8 full 300 s nonlinear Plant-A cases, zero
  hard physical violations and zero fallbacks.
- The registered material subset showed a 7.001% mean tie-IAE improvement, but
  all non-material cases also probed, so M1 correctly remained failed.
- The premature-probe cause was reproduced: the earlier proxy declared ramp
  relevance during the nominal zero-load segment and triggered at 60 s.
- A first fair weighted screen completed W00--W02. All three had zero hard
  violations and zero fallbacks, but perfect-information directions were
  negative; none can support value-recovery claims.
- The weight screen was terminated by the external 70% system-commit guard.
  The guarded task used about 0.4 GiB private memory and one descendant; no
  process multiplication occurred.
- Exact A1-objective WREF replay recovered positive perfect-information value:
  four of four representative cells were positive for tie IAE, with 5.398%
  mean improvement, zero hard violations and zero fallbacks.
- A 0.0025 pu, two-step allocation-neutral probe with a 4 s certificate
  produced 4.09% tie improvement, 50% registered A3-diameter reduction, zero
  signing-time false optimism and zero hard violations in the first high-value
  case.  Across eight all-high-load cases it over-triggered (8/8) and achieved
  only 1.82% mean tie improvement, so that manifest did not pass M1.
- Larger/longer probes were retained as failures: they increased closed-loop
  cost, did not improve the posterior enough under the causal residual bound,
  or crossed an unannounced capability transition.
- The initial eight-case manifest was scientifically unsuitable for an
  abstention Gate: every case used a material high load, and timing was
  confounded with load area.  The corrected value-region manifest keeps the
  original high loads, adds four 0.020 pu low-value controls, uses the same
  14 s load-before-capability separation in both regions, and balances load
  area in each region.  No disturbance was enlarged.
- A resource-interrupted run under that corrected manifest is preserved as
  `VOI_V10_C13_M1_VALUE_REGIONS`.  The task tree stayed near 0.4 GiB but
  unrelated processes pushed system commit above 70%.  New runs checkpoint
  every episode and safely resume without deleting completed failures.

## Required next evidence

1. Resume the corrected eight-case value-region M1 run only after the system
   commit fraction is below the 64% preflight limit.
2. M1 may be declared only if all registered safety, value, posterior-diameter,
   nonempty-certificate, false-optimism and abstention-equivalence requirements
   pass together.
3. Only after a genuine M1 pass may the method be promoted out of scratch and
   independent M2 validation begin.

The latest Windows performance-counter reading was above the registered 64%
preflight ceiling.  No simulation child was started, and the stale background
capacity waiter was stopped so it cannot launch a run unattended.

No Git write operation is authorized at this status.
