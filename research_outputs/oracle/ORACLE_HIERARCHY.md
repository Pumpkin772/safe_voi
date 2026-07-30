# Oracle hierarchy

| Level | Current full state | Current capability | Future load/regime | Purpose |
|---|---:|---:|---:|---|
| O0 | no | no | no | deployable nominal-information reference |
| O1 | yes | no | no | state-information diagnostic |
| O2 | yes | yes | no | current-capability materiality Oracle |
| O3 | yes | yes | yes | optional clairvoyant ceiling only |

O2 is evaluation-only. It is a rolling four-action, four-block nonlinear multiple-shooting NMPC using the same causal load estimate as the nominal baseline. Solver success establishes a qualified local solution only; no global/exact-optimum claim is made.
