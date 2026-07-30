# Final results interpretation

Phase E recovered a stable physical platform and a qualified current-capability Oracle. H1 is supported: O2 qualified at 97.75% of episodes with successful-solve residual p99 2.23e-7, and material cells covered all five mechanisms and all three SG tensions with Plant A/B direction consistency.

Natural closed-loop data did not support passive capability sets (H2 falsified). Safe active probing produced information in three mechanisms but increased frequency IAE by 261%, ACE IAE by 280%, physical failures, and exceeded the mileage budget (H3 falsified). The immutable Gate rule therefore selected branch R.

Branch R passed success, performance, real-time, tube, fallback, and Plant A/B direction components. On validation, success was 88.0% versus 89.0%; paired improvements were 31.5% frequency IAE, 21.6% ACE IAE, and 25.1% tie-line IAE. Nevertheless, solver infeasibility was 1.846%, above the 1% Gate. G6 is fatal, so the binding result is **METHOD_NOT_SUPPORTED_BY_EVIDENCE**.

E7 and E8 are explicitly not evaluated. No final seed, known/OOD final comparison, recursive-feasibility theorem, or robust-safety claim is supplied.
