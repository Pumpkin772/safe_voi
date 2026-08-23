# safe_voi

This repository contains the Direction5 research history and the active study:

> **Direction5: Safe Capability-Information Positive-Value Region Rebuild**

```text
DIRECTION5_SAFE_VOI_POSITIVE_REGION_REBUILD
direction5_safe_voi_positive_region_rebuild
```

The governing research goal is
[`research/direction5_safe_voi_positive_region_rebuild/CODEX_GOAL.md`](research/direction5_safe_voi_positive_region_rebuild/CODEX_GOAL.md).
The method remains **Selective VOI-ACCR-MPC**.

## Frozen predecessor result

The completed predecessor is preserved at Git tag
`direction5-voi-boundary-final` with status:

```text
PAPER_READY_NO_PROBE_BOUNDARY
```

Its registered finite domain contained 1,920 zero-value points and no positive
safe-probe point. The successor project does not overwrite this result.

## Active scientific question

The active branch studies whether a positive information-value region appears
when:

- robust physical safety is separated from distributionally robust operating
  value;
- capability value persists across multiple rolling MPC decisions but expires
  at a registered time;
- the complete causal actual-POI-power sequence is used for capability
  evidence;
- information acquisition is compared between allocation-neutral excitation
  and control-aligned informative surplus actions.

The primary paper object is a break-even boundary over capability prior,
information lifetime, observation quality, and acquisition cost. A uniform
capability prior is not used as the primary claim.

## Current development status

The first full nonlinear Plant-A pilot has shown positive **pure information
value**: using a causal power-delivery certificate substantially improved ACE,
tie-line error, and SG mileage relative to the same surplus action without
posterior recourse. The complete dual policy is not yet better than contract
MPC, so a positive paper result has not yet been established.

Quantitative findings are retained in
[`research_outputs_direction5_safe_voi_positive_region_rebuild/R1_DIAGNOSTIC_FINDINGS.md`](research_outputs_direction5_safe_voi_positive_region_rebuild/R1_DIAGNOSTIC_FINDINGS.md).

## Environment

```powershell
conda env update --name topo_sfr --file environment.yml --prune
conda activate topo_sfr
python -m pip install -e . --no-deps
python -m pytest tests/direction5_safe_voi_positive_region_rebuild -q
```

Run one guarded nonlinear episode at a time. Ordinary controllers cannot read
true capability, true load, exact future events, or future modes.
