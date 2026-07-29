# Phase 6 report: frozen baselines, ablations, and statistical experiments

**Status:** PASS for protocol integrity, complete matrix execution, retained
failures, paired statistics, diagnostic/solver qualification, and trajectory
selection

**Date:** 2026-07-29

**Frozen implementation commit:** `20f652f5f8b180a2518798d0ed85aa3f48212908`

**Protocol material SHA-256:**
`d658cfd95fadb3d7ef3e5fb8ddb6d75ccc9a2315e4a49d997de7b1fef4d0d326`

## Completed items

- Froze the Phase-6 code, configuration, model-library, calibration, tuning,
  and evaluation-only Oracle material before final execution.  The aggregate
  frozen code hash is
  `7234611455d41f535a23de9996770d013d06dfdd3885ae4fefb27a69331e6da7`.
- Executed all 12 predeclared methods: B0--B4, the proposed method P, and six
  ablations (`no-worst`, `no-OOD`, `no-tightening`,
  `fixed-K4-unlabeled`, `labeled-library`, and `no-transition-prior`).  B4 is
  retained only as a truth-informed evaluation upper bound.
- Executed all 21 scenario variants.  The 18 ordinary known variants use 30
  seeds per method; one extreme-known and two OOD variants use 50 seeds per
  method.  The exact matrix size is therefore 8,280 episodes.
- Resumed the immutable per-run store after an execution-host interruption.
  Every existing JSON/Parquet pair was authenticated before reuse; no episode
  was silently repeated, overwritten, or dropped.
- Published the six canonical result tables, Oracle pairing audit, and final
  protocol lock.  All result rows include their execution and scientific
  status rather than filtering failures.
- Produced 10,824 descriptive/bootstrap summary rows, 1,980 paired
  statistical-test rows, 3,168 diagnostic rows, and 3,388 solver rows.  Means
  use 10,000 bootstrap resamples, and inferential families use paired sign-flip
  or exact McNemar tests with Holm correction.
- Verified complete Oracle pairing for all 12 methods: 690/690 finite paired
  regret values per method, with no missing Oracle or cost pair.
- Deterministically selected and replayed 10 representative trajectories and
  three retained worst cases.  Their Parquet traces are bound to the final
  matrix and manifests by SHA-256.

## Matrix integrity acceptance

The final `per_episode_metrics.csv` and `experiment_ledger.csv` each contain
exactly 8,280 rows and the same `(method, scenario_id, seed)` key set.

| Integrity condition | Result |
|---|---:|
| Methods | 12 |
| Scenario variants | 21 |
| Method/scenario cells | 252 |
| Cells with 30 seeds | 216 |
| Cells with 50 seeds | 36 |
| Incomplete runs | 0 |
| Incomplete metric rows | 0 |
| Duplicate run keys | 0 |
| Ledger/result key differences | 0 |
| Scientific failures retained | 19 |

The truth-class population is 6,480 known, 600 extreme-known, and 1,200 OOD
method-episodes.  All 19 scientific failures are explicitly classified as
`catastrophic_not_recovered`.  There are zero safety-boundary, NaN,
persistent-command-violation, or solver-without-fallback catastrophic flags.

Failures by method are: B1 2, B2 4, B3 1, P 3,
`fixed-K4-unlabeled` 3, `labeled-library` 1, `no-OOD` 4, and `no-worst` 1.
B0, B4, `no-tightening`, and `no-transition-prior` have zero scientific
failures.  The matrix was not altered in response to these results.

## Main closed-loop findings

The proposed P method completes 687/690 episodes (99.565%).  Its overall mean
frequency IAE is 1.1956, maximum absolute frequency deviation is 0.2353 Hz,
and observed settling time is 13.339 s.  The most relevant frozen paired
comparisons are:

| Metric (P minus reference) | B1 | B2 |
|---|---:|---:|
| Mean frequency IAE | -0.3066, Holm p=0.000200 | +0.1729, Holm p=0.000200 |
| Mean settling time | -7.876 s, Holm p=0.000200 | +6.305 s, Holm p=0.000200 |
| Mean maximum absolute frequency | +0.001163 Hz, Holm p=0.000600 | +0.000321 Hz, not significant |
| Catastrophic-failure incidence | +0.001449, not significant | -0.001449, not significant |

Thus P materially improves IAE and settling time relative to the fixed
validation-selected model B1, but it does not dominate the online single-model
RLS MPC B2.  P's small maximum-frequency increase over B1 is statistically
detectable because of pairing but is only about 1.16 mHz.  No method is claimed
to be uniformly best.

