"""Fast replay of binding Phase-E evidence without rerunning full experiments."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    status = json.loads((ROOT / "research_outputs_phase_e" / "final" / "FINAL_STATUS.json").read_text())
    gates = pd.read_csv(ROOT / "results_phase_e" / "E9" / "ALL_GATES.csv")
    e3 = json.loads((ROOT / "progress_phase_e" / "E3_full.json").read_text())
    e6 = json.loads((ROOT / "progress_phase_e" / "E6_full.json").read_text())
    assert status["final_research_status"] == "METHOD_NOT_SUPPORTED_BY_EVIDENCE"
    assert e3["gate_passed"] is True
    assert e6["gate_passed"] is False
    assert e6["tests"]["solver_infeasibility"] > 0.01
    assert gates.set_index("gate").loc["G7", "status"] == "NOT_EVALUATED"
    assert status["final_seeds_consumed"] is False
    print(json.dumps({
        "final_status": status["final_research_status"],
        "selected_branch": status["selected_branch"],
        "best_baseline": status["best_deployable_baseline"],
        "e3_progress_sha256": sha256(ROOT / "progress_phase_e" / "E3_full.json"),
        "e6_progress_sha256": sha256(ROOT / "progress_phase_e" / "E6_full.json"),
    }, indent=2))


if __name__ == "__main__":
    main()
