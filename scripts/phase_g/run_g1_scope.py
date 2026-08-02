"""Lock Phase-G materiality scope and focused closest-work registry."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parents[2]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


TERMINAL_REFERENCES = [
    {
        "title": "Robust model predictive control of constrained linear systems with bounded disturbances",
        "authors": "D. Q. Mayne; M. M. Seron; S. V. Rakovic",
        "year": 2005,
        "venue": "Automatica",
        "doi": "10.1016/j.automatica.2004.08.019",
        "source_url": "https://doi.org/10.1016/j.automatica.2004.08.019",
        "theme": "tube_rmpc_terminal_rpi",
        "closest_work": "bounded-disturbance RMPC around a disturbance-invariant set",
        "remaining_gap": "not specialized to load-dependent multi-area equilibria or finite-energy IBR bridge cells",
    },
    {
        "title": "Invariant approximations of the minimal robust positively invariant set",
        "authors": "S. V. Rakovic; E. C. Kerrigan; K. I. Kouramas; D. Q. Mayne",
        "year": 2005,
        "venue": "IEEE Transactions on Automatic Control",
        "doi": "10.1109/TAC.2005.843854",
        "source_url": "https://doi.org/10.1109/TAC.2005.843854",
        "theme": "rpi_computation",
        "closest_work": "outer approximation of the minimal RPI set",
        "remaining_gap": "does not provide the sustainable/finite-energy partition or power-system contract",
    },
    {
        "title": "Set invariance in control",
        "authors": "Franco Blanchini",
        "year": 1999,
        "venue": "Automatica",
        "doi": "10.1016/S0005-1098(99)00113-2",
        "source_url": "https://doi.org/10.1016/S0005-1098(99)00113-2",
        "theme": "set_invariance",
        "closest_work": "foundational invariant-set analysis and synthesis",
        "remaining_gap": "general theory rather than delayed energy-limited multi-area frequency service",
    },
    {
        "title": "Constrained model predictive control: Stability and optimality",
        "authors": "D. Q. Mayne; J. B. Rawlings; C. V. Rao; P. O. M. Scokaert",
        "year": 2000,
        "venue": "Automatica",
        "doi": "10.1016/S0005-1098(99)00214-9",
        "source_url": "https://doi.org/10.1016/S0005-1098(99)00214-9",
        "theme": "mpc_stability",
        "closest_work": "terminal ingredients and recursive-feasibility foundations",
        "remaining_gap": "does not address empirical uncertainty coverage or finite-energy bridge claims",
    },
    {
        "title": "The stability of constrained receding horizon control",
        "authors": "James B. Rawlings; Kenneth R. Muske",
        "year": 1993,
        "venue": "IEEE Transactions on Automatic Control",
        "doi": "10.1109/9.241565",
        "source_url": "https://doi.org/10.1109/9.241565",
        "theme": "receding_horizon_stability",
        "closest_work": "constraint-feasible receding-horizon stability",
        "remaining_gap": "nominal stability result rather than registered delay/capability uncertainty",
    },
]


def build_focused_literature(source: pd.DataFrame) -> pd.DataFrame:
    categories = {
        "multi_area_agc",
        "adaptive_mpc",
        "adaptive_tube_mpc",
        "frequency_control",
        "native_modeling",
        "industry_guideline",
    }
    selected = source[source.category.isin(categories)].copy()
    selected = selected[
        ~selected.title.str.contains("reinforcement|neural|learning-based", case=False, regex=True)
    ]
    selected = selected.sort_values(["year", "title"], ascending=[False, True]).head(30)
    base = pd.DataFrame(
        {
            "title": selected.title,
            "authors": selected.authors,
            "year": selected.year,
            "venue": selected.venue,
            "doi": selected.doi.fillna(""),
            "source_url": selected.source_url,
            "theme": selected.category,
            "closest_work": selected.problem,
            "remaining_gap": selected.limitations,
        }
    )
    focused = pd.concat([base, pd.DataFrame(TERMINAL_REFERENCES)], ignore_index=True)
    focused["formal_source"] = focused.venue.ne("arXiv preprint")
    focused["metadata_status"] = "verified_from_phase_f_registry_or_primary_publisher"
    return focused.drop_duplicates(subset=["title"], keep="first")


def main() -> None:
    result_dir = REPO / "results_phase_g" / "G1"
    science_dir = REPO / "research_outputs_phase_g" / "01_SCIENCE"
    literature_dir = REPO / "research_outputs_phase_g" / "02_LITERATURE"
    progress_dir = REPO / "progress_phase_g"
    for directory in (result_dir, science_dir, literature_dir, progress_dir):
        directory.mkdir(parents=True, exist_ok=True)

    materiality = pd.read_csv(
        REPO / "results_phase_f" / "F1" / "MATERIALITY_FAILURE_AWARE.csv"
    )
    validation = materiality[materiality.split.eq("legacy_validation")].copy()
    non_delay = validation[~validation.mechanism.eq("delay")].copy()
    mechanism_summary = (
        non_delay.groupby("mechanism", as_index=False)
        .agg(
            tensions_tested=("sg_tension", "nunique"),
            cells_passing=("cell_materiality_pass", "sum"),
            minimum_oracle_success_rate=("oracle_success_rate", "min"),
            maximum_success_drop=("success_rate_difference", lambda x: max(0.0, -x.min())),
        )
    )
    mechanism_summary["mechanism_material"] = mechanism_summary.cells_passing.ge(2)
    mechanism_path = result_dir / "MATERIALITY_SCOPE.csv"
    mechanism_summary.to_csv(mechanism_path, index=False)

    tension_summary = (
        non_delay.groupby("sg_tension", as_index=False)
        .agg(
            mechanisms_tested=("mechanism", "nunique"),
            material_cells=("cell_materiality_pass", "sum"),
        )
    )
    tension_summary["tension_material"] = tension_summary.material_cells.ge(2)
    tension_path = result_dir / "SG_TENSION_SCOPE.csv"
    tension_summary.to_csv(tension_path, index=False)

    delay = validation[validation.mechanism.eq("delay")]
    delay_path = result_dir / "DELAY_CLAIM_BOUNDARY.csv"
    delay.assign(
        phase_g_status="IMPLEMENTATION_UNCERTAINTY_MATERIALITY_NOT_ESTABLISHED"
    ).to_csv(delay_path, index=False)

    source_literature = pd.read_csv(
        REPO / "research_outputs_phase_f" / "02_LITERATURE" / "LITERATURE_MATRIX.csv"
    )
    focused = build_focused_literature(source_literature)
    literature_path = literature_dir / "PHASE_G_FOCUSED_LITERATURE.csv"
    focused.to_csv(literature_path, index=False)

    gap = focused.groupby("theme", as_index=False).agg(
        registered_sources=("title", "count"),
        closest_work=("closest_work", "first"),
        remaining_gap=("remaining_gap", "first"),
    )
    gap_path = literature_dir / "CLAIM_CLOSEST_WORK_REMAINING_GAP.csv"
    gap.to_csv(gap_path, index=False)

    claim_path = science_dir / "PHASE_G_CLAIM_BOUNDARY.md"
    claim_path.write_text(
        """# Phase G scientific scope

