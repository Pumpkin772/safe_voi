# Frozen predecessor result

Project: DIRECTION5  
Predecessor method: heuristic VOI-ACCR-MPC  
Frozen source commit: `aa96ac0698046765302d9ade59ce49a74be3009f`  
Frozen result: `DIRECTION5_TERMINATED_WITH_DECISIVE_NEGATIVE_EVIDENCE`

The predecessor result is preserved without reinterpretation. Its valid scope is the
tested heuristic decision-relevance and VoI proxy, the selected two-sample probe, and
the registered M2 V2 experiments. It is not evidence that every safe probe has zero
control value, because it did not solve the nested robust/posterior decision problem.

The retained quantitative facts are:

- M1: development-only pass; M2 V2: independent failure; Final: not evaluated.
- 60 scenarios: 48 full nonlinear Plant-A and 12 native Plant-B scenarios.
- Heuristic worthwhile-region mean improvements were -0.0163% for ACE and
  -0.0526% for tie-line IAE; SG mechanical mileage changed by -1.48%.
- The evaluated perfect-capability controller improved ACE by 0.564% and tie-line
  IAE by 1.422%, below the predecessor's registered 4% materiality threshold.
- Four false-optimistic certificates were found among 21 audited certificate issues.
- 32,043 optimization calls were attempted; no solver failure, restoration, or
  fallback was recorded.
- Final seeds 6200--6299 were not consumed.

The frozen inputs remain in `results_direction5_voi_accr/final/`, and the untracked
review archive remains `DIRECTION5_VOI_ACCR_MPC_SINGLE_REVIEW_PACKAGE.zip`. No file
from that result is overwritten by the boundary study.

