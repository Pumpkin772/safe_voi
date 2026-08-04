# Same-instant contract-collapse impossibility boundary

Take two worlds with identical public histories through the instant before
command `u_k`. In world A true capability still contains the contract. In world
B it changes without announcement immediately before actuation and falls below
every previously known positive lower bound. A causal controller has identical
information and must issue the same `u_k` in both worlds. Choose world B's new
power/ramp/delay set so `u_k` is not executable. No causal controller can
guarantee same-instant executability in both worlds.

The result permits conditional guarantees when the true set contains a valid
contract floor, or when independent SG/slow reserve is sufficient through
detection and handover. It does not prevent detection after an output mismatch.
Contract violations are therefore reported separately and never included in the
within-contract safety theorem.
