"""Verify Phase C literature metadata and build the preregistered evidence matrix."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import re
import ssl
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


REPO = Path(__file__).resolve().parents[2]
OUTPUT = REPO / "research_outputs" / "literature"
USER_AGENT = "Direction5PhaseC/1.0 (mailto:direction5.research@example.com)"


def trusted_ssl_context() -> ssl.SSLContext:
    """Use the environment's maintained CA bundle without disabling TLS checks."""

    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


SSL_CONTEXT = trusted_ssl_context()


DOI_CANDIDATES: tuple[tuple[str, str, str], ...] = (
    ("10.1109/tsg.2025.3647551", "Learning to Model the Dynamics", "black_box_ibr"),
    ("10.1109/tpwrs.2024.3523490", "Switching Dynamic State Estimation", "black_box_ibr"),
    ("10.1109/pesgm52009.2025.11225334", "Neural Dynamic State Estimation", "black_box_ibr"),
    ("10.1109/isgteurope64741.2025.11305262", "Identification of Black-Box", "black_box_ibr"),
    ("10.1109/tpwrs.2023.3337011", "Data-Driven Fast Frequency Control", "frequency_control"),
    ("10.1109/tpwrs.2021.3075641", "Hierarchical Coordinated Fast Frequency", "frequency_control"),
    ("10.1109/pesgm48719.2022.9916777", "Hierarchical Coordinated Fast Frequency", "frequency_control"),
    ("10.1109/aupec62273.2024.10807615", "MPC-based Coordinated Fast Frequency", "frequency_control"),
    ("10.1109/pesgm41954.2020.9281861", "Hierarchical Frequency Control", "frequency_control"),
    ("10.1109/naps.2018.8600596", "ANDES", "native_modeling"),
    ("10.1109/ieeestd.2022.9762253", "Interconnection and Interoperability", "industry_guideline"),
    ("10.1109/tpwrd.2026.3669810", "Inverter Based Resource With a Long Feeder", "native_modeling"),
    ("10.1049/icp.2024.1952", "Inverter-based resource models", "native_modeling"),
    ("10.1038/s41467-025-66604-z", "Data-driven dynamic modeling", "black_box_ibr"),
    ("10.1109/oajpe.2025.3615786", "Electromagnetic Transient Simulation", "native_modeling"),
    ("10.23919/ecc.2019.8795639", "Data-Enabled Predictive Control", "data_predictive"),
    ("10.1109/tac.2020.3000182", "Data-Driven Model Predictive Control", "data_predictive"),
    ("10.1109/tac.2023.3241282", "Robust Data-Enabled Predictive Control", "data_predictive"),
    ("10.1109/tcst.2023.3329334", "Robust and Kernelized Data-Enabled", "data_predictive"),
    ("10.1109/cdc40024.2019.9029522", "Data-Enabled Predictive Control for Grid-Connected", "data_predictive"),
    ("10.1137/15m1013857", "Dynamic Mode Decomposition with Control", "data_predictive"),
    ("10.1016/j.automatica.2018.03.046", "Linear predictors for nonlinear dynamical systems", "data_predictive"),
    ("10.1109/lcsys.2023.3286474", "Data-Driven Output-Feedback Control", "data_predictive"),
    ("10.1109/tac.2024.3494394", "Data-Driven Stochastic Output-Feedback", "data_predictive"),
    ("10.1515/auto-2021-0024", "Data-driven model predictive control", "data_predictive"),
    ("10.1016/j.automatica.2019.02.023", "Robust MPC with recursive model update", "adaptive_mpc"),
    ("10.1016/j.automatica.2013.02.003", "Provably safe and robust learning-based", "adaptive_mpc"),
    ("10.1002/acs.1193", "Robust adaptive MPC", "adaptive_mpc"),
    ("10.1016/j.automatica.2014.10.036", "Adaptive receding horizon control", "adaptive_mpc"),
    ("10.1002/rnc.5175", "Robust adaptive model predictive control", "adaptive_mpc"),
    ("10.1016/j.automatica.2024.111943", "Adaptive learning-based model predictive", "adaptive_mpc"),
    ("10.1002/rnc.6814", "Robust adaptive tube tracking", "adaptive_mpc"),
    ("10.1016/j.ejcon.2023.100849", "Safe learning-based model predictive", "adaptive_mpc"),
    ("10.1016/j.arcontrol.2017.11.001", "Stochastic model predictive control with active uncertainty", "dual_safe"),
    ("10.1109/cdc.2018.8619572", "Learning-Based Model Predictive Control for Safe Exploration", "dual_safe"),
    ("10.1109/cdc42340.2020.9304303", "Active exploration in adaptive model predictive", "dual_safe"),
    ("10.1016/j.automatica.2022.110684", "Safe exploration in model-based reinforcement learning", "dual_safe"),
    ("10.1016/j.automatica.2021.109597", "predictive safety filter", "dual_safe"),
    ("10.1146/annurev-control-090419-075625", "Learning-Based Model Predictive Control", "dual_safe"),
    ("10.1109/lcsys.2025.3575191", "Contingency Model Predictive Control", "dual_safe"),
    ("10.1016/j.ijepes.2014.04.050", "Distributed model predictive load frequency", "multi_area_agc"),
    ("10.1109/tpec.2018.8312114", "Model predictive load frequency control", "multi_area_agc"),
    ("10.1109/ccta.2019.8920505", "Model Predictive Load Frequency Control", "multi_area_agc"),
    ("10.3390/en10010078", "Tie-Line Bias Control", "multi_area_agc"),
    ("10.3390/en17225536", "Robust Distributed Load Frequency Control", "multi_area_agc"),
)


