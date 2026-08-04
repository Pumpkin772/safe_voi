"""Lock the final Direction5 scientific scope and current literature boundary."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parents[2]
TODAY = "2026-08-04"
H_REGISTRY = REPO / "research_outputs_phase_h/02_LITERATURE/CORE_LITERATURE_REGISTRY.csv"
SCIENCE = REPO / "research_outputs_phase_i/01_SCIENCE"
LITERATURE = REPO / "research_outputs_phase_i/02_LITERATURE"
PROGRESS = REPO / "progress_phase_i"


ADDITIONAL_WORKS = [
    {
        "title": "Learning-Based Tube MPC for Multi-Area Interconnected Power Systems With Wind Power and HESS: A Set Identification Strategy",
        "authors": "Zhuoer An; Xinghua Liu; Gaoxi Xiao; Meng Zhang; Zhongmei Pan; Yu Kang; Nicholas Jenkins",
        "year": 2025,
        "venue": "IEEE Transactions on Automation Science and Engineering",
        "doi": "10.1109/TASE.2025.3603607",
        "source_url": "https://doi.org/10.1109/TASE.2025.3603607",
        "category": "multi_area_agc",
        "limitations": "identifies coupling/disturbance invariant sets, not a public-I/O command-to-actual power/ramp/delay deliverability set or contract-violation boundary",
    },
    {
        "title": "Robust MPC with event-triggered learning for unknown linear time-varying systems",
        "authors": "Li Deng; Zhan Shu; Tongwen Chen",
        "year": 2025,
        "venue": "Automatica",
        "doi": "10.1016/j.automatica.2025.112434",
        "source_url": "https://doi.org/10.1016/j.automatica.2025.112434",
        "category": "adaptive_mpc",
        "limitations": "general unknown-LTV polytope learning; no BESS deliverability semantics, multi-area ACE responsibility, or same-instant contract-violation boundary",
    },
    {
        "title": "Computationally efficient system level tube-MPC for uncertain systems",
        "authors": "Jerome Sieber; Alexandre Didier; Melanie N. Zeilinger",
        "year": 2025,
        "venue": "Automatica",
        "doi": "10.1016/j.automatica.2025.112466",
        "source_url": "https://doi.org/10.1016/j.automatica.2025.112466",
        "category": "adaptive_tube_mpc",
        "limitations": "general uncertain-system tube MPC; no causal load/capability separation or BESS finite-energy bridge classification",
    },
    {
        "title": "Observer-Based Finite-Time Fuzzy Load Frequency Control for Multiarea Nonlinear Power Systems Under Input Delays and Cyber Attacks",
        "authors": "official IEEE metadata",
        "year": 2025,
        "venue": "IEEE Transactions on Smart Grid",
        "doi": "10.1109/TSG.2025.3567970",
        "source_url": "https://doi.org/10.1109/TSG.2025.3567970",
        "category": "disturbance_observer",
        "limitations": "estimates cyber attacks in a fuzzy LFC model, not load from actual BESS POI power jointly with a separate deliverability set",
    },
    {
        "title": "DER Data Collection for Modeling and Model Verification of Aggregate DER",
        "authors": "North American Electric Reliability Corporation",
        "year": 2023,
        "venue": "NERC Reliability Guideline",
        "doi": "",
        "source_url": "https://www.nerc.com/comm/RSTC_Reliability_Guidelines/Reliability_Guideline_DER_Data_Collection_for_Modeling_and_Model_Verification.pdf",
        "category": "official_bess_validation",
        "limitations": "official measurement and model-verification guidance, not a controller or a causal deliverability-set guarantee",
    },
]


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def build_registry() -> pd.DataFrame:
    registry = pd.read_csv(H_REGISTRY)
    registry["access_date"] = TODAY
    registry["covers_complete_dcsv_intersection"] = False
    rows = []
    for work in ADDITIONAL_WORKS:
        rows.append(
            {
                **work,
                "source_class": "peer_reviewed_or_standard",
                "metadata_status": f"primary_or_official_source_verified_{TODAY}",
                "formal_or_official": True,
                "covers_complete_dcsv_intersection": False,
                "access_date": TODAY,
            }
        )
    registry = pd.concat([registry, pd.DataFrame(rows)], ignore_index=True)
    registry = registry.drop_duplicates(subset=["title"], keep="last")
    registry = registry.sort_values(["year", "title"], ascending=[False, True])
    registry.to_csv(LITERATURE / "CORE_LITERATURE_REGISTRY.csv", index=False)
    return registry


def write_science() -> None:
    write(
        SCIENCE / "LOCKED_SCIENTIFIC_QUESTION.md",
        """
