# Model validation report

C3 independently checked the corrected implementation. Analytic/central-difference Jacobian maximum error is `0`. The selected integration step is 0.01 s against the 0.005 s reference; its maximum audited metric error is 0.699%, below the locked 1% rule. All required 0.005/0.01/0.02/0.05 s runs are retained in `step_convergence.csv`. Plant A/B both initially move in the physically correct direction after the same positive load step.
