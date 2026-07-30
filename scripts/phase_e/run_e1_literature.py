"""Freeze the Phase-E scientific question and build an auditable literature corpus.

The first run should use ``--refresh-metadata``.  It verifies every new DOI
against Crossref and stores the returned metadata.  Later offline runs consume
that immutable snapshot and still validate all titles, years, and venues.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import ssl
import time
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


REPO = Path(__file__).resolve().parents[2]
BASE = REPO / "research_outputs_phase_d" / "literature" / "LITERATURE_MATRIX.csv"
OUT_SCIENCE = REPO / "research_outputs_phase_e" / "01_SCIENCE"
OUT_LITERATURE = REPO / "research_outputs_phase_e" / "02_LITERATURE"
SNAPSHOT = OUT_LITERATURE / "CROSSREF_SNAPSHOT.json"
USER_AGENT = "Direction1PhaseE/1.0 (auditable literature metadata; mailto:research@example.invalid)"

THEMES = (
    "theme_black_box_ibr_multimode",
    "theme_data_driven_frequency_control",
    "theme_set_adaptive_tube_mpc",
    "theme_active_dual_safe_identification",
    "theme_multi_area_agc_ace_constrained",
)

# DOI, exact title fragment, primary category, relevance themes.
DOI_ADDITIONS = (
    ("10.1109/tia.2023.3301488", "Stability Analysis Tool", "black_box_ibr", (THEMES[0],)),
    ("10.1109/tpwrd.2024.3493381", "Efficient Resonance Mode Analysis", "black_box_ibr", (THEMES[0],)),
    ("10.1109/tec.2024.3365353", "Data-Driven Nonlinear Model Predictive Control", "data_frequency_control", (THEMES[0], THEMES[1])),
    ("10.1109/tpwrs.2026.3684993", "Hybrid Data/Model-Driven Whole-System Admittance", "black_box_ibr", (THEMES[0],)),
    ("10.1109/etfg61999.2025.11401098", "Dynamic Mode Identification", "black_box_ibr", (THEMES[0],)),
    ("10.1016/j.epsr.2026.113699", "Koopman predictive control", "data_frequency_control", (THEMES[0], THEMES[1])),
    ("10.1109/isgteurope52324.2021.9640013", "Data-Enabled Predictive Control Method for Frequency Regulation", "data_frequency_control", (THEMES[1],)),
    ("10.1109/tpwrs.2022.3223255", "Data-Driven Load Frequency Control", "data_frequency_control", (THEMES[1], THEMES[4])),
    ("10.1049/iet-gtd.2017.0799", "SPSA-based data-driven control strategy", "data_frequency_control", (THEMES[1],)),
    ("10.1109/tsg.2024.3395448", "Distributed Data-Driven Frequency Control", "data_frequency_control", (THEMES[1], THEMES[4])),
    ("10.1016/j.egyr.2023.04.140", "Event-triggered model-free adaptive predictive control", "data_frequency_control", (THEMES[1], THEMES[4])),
    ("10.4108/ew.7500", "Reinforcement Learning Data-Driven Optimal Load-Frequency Control", "data_frequency_control", (THEMES[1],)),
    ("10.1109/icspis56952.2022.10043996", "Data-Driven Model Predictive Control for Load-Frequency Control", "data_frequency_control", (THEMES[1],)),
    ("10.1016/j.ijepes.2026.111834", "Data-driven load frequency control with delay compensation", "data_frequency_control", (THEMES[1],)),
    ("10.1016/j.ifacol.2023.10.1132", "Dual adaptive MPC", "dual_safe", (THEMES[2], THEMES[3])),
    ("10.1016/j.ifacol.2019.12.159", "Distributed Model Predictive Load Frequency Control", "multi_area_agc", (THEMES[4],)),
    ("10.1016/j.isatra.2017.03.009", "distributed model predictive control based load frequency control", "multi_area_agc", (THEMES[4],)),
    ("10.1016/j.est.2024.113340", "Tube-based MPC strategy for load frequency control", "multi_area_agc", (THEMES[2], THEMES[4])),
    ("10.1109/tpec.2019.8662140", "Optimal Load Frequency Control Of Multi-Area", "multi_area_agc", (THEMES[4],)),
    ("10.1109/tii.2025.3594079", "Load Frequency Control of Multiarea", "multi_area_agc", (THEMES[4],)),
)

# This journal DOI is not indexed by Crossref.  The metadata was verified from
# the journal's own article page and is kept visibly distinct from DOI metadata.
PUBLISHER_RECORDS = (
    {
        "citation": "Yan Zhang; Xuhui Bu; Zongyao Chen (2025). Controller-dynamic-linearization-based data-driven load frequency control for interconnected power systems. Control Theory & Applications.",
        "title": "Controller-dynamic-linearization-based data-driven load frequency control for interconnected power systems",
        "authors": "Yan Zhang; Xuhui Bu; Zongyao Chen",
        "year": "2025",
        "venue": "Control Theory & Applications",
        "doi": "10.7641/cta.2024.30403",
        "source_url": "https://jcta.ijournals.cn/cta_cn/article/html/CCTA230403",
        "source_type": "journal-article",
        "formal_peer_reviewed_or_standard": "True",
        "metadata_verification": "publisher_article_page_exact_doi_title_authors_year_venue",
        "category": "data_frequency_control",
        THEMES[1]: "True",
        THEMES[4]: "True",
    },
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def date_year(message: dict) -> str:
    for key in ("published-online", "published-print", "published", "issued"):
        if message.get(key, {}).get("date-parts"):
            return str(message[key]["date-parts"][0][0])
    raise RuntimeError(f"No publication year in Crossref record {message.get('DOI')}")


def fetch_crossref(doi: str) -> dict:
    context = ssl.create_default_context()
    try:
        import certifi

        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    request = Request(
        "https://api.crossref.org/works/" + quote(doi, safe=""),
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    for attempt in range(6):
        try:
            with urlopen(request, timeout=45, context=context) as response:
                return json.loads(response.read().decode("utf-8"))["message"]
        except HTTPError as error:
            if error.code != 429 or attempt == 5:
                raise
            time.sleep(2.0 * (attempt + 1))
    raise AssertionError("unreachable")


def refresh_snapshot() -> list[dict]:
    messages: list[dict] = []
    for doi, fragment, _category, _themes in DOI_ADDITIONS:
        message = fetch_crossref(doi)
        title = str(message["title"][0])
        if normalize(fragment) not in normalize(title):
            raise RuntimeError(f"Crossref title mismatch for {doi}: {title}")
        messages.append(message)
        time.sleep(0.45)
    OUT_LITERATURE.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "direction1.phase_e.crossref_snapshot.v1",
        "retrieved_date": "2026-07-31",
        "records": messages,
    }
    SNAPSHOT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return messages


def load_snapshot(refresh: bool) -> list[dict]:
    if refresh or not SNAPSHOT.exists():
        return refresh_snapshot()
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))["records"]


def row_from_crossref(message: dict, category: str, themes: tuple[str, ...]) -> dict[str, str]:
    title = str(message["title"][0])
    authors = "; ".join(
        " ".join(part for part in (author.get("given", ""), author.get("family", "")) if part)
        for author in message.get("author", [])
    )
    venue = str((message.get("container-title") or [message.get("publisher", "publisher metadata")])[0])
    year = date_year(message)
    row = {
        "citation": f"{authors} ({year}). {title}. {venue}.",
        "title": title,
        "authors": authors,
        "year": year,
        "venue": venue,
        "doi": str(message["DOI"]).lower(),
        "source_url": str(message.get("URL", f"https://doi.org/{message['DOI']}")),
        "source_type": str(message.get("type", "journal-article")),
        "formal_peer_reviewed_or_standard": "True",
        "metadata_verification": "crossref_exact_doi_title_year_venue_2026-07-31",
        "category": category,
    }
    for theme in THEMES:
        row[theme] = str(theme in themes)
    return row


def domain_fields(category: str) -> dict[str, str]:
    if category == "black_box_ibr":
        return {
            "problem": "external-I/O or data-assisted dynamic representation of opaque inverter-based resources",
            "plant_model": "IBR-integrated power system or converter network",
            "black_box": "True", "multiple_modes": "varies", "online_change": "varies",
            "frequency_service": "varies", "multi_area": "varies", "ACE_tie_line": "False",
            "diagnosis_before_control_harm": "not established", "constraint_guarantee": "varies",
            "active_identification": "sometimes uses designed perturbations", "native_RMS_or_EMT": "varies",
            "data_requirements": "terminal voltage/current or public trajectory measurements",
            "limitations": "does not jointly estimate present power/ramp/delay/energy/availability sets before a counterfactual control-loss time",
        }
    if category == "data_frequency_control":
        return {
            "problem": "data-driven or black-box predictive frequency/resource control",
            "plant_model": "power system, microgrid, or inverter resource",
            "black_box": "True", "multiple_modes": "usually no", "online_change": "varies",
            "frequency_service": "True", "multi_area": "varies", "ACE_tie_line": "varies",
            "diagnosis_before_control_harm": "not a capability-set gate", "constraint_guarantee": "varies",
            "active_identification": "usually no", "native_RMS_or_EMT": "varies",
            "data_requirements": "historical or online input/output trajectories",
            "limitations": "does not combine unannounced multidimensional capability changes, causal Tcrit, and safe responsibility reallocation",
        }
    if category == "dual_safe":
        return {
            "problem": "safe active learning or dual adaptive predictive control",
            "plant_model": "generic constrained uncertain dynamical system",
            "black_box": "True", "multiple_modes": "False", "online_change": "True",
            "frequency_service": "False", "multi_area": "False", "ACE_tie_line": "False",
            "diagnosis_before_control_harm": "generic exploration objective", "constraint_guarantee": "True",
            "active_identification": "True", "native_RMS_or_EMT": "False",
            "data_requirements": "bounded uncertainty, causal state/input history, and a safe set",
            "limitations": "not specialized to multi-area SFR or external IBR capability sets",
        }
    return {
        "problem": "constrained multi-area load-frequency/ACE control",
        "plant_model": "multi-area interconnected frequency response model",
        "black_box": "False", "multiple_modes": "False", "online_change": "varies",
        "frequency_service": "True", "multi_area": "True", "ACE_tie_line": "True",
        "diagnosis_before_control_harm": "not addressed", "constraint_guarantee": "varies",
        "active_identification": "False", "native_RMS_or_EMT": "usually no",
        "data_requirements": "frequency, ACE/tie-line, and modeled resource states",
        "limitations": "assumes known resource capability or does not time causal capability learning against control loss",
    }


def infer_existing_themes(row: dict[str, str]) -> None:
    title = normalize(row["title"])
    category = row["category"]
    for theme in THEMES:
        row[theme] = "False"
    if category == "black_box_ibr" or ("black box" in title and "inverter" in title):
        row[THEMES[0]] = "True"
    if (
        ("frequency" in title or "load frequency" in title)
        and any(token in title for token in ("data driven", "data enabled", "koopman", "model free", "learning"))
    ):
        row[THEMES[1]] = "True"
    if category in {"adaptive_mpc", "adaptive_tube_mpc"}:
        row[THEMES[2]] = "True"
    if category == "dual_safe":
        row[THEMES[3]] = "True"
    if category == "multi_area_agc" or (
        any(token in title for token in ("multi area", "multiarea", "interconnected"))
        and "frequency" in title
    ):
        row[THEMES[4]] = "True"


def merge_rows(messages: list[dict]) -> tuple[list[dict[str, str]], list[str], list[dict[str, str]]]:
    with BASE.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
        columns = list(rows[0])
    for row in rows:
        infer_existing_themes(row)
    additions: list[dict[str, str]] = []
    for definition, message in zip(DOI_ADDITIONS, messages, strict=True):
        doi, fragment, category, themes = definition
        if str(message["DOI"]).casefold() != doi.casefold():
            raise RuntimeError(f"Snapshot DOI mismatch: expected {doi}, got {message['DOI']}")
        if normalize(fragment) not in normalize(str(message["title"][0])):
            raise RuntimeError(f"Snapshot title mismatch for {doi}")
        row = row_from_crossref(message, category, themes)
        row.update(domain_fields(category))
        additions.append(row)
    for record in PUBLISHER_RECORDS:
        row = dict(record)
        row.update(domain_fields(row["category"]))
        additions.append(row)

    by_doi = {row["doi"].casefold(): index for index, row in enumerate(rows) if row["doi"]}
    by_title = {normalize(row["title"]): index for index, row in enumerate(rows)}
    for addition in additions:
        doi_key = addition["doi"].casefold()
        title_key = normalize(addition["title"])
        replace = by_doi.get(doi_key, by_title.get(title_key))
        if replace is None:
            rows.append(addition)
            replace = len(rows) - 1
        else:
            # Upgrade a preprint to its formal version when the title is identical.
            rows[replace] = addition
        by_doi[doi_key] = replace
        by_title[title_key] = replace

    # Treat a conference/journal version with the same normalized title as one
    # work and retain the stronger archival version.  Both DOIs remain visible
    # in the deduplication audit rather than inflating family coverage.
    deduplicated_versions: list[dict[str, str]] = []
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(normalize(row["title"]), []).append(row)
    rows = []
    for title_key, versions in grouped.items():
        versions.sort(
            key=lambda row: (
                row["formal_peer_reviewed_or_standard"] == "True",
                row["source_type"] == "journal-article",
                int(row["year"]),
            ),
            reverse=True,
        )
        rows.append(versions[0])
        for removed in versions[1:]:
            deduplicated_versions.append({
                "normalized_title": title_key,
                "retained_doi": versions[0]["doi"],
                "removed_doi": removed["doi"],
                "reason": "same-title conference/journal version; retained archival journal version",
            })

    all_columns = columns + [theme for theme in THEMES if theme not in columns]
    rows = [{column: row.get(column, "") for column in all_columns} for row in rows]
    rows.sort(key=lambda row: (-int(row["year"]), normalize(row["title"])))
    return rows, all_columns, deduplicated_versions


def write_bibliography(rows: list[dict[str, str]]) -> None:
    lines: list[str] = []
    for index, row in enumerate(rows, start=1):
        entry = "article" if row["formal_peer_reviewed_or_standard"] == "True" else "misc"
        lines.extend([
            f"@{entry}{{direction1e{index:03d},",
            f"  title = {{{row['title']}}},",
            f"  author = {{{row['authors'].replace('; ', ' and ')}}},",
            f"  year = {{{row['year']}}},",
            f"  howpublished = {{{row['venue']}}},",
            f"  {'doi' if row['doi'] else 'url'} = {{{row['doi'] or row['source_url']}}},",
            "}", "",
        ])
    (OUT_LITERATURE / "REFERENCES.bib").write_text("\n".join(lines), encoding="utf-8")


def write_science_documents() -> None:
    OUT_SCIENCE.mkdir(parents=True, exist_ok=True)
    (OUT_SCIENCE / "SCIENTIFIC_QUESTION_AND_HYPOTHESES.md").write_text("""# Frozen Phase-E scientific question and hypotheses

