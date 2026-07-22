from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json

import numpy as np
import pytest

from d5freq.evaluation.experiment_store import (
    PerRunExperimentStore,
    RunConflictError,
    RunIdentity,
    RunIdentityMismatchError,
    RunIntegrityError,
)
from d5freq.evaluation.results_schema import EpisodeResult


def _result(identity: RunIdentity, *, freq_iae: float = 1.0) -> EpisodeResult:
    return EpisodeResult(
        run_id=identity.run_id,
        scenario_id=identity.scenario_id,
        method=identity.method,
        seed=identity.seed,
        run_completed=True,
        metrics_complete=True,
        freq_iae=freq_iae,
    )


def test_strict_json_round_trip_has_null_not_nan_and_verified_sha256(tmp_path) -> None:
    store = PerRunExperimentStore(tmp_path / "runs")
    identity = RunIdentity("run/a", "scenario", "P", 7)

    saved = store.save(
        identity,
        _result(identity),
        {"trace": [0.0, np.nan, np.inf], "array": np.array([1.0, 2.0])},
    )
    raw = saved.path.read_text(encoding="utf-8")
    loaded_json = json.loads(raw, parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
    loaded = PerRunExperimentStore(tmp_path / "runs").load(identity)

    assert "NaN" not in raw and "Infinity" not in raw
    assert loaded_json["body"]["run_payload"]["trace"] == [0.0, None, None]
    assert loaded is not None
    assert loaded.sha256 == saved.sha256
    assert loaded.episode_result == saved.episode_result
    assert loaded.run_payload["array"] == [1.0, 2.0]


def test_resume_rejects_tampering_and_same_run_id_with_changed_identity(tmp_path) -> None:
    store = PerRunExperimentStore(tmp_path)
    identity = RunIdentity("same-run", "scenario-a", "P", 1)
    saved = store.save(identity, _result(identity), {})

    with pytest.raises(RunIdentityMismatchError):
        store.load(RunIdentity("same-run", "scenario-b", "P", 1))

    envelope = json.loads(saved.path.read_text(encoding="utf-8"))
    envelope["body"]["episode_result"]["freq_iae"] = 999.0
    saved.path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(RunIntegrityError, match="SHA-256 mismatch"):
        store.load(identity)


def test_conflicting_rewrite_never_overwrites_valid_existing_run(tmp_path) -> None:
    store = PerRunExperimentStore(tmp_path)
    identity = RunIdentity("run", "scenario", "P", 1)
    first = store.save(identity, _result(identity, freq_iae=1.0), {"attempt": 1})

    with pytest.raises(RunConflictError):
        store.save(identity, _result(identity, freq_iae=2.0), {"attempt": 2})

    loaded = store.load(identity)
    assert loaded is not None
    assert loaded.sha256 == first.sha256
    assert loaded.episode_result.freq_iae == 1.0
    assert loaded.run_payload["attempt"] == 1


def test_parallel_distinct_runs_publish_only_independent_files(tmp_path) -> None:
    store = PerRunExperimentStore(tmp_path)
    identities = [RunIdentity(f"run-{seed}", "scenario", "P", seed) for seed in range(8)]

    def save(identity: RunIdentity) -> str:
        return store.save(identity, _result(identity), {"seed": identity.seed}).sha256

    with ThreadPoolExecutor(max_workers=4) as executor:
        digests = list(executor.map(save, identities))

    assert len(set(digests)) == len(identities)
    assert len(list(tmp_path.glob("*.json"))) == len(identities)
    assert not list(tmp_path.glob("*.tmp"))
    for identity in identities:
        loaded = store.load(identity)
        assert loaded is not None
        assert loaded.run_payload["seed"] == identity.seed
