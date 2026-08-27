# R3 acquisition-matched selective V2 panel

V2 uses the rule frozen in
`research/direction5_safe_voi_positive_region_rebuild/08_ACQUISITION_MATCHED_GATE_PREREGISTRATION.md`:
the public-state PI-gap screen is followed, only when positive, by the common
rolling acquisition prefix and registered stochastic continuation value.

The V1 run for seed 8109 predates the correction that binds the simulator's
actual capability-change time to the registered random transition.  It remains
historical development output but must be rerun under V2 before entering the
V2 panel denominator.

## High-capability seed 8109

The actual and reported capability transition both occurred at
`145.812047580 s`.  No state in the complete 720 s trajectory satisfied the
basic binding-command, frequency, ACE, SoC, and cooldown conditions for a
first-stage value evaluation.

```text
eligible first-stage evaluations        0
first-stage positive states             0
second-stage evaluations                0
acquisition windows                     0
frequency peak                          0.102435273 Hz
grid-service cost                       48.672952982 s
attempted optimization calls            181
solver failures / fallbacks             0 / 0
hard physical violations                0
```

This is a pre-screen abstention rather than a negative second-stage value.  The
executed controller is the contract-set rolling MPC by construction.

## High-capability seed 8110

The actual and reported capability transition both occurred at
`110.979067436 s`.  The independent contingency occurred at `382.896180081 s`
with magnitude `-0.0486420863 pu` in both areas.  Fifteen causally eligible
states were evaluated after the event.

```text
eligible first-stage evaluations       15
maximum predicted high-posterior value 0.064491678
first-stage positive states             0
second-stage evaluations                0
acquisition windows                     0
frequency peak                          0.203042591 Hz
grid-service cost                       60.833668059 s
attempted optimization calls            197
solver failures / fallbacks             0 / 0
hard physical violations                0
```

The maximum screen value occurred at `660 s` and remained below the frozen
`0.08` computational threshold.  High realized capability was therefore not
sufficient for information acquisition.  Since no surplus window or posterior
update occurred, the executed method is the same contract-set rolling MPC by
construction; no duplicate exploit-only episode is needed for this path.

## High-capability seed 8111

The actual and reported capability transition both occurred at
`142.347745428 s`.  The independent area-1 contingency occurred at
`324.930131471 s` with magnitude `-0.0311114054 pu`.

```text
eligible first-stage evaluations        4
maximum predicted high-posterior value 1.4688e-08
first-stage positive states             0
second-stage evaluations                0
acquisition windows                     0
frequency peak                          0.094318438 Hz
grid-service cost                       38.544750902 s
attempted optimization calls            185
solver failures / fallbacks             0 / 0
hard physical violations                0
```

All four candidate states had essentially zero decision value for a high-power
posterior.  This is another strict abstention path, not evidence that the
positive region is globally empty.

## High-capability seed 8112

The actual and reported capability transition both occurred at
`136.625620493 s`.  The independent area-1 contingency occurred at
`267.898503148 s` with magnitude `+0.0496142384 pu`.

```text
eligible first-stage evaluations       11
maximum predicted high-posterior value 0.052842445
first-stage positive states             0
second-stage evaluations                0
acquisition windows                     0
frequency peak                          0.150374477 Hz
grid-service cost                       56.650930087 s
attempted optimization calls            192
solver failures / fallbacks             0 / 0
hard physical violations                0
```

The maximum screen value occurred at `308 s` and remained below the frozen
`0.08` threshold.  This fourth corrected trajectory is therefore also an
abstention path exactly equal to the contract-set rolling MPC.  The V2 panel is
currently four safe abstentions from four high-capability trajectories; this
still measures sparsity, not emptiness, because no state has yet reached the
second-stage calculation.

## High-capability seed 8115

The actual and reported capability transition both occurred at
`122.485690109 s`.  The independent both-area contingency occurred at
`275.278198450 s` with magnitude `+0.0439276893 pu`.

```text
eligible first-stage evaluations        8
maximum predicted high-posterior value 0.007206253
first-stage positive states             0
second-stage evaluations                0
acquisition windows                     0
frequency peak                          0.193486689 Hz
grid-service cost                       54.039817405 s
attempted optimization calls            189
solver failures / fallbacks             0 / 0
hard physical violations                0
```

The maximum screen value occurred at `336 s`.  The trajectory therefore lies
well inside the action-insensitive abstention region and executes the contract
MPC throughout.

## High-capability seed 8117

The actual and reported capability transition both occurred at
`138.191498236 s`.  The independent area-0 contingency occurred at
`344.288964360 s` with magnitude `+0.0270357366 pu`.

```text
eligible first-stage evaluations        0
first-stage positive states             0
second-stage evaluations                0
acquisition windows                     0
frequency peak                          0.091755204 Hz
grid-service cost                       40.593881260 s
attempted optimization calls            181
solver failures / fallbacks             0 / 0
hard physical violations                0
```

No point simultaneously met the binding-command, frequency, ACE, SoC, and
cooldown conditions.  This is a causal pre-screen abstention and supplies no
second-stage value observation.
