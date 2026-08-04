# Phase I correction and retraction

## Corrected verdict

The Phase-I terminal claim is withdrawn as decisive scientific evidence.  The
frozen run remains evidence about the tested prototype, but its method-level
termination was driven by an unstable primary statistic, omission of the
contract-only rolling MPC comparator, a heuristic deliverability estimator, and
an incomplete solver denominator.

```text
PHASE_I_TERMINATION: WITHDRAWN
CORRECTED_INTERPRETATION: PROTOTYPE_FAILED_REGISTERED_GATES_UNDER_DEFECTIVE_ATTRIBUTION
FINAL_DIRECTION5_DECISION: PENDING_R1_TO_R5
```

No Phase-I episode, warning, threshold, or raw result was changed.  This R0
analysis reads only the frozen Phase-I evidence.

## Scenario-balanced both-success aggregates

| metric | Phase-I DCSV | fixed-allocation PI | aggregate improvement |
|---|---:|---:|---:|
| frequency_peak_hz | 0.302941 | 0.295969 | -2.36% |
| ace_iae_pu_s | 2.27489 | 3.56221 | 36.14% |
| tie_rms_pu | 0.00332542 | 0.00429769 | 22.62% |

The diagnostic mean of episode-wise relative ratios is retained in the CSV for
forensic reproduction only and is explicitly not a primary metric.

## Corrected solver denominator

- attempted optimization decisions: 20273;
- inferred raw solver invocations: 21097;
- fallback outcomes omitted by the old success-only denominator: 712;
- unresolved mathematical-infeasibility fraction of attempted decisions:
  3.512060%;
- fallback fraction of attempted decisions: 3.512060%.

Thus correcting the denominator does not rescue the Phase-I prototype's solver
Gate; it only makes the failure rate auditable.

## Missing comparator and attribution

`RollingContractMPC` existed in Phase I but was not included in I6.  Because the
online envelope altered only an objective weight, I6 could not attribute any
observed difference to a contract-safe online-capability contribution.  R0 does
not impute the missing comparator result.