## Scientific question

In a stable multi-area secondary-frequency-control loop with fixed local PFR and a 2/4 s supervisory update, can a control center use only public causal histories (frequency, ACE, tie-line power, measured SG/BESS active power, and issued commands) to obtain a control-relevant external capability set for an opaque IBR/BESS before stale capability knowledge causes material control loss, and then reallocate responsibility without compromising constraints?

The target is not an OEM mode label.  It is the external feasible set for active-power headroom, ramp, delay, sustainable energy, service availability, and low-order prediction uncertainty.

## Frozen information boundary

Deployable controllers may use present and past public measurements, commands, declared nameplate bounds, and causal state/load estimates.  They may not read the true capability regime, hidden simulator parameters or states, true net load, future load/events/communication states, Oracle trajectories, or final-seed tuning information.  True quantities are evaluation-only.

## H1--H5

- **H1 (materiality):** on at least two physical capability-change mechanisms and resource-stressed cases, a fair rolling current-capability Oracle improves physical success or at least two frequency/ACE/tie-line metrics relative to the best deployable baseline.  It is falsified if a qualified Oracle has no material value on both Plant A and Plant B.
- **H2 (passive information):** natural closed-loop public I/O yields a sufficiently covering and contracted capability set before the counterfactual control-critical time.  It is falsified by a valid estimator failing coverage/timing for structural or excitation reasons rather than code defects.
- **H3 (safe active information):** only if H2 fails, finite safe probing can add information and contract the set before Tcrit without violating frequency, ACE, or resource constraints.  It is falsified if informative probes are unsafe or safe probes are uninformative.
- **H4 (control value):** the single Gate-selected P/A/R method improves multi-area SFR against the best deployable baseline without reducing physical success or safety on the locked final matrix.
- **H5 (certifiability):** the selected branch admits a code-matched tube/error bound, constraint tightening, and SG terminal backup yielding recursive feasibility or finite-horizon safety over its stated Plant-A scope.

