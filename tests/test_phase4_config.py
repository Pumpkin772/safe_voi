from __future__ import annotations

from pathlib import Path

from d5freq.utils.config import load_yaml


ROOT = Path(__file__).resolve().parents[1]


def test_phase4_thresholds_search_and_sensitivity_are_explicit() -> None:
    config = load_yaml(ROOT / "configs" / "base.yaml")
    belief = config["belief"]
    ood = config["ood"]
    search = ood["calibration_search"]

    assert belief["switch_epsilon"] in belief["switch_epsilon_sensitivity"]
    assert ood["alpha_on"] in search["alpha_on"]
    assert ood["alpha_off"] in search["alpha_off"]
    assert ood["hold_on_steps"] in search["hold_on_steps"]
    assert ood["hold_off_steps"] in search["hold_off_steps"]
    assert all(
        any(alpha_on < alpha_off for alpha_off in search["alpha_off"])
        for alpha_on in search["alpha_on"]
    )
    assert ood["calibration_known_modes_only"] is True
