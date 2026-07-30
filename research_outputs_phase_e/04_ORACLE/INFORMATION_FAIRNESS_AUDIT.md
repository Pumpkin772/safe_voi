# E3 information fairness audit

All deployable methods receive `PublicObservationV2`, the same causal state/load estimator, the same update period, declared SG reserve, and no capability truth.  Nominal MPC retains nameplate capability; RLS uses only past command/POI-power pairs; robust MPC uses the frozen global worst-case set.  Only O2 receives current truth and true current physical state, through a method whose class and output are explicitly marked evaluation-only.  No controller receives future loads, events, modes, or final seeds.
