# Phase 2 report: state estimation and baseline frequency control

**Status:** PASS  
**Date:** 2026-07-22  
**Implementation commit:** `eb449d810920afe7ddcec37883c6b92af766192b`

## Completed items

- Implemented the five-state grid Kalman filter for equations (31)–(37), with
  measured order `[omega_pu, p_mech_pu]`, exact `A_d/B_d/E_d/G_d` propagation,
  mapped load-random-walk covariance, solve-based gain computation, and a
  Joseph-form covariance update.
- Added defensive state/covariance interfaces and a controller adapter that
  propagates only controller-visible measurements and prior commands.
- Implemented equation (70)'s auditable fallback trigger and equation (71)'s
  rate-limited IBR withdrawal.
- Implemented the reduced four-state DARE design in equations (72)–(75), with
  load-estimate equilibrium translation, SG amplitude/rate enforcement, and a
  continuously reusable estimator state for mid-episode fallback.
- Implemented a seven-state, two-input convex fixed-model MPC bootstrap with a
  single shared command sequence, command amplitude/rate constraints, external
  IBR power/capability constraints, warm start, solver status records, and a
  high-penalty transient power slack for reachable mode-capability changes.
- Added support for exact-zero IBR capacity and verified the horizon-one CVXPY
  solution against an independently derived KKT solution.
- Isolated Oracle model selection under `evaluation/baselines/oracle.py`. Its
  executable entry point is `act_evaluation_only`; it is deliberately not a
  `FrequencyController`, and normal controller code has no evaluation import or
  truth-label input.
- Added explicit versioned Kalman `Q`, `R`, `P0`, and calibrated
  `load_random_walk_std_pu_per_s: 1.0e-4` settings to `configs/base.yaml`.
- Extended the living formula map through equations (31)–(37), (62)–(64), and
  (70)–(75), including the estimator observability qualification.

## Acceptance evidence

Canonical strict command:

```powershell
conda run -n topo_sfr python -m pytest -q -W error --cov=src/d5freq
```

Final result: **171 passed, 0 failed, 0 errors, 0 warnings**. Source coverage is
**86%**. JUnit and coverage XML are retained as `phase2_junit.xml` and
`phase2_coverage.xml`. `compileall`, `git diff --check`, and `pip check` passed.

The tests include:

- equation-by-equation Kalman prediction/update references and long-run PSD
  covariance checks;
- exact preservation of the configured `sigma_d² G_d G_d^T` mapping;
- explicit rank-four observability qualification, with only the constant
  integral-state offset unobservable and the load disturbance observable;
- DARE gain equality, Schur stability, load-equilibrium translation, fallback
  triggers, command withdrawal, and SG amplitude/rate bounds;
- a 90 s true nonlinear hybrid fixed-MPC episode with a +0.04 pu permanent load
  step at 5 s and a last-10-second `max |Delta f| < 0.002 Hz` gate;
- a 90 s true nonlinear hybrid LQI episode using the configured `unavailable`
  IBR mode, with SG-only capacity-feasible recovery;
- QP dynamics, shared-input, command, IBR power/capability, and rate constraints;
- an independent horizon-one KKT solution;
- lower-capacity mode-transition envelopes/slack and exact-zero capacity;
- Oracle evaluation-only API isolation and recursive static information-boundary
  scans over controllers, estimation, and optimization.

## Reproducible closed-loop artifact

Command:

```powershell
conda run -n topo_sfr python scripts/phase2_validate_baselines.py
```

The seeded run produced 180 samples per 90 s episode and returned
`accepted=true`:

| Scenario | Statuses | Last-10-s max absolute frequency error | Final load estimate |
|---|---:|---:|---:|
| Fixed nominal MPC, nominal truth | 180/180 optimal | 0.0009383358 Hz | 0.04000001625 pu |
| LQI fallback, configured unavailable truth | 180/180 fallback_lqi | 0.0000108998 Hz | 0.03999999900 pu |

