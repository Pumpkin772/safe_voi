# Novelty Comparison

| Work family | Black-box/mode change | Multi-area ACE/tie-line | `Tdet<Tcrit` before harm | Constraint-safe adaptation | Native RMS/DAE | Phase C distinction |
|---|---:|---:|---:|---:|---:|---|
| Black-box/switching IBR identification | Yes | No | No | No | Limited | Replaces label recovery with control-equivalent capability sets and closes the control loop |
| Hierarchical/data-driven IBR frequency control | Often | Yes | No | Partial | Some | Adds unannounced physical capability change, unknown-load separation and responsibility transfer |
| DeePC/Koopman/data-driven MPC | Generic | Usually no | No | Under assumptions | Rare | Makes power/ramp/delay/energy capability explicit and subjects branch choice to science Gates |
| Robust/set-adaptive MPC | Generic uncertainty | No | No | Yes | No | Specializes truth-covering sets/tubes to multi-area IBR capability and hidden load/SoC |
| Dual/safe-exploration MPC | Generic uncertainty | No | Generic only | Yes | No | Permits excitation only if passive `Tdet<Tcrit` fails and the frequency safe set certifies it |
| Multi-area LFC/AGC MPC | No | Yes | No | Varies | Usually aggregate | Adds opaque IBR capability change, external-only diagnosis and Plant B cross-validation |
| NERC/IEEE modeling guidance | Field evidence | System-level | No algorithm | Requirements | RMS/EMT | Converts industry motivation into a falsifiable closed-loop control protocol |

Phase C must not claim first use of any row's individual method. Its claim, if the Gates support it, is the validated intersection described in the final column.
