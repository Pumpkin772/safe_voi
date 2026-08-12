# Literature position for the exact VoI boundary

The closest control literature establishes safe exploration and uncertainty-reducing
adaptive MPC, but does not provide the black-box IBR *net control-value boundary*
studied here.

1. Parsi, Iannelli, and Smith, *Active exploration in adaptive model predictive
   control*, CDC 2020, DOI 10.1109/CDC42340.2020.9304303
   (`https://arxiv.org/abs/2003.14120`). This work combines set-membership updates,
   predicted worst-case cost, and robust constraints. It motivates a nested
   exploration/recourse calculation, but does not specialize the decision to
   power/ramp/delay deliverability or prove an operational no-probe region.
2. Parsi, Liu, Iannelli, and Smith, *Dual adaptive MPC using an exact set-membership
   reformulation*, Automatica 2024 (`https://arxiv.org/abs/2211.16300`). It gives an
   exact set-membership reformulation and robust feasibility result. The present study
   instead enumerates every posterior induced by bounded POI-power observation tubes
   and compares the resulting recourse cost with the same contract MPC.
3. Zholbaryssov and Dominguez-Garcia, *Safe Data-Driven Secondary Control of
   Distributed Energy Resources*, IEEE Transactions on Power Systems 36(6), 2021,
   DOI 10.1109/TPWRS.2021.3084440
   (`https://experts.illinois.edu/en/publications/safe-data-driven-secondary-control-of-distributed-energy-resource/`).
   Its persistent excitation is constructed not to compromise operational reliability;
   it does not test whether the closed-loop control benefit pays for the probe.
4. Pierre et al., *Probing Signal Design for Power System Identification*, IEEE
   Transactions on Power Systems 25(2), 2010, DOI 10.1109/TPWRS.2009.2033801, and
   the NREL review of active probing (`https://www.osti.gov/pages/biblio/1855376`).
   This line optimizes identification quality and signal-to-noise properties, whereas
   the present objective charges the complete probe counterfactual and subsequent
   recourse.
5. Dželo, Mešanović, and Cosovic, *Identification of Black-Box Inverter-Based
   Resource Control Using Hammerstein-Wiener Models*
   (`https://arxiv.org/abs/2411.13213`). This supports the practical importance of
   black-box IBR dynamics, but addresses model reconstruction rather than the value of
   learning a deliverability set for constrained frequency control.

The intended novelty is therefore narrow: a registered-formulation perfect-information
ceiling, an exact bounded-observation posterior enumeration, a closed-loop net VoI, and
a no-probe result for the same physical objective and contract-MPC policy class. A
positive-region claim will be made only if it reproduces on independent full nonlinear
Plant A and is consistent with native Plant B; safe abstention on Plant B is admissible.

