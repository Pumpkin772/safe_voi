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
calculation will be repeated after total-system commit returns below the
unchanged preflight limit.