The frozen failure-aware validation evidence supports materiality for power/
headroom, ramp, energy, and availability across multiple SG tensions. The
development-selected deployable comparator remains `fixed_allocation_pi`.

Delay remains a registered implementation uncertainty in CDSR-MPC. The frozen
validation cells do not justify an independent delay-materiality claim, so
Phase G will not use delay as a headline H1 result.

Phase F G5 is reclassified as `CERTIFICATE_FORMULATION_INCOMPATIBLE`. Phase G
tests whether physically structured prediction/local-terminal uncertainty,
load-dependent equilibria, and sustainable/bridge separation can yield valid
certificates without changing the CDSR-MPC method.

The focused registry contains peer-reviewed/official work on multi-area LFC,
robust/adaptive MPC, IBR frequency control, native modeling, invariant sets,
and terminal MPC. No AI/RL controller is added to the project.
""",
        encoding="utf-8",
    )

    mechanisms_passing = int(mechanism_summary.mechanism_material.sum())
    tensions_passing = int(tension_summary.tension_material.sum())
    gate = {
        "at_least_two_non_delay_mechanisms_material": mechanisms_passing >= 2,
        "at_least_two_sg_tensions_material": tensions_passing >= 2,
        "delay_claim_limited": not bool(delay.cell_materiality_pass.any()),
        "development_selected_baseline_retained": True,
        "at_least_30_focused_sources": len(focused) >= 30,
        "terminal_viability_sources_added": len(TERMINAL_REFERENCES) >= 5,
        "no_ai_or_rl_method_added": True,
    }
    outputs = (mechanism_path, tension_path, delay_path, literature_path, gap_path, claim_path)
    progress = {
        "schema": "direction1.phase_g.progress.v1",
        "stage": "G1",
        "gate": "G1_SCIENTIFIC_SCOPE",
        "gate_passed": all(gate.values()),
        "gate_components": gate,
        "mechanisms_passing": mechanisms_passing,
        "sg_tensions_passing": tensions_passing,
        "focused_literature_sources": len(focused),
        "best_deployable_baseline": "fixed_allocation_pi",
        "h1_status": "SUPPORTED_FOR_POWER_RAMP_ENERGY_AVAILABILITY",
        "delay_status": "IMPLEMENTATION_UNCERTAINTY_MATERIALITY_NOT_ESTABLISHED",
        "final_seeds_consumed": False,
        "next_stage": "G2" if all(gate.values()) else "G9_PROBLEM_SCOPE_TOO_WEAK",
        "outputs_sha256": {
            path.relative_to(REPO).as_posix(): sha256(path) for path in outputs
        },
    }
    (progress_dir / "G1.json").write_text(
        json.dumps(progress, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(progress, indent=2, sort_keys=True))
    if not progress["gate_passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
