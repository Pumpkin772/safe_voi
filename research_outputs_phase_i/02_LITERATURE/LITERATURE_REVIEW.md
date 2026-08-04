# Phase-I literature review and novelty lock

Cut-off: **2026-08-04**. The registry contains **70** unique core
records from 2019--2026; all are peer-reviewed publications or official
standards/guidelines. Primary publisher/DOI or official-source metadata was used
for the execution-date update. No record was coded as covering the complete
Direction5 intersection.

## What the literature already contains

Set-membership robust/adaptive MPC, offset-free disturbance estimation,
data-driven frequency control, multi-area tube MPC with HESS, actuator-fault
observers, BESS energy constraints and native model-validation guidance all
exist. In particular, An et al. (2025) is the closest application paper and
Aboudonia and Lygeros (2025) the closest generic interconnected-system method.
Recent 2025 Automatica work also supplies event-triggered uncertainty learning
and efficient online tube construction. These works rule out component-level
novelty claims.

## Remaining bounded intersection

The screened formal corpus did not identify a single work that jointly uses
actual BESS POI power to separate persistent net load, maintains a causal
command-to-actual `{P+,P-,R+,R-,delay}` set, distinguishes a contractual hard
floor from an online performance envelope, implements sustainable/bridge/
infeasible conditions in a true rolling multi-area MPC, states the same-instant
contract-violation impossibility boundary, and validates on both a nonlinear
plant and a native network-dynamic plant. Phase I therefore claims only this
tested intersection, contingent on H1--H6 and I6.

Energy and availability are deliberately removed from the hidden-estimation
claim: energy is computed from measured SoC and availability is expressed only
through observed deliverability. Native Plant B evidence is required; a reduced
surrogate cannot support the claim.

## Registry composition

- `adaptive_mpc`: 6
- `adaptive_tube_mpc`: 5
- `black_box_ibr`: 9
- `data_frequency_control`: 9
- `data_predictive`: 8
- `disturbance_observer`: 2
- `dual_safe`: 6
- `frequency_control`: 4
- `industry_guideline`: 1
- `multi_area_agc`: 7
- `native_modeling`: 3
- `official_bess_validation`: 2
- `official_ibr_validation`: 4
- `offset_free_mpc`: 3
- `viability_mpc`: 1

The detailed closest-work and experiment/theorem mapping is frozen in
`CLAIM_CLOSEST_WORK.csv`; search themes and the execution date are frozen in
`SEARCH_LOG.csv`.