URL_CANDIDATES: tuple[dict[str, Any], ...] = (
    {
        "title": "EMT Analysis in Operations Planning for BPS-Connected Inverter-Based Resources",
        "year": 2025,
        "url": "https://www.nerc.com/globalassets/our-work/reports/white-papers/whitepaper_-emt-analysis-in-operations_v2.0_final.pdf",
        "category": "industry_guideline",
        "venue": "NERC white paper",
        "authors": "North American Electric Reliability Corporation",
        "formal": False,
    },
    {
        "title": "Findings from Inverter-Based Resource Model Quality Deficiencies Alert",
        "year": 2025,
        "url": "https://www.nerc.com/globalassets/programs/bpsa/alerts/2025/inverter-based_resource_modeling_deficiencies_aggregated_report.pdf",
        "category": "industry_guideline",
        "venue": "NERC aggregated report",
        "authors": "North American Electric Reliability Corporation",
        "formal": False,
    },
    {
        "title": "Inverter-Based Resource Performance Issues Public Report",
        "year": 2023,
        "url": "https://www.nerc.com/globalassets/our-work/reports/white-papers/nerc_inverter-based_resource_performance_issues_public_report_2023.pdf",
        "category": "industry_guideline",
        "venue": "NERC Level 2 Alert report",
        "authors": "North American Electric Reliability Corporation",
        "formal": False,
    },
    {
        "title": "2022 Odessa Disturbance Report",
        "year": 2022,
        "url": "https://www.nerc.com/globalassets/our-work/reports/white-papers/nerc_2022_odessa_disturbance_report-1.pdf",
        "category": "industry_guideline",
        "venue": "NERC disturbance report",
        "authors": "North American Electric Reliability Corporation",
        "formal": False,
    },
    {
        "title": "Data-Driven Koopman Predictive Control for Frequency Regulation of Power Systems using Black-Box IBRs",
        "year": 2026,
        "url": "https://arxiv.org/abs/2604.02251",
        "category": "data_predictive",
        "venue": "arXiv preprint",
        "authors": "S. Rezaei; X. Wang; S. Geng",
        "formal": False,
    },
)