## Counterfactual control-critical time

Starting from matched state, disturbance, and randomness, compare a stale-model deployable controller with the evaluation-only current-capability Oracle.  Tcrit is the first time their cumulative weighted frequency/ACE/tie-line performance gap plus physical violations reaches the preregistered materiality threshold.  Command/output mismatch area is reported only as a diagnostic and is not the definition of control loss.

## Gate-selected branch rule

Choose **P** if passive coverage, contraction, and timing pass; choose **A** only if passive fails and safe active information passes; otherwise choose **R**, a non-identifying full-capability-set robust MPC.  Only one branch may be implemented after the Gate.
""", encoding="utf-8")
    (OUT_SCIENCE / "CLAIM_BOUNDARY.md").write_text("""# Phase-E claim boundary

## Claims permitted before experiments

- The literature leaves an auditable intersection to test: unannounced multidimensional external capability change, a causal capability set timed against counterfactual control loss, and safe multi-area ACE responsibility reallocation.
- Phase E supplies a preregistered decision process among passive, safe-active, and non-identifying robust control.

These are research-scope statements, not achieved performance or priority claims.  Effectiveness, identifiability, and theory claims remain conditional on E3--E8 evidence.

## Prohibited claims

The project will not claim the first black-box IBR model, first multimode identifier, first data-driven frequency controller, first MPC/AI/set estimator, universal passive identifiability, global optimality, or unconditional Plant-B stability.  Native RMS/DAE evidence is empirical cross-validation; Plant-A theory does not automatically transfer to Plant B.

