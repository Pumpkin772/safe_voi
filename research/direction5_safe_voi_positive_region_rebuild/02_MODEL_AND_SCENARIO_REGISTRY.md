# Model and scenario registry

## Two time scales

- rolling MPC horizon: 24 or 32 s;
- capability-information validity horizon: 120–300 s.

The controller repeatedly solves the rolling MPC.  The longer horizon is used
only to value a capability estimate over its registered lifetime.  It does not
provide the realized future disturbance sequence to the online controller.

## Safety and value

Safety is robust over the contract floor, retained capability hypotheses,
delay pipeline, measured SoC energy, ramp limits, command saturation, and the
registered disturbance envelope.  Value is the expectation over an event
distribution frozen before validation and the minimum paired benefit over
capability hypotheses. Both contract and probe policies use the same event
draws and normalized frequency/ACE/tie objective. Capability averaging is not
used as the primary result without an external prior.

## Capability model

- hidden dimensions: power, ramp, delay;
- energy: measured SoC and device energy rating;
- availability: folded into deliverable power/ramp hypotheses;
- contract floor: unchanged from the public capability contract;
- online envelope: causal set-membership set from actual POI power;
- transition: unannounced to the controller and persistent for at least the
  registered information-validity horizon.

## Episode structure

Each 480 s core episode contains:

1. 0–60 s nominal warm-up;
2. an unannounced capability transition sampled independently at 90–150 s;
3. a causal quiet eligibility window in which probing is allowed only when
   measured frequency, ACE, tie, command, and constraint margins are safe;
4. one load/regulation event independently sampled from `U[210,390] s`;
5. rolling control through the entire 480 s episode.

Exact future event times, signs, areas, and magnitudes are evaluation-only.
The controller may know only the frozen event distribution.

## Registered physical ranges

- control period: 2 or 4 s;
- load magnitude: 0.025–0.070 pu, with independent sign and area;
- performance-envelope power: 0.040–0.080 pu;
- ramp: 0.020–0.050 pu/s;
- delay: 0.2–1.8 s;
- initial SoC: 0.35–0.65;
- probe amplitude: 0.0005–0.015 pu;
- physical probe duration: 4, 8, or 12 s.

The development probe set contains both allocation-neutral SG–IBR redispatch
and control-aligned BESS surplus requests. The latter never reduces the SG
contract-safe base action before actual surplus delivery is observed. It is
triggered by current measured need and binding command margin, not by a future
event label.

The event range is not enlarged beyond the predecessor nonlinear validation.
The change is the persistence and causal time available to use information.

## Seed firewall

Development, validation, final, and normal1h seed ranges are disjoint.  The
scenario generator uses separate child RNG streams for capability transition,
load timing, load magnitude, area/sign, measurement noise, and initial state so
that capability and load events are not mechanically coupled by one draw.
