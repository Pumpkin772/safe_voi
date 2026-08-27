# R3 upward localized-load exploration

Seeds `8127`, `8131`, and `8132` were fixed before this exploratory cell was
calculated.  They all use positive contingencies of at least 0.040 pu, but the
contingency is localized to area 0 or area 1.

| seed | area | windows | high certified | total grid value (s) | pure information grid value (s) |
| ---: | --- | ---: | --- | ---: | ---: |
| 8127 | area0 | 2 | yes | +0.011675166 | -0.064443505 |
| 8131 | area0 | 2 | no | -0.399262507 | 0.000000000 |
| 8132 | area1 | 0 | no | 0.000000000 | 0.000000000 |

All nine trajectories were physically successful, with zero solver failures
and zero fallback calls.  In seed 8127, posterior recourse slightly improved
the normalized frequency and ACE components but worsened the tie-line
component enough to make pure information value negative.  Positive load sign
and high contingency magnitude are therefore not sufficient conditions for a
positive information region.

The remaining contrast with positive mechanism seed 8256 is spatial: seed
8256 used a `both`-area contingency.  Before evaluating that factor, the first
three 4 s development seeds with positive sign, `both` area, and contingency
magnitude at least 0.040 pu are fixed as `8143`, `8154`, and `8170`.  This is
an explicitly exploratory conditional cell; it is not independent validation.
