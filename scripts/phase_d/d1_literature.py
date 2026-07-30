"""Extend the frozen, verified Phase C corpus for the Direction1 question."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import re
import ssl
from urllib.parse import quote
from urllib.request import Request, urlopen


REPO = Path(__file__).resolve().parents[2]
BASE = REPO / "research_outputs" / "literature" / "LITERATURE_MATRIX.csv"
OUT = REPO / "research_outputs_phase_d" / "literature"
USER_AGENT = "Direction1PhaseD/1.0 (research metadata verification)"

DOI_ADDITIONS = (
    ("10.23919/ACC.2019.8814456", "Robust Adaptive Tube Model Predictive Control", "adaptive_tube_mpc"),
    ("10.1016/j.automatica.2023.111169", "Robust adaptive MPC using control contraction metrics", "adaptive_tube_mpc"),
    ("10.1016/j.automatica.2023.110959", "Robust adaptive model predictive control with persistent excitation conditions", "adaptive_tube_mpc"),
    ("10.1002/rnc.70319", "Robust Adaptive Model Predictive Control for Tracking", "adaptive_tube_mpc"),
)

PREPRINT_ADDITIONS = (
    {
        "title": "Robust adaptive NMPC using ellipsoidal tubes",
        "authors": "Johannes Buerger; Mark Cannon", "year": "2026",
        "venue": "arXiv preprint", "doi": "", "source_url": "https://arxiv.org/abs/2603.05029",
        "source_type": "posted-content", "formal_peer_reviewed_or_standard": "False",
        "metadata_verification": "primary_arxiv_title_author_year", "category": "adaptive_tube_mpc",
    },
    {
        "title": "Data-Driven Robust MPC for Unknown Nonlinear Systems via Set-Membership Learning",
        "authors": "Yuzhou Wei; Wenjie Liu; Yifan Xie; Frank Allgoewer; Jian Sun; Gang Wang",
        "year": "2026", "venue": "arXiv preprint", "doi": "",
        "source_url": "https://arxiv.org/abs/2606.24316", "source_type": "posted-content",
        "formal_peer_reviewed_or_standard": "False",
        "metadata_verification": "primary_arxiv_title_author_year", "category": "adaptive_tube_mpc",
    },
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes())
    return digest.hexdigest()


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def crossref(doi: str, fragment: str, category: str) -> dict[str, str]:
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
    with urlopen(request, timeout=45, context=context) as response:
        message = json.loads(response.read().decode("utf-8"))["message"]
    title = str(message["title"][0])
    if normalize(fragment) not in normalize(title):
        raise RuntimeError(f"Crossref title mismatch for {doi}: {title}")
    date_parts = message.get("published", message.get("issued"))["date-parts"][0]
    year = str(date_parts[0])
    authors = "; ".join(
        " ".join(part for part in (author.get("given", ""), author.get("family", "")) if part)
        for author in message.get("author", [])
    )
    venue = str((message.get("container-title") or ["publisher metadata"])[0])
    return {
        "citation": f"{authors} ({year}). {title}. {venue}.", "title": title,
        "authors": authors, "year": year, "venue": venue, "doi": doi.lower(),
        "source_url": str(message.get("URL", f"https://doi.org/{doi}")),
        "source_type": str(message.get("type", "journal-article")),
        "formal_peer_reviewed_or_standard": "True",
        "metadata_verification": "crossref_exact_doi_title_fragment_year",
        "category": category,
    }


def domain_fields() -> dict[str, str]:
    return {
        "problem": "causal set-membership adaptation with robust predictive constraint handling",
        "plant_model": "uncertain constrained linear or nonlinear system",
        "black_box": "True", "multiple_modes": "False", "online_change": "True",
        "frequency_service": "False", "multi_area": "False", "ACE_tie_line": "False",
        "diagnosis_before_control_harm": "generic precursor", "constraint_guarantee": "True",
        "active_identification": "optional or required persistent excitation",
        "native_RMS_or_EMT": "False",
        "data_requirements": "bounded disturbances and causal state/input/output histories",
        "limitations": "not specialized to passive IBR current-capability sets, delay uncertainty, multi-area ACE, or native RMS validation",
    }


def verify_primary_url(row: dict[str, str]) -> None:
    request = Request(row["source_url"], headers={"User-Agent": USER_AGENT})
    context = ssl.create_default_context()
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    with urlopen(request, timeout=45, context=context) as response:
        if not 200 <= response.status < 400:
            raise RuntimeError(f"primary source unavailable: {row['source_url']}")


def write_bibliography(rows: list[dict[str, str]]) -> None:
    lines: list[str] = []
    for index, row in enumerate(rows, start=1):
        entry = "article" if row["formal_peer_reviewed_or_standard"] == "True" else "misc"
        lines.extend([
            f"@{entry}{{direction1d{index:02d},", f"  title = {{{row['title']}}},",
            f"  author = {{{row['authors'].replace('; ', ' and ')}}},", f"  year = {{{row['year']}}},",
            f"  howpublished = {{{row['venue']}}},",
            f"  {'doi' if row['doi'] else 'url'} = {{{row['doi'] or row['source_url']}}},", "}", "",
        ])
    (OUT / "SOURCE_BIBLIOGRAPHY.bib").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    with BASE.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    columns = list(rows[0])
    fields = domain_fields()
    additions: list[dict[str, str]] = []
    for candidate in DOI_ADDITIONS:
        row = crossref(*candidate)
        row.update(fields)
        additions.append(row)
    for candidate in PREPRINT_ADDITIONS:
        row = dict(candidate)
        verify_primary_url(row)
        row["citation"] = f"{row['authors']} ({row['year']}). {row['title']}. {row['venue']}."
        row.update(fields)
        additions.append(row)
    existing_keys = {(row["doi"].casefold(), normalize(row["title"])) for row in rows}
    for row in additions:
        key = (row["doi"].casefold(), normalize(row["title"]))
        if key not in existing_keys:
            rows.append({column: row.get(column, "") for column in columns})
            existing_keys.add(key)
    rows.sort(key=lambda row: (-int(row["year"]), normalize(row["title"])))

    total = len(rows)
    recent = sum(int(row["year"]) >= 2022 for row in rows)
    peer = sum(row["formal_peer_reviewed_or_standard"] == "True" for row in rows)
    verified = sum(bool(row["metadata_verification"]) for row in rows)
    anchors = {
        "huang_multiple_unknown_modes_tsg": any(row["doi"].lower() == "10.1109/tsg.2025.3647551" for row in rows),
        "huang_switching_dse_tpwrs": any(row["doi"].lower() == "10.1109/tpwrs.2024.3523490" for row in rows),
        "rezaei_koopman_2026": any("2604.02251" in row["source_url"] for row in rows),
        "lu_robust_adaptive_tube_acc_2019": any(row["doi"].lower() == "10.23919/acc.2019.8814456" for row in rows),
        "recent_set_membership_nmpc": any("2603.05029" in row["source_url"] for row in rows),
        "nerc_model_quality": any("NERC" in row["venue"] and int(row["year"]) >= 2024 for row in rows),
    }
    passed = total >= 50 and recent >= 30 and peer / total >= 0.8 and verified == total and all(anchors.values())
    if not passed:
        raise RuntimeError(f"D1 Gate failed: total={total}, recent={recent}, peer={peer}, verified={verified}, anchors={anchors}")

    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "LITERATURE_MATRIX.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    write_bibliography(rows)
    verification = {
        "schema": "direction1.phase_d.literature.v1", "total_records": total,
        "records_2022_or_later": recent, "peer_reviewed_or_standard_records": peer,
        "peer_reviewed_fraction": peer / total, "verified_metadata_records": verified,
        "phase_c_corpus_sha256": sha256(BASE), "anchors": anchors,
        "launch_metadata_correction": "Lu/Cannon 2019 is ACC, not TCST; DOI and venue verified through Crossref and Oxford ORA.",
        "gate": "PASS",
    }
    (OUT / "METADATA_VERIFICATION.json").write_text(json.dumps(verification, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "LITERATURE_REVIEW.md").write_text(f"""# Direction1 Phase D literature review

