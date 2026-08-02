from __future__ import annotations

import pandas as pd

from scripts.phase_g.run_g1_scope import build_focused_literature


def test_focused_literature_excludes_ai_rl_and_adds_terminal_sources() -> None:
    source = pd.read_csv(
        "research_outputs_phase_f/02_LITERATURE/LITERATURE_MATRIX.csv"
    )
    focused = build_focused_literature(source)
    assert len(focused) >= 30
    assert not focused.title.str.contains(
        "reinforcement|neural|learning-based", case=False, regex=True
    ).any()
    assert focused.theme.eq("rpi_computation").any()
    assert focused.theme.eq("mpc_stability").any()