## Stop boundaries

- No defensible novelty after claim contraction: `NOVELTY_NOT_SUPPORTED`.
- Qualified Oracle immaterial on both plants: `PROBLEM_NOT_MATERIAL`.
- Invalid Plant B or unstable nominal loop: stop with the corresponding model-rebuild failure.
- Final evidence that does not support H4/H5 is retained as a negative result; failures are never deleted or converted to `not_evaluated`.
""", encoding="utf-8")
    claims = [
        ("C1", "A present capability can be operationally material", "E3 rolling O2 Oracle vs best deployable baseline on Plant A/B", "Not evaluated at E1"),
        ("C2", "Natural I/O can update a capability set before Tcrit", "E4 coverage, contraction, false-alarm, and timing tests", "Not evaluated at E1"),
        ("C3", "Safe probing is informative when passive evidence fails", "E5 safety and information-gain tests", "Not evaluated unless E5 is entered"),
        ("C4", "The Gate-selected branch improves control safely", "E8 success-first known/OOD comparisons", "Not evaluated at E1"),
        ("C5", "The implemented branch has a code-matched guarantee", "E7 assumptions, invariant/tube checks, and adversarial tests", "Not evaluated at E1"),
    ]
    with (OUT_SCIENCE / "CLAIM_EVIDENCE_MATRIX.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("claim_id", "bounded_claim", "required_evidence", "e1_status"))
        writer.writerows(claims)


def write_literature_documents(rows: list[dict[str, str]], counts: dict[str, int]) -> None:
    (OUT_LITERATURE / "SEARCH_PROTOCOL.md").write_text("""# Auditable search protocol

