# R3 optimistic-continuation screen V4

V4 tests whether capability information can matter later in the registered
240 s information lifetime even when the current one-step full-versus-high
MPC value gap is zero or very small.  The continuation bank, 16 s anchor spacing,
`1e-6` entry level, development seeds, and exact-audit state-selection rule were
fixed in `11_OPTIMISTIC_CONTINUATION_SCREEN.md` before these results were run.

## High-capability seed 8120: screen-only trajectory

The ordinary controller completed the full 720 s nonlinear Plant-A trajectory
without probing.  It found five causally and physically eligible states.  The
current local value was numerically zero at four states and only `0.00141` at
the fifth, while the optimistic future-opportunity value was positive at every
state:

| time (s) | current local gap | optimistic future value `S` | screen solves | failures |
| ---: | ---: | ---: | ---: | ---: |
| 422 | -0.0000000496 | 0.0180883641 | 536 | 0 |
| 438 | 0.0014124798 | 0.0136576538 | 536 | 0 |
| 454 | -0.0000000907 | 0.0114427880 | 536 | 0 |
| 470 | 0.0000001565 | 0.0107895586 | 536 | 0 |
| 540 | 0.0000000262 | 0.0051120756 | 400 | 0 |

```text
causally eligible states                5
states above S > 1e-6                   5
exact second-stage evaluations          0
acquisition windows                     0
frequency peak                          0.141185661 Hz
ACE IAE                                  5.520351108 pu s
tie IAE                                  1.589438061 pu s
attempted optimization calls            2910
solver failures / fallbacks             0 / 0
hard / command / contract violations    0 / 0 / 0
```

This trajectory demonstrates the intended distinction between instantaneous
and lifetime information value: the local gap would reject four of the five
states at the `1e-6` numerical entry level and strongly understate the fifth,
whereas public future load continuations expose later capability-binding
opportunities.  `S` remains an optimistic recall screen, not evidence that
acquisition has positive net value.

The preregistered maximum-`S` exact state is `422 s`.  The independently fixed
uniform selection using RNG seed `58100 + 8120` chose index 4 of the time-sorted
eligible states, namely `540 s`.  Neither selection used an exact value.

## Exact-audit execution note

The first `422 s` exact attempt did not start because its descriptive run label
exceeded the Windows path-length limit.  It consumed no simulation result; the
label was shortened without changing any scientific setting.

The unchanged shortened-label attempt was then interrupted after 6348.906 s by
the machine-wide system-commit guard.  Peak total-system commit was 96.73%,
while this research process tree used at most 0.518 GiB and one descendant.
Four workers from an unrelated `peee-py311` fit started immediately before the
commit spike.  No exact scientific result was produced.  The same `422 s`
calculation was repeated after total-system commit returned below the unchanged
preflight limit.

## Exact result at the maximum-S state

The unchanged repeat completed at `422 s`.  The implemented common acquisition
prefix is 10 s: 8 s of control-aligned surplus followed by the estimator's 2 s
post-action response.  The original V4 prose incorrectly stated 12 s; both the
screen and exact calculation used the same physical 10 s prefix, and the prose
was corrected before running the remaining audit states.

```text
screen S                                0.0180883641
current local gap                      -0.0000000496
low-power branch information values     0, 0, 0, 0
high-power branch information values   +0.0364397906
                                       +0.0012033051
                                       +0.0378244662
                                       +0.0025709752
worst high-power value                 +0.0012033051
continuation paths / steps               8 / 115
continuation duration                    230 s
internal exact solves / failures         7392 / 0
weak-Pareto information decision         positive
hard / command / contract violations     0 / 0 / 0
fallbacks                                0
```

Thus the future-opportunity screen successfully recalled a state that the local
`1e-6` screen would reject.  The result is also highly branch dependent: the
two 1.5 s-delay high-power candidates have much smaller information value than
the 0.2 s-delay candidates, but the most conservative high branch remains
strictly positive.  This is one screen-positive development state; it measures
recall and over-optimism at that state, not the false-negative rate of V4.

Subsequent exact-only audit runs use the states already selected in their
screen-only files and do not recompute the 400--536 screen solves.  The exact
acquisition prefix, eight continuation paths, four distinct high-capability
truths, and separate exploit/posterior closed loops are unchanged.

## Exact result at the fixed-uniform state

