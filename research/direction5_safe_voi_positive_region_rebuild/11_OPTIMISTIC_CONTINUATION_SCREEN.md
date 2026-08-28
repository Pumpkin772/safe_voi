# Optimistic continuation screen

The numerical local-gap screen recovered a positive online development pair at
seed 8110, including strict high-capability information value and a non-adverse
low-capability branch.  It remains only provisional: a zero local gap at the
current instant does not rule out a binding capability opportunity later in the
240 s information lifetime.  The remaining old-panel V3 episodes are therefore
not used to freeze a final screen.

## Causal screen

For each causally eligible public state, the V4 screen uses four fixed public
continuation paths with integration seeds:

```text
57101, 57102, 57103, 57104
```

These are independent of the eight-path exact-value bank and every episode
seed.  The first 10 s use the current causal MHE load, matching the implemented
8 s acquisition action and 2 s estimator response prefix.  The remaining path follows the registered bounded
OU-plus-contingency law.  A contract-set MPC is rolled every 4 s along a fixed
public contract-floor model (minimum power, minimum ramp, maximum delay).  At
16 s anchors beginning after the 10 s prefix, the full-set and high-power-set MPC values
are evaluated at the same public predicted state.

The initial version of this paragraph incorrectly said `12 s`.  The executable
definition has always derived the prefix from the physical timing above and
used five 2 s steps, i.e. `10 s`, in both the screen-only seed-8120 trajectory
and its exact audit.  This development-stage documentation correction was made
after inspecting the first exact result; it changes no code, trajectory, seed,
threshold, continuation path, or reported value.

The screen value is

```text
S = max over public paths and anchors of max(J_full - J_high, 0).
```

It assumes successful high-power information, does not deduct acquisition
cost, and takes a maximum rather than an average.  It is therefore deliberately
optimistic for screening.  It is not claimed to be a theorem-level upper bound
because the posterior policy can alter the future state trajectory.  Only the
existing eight-path, eight-capability acquisition-matched calculation decides
whether information is positive.

The numerical entry condition is `S > 1e-6`, using the already fixed solver
margin.  Any screen propagation or solve failure is treated as inconclusive and
sent to the exact calculation rather than rejected.

## New fixed development sample

The next eight previously unused 4 s development seeds, selected numerically
before running V4, are:

```text
8120, 8121, 8122, 8123, 8124, 8125, 8126, 8128
```

Seeds 8127 and later previously used seeds are skipped because their outputs
already exist.  The screen is first recorded without issuing a probe or calling
the exact second stage.  For each seed with eligible states, exact offline value
is then computed at at most two states selected before their exact values are
seen:

1. the state with maximum `S`;
2. one state selected uniformly from the time-sorted eligible states using RNG
   seed `58100 + episode_seed`.

If the two rules select the same state, that state is evaluated once.  If a
trajectory has no eligible state, no exact state is invented or replaced with a
different episode.

The screen is suitable to freeze only if none of the audited exact-positive
states has `S <= 1e-6`.  False positives are allowed because the exact second
stage remains the decision.  If a false negative occurs, the screen may only be
made more permissive; the physical distribution, probe, objective, capability
sets, and numerical threshold remain unchanged.

The earlier 8110/8112 diagnostic states and the V3 seed-8110 positive pair do
not enter the V4 screen-error denominator.  They remain method-development
evidence explaining why a future-lifetime screen is necessary.
