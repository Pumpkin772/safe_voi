from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from d5freq.evaluation.closed_loop_scenarios import (
    FROZEN_METHOD_IDS,
    FROZEN_SCENARIO_IDS,
    load_experiment_protocol,
    parse_experiment_protocol,
)
from d5freq.utils.config import load_yaml


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS_PATH = ROOT / "configs" / "experiments.yaml"


def test_frozen_protocol_has_exact_timebase_methods_variants_and_seed_sets() -> None:
    protocol = load_experiment_protocol(EXPERIMENTS_PATH)

    assert (
        protocol.timebase.episode_duration_s,
        protocol.timebase.control_period_s,
        protocol.timebase.integration_step_s,
    ) == (180.0, 0.5, 0.02)
    assert tuple(method.method_id for method in protocol.methods) == FROZEN_METHOD_IDS
    assert tuple(row.scenario_id for row in protocol.scenario_variants) == (
        FROZEN_SCENARIO_IDS
    )
    assert protocol.seed_sets["smoke"].values == (0, 1)
    assert protocol.seed_sets["tuning"].values == tuple(range(100, 110))
    assert protocol.seed_sets["final_known"].values == tuple(range(1000, 1030))
    assert protocol.seed_sets["final_ood_extreme"].values == tuple(
        range(1000, 1050)
    )
    assert len(protocol.seeds_for("S1_step_pos_002", "final")) == 30
    assert len(protocol.seeds_for("S7_ood_asymmetric_limit", "final")) == 50
    assert len(protocol.seeds_for("S9_compound_unavailable_double_step", "final")) == 50
    assert protocol.full_final_episode_count == 8_280


def test_scenario_families_are_concrete_and_semantically_frozen() -> None:
    protocol = load_experiment_protocol(EXPERIMENTS_PATH)
    by_id = protocol.scenarios_by_id

    s1_magnitudes = sorted(
        row.load_events[0].magnitude_pu
        for row in protocol.scenario_variants
        if row.family == "S1"
    )
    assert s1_magnitudes == [-0.08, -0.06, -0.04, -0.02, 0.02, 0.04, 0.06, 0.08]

    assert [
        row.mode_schedule.switches[0].time_s
        for row in protocol.scenario_variants
        if row.family == "S2"
    ] == [50.0, 60.0, 90.0]
    assert [
        row.noise_profile for row in protocol.scenario_variants if row.family == "S6"
    ] == ["low", "medium", "high"]

    s5 = by_id["S5_multi_switch_stochastic"]
    assert s5.stochastic_load.enabled is True
    assert [(switch.time_s, switch.mode) for switch in s5.mode_schedule.switches] == [
        (45.0, "sluggish"),
        (90.0, "derated"),
        (135.0, "nominal"),
    ]

    s9 = by_id["S9_compound_unavailable_double_step"]
    assert [(event.start_time_s, event.magnitude_pu) for event in s9.load_events] == [
        (60.0, 0.08),
        (90.0, -0.04),
    ]
    built = protocol.build_scenario(s9.scenario_id)
    assert built.duration_s == 180.0
    assert built.name == s9.scenario_id
    assert built.mode_schedule.mode_at(59.999) == "nominal"
    assert built.mode_schedule.mode_at(60.0) == "unavailable"


def test_tuning_rule_is_validation_only_and_precedes_final_ledger() -> None:
    rule = load_experiment_protocol(EXPERIMENTS_PATH).tuning_selection
    assert rule.split == "closed_loop_validation"
    assert rule.seed_set == "tuning"
    assert rule.one_global_configuration_for_all_final_scenarios is True
    assert rule.final_test_feedback_forbidden is True
    assert rule.selection_record_required is True
    assert rule.selection_record_must_precede_final_ledger is True
    assert rule.ordered_objectives[0] == "minimize_catastrophic_failure_rate"


@pytest.mark.parametrize("mutation", ["unknown_root", "missing_field", "wrong_seed"])
def test_closed_schema_rejects_unknown_missing_or_changed_frozen_fields(
    mutation: str,
) -> None:
    payload = deepcopy(load_yaml(EXPERIMENTS_PATH))
    if mutation == "unknown_root":
        payload["unregistered_option"] = True
        match = "unknown"
    elif mutation == "missing_field":
        del payload["scenario_variants"][0]["variant"]
        match = "missing"
    else:
        payload["seed_sets"]["final_known"]["stop_inclusive"] = 1030
        payload["seed_sets"]["final_known"]["count"] = 31
        match = "frozen"

    with pytest.raises(ValueError, match=match):
        parse_experiment_protocol(payload)


def test_protocol_timebase_matches_base_config() -> None:
    protocol = load_experiment_protocol(EXPERIMENTS_PATH)
    base = load_yaml(ROOT / "configs" / "base.yaml")
    assert protocol.timebase.episode_duration_s == base["simulation"][
        "episode_duration_s"
    ]
    assert protocol.timebase.control_period_s == base["grid"]["control_period_s"]
    assert protocol.timebase.integration_step_s == base["grid"][
        "integration_step_s"
    ]


def test_only_oracle_and_train_only_ablation_have_declared_truth_access() -> None:
    methods = load_experiment_protocol(EXPERIMENTS_PATH).methods_by_id
    assert methods["B4"].truth_access == "evaluation_oracle_only"
    assert methods["labeled-library"].truth_access == "training_labels_only"
    assert all(
        method.truth_access == "none"
        for method_id, method in methods.items()
        if method_id not in {"B4", "labeled-library"}
    )