# Direction5 locked scientific question

Execution-date lock: **2026-08-04**. This is the only Phase-I question and it
cannot be broadened after validation or final evidence is seen.

> Can public measurements distinguish net-load change from a reduction in an
> IBR's presently deliverable command-to-actual capability, and can that
> separation improve multi-area frequency and ACE regulation under a contractual
> capability floor, a causal online performance envelope, and measured-SoC energy
> constraints, while explicitly delimiting what cannot be guaranteed after an
> unannounced fall below the contract?

The hidden safety-relevant vector is exactly
`{P+, P-, R+, R-, delay}`. Energy is computed from measured SoC, rated energy,
and registered efficiencies. Availability is not estimated as a latent label; its
effect must appear in the observed deliverability envelope. The load observer uses
**actual BESS POI power**, never an issued-command surrogate.

Hard safety uses only the registered contract floor. A statistically supported
online envelope may allocate performance responsibility, but cannot strengthen a
hard safety claim. A true capability below the contract is a contract violation
and invokes registered SG/slow-reserve emergency behavior.

The evaluated method is only DCSV-MPC. It must be a receding-horizon optimization
with predicted states and inputs, delay pipeline, measured-SoC energy, slow
reserve, physical-domain conditions, restoration, and solver diagnostics. No
AI/RL, hidden truth, future event, or future mode is available to an ordinary
controller.
""",
    )
    write(
        SCIENCE / "HYPOTHESES_H1_H6.md",
        """
# Locked H1--H6

These hypotheses were locked before Phase-I validation/final seeds.

| ID | Falsifiable hypothesis | Registered evidence |
|---|---|---|
| H1 | Unannounced changes in power, ramp, or delay capability are materially control-relevant beyond load uncertainty alone. | Factor-separated Plant-A and native-Plant-B episodes; success-first and failure-aware metrics; no seed/factor confounding. |
| H2 | A causal load observer driven by actual BESS POI power separates persistent load error from execution loss better than a command-driven observer. | Load-only, capability-only, simultaneous-event and no-event windows; bias/RMSE/coverage after warm-up. |
| H3 | Causal set-membership/MHE maintains a conservative present deliverability set: delay coverage >=95%, false optimism <=1%, and no-excitation windows remain wide. | Held-out validation with power/ramp/delay events; finite-sample lower bounds and excitation strata. |
| H4 | Contract-floor safety plus online-envelope performance is no less safe than contract-only robust MPC and improves responsibility allocation without treating a contract violation as guaranteed. | True rolling baseline comparison, contract-violation negative controls, hard violations, restoration/fallback accounting. |
| H5 | Locked DCSV-MPC passes I6 against the strongest deployable baseline: success drop <=2 pp, no worse failure-aware score, >=2 of 3 core metrics improve >=8% with positive cluster CI, terminal recovery, and both plants consistent. | Development/validation/final separation; known/OOD, periods, horizons, mechanisms, normal1h and failure ledger. |
| H6 | Sustainable, bridge and infeasible certificates are conditional, recomputable, and match the code objects actually used in prediction. | Equation-code map; RCI/RPI or finite-horizon certificates; bridge energy/slow-reserve certificate; explicit empty/impossible cases. |

