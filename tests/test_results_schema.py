from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from d5freq.evaluation.results_schema import (
    EPISODE_RESULT_COLUMNS,
    SCHEMA_VERSION,
    EpisodeResult,
    episode_results_frame,
    validate_episode_frame,
)


def test_success_and_failed_episode_rows_have_one_stable_json_safe_schema() -> None:
    success = EpisodeResult(
        run_id="run-ok",
        scenario_id="scenario-a",
        method="SD-BMPC",
        seed=np.int64(7),
        run_completed=True,
        metrics_complete=True,
        freq_iae=0.25,
        solver_attempt_count=3,
    )
    failed = EpisodeResult.failed(
        run_id="run-failed",
        scenario_id="scenario-a",
        method="SD-BMPC",
        seed=8,
        failure_stage="simulation",
        failure_type="IntegrationError",
        failure_message="non-finite state",
        catastrophic_nan_detected=True,
    )

    frame = episode_results_frame((success, failed))

    assert tuple(frame.columns) == EPISODE_RESULT_COLUMNS
    assert len(frame) == 2
    assert success.run_completed and success.scientific_success and success.success
    assert not failed.run_completed and not failed.scientific_success
    assert failed.catastrophic_failure
    assert pd.isna(frame.loc[1, "freq_iae"])
    assert success.schema_version == "d5freq.episode-result.v2" == SCHEMA_VERSION
    assert "sg_command_violation_count" in frame.columns
    json.dumps([success.to_json_dict(), failed.to_json_dict()], allow_nan=False)


def test_schema_rejects_ambiguous_status_nonfinite_metrics_and_dropped_failure_metadata() -> None:
    with pytest.raises(ValueError, match="must equal"):
        EpisodeResult(
            run_id="r",
            scenario_id="s",
            method="m",
            seed=1,
            run_completed=True,
            metrics_complete=True,
            scientific_success=False,
        )
    with pytest.raises(ValueError, match="finite or None"):
        EpisodeResult(
            run_id="r",
            scenario_id="s",
            method="m",
            seed=1,
            run_completed=True,
            metrics_complete=True,
            freq_iae=np.nan,
        )
    with pytest.raises(ValueError, match="failure_type"):
        EpisodeResult(
            run_id="r",
            scenario_id="s",
            method="m",
            seed=1,
            run_completed=False,
        )
    with pytest.raises(ValueError, match="schema_version must equal"):
        EpisodeResult(
            run_id="r",
            scenario_id="s",
            method="m",
            seed=1,
            schema_version="d5freq.episode-result.v1",
            run_completed=True,
            metrics_complete=True,
        )


def test_from_metrics_filters_event_payload_but_keeps_catastrophic_subflags() -> None:
    metrics = {
        "metrics_complete": True,
        "freq_iae": 1.5,
        "catastrophic_safety_boundary": True,
        "catastrophic_failure": True,
        "diagnostic_detection_events": [{"delay_s": 1.0}],
    }

    row = EpisodeResult.from_metrics(
        run_id="r",
        scenario_id="s",
        method="m",
        seed=1,
        metrics=metrics,
        run_completed=True,
    )

    assert row.freq_iae == 1.5
    assert row.catastrophic_safety_boundary
    assert row.catastrophic_failure
    assert not row.scientific_success
    assert "diagnostic_detection_events" not in row.to_row()


def test_dataframe_validation_detects_duplicate_episode_identity_and_column_reordering() -> None:
    first = EpisodeResult(
        run_id="duplicate",
        scenario_id="s",
        method="m",
        seed=1,
        run_completed=True,
        metrics_complete=True,
    )
    frame = pd.DataFrame.from_records(
        [first.to_row(), first.to_row()], columns=EPISODE_RESULT_COLUMNS
    )
    with pytest.raises(ValueError, match="exactly one"):
        validate_episode_frame(frame)

    reordered = pd.DataFrame.from_records([first.to_row()], columns=EPISODE_RESULT_COLUMNS)
    reordered = reordered.loc[:, list(reversed(EPISODE_RESULT_COLUMNS))]
    with pytest.raises(ValueError, match="canonical order"):
        validate_episode_frame(reordered)
