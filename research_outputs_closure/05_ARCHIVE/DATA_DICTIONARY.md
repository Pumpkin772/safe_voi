# Direction5 closure data dictionary

## Primary episode and cycle tables

- `FINAL_EPISODES.parquet`: one row per scenario-method run. Key fields include scenario ID, seed, plant, condition, physical domain, method, success/terminal flags, performance metrics, solver/restoration/fallback counts, and provenance.
- `FINAL_CYCLES.parquet`: rolling control decisions and applied actions. The optimization-decision denominator includes accepted primary, accepted restoration, fallback, and unhandled decisions; raw solver invocations additionally count restoration attempts.
- `FINAL_PAIRED_ROWS.parquet`: paired DCSV-CR versus contract-only rows after physical-domain classification.

## Registered summaries

- `FINAL_STATISTICS.csv`: scenario-balanced aggregate means and paired absolute differences. Mean episode-relative ratios are diagnostic only.
- `FINAL_BOOTSTRAP.csv`: seed/design-cell hierarchical bootstrap intervals.
- `FINAL_PAIRED_FAILURES.csv`: mutually exclusive both-success, one-method-fails, both-fail, not-evaluated, physically-infeasible, and contract-violation categories.
- `FINAL_SOLVER_DENOMINATOR.csv`: attempted optimization decisions and raw solver invocations with auditable identities.
- `FINAL_KNOWN_OOD.csv`, `FINAL_DOMAIN_STATISTICS.csv`, and `FINAL_PLANT_DIRECTION.csv`: registered subgroup evidence.

## Boolean and missing-value semantics

`False` is a measured negative result. `NOT_EVALUATED` is neither failure nor success. `PHYSICALLY_INFEASIBLE_CERTIFIED` is separated before ordinary controller scoring. Empty cells in penalty columns denote the both-success primary analysis, not missing experiments.

## Units

Frequency is Hz; time is seconds; power and ACE quantities are per-unit unless named otherwise; energy state is measured SoC; tie-line RMS is per-unit. Solver time fractions are dimensionless fractions of the control period.
