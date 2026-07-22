# Phase 5 report: self-diagnosing belief-space MPC and safe fallback

**Status:** PASS for implementation, numerical qualification, runtime
information isolation, and reproducible audit artifacts

**Date:** 2026-07-23

**Implementation commit:** `d3cbfdf91b2544c14889ca6c21c66089f5c2b049`

## Completed items

- Implemented equations (52)--(66) over the frozen six native Phase-3 ARX
  components.  Every component has a ten-state joint grid/ARX prediction, and
  all six components share exactly one executable SG/IBR sequence with shape
  `(2, 20)`.
- Included all six components in the belief-weighted expected cost.  The robust
  constraint and worst-cost set is the minimum stable-tie 0.99 credible set in
  a confident `KNOWN` state and all six components for normalized entropy at
  least 0.70, `SUSPECT`, or a diagnostic numerical issue.
- Implemented one shared nonnegative frequency slack, RoCoF slack, and power
  slack sequence.  Frequency/RoCoF q95 values use future leads `1..20` in
  their persisted Hz and Hz/s units, without a second nominal-frequency
  conversion.
- Enforced common SG/IBR command and command-rate limits plus per-component
  external IBR power and directional power-rate capability bounds.
- Used one DCP/DPP CVXPY template whose exact binary risk mask changes without
  rebuilding or recanonicalizing the problem.  Reset-time solver
  canonicalization is outside the timed control loop.
- Added a strict solver adapter with MOSEK, Gurobi, CLARABEL, and SCS priority.
  Only exact `optimal` is executable.  Inaccurate, infeasible, unbounded,
  timeout, failed-status, exception, missing, or non-finite results are logged,
  cleared, and rejected.
- Implemented the three executable states `NORMAL_BELIEF_MPC`,
  `ROBUST_BELIEF_MPC`, and `FALLBACK`.  `OOD_ACTIVE` and `RECOVERY` remain in
  fallback; recovery uses an exact hold and linear blend policy.
- Reused one continuously propagated grid Kalman estimate across MPC and LQI.
  Each distinct timestamp causes exactly one diagnostic update and one
  estimator update.  A repeated identical timestamp is idempotent, while a
  repeated timestamp with changed signals is rejected.
- Recomputed LQI and rate-limited IBR withdrawal at every fallback, hold, and
  blend sample.  Solver/rejection recurrence clears the prior executable warm
  start.  Every fallback event retains its reasons, sample count, start/end
  times, and duration.
- Added the production `from_project_files` factory.  It requires native K=6,
  validates both the exact model-library file hash and canonical logical hash
  against the OOD calibration artifact, and records base/MPC/library/
  calibration provenance.
- Added a Phase-5 audit pipeline with strict solver timing/status logs, a
  machine-readable controller-state graph and reproducible PNG, a truth-free
  production-controller smoke log, resolved configuration, environment/Git/
  source hashes, and a self-verifying complete artifact manifest.
- Extended the mathematics-to-code map through equations (52)--(75).

## Numerically stable cost realization

An initial auxiliary-epigraph design was mathematically equivalent but left
weakly anchored variables when a belief was zero or near its `1e-12` floor.
Independent review reproduced very large inactive epigraph values and a
CLARABEL `optimal_inaccurate` result.  That design was removed before the
implementation commit.

The accepted formulation factors equation (57) exactly as

```text
J_m = C(U, U_previous) + ||v_m||^2,
```

where `C` contains every shared input and input-increment term and `v_m`
contains every mode-dependent current-frequency, integral, RoCoF, and terminal
residual.  Since the belief sums to one,

```text
J_exp = C + sum_m b_m ||v_m||^2.
```

For an exact binary risk mask, the worst-mode constraints are

```text
C + mask_m ||v_m||^2 <= t.
```

An active mask is exactly `t >= J_m`; an inactive mask leaves the redundant
`C <= t`.  This graph remains DCP and DPP and has no free expected-cost
epigraphs.  Regression tests cover exact-zero and `1e-12` beliefs, zero
worst-case weight, singleton/all-mode mask changes, and direct evaluation of
equations (58)--(61) on the real K=6, `Np=20` problem with MOSEK.

## Acceptance evidence

Canonical commands are:

```powershell
conda run -n topo_sfr python -m pytest -W error -q

conda run -n topo_sfr python scripts/phase5_validate_sd_bmpc.py `
  --output-dir artifacts/sd_bmpc `
  --repeat-count 5 `
  --controller-smoke-steps 8

conda run -n topo_sfr python scripts/phase5_validate_sd_bmpc.py `
  --output-dir artifacts/sd_bmpc_repro_check `
  --repeat-count 5 `
  --controller-smoke-steps 8
```

The strict source baseline is **458 passed, 0 failed, 0 errors, 0 warnings**.
Coverage of the complete source tree is **80.43%**.  JUnit and coverage XML are
retained as `progress/phase5_junit.xml` and
`progress/phase5_coverage.xml`.  `compileall`, `pip check`, staged-diff
whitespace checks, and NUL-byte checks also passed.

The current desktop session changed from the sandbox account that created old
pytest temporary directories to the local user account.  To avoid modifying
those old-account directories, the independent acceptance rerun used a fresh
random directory under the current user's system temporary directory and
disabled pytest's cache provider.  This permission issue did not affect source,
artifacts, solvers, or scientific values.

