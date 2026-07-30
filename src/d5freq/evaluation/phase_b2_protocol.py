"""Paths and immutable-input helpers for Phase B2 scientific hardening."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from d5freq.utils.config import load_yaml


@dataclass(frozen=True, slots=True)
class PhaseB2Paths:
    """Repository paths which keep all Phase-B2 outputs separate."""

    repo_root: Path
    config: Path
    artifacts_root: Path
    results_root: Path
    figures_root: Path
    logs_root: Path
    progress_root: Path
    phase_b1_tables: Path
    phase_b1_review_zip: Path
    baseline_manifest: Path

    @classmethod
    def from_repo(cls, repo_root: str | Path) -> "PhaseB2Paths":
        root = Path(repo_root).expanduser().resolve()
        artifacts = root / "artifacts_phase_b2"
        return cls(
            repo_root=root,
            config=root / "configs" / "phase_b2.yaml",
            artifacts_root=artifacts,
            results_root=root / "results_phase_b2",
            figures_root=root / "figures_phase_b2",
            logs_root=root / "logs_phase_b2",
            progress_root=root / "progress_phase_b2",
            phase_b1_tables=root / "results_phase_b1" / "tables",
            phase_b1_review_zip=root
            / "D5_PHASE_B1_BOTTLENECK_AUDIT_REVIEW_PACKAGE.zip",
            baseline_manifest=artifacts / "phase_b1_baseline_manifest.json",
        )

    def load_config(self) -> dict[str, object]:
        payload = load_yaml(self.config)
        if payload.get("schema_version") != "d5freq.phase_b2.protocol.v1":
            raise ValueError("unexpected Phase-B2 protocol schema")
        return payload


__all__ = ["PhaseB2Paths"]
