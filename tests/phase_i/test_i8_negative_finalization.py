"""Audit the registered negative I7/I8 route and paper-level artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from PIL import Image

from scripts.phase_i.build_i8_review_package import DIRECTORIES


REPO = Path(__file__).resolve().parents[2]
FINAL = REPO / "results_phase_i/final"


def test_only_allowed_decisive_negative_status_is_emitted() -> None:
    status = json.loads((FINAL / "FINAL_STATUS.json").read_text("utf-8"))
    assert status["project_upper"] == "DIRECTION5"
    assert status["method"] == "DCSV-MPC"
    assert status["final_research_status"] == "DIRECTION5_TERMINATED_WITH_DECISIVE_NEGATIVE_EVIDENCE"
    assert status["phase_h_h7_method_evidence_withdrawn"]
    assert status["gates"] == {
        "I0": "PASS", "I1": "PASS", "I2": "PASS", "I3": "PASS",
        "I4": "PASS", "I5": "PASS", "I6": "FAIL",
        "I7": "NOT_EVALUATED", "I8": status["gates"]["I8"],
    }
    assert status["gates"]["I8"] in {"PENDING_PACKAGE_VERIFICATION", "PASS"}
    assert status["hypotheses_h1_h6"]["H5"] == "NOT_SUPPORTED"


def test_i7_final_firewall_is_explicit_and_not_imputed() -> None:
    i7 = json.loads((REPO / "progress_phase_i/I7.json").read_text("utf-8"))
    assert i7["status"] == "NOT_EVALUATED"
    assert i7["reason"] == "REGISTERED_I6_STOP"
    assert not i7["final_seeds_consumed"]
    register = pd.read_csv(REPO / "results_phase_i/I7/NOT_EVALUATED_REGISTER.csv")
    assert register.status.eq("NOT_EVALUATED").all()
    assert not register.counted_as_success.any()
    assert not register.counted_as_failure.any()
    firewall = pd.read_csv(REPO / "results_phase_i/I7/FINAL_SEED_FIREWALL_MANIFEST.csv")
    assert firewall.seed.tolist() == list(range(100, 160))
    assert firewall.status.eq("NOT_EVALUATED").all()
    assert not firewall.episode_run.any()
    assert not firewall.counted_as_success.any()
    assert not firewall.counted_as_failure.any()


def test_final_claims_do_not_overreach_theory_or_method_evidence() -> None:
    claims = pd.read_csv(FINAL / "SUPPORTED_UNSUPPORTED_CLAIMS.csv").set_index("claim")
    assert claims.loc["Phase H H7 method evidence", "status"] == "WITHDRAWN"
    assert claims.loc["DCSV-MPC deployment advantage", "status"] == "NOT_SUPPORTED"
    assert claims.loc["Bridge guarantee", "status"] == "FINITE_HORIZON_ONLY"
    assert claims.loc["Native Plant B recursive certificate", "status"] == "UNSUPPORTED"
    status = json.loads((FINAL / "FINAL_STATUS.json").read_text("utf-8"))
    assert status["certificate_status"] == "CONDITIONAL_LOCAL_RPI_PLUS_FINITE_HORIZON_BRIDGE"
    assert status["native_plant_b_theory"] == "EMPIRICAL_VALIDATION_ONLY"


def test_paper_figures_have_vector_pdf_and_600dpi_raster_variants() -> None:
    root = REPO / "figures_phase_i/I8"
    stems = {
        "I6_PAIRED_CORE_METRICS", "PLANT_DIRECTION_AUDIT", "KNOWN_OOD_SUCCESS",
        "NORMAL1H_FREQUENCY", "SYSTEM_METHOD_DIAGRAM", "DCSV_DOMAIN_CERTIFICATE_DIAGRAM",
    }
    for stem in stems:
        for suffix in (".svg", ".pdf", ".png"):
            assert (root / f"{stem}{suffix}").stat().st_size > 1000
        with Image.open(root / f"{stem}.png") as image:
            dpi = image.info.get("dpi", (0.0, 0.0))
            assert min(dpi) >= 599.0


def test_every_episode_method_row_has_indexed_cycle_evidence() -> None:
    trace = pd.read_csv(FINAL / "TRACE_EVIDENCE_INDEX.csv")
    assert len(trace) == 300
    assert trace.groupby(["scenario_id", "method"]).size().eq(1).all()
    assert trace.stored_cycle_rows.gt(0).all()
    assert trace.representative_trace.any()
    assert trace.controller_failure_detail.any()
    assert trace.physical_certificate_detail.any()
    assert trace.trace_storage_path.eq("results_phase_i/I6/VALIDATION_CYCLES.parquet").all()


def test_final_review_sections_and_builder_names_are_locked() -> None:
    docs = REPO / "research_outputs_phase_i/08_FINAL"
    required = {
        "PACKAGE_README.md", "FINAL_RESEARCH_REPORT.md", "SUPPORTED_UNSUPPORTED_CLAIMS.md",
        "REVIEWER_RISK_REGISTER.md", "PAPER_ROUTE.md", "REPRODUCIBILITY_REPORT.md",
        "MATHEMATICAL_APPENDIX.md", "CLOSEST_WORK_AND_NOVELTY.md", "FAILURE_DIAGNOSIS.md",
    }
    assert required <= {path.name for path in docs.iterdir() if path.is_file()}
    builder = (REPO / "scripts/phase_i/build_i8_review_package.py").read_text("utf-8")
    assert 'DIRECTION5_PHASE_I_FINAL_CONVERGENCE_SINGLE_REVIEW_PACKAGE' in builder
    assert len(DIRECTORIES) == 18
    assert DIRECTORIES[0] == "00_README"
    assert DIRECTORIES[-1] == "17_FINAL_STATUS"