CATEGORY_FIELDS: dict[str, dict[str, Any]] = {
    "black_box_ibr": {
        "problem": "identify or predict opaque IBR dynamics and changes from external measurements",
        "plant_model": "black-box or switching IBR dynamic model",
        "black_box": True,
        "multiple_modes": True,
        "online_change": True,
        "frequency_service": False,
        "multi_area": False,
        "ACE_tie_line": False,
        "diagnosis_before_control_harm": False,
        "constraint_guarantee": False,
        "active_identification": False,
        "native_RMS_or_EMT": False,
        "data_requirements": "external noisy I/O trajectories; some works use offline labels or excitation",
        "limitations": "does not jointly establish multi-area ACE responsibility, Tdet<Tcrit, and safe closed-loop reallocation",
    },
    "frequency_control": {
        "problem": "fast or coordinated frequency control using inverter-based resources",
        "plant_model": "multi-area nonlinear or phasor-domain power-system simulation",
        "black_box": True,
        "multiple_modes": False,
        "online_change": False,
        "frequency_service": True,
        "multi_area": True,
        "ACE_tie_line": True,
        "diagnosis_before_control_harm": False,
        "constraint_guarantee": "partial",
        "active_identification": False,
        "native_RMS_or_EMT": "varies",
        "data_requirements": "system or trajectory data and measurable area imbalance/frequency signals",
        "limitations": "does not address unannounced capability-set changes with a detection-critical-time Gate",
    },
    "native_modeling": {
        "problem": "credible RMS/DAE or EMT representation and validation of networked IBR dynamics",
        "plant_model": "native network RMS/DAE or EMT",
        "black_box": "varies",
        "multiple_modes": "varies",
        "online_change": False,
        "frequency_service": "supporting",
        "multi_area": "possible",
        "ACE_tie_line": False,
        "diagnosis_before_control_harm": False,
        "constraint_guarantee": False,
        "active_identification": False,
        "native_RMS_or_EMT": True,
        "data_requirements": "network/device parameters and validated operating cases",
        "limitations": "modeling infrastructure or validation evidence, not a deployable adaptive frequency controller",
    },
    "industry_guideline": {
        "problem": "IBR interconnection capability, model quality, disturbance performance, or EMT practice",
        "plant_model": "industry RMS/EMT and field-performance evidence",
        "black_box": True,
        "multiple_modes": True,
        "online_change": "motivating evidence",
        "frequency_service": True,
        "multi_area": True,
        "ACE_tie_line": "indirect",
        "diagnosis_before_control_harm": False,
        "constraint_guarantee": "requirements/guidance",
        "active_identification": False,
        "native_RMS_or_EMT": True,
        "data_requirements": "facility models, event records, settings, and validation records",
        "limitations": "engineering requirement or event evidence rather than a control algorithm",
    },
    "data_predictive": {
        "problem": "predictive control directly or indirectly from measured trajectories",
        "plant_model": "behavioral, Koopman, kernel, or output-feedback data-driven model",
        "black_box": True,
        "multiple_modes": False,
        "online_change": "limited",
        "frequency_service": "some applications",
        "multi_area": False,
        "ACE_tie_line": False,
        "diagnosis_before_control_harm": False,
        "constraint_guarantee": "under stated model/noise assumptions",
        "active_identification": False,
        "native_RMS_or_EMT": False,
        "data_requirements": "persistently exciting or informative input-output trajectories",
        "limitations": "does not by itself solve safe online capability-change diagnosis and responsibility transfer",
    },
    "adaptive_mpc": {
        "problem": "constraint-safe MPC with online model or uncertainty-set adaptation",
        "plant_model": "uncertain constrained linear or nonlinear system",
        "black_box": True,
        "multiple_modes": False,
        "online_change": True,
        "frequency_service": False,
        "multi_area": False,
        "ACE_tie_line": False,
        "diagnosis_before_control_harm": False,
        "constraint_guarantee": True,
        "active_identification": "optional persistent excitation",
        "native_RMS_or_EMT": False,
        "data_requirements": "bounded disturbances and online state/input/output data",
        "limitations": "generic control theory; Phase C must specialize capability sets, estimators, and ACE constraints",
    },
    "dual_safe": {
        "problem": "safe exploration or active uncertainty reduction within predictive control",
        "plant_model": "uncertain constrained dynamical system",
        "black_box": True,
        "multiple_modes": False,
        "online_change": True,
        "frequency_service": False,
        "multi_area": False,
        "ACE_tie_line": False,
        "diagnosis_before_control_harm": "generic precursor",
        "constraint_guarantee": True,
        "active_identification": True,
        "native_RMS_or_EMT": False,
        "data_requirements": "uncertainty representation, safe set, and online measurements",
        "limitations": "not specialized to hidden IBR capability or multi-area frequency responsibility",
    },
    "multi_area_agc": {
        "problem": "multi-area secondary load-frequency and tie-line regulation",
        "plant_model": "aggregated multi-area LFC/AGC",
        "black_box": False,
        "multiple_modes": False,
        "online_change": False,
        "frequency_service": True,
        "multi_area": True,
        "ACE_tie_line": True,
        "diagnosis_before_control_harm": False,
        "constraint_guarantee": "varies",
        "active_identification": False,
        "native_RMS_or_EMT": False,
        "data_requirements": "known area models and ACE/tie-line measurements",
        "limitations": "does not model unannounced black-box IBR capability changes or control-critical detection windows",
    },
}


