# Same-instant deliverability impossibility boundary

Consider two plants with identical public input/output histories through time
`k-1`. In plant A the capability at `k` still contains the contract floor. In
plant B it changes without announcement immediately before actuation and falls
below every previously known positive lower bound. A causal controller receives
the same information in both worlds before issuing `u_k`, so it must issue the
same command. Choose the new power/ramp/delay capability in world B so that this
command is not executable. Therefore no history-only controller can guarantee
same-instant command executability for arbitrary unannounced capability collapse.

This indistinguishability result is independent of optimizer quality. A safety
claim is possible only conditional on at least one of: a valid contract floor,
advance telemetry/announcement, or sufficient independent SG/slow-reserve margin
through detection and handover. Phase I consequently separates:

- within-contract uncertainty: hard constraints use the contract floor;
- online surplus: performance only, with conservative coverage evidence;
- contract violation: detected and routed to emergency reserve, never claimed as
  guaranteed before detection;
- physical infeasibility: certified before ordinary controller scoring.

The result does not imply that degradation cannot be detected after its output
effect appears. It limits only same-instant guarantees before causal evidence
exists.
