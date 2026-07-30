# Capability-Set Robust Tube MPC (branch R)

The selected controller solves a receding finite-horizon QP over explicit state/action sequences and ZOH delayed dynamics. It uses the full preregistered external capability set: 0.03 pu effective power, 0.012 pu/s ramp, and 2 s delay. A finite-horizon box tube propagates public model/load-error bounds under an LQR ancillary gain; state and input limits are tightened by the resulting radii. A fixed-allocation PI action is an optimization reference, not the executed policy. The optimizer executes its first action when feasible and its predicted terminal state lies in the SG-only backup box; otherwise a separately stateful SG-only PI backup is used.

The method never identifies or reads a current capability label. Claims are limited to the registered global set and empirical Plant A/B tests unless E7 certificates justify stronger language.
