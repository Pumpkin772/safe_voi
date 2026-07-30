# Model validation report

C3 independently checked the corrected implementation. Analytic/central-difference Jacobian maximum error is `0`. The selected integration step is 0.005 s; all required 0.005/0.01/0.02/0.05 s runs are retained in `step_convergence.csv`. The 0.01 s comparison is diagnostic, not used to relax the fixed 1% acceptance rule. Plant A/B both initially move in the physically correct direction after the same positive load step.