On the 100 OOD episodes per method, P has no scientific failure, mean IAE
1.2773, mean maximum absolute deviation 0.2468 Hz, and mean fallback duration
18.02 s.  For comparison, B1 has IAE 1.7797 with no failure, while B2 has IAE
1.4954 with four failures.  On ordinary known episodes P has three failures
and mean IAE 1.0717; B2 has no known failure and mean IAE 0.8751.  These split
results are retained to avoid an aggregate-only performance claim.

B4 is not a deployable baseline: it consumes evaluator truth.  Its overall
mean Oracle regret is exactly zero by construction.  P's mean Oracle regret is
0.1554; B1 is 0.4619 and B2 is -0.0176.  Negative empirical regret for a
non-Oracle method is possible because B4 is an isolated ARX-selection upper
bound, not a per-episode global optimum over every controller architecture.

## Diagnostic findings and limitations

P's final-matrix online diagnostic results are materially weaker than its
closed-loop completion rate:

| Diagnostic metric | P result |
|---|---:|
| Mode accuracy | 0.3545 |
| Macro-F1 | 0.1519 |
| Brier score | 1.0180 |
| ECE | 0.4616 |
| OOD AUROC (100 OOD episodes) | 0.5213 |
| OOD AUPRC (100 OOD episodes) | 0.5280 |
| OOD detected | 15/100 |
| Mean detected-event delay | 31.87 s |
| Known-scenario false-alarm rate | 88.86 per hour |

These are final closed-loop population metrics and are not interchangeable
with Phase-4's smaller fixed diagnostic evaluation.  The poor mode/OOD
separation is a primary research limitation, not a packaging or execution
failure.  The safety state machine still converts diagnostic uncertainty and
solver rejection into auditable fallback rather than allowing an invalid MPC
solution to execute.

The forced K=4 unlabeled ablation has better OOD ranking in this final matrix
(AUROC 0.6303, AUPRC 0.6447, 48/100 detected), but worse OOD control IAE
(1.6474) and long observed settling time (35.66 s).  This is evidence against
using one diagnostic metric as a surrogate for closed-loop quality.

## Solver qualification

P's mean episode-level solve-time mean is 0.1021 s and its mean episode-level
p95 is 0.1620 s.  Its aggregate timeout rate is 0.8594%; infeasible and
inaccurate rates are both zero.  B1 and B2 are faster (mean solve times 0.0449
and 0.0428 s) and have timeout rates 0 and 0.00168%, respectively.  The paired
P-minus-B1/B2 solve-time and timeout differences are Holm-significant.

The Phase-6 stderr log contains expected backend warnings for time-limit or
inaccurate candidate returns.  The strict solver adapter rejects those
candidates, clears values, and uses fallback; the log contains no traceback,
`ERROR`, exception, or failed orchestration record.  Solver timings are
specific to this Windows host, its current load, and the installed licenses.

## Principal artifacts and hashes

| Artifact | SHA-256 |
|---|---|
| `per_episode_metrics.csv` | `d5921a52e62122ca0f6b038abd7972acc4257b4a8cb88afb7cade37b1ce83b3a` |
| `summary_metrics.csv` | `5102bc35271db83e63ffba8a2adc628e503e5c99293232a17abc572ba0dec9d6` |
| `statistical_tests.csv` | `52ecf47674c0a0f90949dd9c1751ab1eec00f8d928ac281ed66040a8c5cd1b34` |
| `diagnostic_metrics.csv` | `a68c7924593fa8b5831f5e4bb113aa57cfc5ff99d0c231f7d242458ae0401fe7` |
| `solver_metrics.csv` | `77665e62c4eaa881a8b5ac4158986a665e3218ef91637e3b460d8e7404e8e010` |
| `experiment_ledger.csv` | `7f6a35cd378734f803ac750991848744d3341c02f1f54197c04e9d90103ca3a1` |
| `protocol_lock.json` | `11b8d97819f893199016449c6ad5de2fa8107d9671f62c1aa4abda4e4e564233` |
| representative trajectory manifest | `dab9c3e40995b16118630fea3c9ecd00914e8f0a6b476443b69b5b2977159d58` |
| worst-case trajectory manifest | `4be5ff4609bbe560996c9d593e9f6dbbaec32897e7c5daac0cf162b287c944f5` |

## Phase 6 acceptance decision

PASS.  The complete frozen population is present, every failure remains in the
statistical tables, pairing is complete, uncertainty and censoring are
explicit, and the scientific limitations are reported rather than repaired
post hoc.  Phase 7 may use only these canonical final tables and authenticated
selected trajectories.