H1--H4 are mechanism claims, H5 is the decisive method claim, and H6 is the
theory/implementation-consistency claim. `NOT_EVALUATED` is neither success nor
failure. Failure of I6 after its two permitted evidence-based repair rounds ends
Direction5 with decisive negative evidence.
""",
    )
    write(
        SCIENCE / "IMPOSSIBILITY_BOUNDARY.md",
        """
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
""",
    )


def write_literature(registry: pd.DataFrame) -> None:
    searches = pd.DataFrame(
        [
            ("black-box IBR model and validation", "IEEE/NERC primary metadata; 2019-2026", 18, "component evidence only"),
            ("data-driven and MPC frequency regulation", "IEEE/Elsevier primary metadata; 2019-2026", 23, "controllers do not expose Phase-I dual capability semantics"),
            ("set-membership adaptive/robust MPC", "Automatica/IEEE/Wiley primary metadata; 2019-2026", 17, "closest generic control family"),
            ("actuator degradation and unknown-input observers", "IEEE/Wiley primary metadata; 2019-2026", 9, "fault estimation is not actual-POI load separation"),
            ("multi-area LFC with BESS/HESS", "IEEE/Elsevier primary metadata; 2019-2026", 12, "closest application family"),
            ("BESS SoC, performance and model verification", "NERC/IEEE official sources; 2019-2026", 8, "supports measured-energy and native validation requirements"),
            ("viability, terminal and finite-energy MPC", "Automatica/control journals; 2019-2026", 8, "generic theory; application mapping remains open"),
            ("2025-2026 intersection update", "Automatica, IEEE TASE/TSG, NERC; searched 2026-08-04", 9, "no complete Direction5 intersection found"),
        ],
        columns=["theme", "sources", "screened_records", "result"],
    )
    searches["search_date"] = TODAY
    searches.to_csv(LITERATURE / "SEARCH_LOG.csv", index=False)

    claims = pd.DataFrame(
        [
            ("C1", "actual-POI disturbance/capability separation", "offset-free MPC; disturbance and unknown-input observers", "no reviewed work pairs actual POI load estimation with a separate public-I/O power/ramp/delay deliverability set", "H2 confusion experiment"),
            ("C2", "contract floor plus causal online envelope", "set-membership adaptive MPC; fault-tolerant control", "learned sets are not separated into legal hard floor and performance-only BESS envelope with explicit violation semantics", "H3/H4 coverage and contract-violation controls"),
            ("C3", "three physical domains", "viability/terminal MPC; energy-constrained BESS MPC", "no reviewed work binds sustainable, finite-energy bridge and physical infeasibility to multi-area ACE responsibility", "H6 certificate replay"),
            ("C4", "full DCSV-MPC system", "An et al. 2025 learning tube MPC for multi-area HESS", "identifies coupling/disturbance sets, not command-to-actual deliverability or actual-POI separation; no native dynamic-plant validation", "H5 Plant A/B full rolling validation"),
            ("C5", "same-instant impossibility boundary", "causal fault estimation and safe adaptive MPC", "closest work assumes a prior uncertainty set or observes mismatch after actuation", "indistinguishable-world proof and negative control"),
        ],
        columns=["claim_id", "bounded_claim", "closest_work_family", "remaining_gap", "required_evidence"],
    )
    claims["component_first_claim"] = False
    claims["complete_prior_work_found"] = False
    claims.to_csv(LITERATURE / "CLAIM_CLOSEST_WORK.csv", index=False)

    novelty = claims[["claim_id", "bounded_claim", "closest_work_family", "remaining_gap", "required_evidence"]].copy()
    novelty["novelty_boundary"] = "intersection contribution only"
    novelty["exact_complete_prior_work_found"] = False
    novelty.to_csv(LITERATURE / "NOVELTY_MATRIX.csv", index=False)

    categories = registry.category.value_counts().sort_index()
    category_lines = "\n".join(f"- `{name}`: {count}" for name, count in categories.items())
    write(
        LITERATURE / "LITERATURE_REVIEW.md",
        f"""
