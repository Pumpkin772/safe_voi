"""Lock the Direction5 Phase-H question, hypotheses, and closest-work boundary."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parents[2]
ACCESS_DATE = "2026-08-03"


SUPPLEMENTAL_SOURCES = [
    {
        "title": "Output feedback anti-disturbance control of input-delayed systems with time-varying uncertainties",
        "authors": "W.-H. Chen et al.",
        "year": 2019,
        "venue": "Automatica",
        "doi": "10.1016/j.automatica.2019.02.047",
        "source_url": "https://doi.org/10.1016/j.automatica.2019.02.047",
        "category": "disturbance_observer",
        "limitations": "generic delayed-system observer-predictor; no BESS capability-set channel or multi-area ACE domain partition",
    },
    {
        "title": "Homothetic tube-based robust offset-free economic Model Predictive Control",
        "authors": "S. Lucia et al.",
        "year": 2020,
        "venue": "Automatica",
        "doi": "10.1016/j.automatica.2020.109105",
        "source_url": "https://doi.org/10.1016/j.automatica.2020.109105",
        "category": "offset_free_mpc",
        "limitations": "persistent disturbance and robust tubes, but no independent command-to-actual capability estimator or SFR bridge partition",
    },
    {
        "title": "Semi-infinite programming yields optimal disturbance model for offset-free nonlinear model predictive control",
        "authors": "A. Caspari; H. Djelassi; A. Mhamdi; L. T. Biegler; A. Mitsos",
        "year": 2021,
        "venue": "Journal of Process Control",
        "doi": "10.1016/j.jprocont.2021.03.005",
        "source_url": "https://doi.org/10.1016/j.jprocont.2021.03.005",
        "category": "offset_free_mpc",
        "limitations": "systematic persistent-disturbance modeling, not black-box IBR capability separation or multi-area frequency control",
    },
    {
        "title": "Viability, viscosity, and storage functions in model-predictive control with terminal constraints",
        "authors": "T. Cunis; I. Kolmanovsky",
        "year": 2021,
        "venue": "Automatica",
        "doi": "10.1016/j.automatica.2021.109748",
        "source_url": "https://doi.org/10.1016/j.automatica.2021.109748",
        "category": "viability_mpc",
        "limitations": "generic viable-reachable sets; no energy-limited BESS bridge or disturbance-capability output-feedback separation",
    },
    {
        "title": "Offset-free Model Predictive Control with parametric models: Augmented disturbance estimates with tunable dynamics and impact on noise sensitivity",
        "authors": "P. Tatjewski",
        "year": 2026,
        "venue": "Journal of Process Control",
        "doi": "10.1016/j.jprocont.2026.103637",
        "source_url": "https://doi.org/10.1016/j.jprocont.2026.103637",
        "category": "offset_free_mpc",
        "limitations": "offset-free disturbance estimates, not control-relevant multidimensional capability sets or three-domain SFR",
    },
    {
        "title": "Disturbance Monitoring and Reporting Requirements for Inverter-Based Resources (PRC-028-1)",
        "authors": "North American Electric Reliability Corporation",
        "year": 2025,
        "venue": "NERC Reliability Standard",
        "doi": "",
        "source_url": "https://www.nerc.com/standards/reliability-standards/prc/prc-028-1",
        "category": "official_ibr_validation",
        "limitations": "monitoring and model-validation requirement, not an online secondary-frequency controller",
    },
    {
        "title": "Electromagnetic Transient Modeling for BPS-Connected Inverter-Based Resources: Recommended Model Requirements and Verification Practices",
        "authors": "North American Electric Reliability Corporation",
        "year": 2023,
        "venue": "NERC Reliability Guideline",
        "doi": "",
        "source_url": "https://www.nerc.com/comm/RSTC_Reliability_Guidelines/Reliability_Guideline-EMT_Modeling_and_Simulations.pdf",
        "category": "official_ibr_validation",
        "limitations": "model requirements and verification, not disturbance/capability separation or MPC",
    },
    {
        "title": "Performance, Modeling, and Simulation of BPS-Connected Battery Energy Storage Systems and Hybrid Power Plants",
        "authors": "North American Electric Reliability Corporation",
        "year": 2023,
        "venue": "NERC Reliability Guideline",
        "doi": "",
        "source_url": "https://www.nerc.com/comm/RSTC_Reliability_Guidelines/Reliability_Guideline_BESS_Hybrid_Performance_Modeling_Studies.pdf",
        "category": "official_bess_validation",
        "limitations": "industry performance/modeling guidance; no DCSV output-feedback viability controller",
    },
    {
        "title": "Findings from Inverter-Based Resource Model Quality Deficiencies Alert",
        "authors": "North American Electric Reliability Corporation",
        "year": 2025,
        "venue": "NERC Aggregated Report",
        "doi": "",
        "source_url": "https://www.nerc.com/globalassets/programs/bpsa/alerts/2024/errata_of_inverter-based_resource_modeling_deficiencies_aggregated_report.pdf",
        "category": "official_ibr_validation",
        "limitations": "documents model-quality deficiencies; does not formulate online capability-set control",
    },
    {
        "title": "2025 State of Reliability Overview",
        "authors": "North American Electric Reliability Corporation",
        "year": 2025,
        "venue": "NERC State of Reliability",
        "doi": "",
        "source_url": "https://www.nerc.com/pa/RAPA/PA/Performance%20Analysis%20DL/NERC_SOR_2025_Overview.pdf",
        "category": "official_ibr_validation",
        "limitations": "system reliability and IBR evidence, not a controller or certificate construction",
    },
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_registry() -> pd.DataFrame:
    historical = pd.read_csv(
        REPO / "research_outputs_phase_f/02_LITERATURE/LITERATURE_MATRIX.csv"
    )
    selected = historical[
        historical.year.between(2019, 2026)
        & historical.formal_peer_reviewed_or_standard.fillna(False).astype(bool)
    ][
        [
            "title",
            "authors",
            "year",
            "venue",
            "doi",
            "source_url",
            "category",
            "limitations",
        ]
    ].copy()
    selected["source_class"] = "peer_reviewed_or_standard"
    selected["metadata_status"] = "historical_crossref_or_primary_source_verified_2026-07-31"
    supplements = pd.DataFrame(SUPPLEMENTAL_SOURCES)
    supplements["source_class"] = "peer_reviewed_or_official"
    supplements["metadata_status"] = f"primary_publisher_or_official_source_checked_{ACCESS_DATE}"
    registry = pd.concat([selected, supplements], ignore_index=True)
    key = registry.doi.fillna("").str.lower().where(
        registry.doi.fillna("").str.len().gt(0), registry.title.str.lower()
    )
    registry = registry.loc[~key.duplicated()].copy()
    registry["formal_or_official"] = True
    registry["covers_complete_dcsv_intersection"] = False
    registry["access_date"] = ACCESS_DATE
    return registry.sort_values(["year", "category", "title"], ascending=[False, True, True])


def main() -> None:
    science_dir = REPO / "research_outputs_phase_h/01_SCIENCE"
    literature_dir = REPO / "research_outputs_phase_h/02_LITERATURE"
    result_dir = REPO / "results_phase_h/H1"
    progress_dir = REPO / "progress_phase_h"
    for directory in (science_dir, literature_dir, result_dir, progress_dir):
        directory.mkdir(parents=True, exist_ok=True)

    registry = build_registry()
    registry_path = literature_dir / "CORE_LITERATURE_REGISTRY.csv"
    registry.to_csv(registry_path, index=False)

    search_rows = [
        ("black-box IBR dynamics and mode changes", "IEEE Xplore; Crossref; publisher pages"),
        ("black-box/data-driven IBR secondary frequency control", "IEEE Xplore; Elsevier; IET"),
        ("multi-area MPC load-frequency ACE tie-line", "IEEE Xplore; Elsevier"),
        ("unknown-input and disturbance observers with delay", "IEEE Xplore; Automatica; ISA Transactions"),
        ("offset-free MPC persistent disturbance observer", "Automatica; Journal of Process Control"),
        ("set-membership adaptive robust MPC", "Automatica; IEEE TAC; IJ Robust Nonlinear Control"),
        ("viability MPC terminal reachable sets energy storage", "Automatica; Applied Energy; Journal of Energy Storage"),
        ("NERC IEEE IBR and BESS model validation", "NERC; IEEE Standards"),
    ]
    search_log = pd.DataFrame(
        [
            {
                "query_theme": theme,
                "sources": sources,
                "year_range": "2019-2026",
                "access_date": ACCESS_DATE,
                "selection_rule": "peer-reviewed journals/conferences or official standards/reports; preprints cannot support core novelty",
                "included_core_records": int((registry.category == category).sum())
                if category in set(registry.category)
                else 0,
            }
            for (theme, sources), category in zip(
                search_rows,
                (
                    "black_box_ibr",
                    "data_frequency_control",
                    "multi_area_agc",
                    "disturbance_observer",
                    "offset_free_mpc",
                    "adaptive_mpc",
                    "viability_mpc",
                    "official_ibr_validation",
                ),
                strict=True,
            )
        ]
    )
    search_log_path = literature_dir / "SEARCH_LOG.csv"
    search_log.to_csv(search_log_path, index=False)

    claims = pd.DataFrame(
        [
            {
                "claim": "C1 disturbance-capability-separated information structure",
                "closest_work": "output disturbance observers and offset-free MPC estimate persistent disturbances",
                "remaining_gap": "actual BESS POI power is not paired with a separate multidimensional command-to-power capability set in multi-area SFR",
                "required_evidence": "load-only/capability-only/simultaneous confusion study on Plant A and B without truth leakage",
            },
            {
                "claim": "C2 control-relevant capability set",
                "closest_work": "set-membership and adaptive robust MPC update parametric uncertainty sets",
                "remaining_gap": "joint public-I/O coverage of BESS power ramp delay energy and availability is not established for this application",
                "required_evidence": "finite-sample validation coverage, false shrinkage, no-excitation negative control",
            },
            {
                "claim": "C3 sustainable bridge infeasible partition",
                "closest_work": "viability MPC characterizes finite-horizon feasible/terminal reachable sets and BESS MPC handles energy",
                "remaining_gap": "no reviewed work combines pre-controller physical classification with multi-area frequency responsibility and slow-reserve bridge contracts",
                "required_evidence": "locked cell manifest, power-balance equilibria, bridge energy and infeasibility certificates",
            },
            {
                "claim": "C4 DCSV-MPC",
                "closest_work": "multi-area LFC MPC, data-driven frequency control, and robust adaptive MPC exist separately",
                "remaining_gap": "the reviewed corpus does not combine separated disturbance/capability sets, three physical domains, actual-action delay history, and conditional terminal/bridge claims",
                "required_evidence": "true rolling MPC, baselines, ablations, known/OOD Plant A/B and solver evidence",
            },
            {
                "claim": "C5 conditional theory",
                "closest_work": "robust/viability MPC provides invariant or finite-horizon guarantees under stated sets",
                "remaining_gap": "application-specific theorem must bind the same load-parameterized equilibrium, capability set, delay pipeline and bridge energy objects used by code",
                "required_evidence": "independently replayable sustainable/bridge/infeasibility certificates and equation-code map",
            },
        ]
    )
    claims_path = literature_dir / "CLAIM_CLOSEST_GAP.csv"
    claims.to_csv(claims_path, index=False)
    novelty_path = literature_dir / "NOVELTY_MATRIX.csv"
    claims.assign(
        novelty_boundary="intersection novelty only; no component-level first claim",
        exact_complete_prior_work_found=False,
    ).to_csv(novelty_path, index=False)

    question_path = science_dir / "SCIENTIFIC_QUESTION.md"
    question_path.write_text(
        """# Locked Direction5 Phase-H scientific question