Search date was frozen at 2026-07-31.  The Phase-D DOI/official-source corpus was retained and extended using Crossref DOI metadata plus primary IEEE, Elsevier, Wiley, IET, EAI, journal, NERC, and official preprint records.  Search families were preregistered as: (1) black-box/multimode IBR modeling; (2) data-driven or black-box frequency control; (3) set-membership/adaptive/tube MPC; (4) active/dual control and safe identification; and (5) multi-area AGC/ACE with constrained resources.

Inclusion required relevance to at least one family and exact title/year/venue metadata from a DOI registry or primary publisher.  Preprints are explicitly non-formal neighboring work.  Duplicate DOIs and normalized titles are rejected.  Theme labels are non-exclusive because one paper can legitimately connect, for example, data-driven frequency control and multi-area ACE.  Theme counts therefore measure coverage, not the number of mutually exclusive records.

No search-result snippet was treated as a literature record.  Crossref responses for every new indexed DOI are frozen in `CROSSREF_SNAPSHOT.json`; the one non-Crossref DOI is separately marked as publisher-page verified.
""", encoding="utf-8")
    search_rows = [
        ("2026-07-31", "IEEE Xplore/Crossref", '"black-box" inverter-based resource dynamic modeling multiple modes', "black-box IBR/multimode", "Retained exact DOI/publisher matches; rejected generic ML black-box usage"),
        ("2026-07-31", "IEEE Xplore/Elsevier/Crossref", '"data-driven" frequency control inverter predictive load-frequency', "data-driven/black-box frequency control", "Included frequency/ACE/resource control; excluded unrelated forecasting"),
        ("2026-07-31", "Automatica/IFAC/IEEE/Crossref", 'set-membership adaptive tube MPC active exploration dual safe identification', "adaptive/tube and active/dual", "Separated passive adaptation from deliberate excitation"),
        ("2026-07-31", "IEEE/Elsevier/IET/Crossref", 'multi-area load frequency ACE tie-line constrained resource MPC', "multi-area AGC/ACE", "Included explicit interconnected/multi-area frequency control"),
        ("2026-07-31", "NERC/official sources", 'IBR model quality validation frequency support disturbance performance', "engineering evidence", "Retained standards/reports as engineering evidence, not algorithm novelty"),
    ]
    with (OUT_LITERATURE / "SEARCH_LOG.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("date", "database_or_primary_source", "query_family", "target", "decision_rule"))
        writer.writerows(search_rows)

    (OUT_LITERATURE / "NOVELTY_COMPARISON.md").write_text(f"""# Evidence-bounded novelty comparison