def normalized(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def fetch_json(url: str) -> dict[str, Any]:
    last: Exception | None = None
    for attempt in range(5):
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urlopen(request, timeout=30, context=SSL_CONTEXT) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError) as exc:
            last = exc
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"metadata request failed after retries: {url}: {last}")


def verify_url(url: str) -> int:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=60, context=SSL_CONTEXT) as response:
        response.read(128)
        return int(response.status)


def author_text(authors: list[dict[str, Any]]) -> str:
    rendered = []
    for author in authors:
        name = " ".join(part for part in (author.get("given", ""), author.get("family", "")) if part)
        if name:
            rendered.append(name)
    return "; ".join(rendered) or "metadata unavailable"


def crossref_row(doi: str, title_fragment: str, category: str) -> dict[str, Any]:
    url = "https://api.crossref.org/works/" + quote(doi, safe="")
    message = fetch_json(url)["message"]
    title = str(message["title"][0])
    if normalized(title_fragment) not in normalized(title):
        raise RuntimeError(f"DOI/title mismatch for {doi}: {title}")
    year: int | None = None
    for field in ("published", "issued", "published-online", "published-print"):
        date_parts = message.get(field, {}).get("date-parts", [[]])[0]
        if date_parts and date_parts[0] is not None:
            year = int(date_parts[0])
            break
    if year is None and message.get("created", {}).get("date-time"):
        year = int(str(message["created"]["date-time"])[:4])
    if year is None:
        raise RuntimeError(f"Crossref metadata has no usable year for {doi}: {title}")
    venue_values = message.get("container-title") or ["publisher metadata"]
    row: dict[str, Any] = {
        "citation": f"{author_text(message.get('author', []))} ({year}). {title}. {venue_values[0]}.",
        "title": title,
        "authors": author_text(message.get("author", [])),
        "year": year,
        "venue": str(venue_values[0]),
        "doi": doi.lower(),
        "source_url": str(message.get("URL", f"https://doi.org/{doi}")),
        "source_type": str(message.get("type", "unknown")),
        "formal_peer_reviewed_or_standard": message.get("type") in {
            "journal-article", "proceedings-article", "book-chapter", "standard"
        },
        "metadata_verification": "crossref_exact_doi_title_fragment_year",
        "category": category,
    }
    row.update(CATEGORY_FIELDS[category])
    return row