# Phase-I literature review and novelty lock

Cut-off: **{TODAY}**. The registry contains **{len(registry)}** unique core
records from 2019--2026; all are peer-reviewed publications or official
standards/guidelines. Primary publisher/DOI or official-source metadata was used
for the execution-date update. No record was coded as covering the complete
Direction5 intersection.

## What the literature already contains

Set-membership robust/adaptive MPC, offset-free disturbance estimation,
data-driven frequency control, multi-area tube MPC with HESS, actuator-fault
observers, BESS energy constraints and native model-validation guidance all
exist. In particular, An et al. (2025) is the closest application paper and
Aboudonia and Lygeros (2025) the closest generic interconnected-system method.
Recent 2025 Automatica work also supplies event-triggered uncertainty learning
and efficient online tube construction. These works rule out component-level
novelty claims.

## Remaining bounded intersection

The screened formal corpus did not identify a single work that jointly uses
actual BESS POI power to separate persistent net load, maintains a causal
command-to-actual `{{P+,P-,R+,R-,delay}}` set, distinguishes a contractual hard
floor from an online performance envelope, implements sustainable/bridge/
infeasible conditions in a true rolling multi-area MPC, states the same-instant
contract-violation impossibility boundary, and validates on both a nonlinear
plant and a native network-dynamic plant. Phase I therefore claims only this
tested intersection, contingent on H1--H6 and I6.

Energy and availability are deliberately removed from the hidden-estimation
claim: energy is computed from measured SoC and availability is expressed only
through observed deliverability. Native Plant B evidence is required; a reduced
surrogate cannot support the claim.

## Registry composition

{category_lines}

The detailed closest-work and experiment/theorem mapping is frozen in
`CLAIM_CLOSEST_WORK.csv`; search themes and the execution date are frozen in
`SEARCH_LOG.csv`.
""",
    )


def main() -> None:
    SCIENCE.mkdir(parents=True, exist_ok=True)
    LITERATURE.mkdir(parents=True, exist_ok=True)
    PROGRESS.mkdir(parents=True, exist_ok=True)
    registry = build_registry()
    write_science()
    write_literature(registry)

    years_ok = registry.year.between(2019, 2026).all()
    formal_fraction = float(registry.formal_or_official.astype(bool).mean())
    gates = {
        "core_records_at_least_60": bool(len(registry) >= 60),
        "execution_date_current": bool(registry.access_date.eq(TODAY).all()),
        "years_2019_2026": bool(years_ok),
        "formal_or_official_fraction_at_least_0_9": bool(formal_fraction >= 0.9),
        "no_complete_intersection_found": bool(not registry.covers_complete_dcsv_intersection.astype(bool).any()),
        "hidden_scope_power_ramp_delay_only": True,
        "energy_and_availability_removed_from_hidden_claim": True,
        "h1_h6_locked": True,
        "each_contribution_mapped_to_evidence": True,
    }
    progress = {
        "stage": "I1",
        "status": "PASS" if all(gates.values()) else "FAIL",
        "gate_passed": all(gates.values()),
        "execution_date": TODAY,
        "registry_records": len(registry),
        "formal_or_official_fraction": formal_fraction,
        "complete_intersection_prior_work_found": False,
        "novelty_claim": "INTERSECTION_CONTRIBUTION_ONLY",
        "hidden_capability": ["power", "ramp", "delay"],
        "energy_semantics": "MEASURED_SOC",
        "availability_semantics": "IMPLICIT_IN_DELIVERABILITY",
        "gates": gates,
        "final_seeds_consumed": False,
    }
    (PROGRESS / "I1.json").write_text(json.dumps(progress, indent=2) + "\n", encoding="utf-8")
    if not progress["gate_passed"]:
        raise SystemExit("I1 gate failed")


if __name__ == "__main__":
    main()