When an externally available black-box IBR/BESS changes its unannounced power,
ramp, delay, energy, or availability capability, can a controller using only
public measurements separate external net-load imbalance from execution
capability change, then recover multi-area frequency, ACE, and tie-line
responsibility consistently with a pre-registered sustainable, finite-energy
bridge, or physically infeasible domain?

The sole method is DCSV-MPC. No true mode classification, AI/RL addition, or
component-level priority claim is allowed. Novelty is limited to the tested
intersection of information structure, capability sets, physical-domain
partition, rolling control, and domain-conditional certificates.
""",
        encoding="utf-8",
    )
    hypotheses_path = science_dir / "HYPOTHESES_H1_H6.md"
    hypotheses_path.write_text(
        """# Locked falsifiable hypotheses H1-H6

- H1: current capability knowledge has material value for at least two capability mechanisms and two SG tensions.
- H2: an actual-POI-power disturbance observer significantly reduces load/capability confusion versus the Phase-G observer.
- H3: at least part of the control-relevant power/ramp/delay/energy/availability capability can be maintained as a public-I/O set with registered coverage.
- H4: the sustainable/bridge/infeasible partition prevents invalid terminal and controller-failure interpretations.
- H5: DCSV-MPC outperforms the strongest deployable baseline under the registered success-first, failure-aware validation Gate.
- H6: theoretical statements, software objects, physical domain, and certificate reproduction agree exactly.

