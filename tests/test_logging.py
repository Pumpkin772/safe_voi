from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from d5freq.utils.logging import JsonlLogger, iter_jsonl, write_jsonl


def test_jsonl_round_trip_supports_scientific_values(tmp_path: Path) -> None:
    path = write_jsonl(
        tmp_path / "events.jsonl",
        [
            {"event": "start", "value": np.float64(1.25)},
            {"event": "samples", "values": np.array([1, 2, 3])},
        ],
    )

    assert list(iter_jsonl(path)) == [
        {"event": "start", "value": 1.25},
        {"event": "samples", "values": [1, 2, 3]},
    ]


def test_logger_preserves_context_and_records_exception(tmp_path: Path) -> None:
    logger = JsonlLogger(tmp_path / "run.jsonl", {"run_id": "smoke-0"})
    logger.info("episode_started", seed=0)
    try:
        raise RuntimeError("solver failed")
    except RuntimeError as error:
        logger.exception("episode_failed", error, retained=True)

    records = list(iter_jsonl(tmp_path / "run.jsonl"))
    assert records[0]["run_id"] == "smoke-0"
    assert records[0]["level"] == "INFO"
    assert records[1]["exception_type"] == "RuntimeError"
    assert records[1]["retained"] is True
    assert "solver failed" in records[1]["traceback"]


def test_jsonl_rejects_nonfinite_values_and_nonobject_records(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError):
        write_jsonl(tmp_path / "invalid.jsonl", [{"value": float("nan")}])
    path = tmp_path / "nonobject.jsonl"
    path.write_text("[1,2,3]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be an object"):
        list(iter_jsonl(path))

