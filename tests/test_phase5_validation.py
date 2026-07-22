from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from d5freq.evaluation.phase5_validation import (
    Phase5Settings,
    assert_runtime_truth_free,
    controller_state_machine_source,
    render_controller_state_machine,
    verify_phase5_artifact_manifest,
    write_phase5_artifact_manifest,
)
from d5freq.utils.config import load_yaml
from d5freq.utils.hashing import sha256_file


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_phase5_settings_resolve_the_frozen_native_problem() -> None:
    settings = Phase5Settings.from_configs(
        load_yaml(REPOSITORY_ROOT / "configs/base.yaml"),
        load_yaml(REPOSITORY_ROOT / "configs/mpc.yaml"),
    )
    assert settings.mpc_config.horizon_steps == 20
    assert settings.mpc_config.sample_time_s == pytest.approx(0.5)
    assert settings.mpc_config.credible_mass == pytest.approx(0.99)
    assert settings.solver_priority[:2] == ("MOSEK", "GUROBI")
    assert settings.solve_timeout_s == pytest.approx(0.20)
    assert settings.ood_config.alpha_on == pytest.approx(0.01)
    assert settings.ood_config.L_off == 5


def test_phase5_settings_reject_a_noncanonical_horizon() -> None:
    base = load_yaml(REPOSITORY_ROOT / "configs/base.yaml")
    mpc = deepcopy(load_yaml(REPOSITORY_ROOT / "configs/mpc.yaml"))
    mpc["mpc"]["horizon_steps"] = 19
    with pytest.raises(ValueError, match="horizon_steps=20"):
        Phase5Settings.from_configs(base, mpc)


def test_state_machine_png_is_reproducible_from_machine_readable_source(
    tmp_path: Path,
) -> None:
    source = controller_state_machine_source()
    state_ids = {item["id"] for item in source["states"]}
    assert state_ids == {
        "NORMAL_BELIEF_MPC",
        "ROBUST_BELIEF_MPC",
        "FALLBACK",
    }
    first = render_controller_state_machine(source, tmp_path / "first.png")
    second = render_controller_state_machine(source, tmp_path / "second.png")
    assert first.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert sha256_file(first) == sha256_file(second)


def test_runtime_truth_guard_allows_belief_but_rejects_private_truth() -> None:
    assert_runtime_truth_free(
        [
            {
                "time_s": 0.0,
                "mode_belief": [0.4, 0.6],
                "map_component_id": 1,
                "controller_state": "ROBUST_BELIEF_MPC",
            }
        ]
    )
    with pytest.raises(ValueError, match="forbidden truth key"):
        assert_runtime_truth_free([{"true_mode_eval_only": "private"}])


def test_phase5_artifact_manifest_covers_all_nonmanifest_files_and_tampering(
    tmp_path: Path,
) -> None:
    (tmp_path / "nested").mkdir()
    (tmp_path / "one.txt").write_text("one\n", encoding="utf-8")
    (tmp_path / "nested/two.json").write_text("{}\n", encoding="utf-8")
    manifest_path, digest = write_phase5_artifact_manifest(tmp_path)
    assert manifest_path.is_file()
    assert len(digest) == 64
    assert verify_phase5_artifact_manifest(tmp_path) is True

    (tmp_path / "one.txt").write_text("changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="file set, size, or SHA-256"):
        verify_phase5_artifact_manifest(tmp_path)