The verified corpus contains {total} records, including {recent} from 2022–2026 and {peer} ({peer/total:.1%}) peer-reviewed papers or formal standards. It spans black-box and switching IBR modeling, native RMS/EMT validation, multi-area ACE control, data-enabled predictive control, set-membership adaptive MPC, robust tubes, safe/dual control, and industry model-quality evidence.

## Evidence synthesis

External-I/O modeling of opaque IBRs and switching dynamic-state estimation are established, but they do not prove that natural frequency-control trajectories identify a *current feasible active-power/ramp/delay/energy set* before control harm. Robust adaptive and tube-MPC theory provides set contraction, recursive-feasibility, and robust-constraint tools under bounded disturbances, but the surveyed papers do not combine those tools with multi-area ACE/tie-line control, hidden IBR service capability, causal passive updates, and a native networked RMS plant. Recent nonlinear tube/set-membership work strengthens the theoretical neighborhood but remains generic or preprint evidence.

The literature therefore supports testing—rather than assuming—the Direction1 claim: a control-relevant capability set estimated from public histories may reduce fixed worst-case conservatism while retaining a tube and SG terminal backup. Novelty is conditional on passing H1–H4; this review makes no priority or effectiveness claim.

## Metadata correction

The launch text called the Lu–Cannon 2019 anchor “TCST.” Verified metadata identify it as the 2019 American Control Conference paper `Robust Adaptive Tube Model Predictive Control`, DOI `10.23919/ACC.2019.8814456`. The record is corrected here.
""", encoding="utf-8")
    (OUT / "NOVELTY_COMPARISON_TABLE.md").write_text("""# Novelty comparison

