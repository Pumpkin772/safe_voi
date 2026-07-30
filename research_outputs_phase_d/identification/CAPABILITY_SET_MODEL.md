# Causal control-relevant capability-set model

The deployable estimator accepts only the issued total BESS command and measured POI active power. A delayed one-step actuator model is evaluated over the registered delay candidates. Achieved command/output pairs raise guaranteed lower power/ramp capability; registered physical ratings remain upper bounds. Energy starts from an operator-declared interval and is propagated with measured POI power and efficiency bounds. A one-sided recursion `g_k=max(0,g_{k-1}+|e_k|/epsilon-nu)` uses only sample `k` and prior state. An alarm expands the set to the global physical set; it never selects an OEM/source label.

The paired augmented Kalman filter estimates unknown area loads from measured frequency, tie-line, SG mechanical power and BESS POI power. True load is accepted only by the evaluation scorer.
