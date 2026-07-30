# Seed Literature for Codex Verification and Expansion

Codex must independently verify titles, authors, year, venue, DOI, and claims. This list is a starting point, not a complete review.

1. H. Huang et al., “Learning to Model the Dynamics of Black-Box Inverter-Based Resources With Multiple Unknown Control Modes From Noisy Measurement Data,” IEEE, 2025, IEEE document 11313680. Focus: black-box IBR mode discovery/modeling from noisy data; does not by itself close the online multi-area frequency-control problem.
2. S. Rezaei, X. Wang, and S. Geng, “Data-Driven Koopman Predictive Control for Frequency Regulation of Power Systems using Black-Box IBRs,” 2026 preprint, arXiv:2604.02251. Focus: data-driven secondary frequency regulation for black-box IBRs under a learned/lifted behavioral model; preprint status must be stated.
3. NERC, “Electromagnetic Transient Analysis in Operations Planning for BPS-Connected Inverter-Based Resources,” 2025. Focus: choice, fidelity, validation, and maintenance of generic versus equipment-specific/black-box IBR models.
4. NERC, “Findings from Inverter-Based Resource Model Quality Deficiencies,” 2025. Focus: systemic mismatch between submitted IBR models and actual plant behavior; motivates monitoring and revalidation.
5. E. Ekomwenrenren et al., “Data-Driven Fast Frequency Control Using Inverter-Based Resources,” IEEE Transactions on Power Systems, 2023. Verify exact bibliographic data. Focus: data-enabled fast frequency control; distinguish fast frequency control from secondary AGC.
6. Primary literature on DeePC, robust DeePC, set-membership adaptive MPC, tube MPC, dual control, fault-tolerant/multiple-model control, change-point detection, and multi-area AGC must be added.

Required novelty columns:

```text
citation,problem,plant_model,black_box,multiple_modes,online_change,
frequency_service,multi_area,ACE_tie_line,diagnosis_before_control_harm,
constraint_guarantee,active_identification,native_RMS_or_EMT,limitations
```
