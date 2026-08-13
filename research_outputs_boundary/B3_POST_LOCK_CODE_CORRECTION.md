# Retained post-lock deterministic code correction

The first genuine 3600 s normal-profile attempt (`seed=7450`) stopped at about
3000 s because measured BESS energy reached its physical lower bound.  The
failed attempt and its traceback are retained under `B3_NORMAL1H`.

Diagnosis found a deterministic integration error: the causal two-area load
MHE returned a signed vector, but `RollingBoundaryController` reduced it to
`max(abs(load))` and `solve_policy` reconstructed the forecast as two positive
loads.  Consequently the BESS could keep discharging when the observed load
had reversed sign.

The correction passes the existing signed causal MHE vector to the unchanged
rolling robust MPC.  It does not alter any objective weight, physical limit,
probe, boundary threshold, scenario, profile, or seed.  It does not rerun or
replace the one-shot final boundary map: the registered offline boundary engine
already uses its declared load vector and is unaffected.  Affected nonlinear
closed-loop evidence must be recomputed or explicitly withdrawn before final
reporting.

The normal-profile resource guard was also corrected operationally after one
retained interruption showed that a 6 GiB *system-wide* commit-growth trigger
could be tripped by an unrelated MATLAB process even though the guarded Python
tree used only 0.42 GiB and total commit remained below 46%.  The relative
growth trigger is 20 GiB for later attempts, while the binding 80% preflight,
92% runtime commit, 8 GiB available-memory, 3 GiB process-tree, and two-
descendant limits remain unchanged.  This changes no controller, physical,
scenario, seed, objective, or result criterion.

For the fresh-process native ANDES replay, one retained episode interruption
showed that an unrelated persistent interactive MATLAB session left about
8.4 GiB available while the measured ANDES process-tree peak was only
0.57 GiB.  The native-Plant-B minimum-available-memory stop was therefore set
to 6 GiB; the 80%/92% system-commit, 20 GiB growth, 3 GiB process-tree, and
two-descendant limits remain binding.  This is an execution-resource setting,
not a scientific or controller change.