The first exact-only attempt at `540 s` was scientifically invalid: suppressing
the earlier diagnostic times left the controller's initial acquisition-window
flag enabled, so it probed before the selected state and produced zero causal
value evaluations.  The run is retained as an implementation failure
(`361` attempted solves, one unintended probe, no physical violation).  The
flag initialization was corrected so that `--screen-only` diagnostic runs can
open a window only at the explicitly selected time.  The first corrected run
was interrupted externally after 6451 s and produced no scientific result.

The unchanged corrected repeat completed at the independently fixed-uniform
state `540 s`:

```text
screen S from screen-only trajectory     0.0051120756
current local gap                       +0.0000000262
low-power branch information values      0, 0, 0, 0
high-power branch information values    +0.0011800515
                                        -0.0082777363
                                        +0.0012844332
                                        -0.0085705992
worst high-power value                  -0.0085705992
continuation paths / steps                8 / 85
continuation duration                     170 s
internal exact solves / failures          5472 / 0
weak-Pareto information decision          nonpositive
hard / command / contract violations      0 / 0 / 0
fallbacks                                 0
```

The fixed-uniform state is therefore a V4 false positive: its optimistic
future-opportunity value is positive, but information is harmful in both
1.5 s-delay high-power branches after the full acquisition and recourse
counterfactual is included.  Together, the two seed-8120 audits show that the
screen has useful recall but is not by itself a safe trigger: exact information
value changes sign across eligible states on the same physical trajectory.
No probe was issued in the valid exact-only run, all `5834` attempted solves
completed, and the ordinary controller did not read hidden truth.

## High-capability seed 8121: screen-only trajectory

The second preregistered development trajectory completed without probing and
produced six causally eligible states.  The current local value remained below
the `1e-6` entry level at every state, whereas every future-opportunity screen
was positive:

| time (s) | current local gap | optimistic future value `S` | screen solves | failures |
| ---: | ---: | ---: | ---: | ---: |
| 492 | +0.0000001305 | 0.0076048086 | 508 | 0 |
| 508 | +0.0000000006 | 0.0056097478 | 472 | 0 |
| 564 | +0.0000002704 | 0.0098489236 | 348 | 0 |
| 580 | +0.0000000289 | 0.0079397219 | 312 | 0 |
| 600 | -0.0000001290 | 0.0092189879 | 264 | 0 |
| 616 | -0.0000000220 | 0.0080191885 | 228 | 0 |

```text
causally eligible states                6
states above S > 1e-6                   6
exact second-stage evaluations          0
acquisition windows                     0
frequency peak                          0.107679720 Hz
ACE IAE                                  5.118000322 pu s
tie IAE                                  1.581808440 pu s
attempted optimization calls            2499
solver failures / fallbacks             0 / 0
hard / command / contract violations    0 / 0 / 0
```

The maximum-`S` rule selected `564 s`.  The independently fixed RNG seed
`58100 + 8121` selected index 3 of the time-sorted states, hence `580 s`.

## Seed 8121 exact result at the maximum-S state

The exact acquisition-and-recourse counterfactual at `564 s` was positive in
all four high-power capability branches:

```text
screen S from screen-only trajectory     0.0098489236
current local gap                       +0.0000002704
low-power branch information values      0, 0, 0, 0
high-power branch information values    +0.1055752595
                                        +0.0148639527
                                        +0.1070791649
                                        +0.0142762861
worst high-power value                  +0.0142762861
continuation paths / steps                8 / 73
continuation duration                     146 s
internal exact solves / failures          4704 / 0
weak-Pareto information decision          positive
hard / command / contract violations      0 / 0 / 0
fallbacks                                 0
```

This is a second development trajectory with a strictly positive exact state.
The conservative branch value is more than an order of magnitude larger than
the positive seed-8120 maximum-S state, despite a local one-step value below the
numerical entry level.  The two 1.5 s-delay branches again provide the limiting
values, but remain positive here.  The result reproduces the existence of a
future-only positive information-value state in development; it does not yet
establish its frequency or independent-validation performance.

## Seed 8121 exact result at the fixed-uniform state

The independently selected `580 s` state was not positive after the complete
counterfactual:

