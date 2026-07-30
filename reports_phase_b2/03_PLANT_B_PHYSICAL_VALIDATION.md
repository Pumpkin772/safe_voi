# Plant B Physical Validation

Status: **PASS** (16/16 registered checks passed).

The validation covers zero-disturbance equilibrium, two-area power/tie-line signs, ACE signs, physical command onset, mechanical-power GRC, reserve projection, BESS ramp and power limits, SoC/efficiency direction, energy-dependent headroom, service disablement with retained local droop, and state continuity across regime changes. Unit tests additionally verify both 2 s and 4 s upper-control periods and enforce the ordinary-controller information boundary.

The fixed O0 ACE PI was selected only on development step cases. In the 180 s capability check, 6 of 9 SG/load combinations restored maximum absolute ACE below 0.002 pu. Non-restoration in scarce/critical cases is retained as scientific evidence when reserve is insufficient; it is not filtered out.

Artifacts:

- `results_phase_b2/plant_b_validation/open_loop_regime_response.csv`
- `results_phase_b2/plant_b_validation/sg_capability_response.csv`
- `results_phase_b2/plant_b_validation/physical_validation_checks.csv`
- `results_phase_b2/plant_b_validation/sg_capability_engineering_units.csv`
- `figures_phase_b2/plant_b_block_diagram.png`
- `figures_phase_b2/open_loop_regime_responses.png`

The physical model is an auditable average-value scientific test plant, not a claim of electromagnetic-transient or vendor-specific fidelity. Structural OOD is deliberately a held-out composite of slower command/power dynamics, asymmetric ramp capability, limited headroom and dropout.
