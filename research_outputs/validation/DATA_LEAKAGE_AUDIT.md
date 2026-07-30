# Data leakage audit

Deployed observation APIs contain frequency/COI frequency, ACE, tie-line flow, measured resource outputs and issued commands. They do not accept or return true regime, hidden parameters, true load, future load, future mode/event, availability, internal delay, or unmeasured energy/SoC. Oracle-only code must live under evaluation and is separately tested at C4.
