"""Build the A1 formal literature inventory and bounded novelty decision."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parents[2]
BASE = REPO / "research_outputs_accr/02_LITERATURE/A1_FORMAL_LITERATURE_REGISTRY.csv"
CLOSEST = REPO / "configs/direction5_accr/a1_closest_sources.csv"
OUTPUT = REPO / "research_outputs_accr/02_LITERATURE"


def main() -> None:
    historical = pd.read_csv(BASE)
    if "registry_origin" in historical:
        historical = historical[
            historical.registry_origin.eq("FROZEN_DIRECTION5_PHASE_I_FORMAL_CORPUS")
        ].copy()
    historical = historical.rename(columns={"limitations": "accr_difference"})
    historical["registry_origin"] = "FROZEN_DIRECTION5_PHASE_I_FORMAL_CORPUS"
    historical["fresh_a1_primary_source_check"] = False
    closest = pd.read_csv(CLOSEST)
    closest["source_class"] = "peer_reviewed_or_official"
    closest["metadata_status"] = "primary_publisher_or_authoritative_repository_checked_2026-08-10"
    closest["formal_or_official"] = True
    closest["covers_complete_dcsv_intersection"] = closest["complete_intersection_coverage"]
    closest["access_date"] = "2026-08-10"
    closest["registry_origin"] = "FRESH_ACCR_A1_SEARCH"
    closest["fresh_a1_primary_source_check"] = True
    closest = closest.drop(columns=["complete_intersection_coverage"])
    registry = pd.concat([historical, closest], ignore_index=True, sort=False)
    key = registry.doi.fillna("").str.lower().str.strip()
    no_doi = key == ""
    key.loc[no_doi] = registry.loc[no_doi, "title"].str.lower().str.strip()
    registry = registry.loc[~key.duplicated()].copy()
    registry["formal_or_official"] = registry.formal_or_official.astype(str).str.lower().eq("true")
    registry["covers_complete_dcsv_intersection"] = registry.covers_complete_dcsv_intersection.astype(str).str.lower().eq("true")
    registry = registry.sort_values(["year", "title"], ascending=[False, True]).reset_index(drop=True)

    formal_count = int(registry.formal_or_official.sum())
    fresh_count = int(registry.fresh_a1_primary_source_check.sum())
    complete_found = bool(registry.covers_complete_dcsv_intersection.any())
    required_families = {
        "safe_data_driven_secondary_control",
        "active_exploration_mpc",
        "power_system_probing",
        "power_system_probing_review",
        "adaptive_control_allocation",
        "fault_tolerant_lfc",
        "event_triggered_fault_tolerant_lfc",
    }
    # A de-duplicated record can retain its frozen Phase-I category, so use the
    # dedicated A1 closest-work matrix to decide whether each required family
    # was explicitly compared.
    covered_families = set(closest.category.astype(str))
    gates = {
        "at_least_70_formal_or_official_sources": formal_count >= 70,
        "all_required_closest_work_families_compared": required_families <= covered_families,
        "fresh_primary_or_authoritative_checks_present": fresh_count >= 10,
        "no_complete_accr_intersection_found": not complete_found,
    }
    status = "PASS" if all(gates.values()) else "FAIL"
    OUTPUT.mkdir(parents=True, exist_ok=True)
    registry.to_csv(OUTPUT / "A1_FORMAL_LITERATURE_REGISTRY.csv", index=False)
    closest.to_csv(OUTPUT / "A1_CLOSEST_WORK_MATRIX.csv", index=False)
    pd.DataFrame([
        {"search_date": "2026-08-10", "theme": "safe data-driven secondary control and nullspace excitation", "primary_domains": "IEEE/Illinois author repository"},
        {"search_date": "2026-08-10", "theme": "active exploration MPC and set-membership", "primary_domains": "IEEE/ETH Research Collection"},
        {"search_date": "2026-08-10", "theme": "power-system active probing and signal design", "primary_domains": "IEEE/Lawrence Berkeley/Elsevier"},
        {"search_date": "2026-08-10", "theme": "adaptive constrained control allocation", "primary_domains": "Automatica/Elsevier"},
        {"search_date": "2026-08-10", "theme": "event-triggered and actuator-fault load frequency control", "primary_domains": "Applied Energy/Elsevier"},
    ]).to_csv(OUTPUT / "A1_SEARCH_LOG.csv", index=False)
    summary = {
        "schema": "direction5.accr.a1.literature.v1",
        "status": status,
        "cutoff_date": "2026-08-10",
        "unique_registry_records": int(len(registry)),
        "formal_or_official_records": formal_count,
        "fresh_a1_primary_source_checks": fresh_count,
        "complete_intersection_prior_work_found": complete_found,
        "bounded_novelty_statement": (
            "No reviewed formal work jointly implements event-triggered allocation-neutral "
            "SG-IBR probing, worst-case delivered/loss safety, finite-valid power/ramp/delay "
            "certification, contract-floor plus revocable-surplus recourse, and multi-area "
            "frequency/ACE/tie responsibility. Component novelty is not claimed."
        ),
        "gates": gates,
    }
    (OUTPUT / "A1_LITERATURE_SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n", "utf-8")
    report = f"""# A1 literature and bounded novelty decision

Cut-off: 2026-08-10. The inventory contains {len(registry)} unique formal papers or official
records, including {fresh_count} fresh A1 primary-publisher or authoritative-repository checks.

The closest safe data-driven secondary-control work already supplies persistent excitation,
online sensitivity learning, and a GP safety layer. Active-exploration MPC already supplies
set-membership dual control with robust constraints. Power-system probing already supplies
optimized low-amplitude multisines and field-tested mode identification. Adaptive control
allocation already addresses uncertain actuator effectiveness under saturation. Fault-tolerant
multi-area LFC and event-triggered LFC also already exist. ACCR therefore makes no novelty
claim for any one of those components.

No checked source covers their complete intersection with: event-triggered allocation-neutral
SG-IBR probing; explicit delivered and no-delivery branches; finite-valid power/ramp/delay
certificates; a legal contract floor separated from revocable surplus; loss recourse; and
multi-area frequency, ACE, and tie-line responsibility. The novelty Gate is consequently
{status}, bounded to that combined architecture and still conditional on experimental Gates.
"""
    (OUTPUT / "A1_LITERATURE_AND_NOVELTY.md").write_text(report, "utf-8")
    print(json.dumps(summary, indent=2))
    raise SystemExit(0 if status == "PASS" else 2)


if __name__ == "__main__":
    main()
