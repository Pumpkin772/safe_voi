# D3 causality audit

- `CausalCapabilitySetEstimator.update` parameters: `self, issued_total_command_pu, measured_power_pu`.
- No centered convolution or symmetric filter exists.
- Every update is called after the current measurement and before any later sample is generated.
- Alarm handling uses no post-alarm window and emits no source label.
- Development seeds 0–11 and validation seeds 100–111 were used; no final seed was used.
- Timing not evaluated due to absent excitation is stored separately and is not counted as method failure.
