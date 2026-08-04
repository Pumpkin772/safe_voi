# R2 repair ledger

## Repair 1 — revocable online performance witness

The first registered R2 run passed observer selection, delay/ramp coverage,
change reset, no-excitation, baseline stability and rolling-MPC structure, but
failed power coverage (55/60, 91.67%) and false optimism (263/5,340, 4.93%).
All misses were concentrated in registered abrupt capability-drop episodes.

Diagnosis order: code and numerical execution were sound; the estimator rule
was misspecified. It promoted the largest historical achieved power and allowed
immediate re-promotion after reset. A historical peak is not causal evidence of
current deliverability after an unannounced transition.

Repair 1 replaces that monotone peak with a short-lived witness requiring six
same-direction, high-request observations and a near-steady delivered-power
plateau. The witness is revoked immediately when its causal conditions are not
met and after every model-set reset. The contract guaranteed floor remains the
only hard safety capability. No Gate, scenario, seed, split or physical bound
was changed.
