# Full nonlinear Plant A

`direction5freq.models.plant_a_full.PlantAFull` integrates two-area swing,
tie-line, governor, valve, turbine and GRC dynamics with RK4 at the registered
physical step. BESS PFR and SFR share one physical command-to-actual actuator
with continuous delay interpolation, power/ramp limits and measured-SoC energy.
Slow reserve is a finite-ramp first-order state and contributes generation to
the power balance. Frequency, tie, valve, mechanical power, actual POI power,
SoC, reserve, commands and saturation flags are available to the evidence
driver. Capability truth is evaluation-side only.
