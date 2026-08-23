# Literature position and bounded novelty

## Closest control literature

1. Parsi, Iannelli, and Smith, **Active exploration in adaptive model
   predictive control**, CDC 2020,
   [arXiv:2003.14120](https://arxiv.org/abs/2003.14120). This work includes the
   dual effect through predicted worst-case cost and maintains robust state and
   input constraints. Direction5 cannot claim the first active-exploration MPC.

2. Parsi, Liu, Iannelli, and Smith, **Dual adaptive MPC using an exact
   set-membership reformulation**, Automatica,
   [arXiv:2211.16300](https://arxiv.org/abs/2211.16300). This work embeds exact
   set-membership equations in dual MPC and establishes robust constraint and
   feasibility properties. Direction5 cannot claim the first exact
   set-membership dual MPC.

3. Schwenkel, Köhler, Müller, and Allgöwer, **Robust Economic Model Predictive
   Control without Terminal Conditions**,
   [arXiv:1911.12235](https://arxiv.org/abs/1911.12235). This work establishes
   robust economic-MPC guarantees under bounded disturbances. It supports the
   separation between physical robustness and an operating-performance
   objective, but it does not give the capability-information prior/lifetime
   boundary studied here.

4. Zholbaryssov and Dominguez-Garcia, **Safe Data-Driven Secondary Control of
   Distributed Energy Resources**, IEEE Transactions on Power Systems, 2021,
   DOI `10.1109/TPWRS.2021.3084440`. It provides safe data-driven secondary
   control with excitation. Direction5 cannot claim the first safe excitation
   in secondary control.

5. Pierre et al., **Probing Signal Design for Power System Identification**,
   IEEE Transactions on Power Systems, 2010,
   DOI `10.1109/TPWRS.2009.2033801`. It optimizes probing for identification;
   Direction5 instead asks whether closed-loop future control value repays the
   complete acquisition cost.

6. The frozen predecessor study already compared black-box IBR modelling and
   active probing literature and found no positive registered safe-probe point.
   Its negative result remains part of the claim lineage rather than being
   displaced by the successor model.

## What is not novel

- active exploration or dual control in general;
- set-membership adaptive MPC;
- robust or stochastic economic MPC;
- power-system probing signals;
- black-box IBR identification;
- multi-area frequency MPC;
- using actual POI power as a measurement.

## Candidate bounded contribution

The potentially publishable contribution is the combination of:

1. robust physical safety over every retained power/ramp/delay branch;
2. a complete capability-prior ambiguity boundary rather than an assumed
   uniform prior;
3. a break-even information lifetime that starts at the first evidence sample
   and explicitly charges certification time;
4. full causal actual-POI stacked evidence with correlated residuals;
5. a comparison between allocation-neutral excitation and a
   **control-aligned informative surplus action**;
6. decomposition of immediate control value, pure information value, and total
   value against the same rolling contract MPC;
7. exact abstention when the ambiguity-set value is nonpositive.

The novelty claim is conditional on independent nonlinear validation finding a
nonempty region where total dual value is positive. If only exploit-only
control improves, the result must be described as opportunistic passive
certification rather than positive active-information value.
