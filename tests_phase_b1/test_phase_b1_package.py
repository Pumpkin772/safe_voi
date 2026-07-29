from __future__ import annotations

import pytest

from d5freq.evaluation.phase_b1_analysis import REQUIRED_TABLES
from d5freq.evaluation.phase_b1_package import (
    REQUIRED_FIGURE_PREFIXES,
    TOP_LEVEL_REPORTS,
    validate_package_mapping,
)


def _complete_mapping() -> dict[str, bytes]:
    mapping = {name: b"report" for name in TOP_LEVEL_REPORTS}
    mapping.update({f"results/tables/{name}": b"header\n" for name in REQUIRED_TABLES})
    mapping.update({f"figures/{prefix}figure.png": b"png" for prefix in REQUIRED_FIGURE_PREFIXES})
    mapping["results/runs/final/per_run/a.json"] = b"{}"
    mapping["results/oracle_validation/episodes.csv"] = b"header\n"
    mapping["artifacts/protocol_lock_phase_b1.json"] = b"{}"
    mapping["artifacts/oracle_validation_selection.json"] = b"{}"
    return mapping


def test_review_package_mapping_requires_all_reports_tables_figures_and_evidence() -> None:
    mapping = _complete_mapping()
    validate_package_mapping(mapping)
    del mapping["results/tables/problem_materiality.csv"]
    with pytest.raises(RuntimeError, match="missing required result tables"):
        validate_package_mapping(mapping)


def test_review_package_mapping_rejects_credentials_cache_and_high_frequency_raw() -> None:
    for forbidden in (
        "environment/gurobi.lic",
        "source/__pycache__/x.pyc",
        "results/high_frequency_trace/a.json",
        ".git/objects/a",
    ):
        mapping = _complete_mapping()
        mapping[forbidden] = b"forbidden"
        with pytest.raises(RuntimeError):
            validate_package_mapping(mapping)
