# R3 acquisition-matched selective V2 panel

V2 uses the rule frozen in
`research/direction5_safe_voi_positive_region_rebuild/08_ACQUISITION_MATCHED_GATE_PREREGISTRATION.md`:
the public-state PI-gap screen is followed, only when positive, by the common
rolling acquisition prefix and registered stochastic continuation value.

The V1 run for seed 8109 predates the correction that binds the simulator's
actual capability-change time to the registered random transition.  It remains
historical development output but must be rerun under V2 before entering the
V2 panel denominator.

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
