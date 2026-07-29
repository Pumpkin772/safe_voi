"""Auditable, resumable execution of preregistered Phase-B1 final matrices."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from d5freq.evaluation.experiment_store import PerRunExperimentStore
from d5freq.evaluation.phase_b1_experiments import (
    PhaseB1RunReceipt,
    PhaseB1RunSpec,
    execute_phase_b1_run,
)
from d5freq.evaluation.phase_b1_protocol import PhaseB1Paths, protocol_lock_sha256
from d5freq.utils.hashing import sha256_json


EXECUTION_MARKER_SCHEMA = "d5freq.phase_b1.final_execution_marker.v1"
ATTEMPT_FAILURE_SCHEMA = "d5freq.phase_b1.attempt_failure.v1"


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ) + "\n"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _spec_payload(spec: PhaseB1RunSpec) -> dict[str, Any]:
    payload = asdict(spec)
    payload["repo_root"] = str(spec.repo_root)
    return payload


def final_plan_sha256(plan: Sequence[PhaseB1RunSpec]) -> str:
    if not plan:
        raise ValueError("final plan cannot be empty")
    return sha256_json([_spec_payload(spec) for spec in plan])


def ensure_execution_marker(
    paths: PhaseB1Paths,
    *,
    matrix_id: str,
    plan: Sequence[PhaseB1RunSpec],
) -> Path:
    if not matrix_id or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789_" for char in matrix_id):
        raise ValueError("matrix_id must be lowercase snake case")
    if not plan or any(spec.stage != "final" for spec in plan):
        raise ValueError("execution marker requires a non-empty final plan")
    path = paths.artifacts_root / "final_execution" / f"{matrix_id}_plan.json"
    digest = final_plan_sha256(plan)
    immutable = {
        "schema_version": EXECUTION_MARKER_SCHEMA,
        "matrix_id": matrix_id,
        "plan_sha256": digest,
        "episode_count": len(plan),
        "protocol_lock_sha256": protocol_lock_sha256(paths),
        "final_feedback_forbidden": True,
        "unique_run_ids": len({spec.identity.run_id for spec in plan}),
    }
    if immutable["unique_run_ids"] != immutable["episode_count"]:
        raise RuntimeError("final plan contains duplicate run IDs")
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        for key, value in immutable.items():
            if existing.get(key) != value:
                raise RuntimeError(f"final execution marker changed at {key}")
        return path
    _atomic_json(
        path,
        {
            **immutable,
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "run_ids_sha256": sha256_json(sorted(spec.identity.run_id for spec in plan)),
        },
    )
    return path


def attempt_failure_path(paths: PhaseB1Paths, spec: PhaseB1RunSpec) -> Path:
    filename = sha256_json({"run_id": spec.identity.run_id}) + ".json"
    return paths.results_root / "runs" / spec.stage / "attempt_failures" / filename


def write_attempt_failure(
    paths: PhaseB1Paths,
    spec: PhaseB1RunSpec,
    error: BaseException,
) -> Path:
    path = attempt_failure_path(paths, spec)
    if path.is_file():
        return path
    message = str(error)
    if len(message) > 4000:
        message = message[:3999] + "…"
    body = {
        "schema_version": ATTEMPT_FAILURE_SCHEMA,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "failed_before_canonical_episode_publication",
        "run_spec": _spec_payload(spec),
        "run_identity": spec.identity.to_dict(),
        "failure_type": type(error).__name__,
        "failure_message": message,
        "retry_forbidden_without_explicit_review": spec.stage == "final",
    }
    _atomic_json(path, {"body": body, "sha256": sha256_json(body)})
    return path


def execute_final_plan(
    paths: PhaseB1Paths,
    *,
    matrix_id: str,
    plan: Sequence[PhaseB1RunSpec],
    max_workers: int,
    progress: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Execute each not-yet-attempted final episode exactly once.

    Verified canonical envelopes are resumed without launching workers.  A prior
    pre-publication failure receipt is also never retried implicitly; it stays
    visible for review and requires an explicit protocol decision to retry.
    """

    workers = int(max_workers)
    if workers < 1:
        raise ValueError("max_workers must be positive")
    ensure_execution_marker(paths, matrix_id=matrix_id, plan=plan)
    store = PerRunExperimentStore(paths.results_root / "runs" / "final" / "per_run")
    verified_existing: list[PhaseB1RunSpec] = []
    prior_attempt_failures: list[PhaseB1RunSpec] = []
    pending: list[PhaseB1RunSpec] = []
    for spec in plan:
        if store.load(spec.identity) is not None:
            verified_existing.append(spec)
        elif attempt_failure_path(paths, spec).is_file():
            prior_attempt_failures.append(spec)
        else:
            pending.append(spec)
    progress(
        f"{matrix_id}: total={len(plan)} existing={len(verified_existing)} "
        f"prior_failures={len(prior_attempt_failures)} pending={len(pending)}"
    )
    completed: list[PhaseB1RunReceipt] = []
    new_failures: list[str] = []
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(execute_phase_b1_run, spec): spec for spec in pending}
        for ordinal, future in enumerate(as_completed(futures), start=1):
            spec = futures[future]
            try:
                completed.append(future.result())
            except BaseException as error:  # persist every infrastructure failure
                write_attempt_failure(paths, spec, error)
                new_failures.append(spec.identity.run_id)
            if ordinal % 25 == 0 or ordinal == len(pending):
                progress(
                    f"{matrix_id} progress: {ordinal}/{len(pending)}; "
                    f"new_attempt_failures={len(new_failures)}"
                )
    summary = {
        "schema_version": "d5freq.phase_b1.execution_summary.v1",
        "matrix_id": matrix_id,
        "plan_sha256": final_plan_sha256(plan),
        "episode_count": len(plan),
        "verified_existing_count": len(verified_existing),
        "prior_attempt_failure_count": len(prior_attempt_failures),
        "new_canonical_count": len(completed),
        "new_scientific_failure_count": sum(not row.scientific_success for row in completed),
        "new_attempt_failure_count": len(new_failures),
        "canonical_total_after_run": sum(
            store.load(spec.identity) is not None for spec in plan
        ),
        "attempt_failure_total_after_run": sum(
            attempt_failure_path(paths, spec).is_file() for spec in plan
        ),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    destination = paths.results_root / "execution" / f"{matrix_id}_summary.json"
    _atomic_json(destination, summary)
    return summary


__all__ = [
    "ATTEMPT_FAILURE_SCHEMA",
    "EXECUTION_MARKER_SCHEMA",
    "attempt_failure_path",
    "ensure_execution_marker",
    "execute_final_plan",
    "final_plan_sha256",
    "write_attempt_failure",
]
