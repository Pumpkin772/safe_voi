# Phase 1 report: physical system and hidden-mode simulator

**Status:** PASS  
**Date:** 2026-07-22  
**Implementation commit:** `cfb911f88682641332868e1881ca5c13d7dba047`

## Completed items

- Implemented the five-state aggregate frequency model with swing, turbine,
  governor, primary droop, integral, and load-disturbance states.
- Implemented exact multi-input ZOH discretization through an augmented matrix
  exponential and verified it against independent SciPy references.
- Implemented simulator-private second-order IBR truth dynamics with deadband,
  delayed command, frequency response, asymmetric target saturation, and
  asymmetric output ramp limits.
- Added four known modes (`nominal`, `sluggish`, `derated`, `unavailable`) and
  two held-out OOD truth configurations (`asymmetric_limit`,
  `time_varying_delay`).
- Implemented deterministic fixed and sinusoidal time-varying delays with a
  right-continuous command ZOH history.
- Implemented load steps, pulses, sampled white noise, sampled random walk, and
  strictly ordered piecewise-constant hidden-mode schedules.
- Implemented a single seven-state coupled RK4 simulator. Every RK4 stage uses
  stage IBR power in the grid derivative and stage frequency in the IBR
  derivative.
- Implemented control-period ZOH, explicit seeded measurement noise, episode
  duration handling, and deterministic reset behavior.
- Kept `Scenario` and hidden-mode schedules simulator-private. The controller
  receives only `Measurement`; truth is returned separately in an evaluation
  dictionary under `true_mode_eval_only`.
- Added a reproducible script that generated the four known-mode step-response
  CSV, figure, and SHA-256 metadata under `artifacts/phase1/`.
- Added the living formula-to-code map for equations (1)–(16).

## Acceptance evidence

Canonical command:

```powershell
conda run -n topo_sfr python -m pytest -q
```

Final Phase 1 result: **118 passed, 0 failed, 0 errors**. Source coverage is
**88%**. `compileall` and `git diff --check` passed. JUnit and coverage XML are
retained as `phase1_junit.xml` and `phase1_coverage.xml`.

The acceptance tests verify:

- exact zero-state equilibrium;
- positive load causing negative frequency tendency;
- continuous/discrete matrix shapes, values, and defensive copying;
- RK4 fourth-order convergence;
- deadband edge behavior;
- positive/negative saturation and ramp limits;
- fixed-delay prehistory and no response before the delay;
- second-order nominal/sluggish response separation;
- derating changes the target without instantaneously clipping physical power;
- mode-switch state/history continuity;
- deterministic load and measurement noise for equal seeds;
- no right-end leakage of load or mode events into the preceding RK4 segment;
- no right-end leakage of a delayed ZOH command;
- successful construction of all versioned known and OOD model configurations;
- absence of hidden truth fields in controller-visible APIs.

## Mode-response artifact

The generated response evidence contains 2,004 rows total (501 samples per
mode) over 10 s at 0.02 s integration resolution. The curves are clearly
distinct: nominal is fast and approaches
the deadband-adjusted command, sluggish has lower gain and slower dynamics,
derated reaches its external target limit, and unavailable retains only a weak
response.

Files:

- `artifacts/phase1/known_mode_step_responses.csv`
- `artifacts/phase1/known_mode_step_responses.png`
- `artifacts/phase1/known_mode_step_responses_metadata.json`

CSV SHA-256:
`20e4dd084ef906f8738e3b465983159e4ba858f575e14bd041413309ed6e6cb2`.

Reproduction command:

```powershell
conda run -n topo_sfr python scripts/phase1_generate_mode_responses.py
```

## Resolved failures and numerical issues

Initial module tests passed independently, but cross-review identified three
hybrid-event risks before acceptance:

1. The grid's fifth state is load level `d_pu`; passing load level as
   `d_dot` would incorrectly turn a step into a ramp. The simulator now applies
   load levels as state jumps at event boundaries and keeps `d_dot=0` inside
   each constant segment.
2. RK4 evaluates its fourth stage at the interval endpoint. Mode and load
   changes are therefore used only after explicitly splitting the interval and
   freezing the old value on the preceding segment closure.
3. Fixed delayed commands have the same endpoint issue. Command visibility
   transition times are now included as integration boundaries, and the prior
   command is used for the preceding segment's endpoint stage.

All three behaviors have regression tests.

## Remaining limitations

- The sinusoidal time-varying OOD delay is evaluated at each RK4 stage but its
  implicit command-crossing roots are not solved as exact event times. Its
  convergence and detection behavior must be quantified in the OOD phase; it
  is not used as a known training mode.
- `p_max_pos_pu` and `p_max_neg_pu` constrain the internal target `q_bar`, as
  specified by equation (14). After an abrupt derating, physical `p_ibr_pu`
  may temporarily exceed the new target and then withdraw under its ramp/lag;
  this is intentional, tested, and must not be reported as an instantaneous
  hard output clamp.
- This phase establishes open-loop truth dynamics only. State estimation and
  closed-loop recovery are Phase 2 claims, not Phase 1 claims.

## Phase 2 entry decision

The Phase 1 gate is open. Phase 2 may implement exact discrete grid models,
the augmented load-disturbance Kalman filter, IBR-unavailable LQI fallback,
fixed nominal MPC, and evaluation-only Oracle MPC. Phase 2 is not accepted
until nominal step recovery, IBR-unavailable fallback, estimator behavior,
controller constraint, and Oracle-isolation tests pass and
`progress/PHASE_2_REPORT.md` is written.
