# Limitations and Failures

Final decision: `COMBINED:CONTROL_DESIGN_DOMINANT+MODEL_MISMATCH_DOMINANT`.

Canonical/retained planned episodes: 15120; scientific or pre-publication failures: 76; compact audit-computation failures: 0.

B4-vs-B5 mean IAE gap: 8.13%; correct-candidate Bayes delayed/censored switch fraction: 36.55%; best isolated control-factor gain: 8.63%.

B5 is a simulator-exact nonlinear *plant* benchmark with finite-horizon, finite candidate-grid shooting; it is not a proof of the globally optimal nonlinear policy. It observes current true mode/IBR parameters only and never future load or mode. Solver failures are not replaced by B0. No failed, timed-out, infeasible, censored, or pre-publication attempt is deleted. Representative trajectories were preregistered; all high-frequency raw traces are excluded from the package.
