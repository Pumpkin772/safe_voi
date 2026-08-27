# R3 first SG-conserving-16 replication summary

The first 4 s replication seeds `8103`, `8104`, and `8105` were fixed before
their outcomes were calculated.  All three happened to draw negative
contingency signs.  The controller configuration remained identical to the
positive mechanism seed 8256.

| seed | windows | high certified | total grid value: contract-dual (s) | pure information: exploit-dual (s) | interpretation |
| ---: | ---: | --- | ---: | ---: | --- |
| 8103 | 1 | no | -0.158475362 | 0.000000000 | incomplete acquisition; missing abstention condition |
| 8104 | 0 | no | 0.000000000 | 0.000000000 | exact natural abstention |
| 8105 | 2 | yes | -0.378841147 | -0.104568500 | correct information, adverse recourse value |

All nine trajectories were physically successful.  Each used 181 rolling MPC
calls with zero solver failures and zero fallback calls.  The initial
SG-conserving-16 prototype therefore does not have unconditional positive
information value and is not frozen for validation.

The contrast with positive-load seed 8256 motivates an explicitly exploratory
direction-conditioned cell.  This is not presented as preregistered evidence:
it was defined after the first replication outcomes.  The cell uses 4 s
control, positive contingency sign, and contingency magnitude at least 0.040
pu.  Before any outcome in this cell is calculated, the first three
development seeds in numeric order satisfying those public design filters are
fixed as `8127`, `8131`, and `8132`.  Event magnitude is not increased and the
ordinary controller does not receive the future sign, magnitude, time, area,
or regulation realization.  The purpose is to test a causal upward-demand
positive region while retaining the negative-direction results as a separate
zero/adverse region.
