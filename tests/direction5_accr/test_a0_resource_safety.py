from __future__ import annotations

from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[2]


def test_a0_has_no_process_pool_and_refuses_parallel_workers() -> None:
    source = (REPO / "scripts/direction5_accr/run_a0_platform.py").read_text("utf-8")
    assert "ProcessPoolExecutor" not in source
    assert "choices=(1,)" in source
    assert "DIRECTION5_RESOURCE_GUARDED" in source
    assert "run_plant_b_isolated" in source


def test_native_andes_fails_closed_instead_of_automatic_codegen() -> None:
    source = (REPO / "src/direction5freq/models/plant_b_andes_full.py").read_text("utf-8")
    assert 'autogen_stale=False' in source
    assert "refuse_automatic_codegen" in source
    assert "DIRECTION5_RESOURCE_GUARDED" in source


def test_a0_resource_limits_are_hard_and_conservative() -> None:
    lock = yaml.safe_load(
        (REPO / "configs/direction5_accr/a0_platform_lock.yaml").read_text("utf-8")
    )
    limits = lock["resource_guard"]
    assert lock["execution_workers"] == 1
    assert lock["andes_execution"] == "ISOLATED_SINGLE_PROCESS"
    # Windows creates one conhost for the guarded A0 process; the second and
    # only other permitted descendant is the isolated Plant-B worker.
    assert limits["max_descendant_processes"] == 2
    assert limits["max_process_tree_private_gib"] <= 4.0
    assert limits["max_system_commit_fraction"] <= 0.65
    assert limits["poll_interval_s"] <= 0.10


def test_a6_starts_with_buffer_and_keeps_conservative_runtime_caps() -> None:
    lock = yaml.safe_load(
        (REPO / "configs/direction5_accr/a6_validation_lock.yaml").read_text("utf-8")
    )
    limits = lock["resource_guard"]
    assert limits["preflight_max_system_commit_fraction"] <= 0.64
    assert limits["max_system_commit_fraction"] <= 0.70
    assert limits["max_system_commit_fraction"] - limits["preflight_max_system_commit_fraction"] >= 0.059
    assert limits["min_available_physical_gib"] >= 8.0
    assert limits["max_process_tree_private_gib"] <= 4.0
    assert limits["max_descendant_processes"] <= 2
