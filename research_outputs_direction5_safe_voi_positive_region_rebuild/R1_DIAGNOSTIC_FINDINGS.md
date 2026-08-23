# R1 development diagnostics

These calculations use development models only. They are not validation or a
positive paper result.

## Information horizon alone is not the mechanism

At the predecessor's highest-VPI point, extending the one-shot prediction
horizon changed registered worst-case perfect-information value from:

| horizon | worst-case perfect-information value |
|---:|---:|
| 24 s | 0.0130019 |
| 32 s | 0.0143158 |
| 48 s | 0.0146660 |

The value saturates quickly. A longer MPC prediction horizon alone does not
create a material positive-probe region. Reusable information must instead be
valued across later rolling decisions and must expire at its registered
validity time.

## Small delay probe: positive ideal upper value, negative actual scalar value

At the same point, a 4 s allocation-neutral probe of 0.0005 pu was safe over
all eight capability vertices. Its perfect-posterior upper net value was
`+0.0035370`, but its actual scalar-observation value was `-0.0258209` because
the scalar posterior retained too many hypotheses. Larger 4/8 s probes from
0.0010 to 0.0025 pu were all negative even under perfect posterior recourse.

The active 0.0005 pu probe separated the two delay response groups by 4.45
effective standard deviations, corresponding to a two-group equal-prior error
of about 1.31%. However, the passive contract trajectory already separated the
same groups by 4.36 standard deviations (about 1.46% error) and had a larger
ideal delay-group value (`0.007886` versus `0.003537`). Thus the active dither
added little information and was dominated by passive excitation in this cell.

## Worst-capability cost hid large average operating value

As a diagnostic only, uniform averaging over capability vertices gave:

| cell | predecessor worst-capability VPI | uniform-capability expected VPI |
|---|---:|---:|
| delay-material | 0.0130019 | 0.1126558 |
| power/ramp-only | 8.4e-9 | 0.0775394 |

This shows why a stochastic operating-value formulation can be material, but a
uniform capability prior has no external evidence and therefore cannot be the
primary paper result. The implementation has been corrected so the primary
quantity is expected over the frozen event distribution and takes the minimum
paired benefit over capability hypotheses. Bayesian capability averaging is
secondary and requires an external prior.

## Binding power/ramp probe: identifiable but too expensive under old metric

In the power/ramp-only cell, the robust contract command reached 0.0451 pu,
close to the 0.045 pu guaranteed power floor. A 24 s, 0.010 pu delayed
biphasic probe was physically safe and separated the two response groups by
5.79 standard deviations; the nearest-pair equal-prior error was 0.19%.

However, the predecessor objective charged its command-smoothing regularizer
as physical probe cost. The measured acquisition cost was `6.9733`, while the
uniform diagnostic value per later event was only `0.07754`. Even eight future
events could not repay this cost. Smaller probes were cheaper but did not
separate the capability groups at the registered 1% error level.

## Scientific interpretation and next calculation

The first development search did not yet establish a usable active positive
region. It identified two decisive modelling questions:

1. scalar observation loses useful temporal information, but delay information
   may already be available passively;
2. the predecessor objective conflates numerical command smoothing with
   physical frequency/ACE/tie, SG mileage, and BESS-throughput cost.

The next experiment will keep hard physical safety unchanged, separate the
scientific performance metric from the optimizer's small smoothing
regularizer, and run a preregistered 2x2x2 comparison of information lifetime,
scalar/vector observation, and worst/expected event valuation. The capability
dimension will remain robust in the primary analysis.

## Control-aligned sequential excitation

A second probe family retained the SG contract-safe command and added a small
BESS surplus request only while the robust BESS command was already close to
the 0.045 pu public power floor. This uses current regulation need rather than
a future-event label.

At amplitude 0.003 pu:

- every capability vertex remained physically safe;
- one 24 s window separated the two power-response groups by 1.472 standard
  deviations;
- ten independent non-overlapping windows are required for a one-percent
  equal-prior binary error;
- mean accumulated grid-service cost change through those ten windows was
  `-0.06221`, so the excitation improved rather than degraded mean regulation;
- the low-power branch accumulated a small adverse change of about `+0.00187`,
  while the high-power branch improved.

At 0.0025 pu both power groups improved in each window, but sixteen windows
were required, exceeding a 300 s validity interval if each complete 24 s
window is used. Larger amplitudes certified faster but worsened grid cost.

This is the first credible active mechanism found in development: useful
control action and information acquisition are directionally aligned. It is
not yet a positive primary result because the strict minimum over capability
hypotheses remains slightly negative at 0.003 pu, and the independent-window
noise assumption still needs correlated-noise sensitivity and nonlinear
closed-loop confirmation.

## First full nonlinear Plant-A check

The first nonlinear paired high-capability episode used seed 8100, a 300 s full
rolling simulation, a capability change at 90 s, and an independent load event
at 120 s. Contract MPC and the probe-only policy both remained physically
successful with no hard violation, solver failure, or fallback.

The initial 0.003 pu policy used nine windows but did not yet use its posterior.
Relative to contract MPC it produced:

- identical frequency peak: `0.399575 Hz`;
- ACE IAE `2.752961` versus `2.640688` (4.25% worse);
- tie IAE `0.325860` versus `0.286786` (13.62% worse);
- SG mechanical mileage `0.529238` versus `0.392528` (34.83% higher).

Reducing to 0.0025 pu and five windows narrowed but did not reverse the gap:

- ACE IAE `2.675623` (1.32% worse than contract);
- tie IAE `0.297514` (3.74% worse);
- SG mechanical mileage `0.462779` (17.90% higher);
- frequency peak unchanged and all physical/solver conditions still satisfied.

These are exploit-only/probe-cost results, not the complete dual policy: no
posterior-dependent recourse was applied. They show that the frozen linear
screen understated nonlinear feedback and SG-mileage cost. The next nonlinear
comparison therefore separates contract, exploit-only surplus, and dual
surplus with a causal power-delivery certificate and expiry.

An attempted 0.002 pu run produced no scientific result because unrelated
system memory use raised total commit from about 85% to 91.97% within seconds;
the resource monitor stopped the worker while its own private memory was about
0.40 GiB. It is retained as not evaluated, not counted as method failure.