```text
screen S from screen-only trajectory     0.0079397219
current local gap                       +0.0000000289
low-power branch information values      0, 0, 0, 0
high-power branch information values    +0.0436937957
                                        -0.0105516305
                                        +0.0553769327
                                        -0.0123004172
worst high-power value                  -0.0123004172
continuation paths / steps                8 / 65
continuation duration                     130 s
internal exact solves / failures          4192 / 0
weak-Pareto information decision          nonpositive
hard / command / contract violations      0 / 0 / 0
fallbacks                                 0
```

As in seed 8120, the fixed-uniform screen-positive state is a false positive
because both 1.5 s-delay high-power branches are adverse.  After two
development seeds, the maximum-screen state is exact-positive in `2/2`
trajectories, while the fixed-uniform screen-positive state is exact-positive
in `0/2`.  This small sample supports the ranking value of `S`, but rejects a
plain `S > 0` acquisition trigger.  The remaining preregistered seeds are
needed before fixing a selective rule.

## High-capability seed 8122: screen-only trajectory

The third preregistered trajectory produced seven eligible states.  Six had a
strictly positive screen; the final `714 s` state had no remaining continuation
anchor and therefore zero screen value:

| time (s) | current local gap | optimistic future value `S` | screen solves | failures |
| ---: | ---: | ---: | ---: | ---: |
| 330 | +0.0000000034 | 0.0828631116 | 536 | 0 |
| 350 | -0.0000000002 | 0.0910195543 | 536 | 0 |
| 366 | -0.0000000642 | 0.0714912201 | 536 | 0 |
| 610 | +0.0000000158 | 0.1095560385 | 244 | 0 |
| 636 | +0.0000000132 | 0.0928335993 | 184 | 0 |
| 652 | +0.0000000016 | 0.0108827557 | 148 | 0 |
| 714 | -0.0000003118 | 0.0000000000 | 0 | 0 |

```text
causally eligible states                7
states above S > 1e-6                   6
exact second-stage evaluations          0
acquisition windows                     0
frequency peak                          0.215795414 Hz
ACE IAE                                  5.456747482 pu s
tie IAE                                  1.233610400 pu s
attempted optimization calls            2552
solver failures / fallbacks             0 / 0
hard / command / contract violations    0 / 0 / 0
```

The maximum-`S` state is `610 s`.  Fixed RNG seed `58100 + 8122` selected
index 0 of the time-sorted eligible states, namely `330 s`.

## Seed 8122 exact result at the maximum-S state

The exact counterfactual at `610 s` was positive in every high-power branch:

```text
screen S from screen-only trajectory     0.1095560385
current local gap                       +0.0000000158
low-power branch information values      0, 0, 0, 0
high-power branch information values    +0.0415124841
                                        +0.0184103686
                                        +0.0413305025
                                        +0.0184455168
worst high-power value                  +0.0184103686
continuation paths / steps                8 / 50
continuation duration                     100 s
internal exact solves / failures          3232 / 0
weak-Pareto information decision          positive
hard / command / contract violations      0 / 0 / 0
fallbacks                                 0
```

The maximum-screen rule has now selected an exact-positive state on all three
completed development trajectories.  The conservative exact values are
`+0.0012033`, `+0.0142763`, and `+0.0184104`; local one-step values at all three
states were below `1e-6`.  This strengthens the evidence that `S` contains
useful temporal-ranking information, while the fixed-uniform audits continue
to measure whether that ranking is selective enough.

## Seed 8122 exact result at the fixed-uniform state

Unlike the first two fixed-uniform audits, the independently selected `330 s`
state was positive in all high-power branches:

```text
screen S from screen-only trajectory     0.0828631116
current local gap                       +0.0000000034
low-power branch information values      0, 0, 0, 0
high-power branch information values    +0.0742052885
                                        +0.0336386712
                                        +0.0734507639
                                        +0.0351050518
worst high-power value                  +0.0336386712
continuation paths / steps                8 / 115
continuation duration                     230 s
internal exact solves / failures          7392 / 0
weak-Pareto information decision          positive
hard / command / contract violations      0 / 0 / 0
fallbacks                                 0
```

After three development seeds, maximum-screen states are exact-positive in
`3/3`, and fixed-uniform eligible states are exact-positive in `1/3`.  The
seed-8122 result shows that the positive region is not confined to one selected
maximum or a short end-of-episode interval: it includes an independently chosen
early state with 230 s of remaining recourse value.  The mixed fixed-uniform
outcomes also preserve the boundary evidence rather than turning V4 into an
unconditional probe rule.
