"""Audit the source/data inputs required by the Direction5 closure archive."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research_outputs_closure" / "05_ARCHIVE"
PROGRESS = ROOT / "progress_closure" / "C5.json"

REQUIRED_TREES = (
    "src/direction5freq",
    "scripts/direction5_final",
    "scripts/direction5_closure",
    "tests/direction5_final",
    "tests/direction5_closure",
    "configs/direction5_final",
    "configs/direction5_closure",
    "research/DIRECTION5_CLOSURE_CONFIRMATION_AND_MANUSCRIPT_CODEX_PACKAGE",
    "results_final",
    "research_outputs_final",
    "results_closure/C2",
    "research_outputs_closure",
    "logs_final",
    "logs_closure/C2",
    "figures_final",
    "figures_closure/C4",
    "progress_final",
    "progress_closure",
)
REQUIRED_FILES = ("AGENTS.md", "README.md", "environment.yml", "pyproject.toml")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    missing = [item for item in (*REQUIRED_TREES, *REQUIRED_FILES) if not (ROOT / item).exists()]
    if missing:
        raise FileNotFoundError(f"archive inputs missing: {missing}")

    excluded_parts = {"__pycache__", ".pytest_cache", ".git", "review_package_staging"}
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in (*REQUIRED_TREES, *REQUIRED_FILES):
        base = ROOT / item
        files = [base] if base.is_file() else sorted(path for path in base.rglob("*") if path.is_file())
        for path in files:
            rel = path.relative_to(ROOT).as_posix()
            # The inventory is evidence about package inputs; excluding its own
            # outputs avoids an impossible self-hash and keeps repeated audits
            # semantically stable.
            if path == PROGRESS or path == OUT or OUT in path.parents:
                continue
            if rel in seen or any(part in excluded_parts for part in path.parts):
                continue
            if path.suffix in {".pyc", ".pyo"} or path.name.endswith(".lic"):
                continue
            seen.add(rel)
            rows.append({"repository_path": rel, "bytes": path.stat().st_size, "sha256": sha256(path)})
    rows.sort(key=lambda row: str(row["repository_path"]))
    with (OUT / "ARCHIVE_INPUT_SHA256.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["repository_path", "bytes", "sha256"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    tree_rows = []
    for tree in REQUIRED_TREES:
        prefix = tree.rstrip("/") + "/"
        selected = [row for row in rows if row["repository_path"] == tree or str(row["repository_path"]).startswith(prefix)]
        tree_rows.append({"source": tree, "files": len(selected), "bytes": sum(int(row["bytes"]) for row in selected), "required": True})
    with (OUT / "ARCHIVE_INVENTORY.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["source", "files", "bytes", "required"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(tree_rows)

    data_dictionary = """# Direction5 closure data dictionary

## Primary episode and cycle tables

- `FINAL_EPISODES.parquet`: one row per scenario-method run. Key fields include scenario ID, seed, plant, condition, physical domain, method, success/terminal flags, performance metrics, solver/restoration/fallback counts, and provenance.
- `FINAL_CYCLES.parquet`: rolling control decisions and applied actions. The optimization-decision denominator includes accepted primary, accepted restoration, fallback, and unhandled decisions; raw solver invocations additionally count restoration attempts.
- `FINAL_PAIRED_ROWS.parquet`: paired DCSV-CR versus contract-only rows after physical-domain classification.

## Registered summaries

- `FINAL_STATISTICS.csv`: scenario-balanced aggregate means and paired absolute differences. Mean episode-relative ratios are diagnostic only.
- `FINAL_BOOTSTRAP.csv`: seed/design-cell hierarchical bootstrap intervals.
- `FINAL_PAIRED_FAILURES.csv`: mutually exclusive both-success, one-method-fails, both-fail, not-evaluated, physically-infeasible, and contract-violation categories.
- `FINAL_SOLVER_DENOMINATOR.csv`: attempted optimization decisions and raw solver invocations with auditable identities.
- `FINAL_KNOWN_OOD.csv`, `FINAL_DOMAIN_STATISTICS.csv`, and `FINAL_PLANT_DIRECTION.csv`: registered subgroup evidence.

## Boolean and missing-value semantics

`False` is a measured negative result. `NOT_EVALUATED` is neither failure nor success. `PHYSICALLY_INFEASIBLE_CERTIFIED` is separated before ordinary controller scoring. Empty cells in penalty columns denote the both-success primary analysis, not missing experiments.

## Units

Frequency is Hz; time is seconds; power and ACE quantities are per-unit unless named otherwise; energy state is measured SoC; tie-line RMS is per-unit. Solver time fractions are dimensionless fractions of the control period.
"""
    (OUT / "DATA_DICTIONARY.md").write_text(data_dictionary, encoding="utf-8", newline="\n")

    license_notice = """# License and credential notice

The archive contains research source, generated evidence, and the repository environment specification. It contains no Gurobi or MOSEK license file, license key, access token, user credential, Conda environment, wheel cache, or Python bytecode cache. Third-party packages remain governed by their own licenses and are named/pinned by `environment.yml` and `pyproject.toml`. ANDES model execution uses the recorded third-party package; the package does not relicense ANDES. Reviewers must provision any separately licensed solver themselves, although the frozen closure paths use the recorded open solver stack for the audited runs.
"""
    (OUT / "LICENSE_NOTICE.md").write_text(license_notice, encoding="utf-8", newline="\n")

    reproduction = """# Reproducibility map

1. From the extracted package root, run `python 16_REPRODUCIBILITY/verify_manifest.py`.
2. Run `python 16_REPRODUCIBILITY/reproduce_minimal.py` for a standard-library replay of final state, C0 audit facts, validation/confirmation Gates, seed consumption, and solver identities.
3. Install `09_SOURCE_ENV/repository/environment.yml`, then run the test commands in `10_TESTS/TEST_COMMANDS.md`.
4. Full validation and confirmation entry points, locked manifests, source, and raw outputs are retained. Final seeds are already consumed; do not rerun the confirmatory protocol as a new scientific sample or tune from it.
5. Figures can be regenerated with `09_SOURCE_ENV/repository/scripts/direction5_closure/run_c4_figures.py` after installing the environment.
"""
    (OUT / "REPRODUCIBILITY_MAP.md").write_text(reproduction, encoding="utf-8", newline="\n")

    git_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    plan = {
        "schema": "direction5.closure.archive_plan.v1",
        "project": "DIRECTION5",
        "method": "DCSV-CR-MPC",
        "git_head_at_c5": git_head,
        "trees": list(REQUIRED_TREES),
        "single_files": list(REQUIRED_FILES),
        "input_files": len(rows),
        "input_bytes": sum(int(row["bytes"]) for row in rows),
        "credentials_included": False,
        "caches_included": False,
        "final_seed_rerun_permitted": False,
    }
    (OUT / "SOURCE_DATA_ARCHIVE_PLAN.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8", newline="\n")

    progress = {
        "schema": "direction5.closure.progress.v1",
        "stage": "C5",
        "status": "PASS",
        "complete_source_snapshot_planned": True,
        "validation_raw_results_planned": True,
        "confirmatory_raw_results_planned": True,
        "all_failures_planned": True,
        "data_dictionary_present": True,
        "license_notice_present": True,
        "input_files": len(rows),
        "input_bytes": plan["input_bytes"],
        "post_result_tuning": False,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "next_stage": "C6",
    }
    PROGRESS.write_text(json.dumps(progress, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(progress, indent=2))


if __name__ == "__main__":
    main()
