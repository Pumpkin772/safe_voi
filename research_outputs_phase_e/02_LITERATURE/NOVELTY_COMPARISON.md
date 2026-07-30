# Evidence-bounded novelty comparison

The matrix contains 75 records, including 69 formal papers or standards.  Non-exclusive preregistered theme counts are: black-box/multimode IBR 11; data-driven/black-box frequency control 12; set-membership/adaptive/tube MPC 16; active/dual/safe identification 8; multi-area AGC/ACE/constrained resources 15.

## Closest-work comparison

| Closest work | What it establishes | Unannounced multidimensional capability change | Causal external capability set | Tcrit/materiality before identification | Multi-area ACE responsibility | Safe rolling constrained control | Native RMS/DAE cross-validation |
|---|---|---:|---:|---:|---:|---:|---:|
| Huang et al., IEEE TSG, DOI 10.1109/TSG.2025.3647551 | Continuous-time black-box IBR models with unknown modes and noisy data | no | no | no | no | no | no |
| Rezaei et al., EPSR, DOI 10.1016/j.epsr.2026.113699 | Data-driven rolling Koopman frequency control using black-box IBRs | no | no | no | limited | yes | no |
| Parsi et al., IFAC, DOI 10.1016/j.ifacol.2023.10.1132 | Exact set-membership dual adaptive MPC with robust constraints | generic parameters | parameter set | no | no | yes | no |
| Wang et al., Journal of Energy Storage, DOI 10.1016/j.est.2024.113340 | Tube MPC for multi-area LFC with hybrid storage | no | no | no | yes | yes | no |
| Ekomwenrenren et al., IEEE TPWRS, DOI 10.1109/TPWRS.2023.3337011 | Model-free, area-based fast frequency control using IBRs | no | no | no | frequency areas | not capability-set safe | no |

## Resulting boundary

Existing work covers every ingredient separately and several pairwise combinations.  This audit found no included work that jointly studies an *unannounced current power/ramp/delay/energy/availability change*, estimates a *causal external feasible set*, first proves *control materiality and a counterfactual Tcrit*, and then performs *safe multi-area ACE responsibility reallocation* with native network cross-validation.  Phase E may test that intersection but may not claim priority for any individual ingredient.