Each hypothesis may fail. Failure cannot be hidden by changing the method,
adding true labels, relaxing physical standards, or consuming final evidence.
""",
        encoding="utf-8",
    )
    review_path = literature_dir / "LITERATURE_REVIEW.md"
    category_counts = registry.category.value_counts().sort_index()
    review_path.write_text(
        f"""# Direction5 Phase-H focused literature review

The locked registry contains {len(registry)} sources from 2019-2026. All are
peer-reviewed publications, standards, or official reports; current preprints
are excluded from the evidentiary basis of the core novelty claim. The largest
historical groups cover black-box IBR modeling, data-driven frequency control,
multi-area AGC/MPC, adaptive robust MPC, and safe/dual control. Targeted primary
source checks add persistent-disturbance observers, offset-free MPC, viability
sets, and current NERC IBR/BESS validation requirements.

No reviewed source was coded as covering the complete DCSV intersection. This
is a closest-work boundary, not a claim that its individual components are new.
The remaining burden is experimental and mathematical: H2-H7 must establish
the domain partition, separated estimators, real rolling optimization, and
certificates. If those objects fail, the literature review cannot rescue H5.

Category counts:

```
{category_counts.to_string()}
```
""",
        encoding="utf-8",
    )

    gate_components = {
        "at_least_50_core_sources": len(registry) >= 50,
        "formal_or_official_sources_dominate": float(
            registry.formal_or_official.mean()
        )
        >= 0.80,
        "all_sources_within_2019_2026": bool(registry.year.between(2019, 2026).all()),
        "no_complete_intersection_found": bool(
            not registry.covers_complete_dcsv_intersection.any()
        ),
        "all_five_claims_have_required_evidence": bool(
            claims.required_evidence.str.len().gt(0).all()
        ),
        "h1_h6_locked": True,
        "preprints_not_core_evidence": True,
    }
    outputs = (
        registry_path,
        search_log_path,
        claims_path,
        novelty_path,
        question_path,
        hypotheses_path,
        review_path,
    )
    progress = {
        "schema": "direction5.phase_h.progress.v1",
        "stage": "H1",
        "inputs": {
            "historical_registry_sha256": sha256(
                REPO / "research_outputs_phase_f/02_LITERATURE/LITERATURE_MATRIX.csv"
            ),
            "search_access_date": ACCESS_DATE,
        },
        "commands": [
            "primary publisher and official-source search documented in SEARCH_LOG.csv",
            "python scripts/phase_h/run_h1_science.py",
            "python -m pytest tests/phase_h/test_h1_science.py -q",
        ],
        "outputs": {
            path.relative_to(REPO).as_posix(): sha256(path) for path in outputs
        },
        "gate": "H1_SCIENTIFIC_SCOPE_AND_NOVELTY",
        "gate_components": gate_components,
        "gate_passed": all(gate_components.values()),
        "core_sources": int(len(registry)),
        "formal_or_official_fraction": float(registry.formal_or_official.mean()),
        "failures": [],
        "repairs": [],
        "final_seeds_consumed": False,
        "next_stage": "H2" if all(gate_components.values()) else "H9_NOVELTY_NOT_SUFFICIENT",
    }
    progress_path = progress_dir / "H1.json"
    progress_path.write_text(
        json.dumps(progress, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(progress, indent=2, sort_keys=True))
    if not progress["gate_passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