Both episodes had zero command-amplitude and command-rate violations. The
fixed-MPC final commands were approximately `u_sg=0.01207386 pu` and
`u_ibr=0.02809797 pu`. The LQI episode restored mechanical power to the load
while the IBR command remained withdrawn.

Generated files (ignored by Git and reproducible from the command above):

- `artifacts/phase2/baseline_acceptance_trajectories.csv`
- `artifacts/phase2/baseline_acceptance_summary.json`

Hashes for this evidence run:

- trajectory CSV:
  `94bec07959f366cc5adadb4069d1623bdc6001bef159ab9a254f575dbdd1341c`;
- summary JSON:
  `6bf83fa3ac02e05907ae5424b80978b92a64564785badf57600a574af9c18d68`;
- validation script:
  `06e62004614b2caf90789abaa798e1a2a3ae279fc863cbc634e106f6105b78a9`.

The CSV keeps evaluator truth only in `eval_`-prefixed columns appended after
each action. No evaluator field is routed into either controller.

## Resolved failures and numerical issues

1. An initial covariance-validation path added machine epsilon to an already
   valid process covariance, breaking exact `G_d` mapping by about `2.2e-16`.
   Construction now preserves validated PSD inputs exactly; stabilization is
   applied only after numerical propagation/update.
2. The first fixed-MPC implementation neither estimated the persistent load nor
   constrained predicted IBR power. Although every QP was optimal, the true
   nonlinear plant retained about 0.15 Hz frequency error. The controller now
   injects the grid Kalman estimate and enforces model capability/rate bounds.
3. The uncalibrated filter default `sigma_d=1.0e-3` caused a sustained roughly
   ±0.028 Hz limit cycle that a mean-only gate concealed. Explicit calibration
   to `1.0e-4` removed it, and acceptance now uses the maximum absolute error
   over the whole tail window.
4. A hard new-mode capacity constraint could be infeasible immediately after a
   derating because physical power cannot jump. The MPC now contracts a
   reachable envelope per prediction step and uses a recorded high-penalty
   transient slack for both capacity and power-rate constraints only when the
   measured initial power lies outside the new capability.
5. A runtime-checkable protocol initially misclassified Oracle as a normal
   controller because Python protocols inspect method names rather than call
   signatures. Renaming its executable method to `act_evaluation_only` makes
   the separation enforceable.

## Qualifications and deferred work

- The full five-state measurement pair has observability rank four because a
  constant offset in `xi_pu_s` cannot affect measured physical dynamics.
  `xi_pu_s` is therefore initialized by definition at the episode boundary and
  continuously integrated. Phase 5 must reuse this estimate when entering LQI;
  it must not reset the filter mid-episode.
- `linearize_grid_ibr` is a Phase-3-predecessor bootstrap used to qualify the
  optimizer and controller plumbing. It consumes physical nominal parameters
  and omits nonlinear delay/deadband/saturation dynamics. It is **not** the final
  Fixed-ARX baseline; Phase 3 must replace it with the unlabeled discovered
  nominal model library before scientific comparisons.
- The Kalman class default remains a smoke-run convenience. All experiment,
  Oracle, and proposed-controller factories must construct it from the explicit
  calibrated YAML values.
- `optimal_inaccurate` is currently represented as a solver success, and the
  configured hard wall-clock timeout is not yet enforced inside this bootstrap
  solver. Phase 5 must classify inaccurate, timeout, excessive-slack, and other
  failure outcomes in the full fallback state machine.
- CLARABEL was used for deterministic development/acceptance evidence only. It
  will not be used to support final performance claims; the final experiment
  solver policy remains MOSEK first and Gurobi second.

## Phase 3 entry decision

The Phase 2 gate is open. Phase 3 may generate safe fixed-mode trajectories and
perform unlabeled local-ARX/GMM mode discovery. Public identification data must
contain no mode labels or label-derived identifiers. Hungarian alignment and
truth labels remain evaluation-only, and the discovered runtime library must
not depend on simulator truth configuration files.