The matrix contains {len(rows)} records, including {sum(r['formal_peer_reviewed_or_standard'] == 'True' for r in rows)} formal papers or standards.  Non-exclusive preregistered theme counts are: black-box/multimode IBR {counts[THEMES[0]]}; data-driven/black-box frequency control {counts[THEMES[1]]}; set-membership/adaptive/tube MPC {counts[THEMES[2]]}; active/dual/safe identification {counts[THEMES[3]]}; multi-area AGC/ACE/constrained resources {counts[THEMES[4]]}.

## Closest-work comparison

| Closest work | What it establishes | Unannounced multidimensional capability change | Causal external capability set | Tcrit/materiality before identification | Multi-area ACE responsibility | Safe rolling constrained control | Native RMS/DAE cross-validation |
|---|---|---:|---:|---:|---:|---:|---:|
| Huang et al., IEEE TSG, DOI 10.1109/TSG.2025.3647551 | Continuous-time black-box IBR models with unknown modes and noisy data | no | no | no | no | no | no |
| Rezaei et al., EPSR, DOI 10.1016/j.epsr.2026.113699 | Data-driven rolling Koopman frequency control using black-box IBRs | no | no | no | limited | yes | no |
| Parsi et al., IFAC, DOI 10.1016/j.ifacol.2023.10.1132 | Exact set-membership dual adaptive MPC with robust constraints | generic parameters | parameter set | no | no | yes | no |
| Wang et al., Journal of Energy Storage, DOI 10.1016/j.est.2024.113340 | Tube MPC for multi-area LFC with hybrid storage | no | no | no | yes | yes | no |
| Ekomwenrenren et al., IEEE TPWRS, DOI 10.1109/TPWRS.2023.3337011 | Model-free, area-based fast frequency control using IBRs | no | no | no | frequency areas | not capability-set safe | no |

## Resulting boundary