| Research family | Causal external I/O | Online capability set | Delay/energy set | Real rolling MPC | Tube/terminal proof | Multi-area ACE/tie | Native RMS cross-validation |
|---|---:|---:|---:|---:|---:|---:|---:|
| Black-box/switching IBR identification | yes | no | no | no | no | limited | some |
| Frequency/AGC MPC | usually | no | no | yes | varies | yes | varies |
| Robust adaptive tube MPC | yes | parameter set | rarely both | yes | yes | no | no |
| DeePC/Koopman/data MPC | yes | model/data set | rarely | yes | varies | limited | limited |
| Direction1 CRCS-TMPC target | yes | **current control capability** | **yes** | **yes** | **yes, Plant A scope** | **yes** | **yes, empirical Plant B** |

The final row is a preregistered target, not an achieved novelty claim. It is withdrawn if H1, H2, H3, or H4 fails as specified.
""", encoding="utf-8")
    (OUT / "SEARCH_LOG.md").write_text("""# Search and verification log

- 2026-07-30: reused the frozen Phase C Crossref/official-source corpus; source hash is recorded in `METADATA_VERIFICATION.json`.
- 2026-07-30: searched IEEE/ORCID/Oxford records for `Lu Cannon robust adaptive tube MPC 2019`; corrected the requested venue from TCST to ACC and verified DOI `10.23919/ACC.2019.8814456`.
- 2026-07-30: searched Crossref and publisher records for recent robust adaptive tube/set-membership MPC; added Automatica `10.1016/j.automatica.2023.111169`, Automatica `10.1016/j.automatica.2023.110959`, and IJRNLC `10.1002/rnc.70319`.
- 2026-07-30: verified primary arXiv records `2603.05029` and `2606.24316`; both are explicitly marked non-peer-reviewed preprints.
- 2026-07-30: retained NERC 2024–2026 model-quality, EMT-practice, disturbance-data, and IBR reporting material as engineering evidence, not algorithm evidence.

Inclusion required exact DOI/title agreement or a reachable primary official/preprint record. Search-result snippets and secondary pages were not treated as evidence records.
""", encoding="utf-8")

    outputs = [OUT / name for name in ("LITERATURE_MATRIX.csv", "SOURCE_BIBLIOGRAPHY.bib", "METADATA_VERIFICATION.json", "LITERATURE_REVIEW.md", "NOVELTY_COMPARISON_TABLE.md", "SEARCH_LOG.md")]
    progress = {
        "stage": "D1", "goal": "Lock the scientific question and verified novelty boundary",
        "status": "PASSED", "gate": "LITERATURE_AND_NOVELTY", "gate_passed": True,
        "inputs_sha256": {"phase_c_literature": sha256(BASE)},
        "commands": ["python scripts/phase_d/d1_literature.py", "python -m pytest tests/phase_d/test_d1_literature.py -q"],
        "tests": {"total": total, "recent": recent, "peer_fraction": peer / total, "verified": verified, "anchors": anchors},
        "failures": [], "repairs": ["Corrected Lu/Cannon 2019 venue metadata", "Added six set-membership/tube-MPC anchors"],
        "outputs_sha256": {path.relative_to(REPO).as_posix(): sha256(path) for path in outputs}, "next_stage": "D2",
    }
    progress_path = REPO / "progress_phase_d" / "D1.json"; progress_path.parent.mkdir(exist_ok=True)
    progress_path.write_text(json.dumps(progress, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(progress, indent=2))


if __name__ == "__main__":
    main()