## Canonical K6/Np20 solver evidence

The canonical audit uses MOSEK 11.2.2.  The one-time optimization-template
precompile took 0.9714 s outside the timed loop; the production controller's
separate reset precompile record is 1.0591 s.

| Risk-mask case | Exact optimal | Wall minimum | Wall median | Wall p95 | Wall maximum |
|---|---:|---:|---:|---:|---:|
| all six components | 5/5 | 0.0628 s | 0.0662 s | 0.0808 s | 0.0843 s |
| singleton component 3 | 5/5 | 0.0547 s | 0.0577 s | 0.0579 s | 0.0579 s |

All ten solves reused the identical CVXPY problem object, returned exact
`optimal`, used a commercial solver, and completed below the configured
0.20 s soft wall budget.  The largest first-record slacks were
`3.334e-7 Hz`, `1.077e-6 Hz/s`, and `1.141e-3 pu` for the all-mode case;
all are below the controller's 0.02 rejection thresholds.

The timeout is deliberately described as a **solver-cooperative soft
deadline**: native solver time-limit options are passed and any solution that
returns after the total wall budget is rejected and cleared.  This is not
process-level preemption and is not a hard real-time guarantee if a backend
ignores its limit or blocks in a bridge call.

## Runtime information boundary and state machine

The production factory was invoked before the simulator-private known-mode
configuration was loaded.  The controller constructor never received that
configuration, and `act` has the sole parameter `measurement`.  Seven
simulator-private records returned during the eight-step smoke were discarded
without inspection or persistence.  Recursive schema guards verify that the
runtime, controller-step, and fallback logs contain no truth key.

The deterministic four-second smoke produced eight exact-optimal actions:
three `ROBUST_BELIEF_MPC` warm-up/uncertain samples followed by five
`NORMAL_BELIEF_MPC` samples, with no fallback event.  Fallback failure,
OOD/recovery, hold/blend, recurrence, slack, timeout, and event-duration paths
are covered by focused integration tests rather than inferred from this short
nominal smoke.

## Reproducibility result

An independent rerun in `artifacts/sd_bmpc_repro_check/` reproduced:

- byte-identical state-machine JSON and PNG;
- byte-identical resolved configuration and source-hash map;
- identical ten-case solver/status sequence;
- exactly zero maximum difference in objective, all three maximum slacks, and
  both first control inputs;
- exactly zero maximum difference in every controller-smoke signal/action
  column other than measured solve time.

Whole solver/runtime tables and their manifests are intentionally not
byte-identical because they persist newly measured wall times, precompile
times, timestamps, and the different output-directory provenance.  No
scientific or executable value changed.

## Required artifacts and hashes

The canonical `artifacts/sd_bmpc/` directory contains 20 files (260,248 bytes).
Principal SHA-256 values are:

- implementation commit: `d3cbfdf91b2544c14889ca6c21c66089f5c2b049`;
- model-library file: `a493380e29efe4879c955f2a3d9891a155fb818f38ffe99c12181616c449bf22`;
- model-library logical content: `29ea385461d2c826cd9f3f46c06afa2d1370b84587fc5b6cfbcc485aab959296`;
- OOD calibration artifact: `190fd05d3d0a449a46770112a0707d33fae16fd118b7c16be44a06916d531141`;
- solver timing/status Parquet: `bbfa1ae1853c5e8db7f80d9860727b34379acc9882245f5d2fdb9de08823dc85`;
- truth-free runtime smoke Parquet: `c2b1132f17413d9e4ec4d31fb9e9a7e1133f229e872bd47dc56e0f4069af674c`;
- Phase-5 summary: `96a42621b0a7ec2baf7f33115c7640d5274f92b4b745199fb3714571e81d2c42`;
- canonical artifact manifest: `d195ae87da71cbd622c7a9918a003f6b493cad36dc4cbfe981030482afd5e1c9`.

The canonical Git provenance records a clean worktree at the implementation
commit.  The manifest verifies every non-manifest artifact by path, size, and
SHA-256 and binds itself through a separate digest sidecar.

## Scope qualifications carried into Phase 6

1. `power_q95_pu` remains persisted model-validation evidence but is not an
   equation-(65)--(66) tightening term.  Frequency and RoCoF use their q95
   tables; power and rate constraints use train/validation capability bounds
   with the shared power slack.
2. The Phase-4 OOD detector remains weak on the prescribed unseen mechanisms
   and has a high known-mode false-alarm rate.  Phase 6 must retain all
   resulting fallback load, missed OOD events, and failures.
3. The nominal smoke establishes construction, timing, state transition, and
   information isolation, not comparative closed-loop performance.  No claim
   against Fixed MPC, RLS, hard MAP, or Oracle is made before the frozen
   Phase-6 matrix is complete.
4. MOSEK timings are specific to this Windows host, solver/license, and current
   load.  CLARABEL/SCS remain debugging fallbacks and are not eligible for
   final performance claims.

## Phase 6 entry decision

All Phase-5 implementation gates are open: the problem is a convex QCQP, the
runtime path is truth-free, non-exact or late solutions cannot execute, and
fallback events are fully auditable.  Phase 6 may now freeze the full scenario,
baseline, ablation, seed, metric, and statistical-analysis configuration before
running any final-test episode.
