# Frozen Phase-E scientific question and hypotheses

## Scientific question

In a stable multi-area secondary-frequency-control loop with fixed local PFR and a 2/4 s supervisory update, can a control center use only public causal histories (frequency, ACE, tie-line power, measured SG/BESS active power, and issued commands) to obtain a control-relevant external capability set for an opaque IBR/BESS before stale capability knowledge causes material control loss, and then reallocate responsibility without compromising constraints?

The target is not an OEM mode label.  It is the external feasible set for active-power headroom, ramp, delay, sustainable energy, service availability, and low-order prediction uncertainty.

## Frozen information boundary

Deployable controllers may use present and past public measurements, commands, declared nameplate bounds, and causal state/load estimates.  They may not read the true capability regime, hidden simulator parameters or states, true net load, future load/events/communication states, Oracle trajectories, or final-seed tuning information.  True quantities are evaluation-only.

## H1--H5

- **H1 (materiality):** on at least two physical capability-change mechanisms and resource-stressed cases, a fair rolling current-capability Oracle improves physical success or at least two frequency/ACE/tie-line metrics relative to the best deployable baseline.  It is falsified if a qualified Oracle has no material value on both Plant A and Plant B.
- **H2 (passive information):** natural closed-loop public I/O yields a sufficiently covering and contracted capability set before the counterfactual control-critical time.  It is falsified by a valid estimator failing coverage/timing for structural or excitation reasons rather than code defects.
- **H3 (safe active information):** only if H2 fails, finite safe probing can add information and contract the set before Tcrit without violating frequency, ACE, or resource constraints.  It is falsified if informative probes are unsafe or safe probes are uninformative.
- **H4 (control value):** the single Gate-selected P/A/R method improves multi-area SFR against the best deployable baseline without reducing physical success or safety on the locked final matrix.
- **H5 (certifiability):** the selected branch admits a code-matched tube/error bound, constraint tightening, and SG terminal backup yielding recursive feasibility or finite-horizon safety over its stated Plant-A scope.

## Counterfactual control-critical time

Starting from matched state, disturbance, and randomness, compare a stale-model deployable controller with the evaluation-only current-capability Oracle.  Tcrit is the first time their cumulative weighted frequency/ACE/tie-line performance gap plus physical violations reaches the preregistered materiality threshold.  Command/output mismatch area is reported only as a diagnostic and is not the definition of control loss.

## Gate-selected branch rule

Choose **P** if passive coverage, contraction, and timing pass; choose **A** only if passive fails and safe active information passes; otherwise choose **R**, a non-identifying full-capability-set robust MPC.  Only one branch may be implemented after the Gate.
