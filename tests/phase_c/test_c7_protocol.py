from __future__ import annotations
import pytest
from d5freq.experiments.phase_c_protocol import *

def test_final_seed_firewall():
    assert_tuning_seeds(DEVELOPMENT_SEEDS);assert_tuning_seeds(VALIDATION_SEEDS)
    with pytest.raises(RuntimeError):assert_tuning_seeds([1000])

def test_not_evaluated_is_distinct_from_failure():
    assert classify(evaluated=False)=='not_evaluated'
    assert classify(applicable=False)=='not_applicable'
    assert classify(performance=True)=='frequency_or_ace_failure'

def test_final_seed_counts_and_scenario_mapping():
    assert len(FINAL_KNOWN_SEEDS)==30 and len(FINAL_OOD_SEEDS)==50
    assert all(scenario_for_seed(s) in KNOWN_SCENARIOS for s in FINAL_KNOWN_SEEDS)
