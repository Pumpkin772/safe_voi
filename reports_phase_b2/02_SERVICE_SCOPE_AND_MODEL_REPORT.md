# Service Scope and Model Report

Phase B2 studies **two-area supplementary/secondary frequency regulation**. The upper layer issues independent SG and IBR supplementary commands every 2 s by default (4 s is a preregistered sensitivity). Fixed SG governor droop and fixed local IBR droop are part of the plant and are never optimized by the upper layer.

Plant B implements the two-area swing/turbine/governor/tie-line equations and area control errors `ACE1 = B1 Δf1 + P12` and `ACE2 = B2 Δf2 - P12`. SG generation-rate constraints are enforced on mechanical-power dynamics, not merely on requested commands. The BESS states include delayed command execution, actual POI power, SoC and a continuous availability state. Physical headroom combines rating, current/apparent-power and sustainable-energy limits. Power, ramp, charge/discharge efficiency, delay/dropout and centralized service enablement are enforced in the simulator.

Ordinary controller telemetry contains frequency, tie-line power, ACE, BESS POI power, SG mechanical power and issued commands. Regime, SoC, availability, headroom cause and realized internal delay remain simulator-only. Oracle access is separated and evaluation-only.

The SG capability levels are adequate, scarce and critical, each with explicit pu/s, pu/min and MW/min GRC reporting. A regime switch changes parameterization without resetting BESS power, SoC, availability or command history.
