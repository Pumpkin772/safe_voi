"""Deterministic, verified Phase-B1 scientific review-package builder."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import zipfile

from d5freq.evaluation.phase_b1_analysis import REQUIRED_TABLES
from d5freq.evaluation.phase_b1_protocol import PhaseB1Paths
from d5freq.utils.hashing import sha256_bytes, sha256_file


PACKAGE_NAME = "D5_PHASE_B1_BOTTLENECK_AUDIT_REVIEW_PACKAGE.zip"
MAX_PACKAGE_BYTES = 512 * 1024 * 1024
TOP_LEVEL_REPORTS = tuple(f"{index:02d}_{name}.md" for index, name in enumerate((
    "EXECUTIVE_SUMMARY",
    "BASELINE_AND_INTEGRITY",
    "PROBLEM_MATERIALITY",
    "MODEL_ADEQUACY",
    "IDENTIFIABILITY",
    "CONTROL_DESIGN_DECOMPOSITION",
    "BOTTLENECK_DECISION",
    "LIMITATIONS_AND_FAILURES",
    "REPRODUCIBILITY_COMMANDS",
)))
REQUIRED_FIGURE_PREFIXES = tuple(f"{index:02d}_" for index in range(1, 13))


def _git(repo: Path, *arguments: str) -> bytes:
    process = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return process.stdout


def _regular_files(root: Path) -> tuple[Path, ...]:
    if not root.is_dir():
        return ()
    return tuple(
        sorted(
            (path for path in root.rglob("*") if path.is_file()),
            key=lambda path: path.relative_to(root).as_posix(),
        )
    )


def _add_tree(
    mapping: dict[str, Path | bytes],
    root: Path,
    archive_root: str,
    *,
    predicate=lambda path: True,
) -> None:
    for path in _regular_files(root):
        relative = path.relative_to(root).as_posix()
        if predicate(path):
            mapping[f"{archive_root}/{relative}"] = path


def build_package_mapping(paths: PhaseB1Paths) -> dict[str, Path | bytes]:
    repo = paths.repo_root
    mapping: dict[str, Path | bytes] = {}
    report_root = paths.progress_root / "review_reports"
    for name in TOP_LEVEL_REPORTS:
        path = report_root / name
        if not path.is_file():
            raise FileNotFoundError(path)
        mapping[name] = path

    for path in (
        repo / "configs/phase_b1_audit.yaml",
        repo / "configs/phase_b1_oracle.yaml",
        repo / "configs/phase_b1_sg_levels.yaml",
    ):
        mapping[f"source/configs/{path.name}"] = path
    for path in sorted((repo / "scripts").glob("phase_b1_*.py")):
        mapping[f"source/scripts/{path.name}"] = path
    for path in sorted((repo / "src/d5freq/evaluation").glob("phase_b1_*.py")):
        mapping[f"source/src/d5freq/evaluation/{path.name}"] = path
    exact = repo / "src/d5freq/evaluation/exact_nonlinear_oracle.py"
    mapping[f"source/src/d5freq/evaluation/{exact.name}"] = exact
    _add_tree(mapping, repo / "tests_phase_b1", "source/tests_phase_b1", predicate=lambda p: "__pycache__" not in p.parts)
    _add_tree(mapping, repo / "research/phase_b1_bottleneck_audit", "research")

    baseline = "f8038467bc7a99b519f6bec692a9ad9c06f8cd19"
    mapping["git/baseline_commit.txt"] = (baseline + "\n").encode()
    mapping["git/phase_b1_commit.txt"] = _git(repo, "rev-parse", "HEAD")
    mapping["git/status.txt"] = _git(repo, "status", "--short", "--branch", "--ignored=no")
    mapping["git/log.txt"] = _git(repo, "log", "--decorate", "--oneline", f"{baseline}..HEAD")
    mapping["git/diff_from_baseline.patch"] = _git(repo, "diff", "--binary", baseline, "HEAD", "--", ".", ":!results_phase_b1/runs")
    mapping["git/tag_phase_a_final_reviewed_v2.txt"] = _git(
        repo, "show", "--no-patch", "--format=fuller", "phase-a-final-reviewed-v2"
    )

    for relative in (
        "artifacts_phase_b1/baseline_manifest.json",
        "progress_phase_b1/PHASE_B0_REPORT.md",
        "logs_phase_b1/pytest_baseline.txt",
        "logs_phase_b1/pytest_baseline.xml",
    ):
        path = repo / relative
        if path.is_file():
            mapping[f"baseline/{Path(relative).name}"] = path

    _add_tree(mapping, paths.results_root, "results")
    _add_tree(mapping, paths.figures_root, "figures")
    _add_tree(
        mapping,
        paths.artifacts_root,
        "artifacts",
        predicate=lambda p: "review_package_staging" not in p.parts,
    )
    _add_tree(mapping, paths.logs_root, "tests_and_logs")
    _add_tree(mapping, paths.progress_root, "progress")
    for name in (
        "environment_topo_sfr.yml",
        "package_versions.txt",
        "solver_smoke.json",
        "pytest_phase_b1.txt",
        "pytest_phase_b1.xml",
        "pytest_full.txt",
        "pytest_full.xml",
        "coverage_phase_b1.xml",
        "coverage_phase_b1.txt",
    ):
        path = paths.logs_root / name
        if not path.is_file():
            raise FileNotFoundError(path)
        mapping[f"environment_and_tests/{name}"] = path
    return mapping


def validate_package_mapping(mapping: Mapping[str, Path | bytes]) -> None:
    names = set(mapping)
    missing_reports = set(TOP_LEVEL_REPORTS) - names
    if missing_reports:
        raise RuntimeError(f"missing review reports: {sorted(missing_reports)}")
    missing_tables = {
        f"results/tables/{name}" for name in REQUIRED_TABLES
    } - names
    if missing_tables:
        raise RuntimeError(f"missing required result tables: {sorted(missing_tables)}")
    for prefix in REQUIRED_FIGURE_PREFIXES:
        if not any(name.startswith(f"figures/{prefix}") and name.endswith(".png") for name in names):
            raise RuntimeError(f"missing required figure category {prefix}")
    required_evidence_prefixes = (
        "results/runs/final/per_run/",
        "results/oracle_validation/",
        "artifacts/protocol_lock_phase_b1.json",
        "artifacts/oracle_validation_selection.json",
    )
    for prefix in required_evidence_prefixes:
        if prefix.endswith(".json"):
            if prefix not in names:
                raise RuntimeError(f"missing evidence file {prefix}")
        elif not any(name.startswith(prefix) for name in names):
            raise RuntimeError(f"missing evidence tree {prefix}")
    for name in names:
        path = PurePosixPath(name)
        lowered = name.lower()
        if path.is_absolute() or ".." in path.parts:
            raise RuntimeError(f"unsafe archive path: {name}")
        if ".git" in path.parts or path.suffix.lower() == ".lic":
            raise RuntimeError(f"forbidden package content: {name}")
        if "__pycache__" in path.parts or path.suffix.lower() in {".pyc", ".tmp"}:
            raise RuntimeError(f"cache/temp content is forbidden: {name}")
        if "high_frequency_trace" in lowered or "high_frequency_truth" in lowered:
            raise RuntimeError(f"high-frequency raw trace is forbidden: {name}")


def _payload_bytes(value: Path | bytes) -> bytes:
    return value.read_bytes() if isinstance(value, Path) else bytes(value)


def _manifest(mapping: Mapping[str, Path | bytes]) -> bytes:
    rows = []
    for name in sorted(mapping):
        data = _payload_bytes(mapping[name])
        rows.append({"path": name, "size_bytes": len(data), "sha256": sha256_bytes(data)})
    return (
        json.dumps(
            {
                "schema_version": "d5freq.phase_b1.review_package_manifest.v1",
                "manifest_scope": "all_archive_members_except_this_manifest",
                "file_count": len(rows),
                "files": rows,
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def build_review_package(paths: PhaseB1Paths) -> Path:
    mapping = build_package_mapping(paths)
    validate_package_mapping(mapping)
    index_buffer = io.StringIO(newline="")
    writer = csv.writer(index_buffer, lineterminator="\n")
    writer.writerow(("archive_path", "size_bytes", "sha256"))
    for name in sorted(mapping):
        data = _payload_bytes(mapping[name])
        writer.writerow((name, len(data), sha256_bytes(data)))
    mapping["git/file_index.csv"] = index_buffer.getvalue().encode("utf-8")
    mapping["SHA256_MANIFEST.json"] = _manifest(mapping)

    destination = paths.repo_root / PACKAGE_NAME
    temporary = destination.with_suffix(".zip.tmp")
    if temporary.exists():
        temporary.unlink()
    with zipfile.ZipFile(
        temporary,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
        allowZip64=True,
    ) as archive:
        for name in sorted(mapping):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, _payload_bytes(mapping[name]), compresslevel=6)
    temporary.replace(destination)
    if destination.stat().st_size >= MAX_PACKAGE_BYTES:
        raise RuntimeError(
            f"review package is {destination.stat().st_size} bytes, not below 512 MiB"
        )
    with zipfile.ZipFile(destination, "r") as archive:
        corrupt = archive.testzip()
        if corrupt is not None:
            raise RuntimeError(f"ZIP CRC verification failed at {corrupt}")
        names = set(archive.namelist())
        if names != set(mapping):
            raise RuntimeError("archive member set differs from the verified package mapping")
    return destination


__all__ = [
    "MAX_PACKAGE_BYTES",
    "PACKAGE_NAME",
    "REQUIRED_FIGURE_PREFIXES",
    "TOP_LEVEL_REPORTS",
    "build_package_mapping",
    "build_review_package",
    "validate_package_mapping",
]