def write_outputs(rows: list[dict[str, Any]], verification: dict[str, Any]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    columns = (
        "citation", "title", "authors", "year", "venue", "doi", "source_url",
        "source_type", "formal_peer_reviewed_or_standard", "metadata_verification",
        "category", "problem", "plant_model", "black_box", "multiple_modes",
        "online_change", "frequency_service", "multi_area", "ACE_tie_line",
        "diagnosis_before_control_harm", "constraint_guarantee", "active_identification",
        "native_RMS_or_EMT", "data_requirements", "limitations",
    )
    with (OUTPUT / "LITERATURE_MATRIX.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in columns} for row in rows)

    bib_lines = []
    for index, row in enumerate(rows, start=1):
        key = f"phasec{index:02d}"
        entry_type = "article" if row["formal_peer_reviewed_or_standard"] else "misc"
        bib_lines.extend(
            (
                f"@{entry_type}{{{key},",
                f"  title = {{{row['title']}}},",
                f"  author = {{{row['authors'].replace('; ', ' and ')}}},",
                f"  year = {{{row['year']}}},",
                f"  howpublished = {{{row['venue']}}},",
                f"  doi = {{{row['doi']}}}," if row["doi"] else f"  url = {{{row['source_url']}}},",
                "}",
                "",
            )
        )
    (OUTPUT / "SOURCE_BIBLIOGRAPHY.bib").write_text("\n".join(bib_lines), encoding="utf-8")
    (OUTPUT / "METADATA_VERIFICATION.json").write_text(
        json.dumps(verification, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    rows = [crossref_row(*candidate) for candidate in DOI_CANDIDATES]
    url_status: dict[str, int] = {}
    for candidate in URL_CANDIDATES:
        status = verify_url(candidate["url"])
        if status < 200 or status >= 400:
            raise RuntimeError(f"official/preprint source unavailable: {candidate['url']}")
        url_status[candidate["url"]] = status
        row = {
            "citation": f"{candidate['authors']} ({candidate['year']}). {candidate['title']}. {candidate['venue']}.",
            "title": candidate["title"],
            "authors": candidate["authors"],
            "year": candidate["year"],
            "venue": candidate["venue"],
            "doi": "",
            "source_url": candidate["url"],
            "source_type": "official-report" if "NERC" in candidate["venue"] else "posted-content",
            "formal_peer_reviewed_or_standard": candidate["formal"],
            "metadata_verification": f"source_url_http_{status}",
            "category": candidate["category"],
        }
        row.update(CATEGORY_FIELDS[candidate["category"]])
        rows.append(row)
    rows.sort(key=lambda row: (-int(row["year"]), row["title"].casefold()))
    total = len(rows)
    formal = sum(bool(row["formal_peer_reviewed_or_standard"]) for row in rows)
    post_2021 = sum(int(row["year"]) > 2021 for row in rows)
    verification = {
        "schema_version": "d5freq.phase_c.literature_verification.v1",
        "total_records": total,
        "formal_peer_reviewed_or_standard_records": formal,
        "records_after_2021": post_2021,
        "minimum_total_satisfied": total >= 40,
        "minimum_formal_satisfied": formal >= 25,
        "at_least_half_after_2021_satisfied": post_2021 * 2 >= total,
        "crossref_exact_doi_records": len(DOI_CANDIDATES),
        "official_or_preprint_url_status": url_status,
        "fabricated_records": 0,
    }
    if not all(
        verification[key]
        for key in (
            "minimum_total_satisfied", "minimum_formal_satisfied",
            "at_least_half_after_2021_satisfied",
        )
    ):
        raise RuntimeError(f"literature preregistration counts not met: {verification}")
    write_outputs(rows, verification)
    print(json.dumps(verification, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