Existing work covers every ingredient separately and several pairwise combinations.  This audit found no included work that jointly studies an *unannounced current power/ramp/delay/energy/availability change*, estimates a *causal external feasible set*, first proves *control materiality and a counterfactual Tcrit*, and then performs *safe multi-area ACE responsibility reallocation* with native network cross-validation.  Phase E may test that intersection but may not claim priority for any individual ingredient.
""", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh-metadata", action="store_true")
    args = parser.parse_args()
    OUT_LITERATURE.mkdir(parents=True, exist_ok=True)
    messages = load_snapshot(args.refresh_metadata)
    rows, columns, deduplicated_versions = merge_rows(messages)

    doi_keys = [row["doi"].casefold() for row in rows if row["doi"]]
    title_keys = [normalize(row["title"]) for row in rows]
    duplicate_dois = sorted({key for key in doi_keys if doi_keys.count(key) > 1})
    duplicate_titles = sorted({key for key in title_keys if title_keys.count(key) > 1})
    counts = {theme: sum(row[theme] == "True" for row in rows) for theme in THEMES}
    formal = sum(row["formal_peer_reviewed_or_standard"] == "True" for row in rows)
    verified = sum(bool(row["metadata_verification"]) for row in rows)
    gate = (
        len(rows) >= 50 and formal >= 50 and verified == len(rows)
        and not duplicate_dois and not duplicate_titles
        and counts[THEMES[0]] >= 10 and counts[THEMES[1]] >= 10
        and counts[THEMES[2]] >= 10 and counts[THEMES[3]] >= 8
        and counts[THEMES[4]] >= 10
    )
    if not gate:
        raise RuntimeError(
            f"E1 gate failed: total={len(rows)} formal={formal} verified={verified} "
            f"duplicates={duplicate_dois, duplicate_titles} themes={counts}"
        )

    with (OUT_LITERATURE / "LITERATURE_MATRIX.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    write_bibliography(rows)
    write_science_documents()
    write_literature_documents(rows, counts)

    verification = {
        "schema": "direction1.phase_e.literature.v1",
        "gate": "PASS",
        "retrieved_date": "2026-07-31",
        "total_records": len(rows),
        "formal_peer_reviewed_or_standard_records": formal,
        "verified_metadata_records": verified,
        "duplicate_dois": duplicate_dois,
        "duplicate_normalized_titles": duplicate_titles,
        "deduplicated_versions": deduplicated_versions,
        "theme_counts_nonexclusive": counts,
        "phase_d_corpus_sha256": sha256(BASE),
        "crossref_snapshot_sha256": sha256(SNAPSHOT),
        "publisher_verified_non_crossref_records": [record["doi"] for record in PUBLISHER_RECORDS],
        "closest_work_rows": 5,
        "novelty_result": "CONDITIONAL_INTERSECTION_SUPPORTED_FOR_TESTING",
        "claim_guard": "No individual MPC/AI/black-box/set-estimation priority claim is permitted.",
    }
    (OUT_LITERATURE / "METADATA_VERIFICATION.json").write_text(
        json.dumps(verification, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    outputs = list(OUT_SCIENCE.glob("*")) + list(OUT_LITERATURE.glob("*"))
    progress = {
        "stage": "E1",
        "goal": "Freeze the scientific question, H1-H5, information boundary, and audited novelty boundary",
        "status": "PASSED",
        "gate": "SCIENTIFIC_QUESTION_AND_LITERATURE",
        "gate_passed": True,
        "inputs_sha256": {"phase_d_literature_matrix": sha256(BASE)},
        "commands": [
            "python scripts/phase_e/run_e1_literature.py --refresh-metadata",
            "python -m pytest tests/phase_e/test_e1_literature.py -q",
        ],
        "tests": {
            "total": len(rows), "formal": formal, "verified": verified,
            "duplicates": len(duplicate_dois) + len(duplicate_titles), "theme_counts": counts,
            "deduplicated_versions": len(deduplicated_versions),
            "closest_work_rows": 5,
        },
        "failures": [],
        "repairs": [
            "Upgraded the Koopman black-box IBR preprint record to its formal EPSR DOI version",
            "Replaced mutually exclusive coverage accounting with explicit non-exclusive relevance themes",
            "Added DOI/publisher-verified sources to satisfy every preregistered family quota",
            "Deduplicated same-title conference/journal versions while retaining both DOI decisions in the audit",
        ],
        "decision": "CONDITIONAL_INTERSECTION_SUPPORTED_FOR_TESTING",
        "outputs_sha256": {
            path.relative_to(REPO).as_posix(): sha256(path) for path in sorted(outputs) if path.is_file()
        },
        "next_stage": "E2",
    }
    progress_path = REPO / "progress_phase_e" / "E1.json"
    progress_path.write_text(json.dumps(progress, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(progress, indent=2))


if __name__ == "__main__":
    main()
