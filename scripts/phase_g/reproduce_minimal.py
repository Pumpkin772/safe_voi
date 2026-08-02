"""Minimal replay of the binding Phase-G G2 stopping result."""

from __future__ import annotations

import csv
import json
from pathlib import Path


HERE = Path(__file__).resolve()
ROOT = HERE.parents[1] if (HERE.parents[1] / "17_FINAL_STATUS").is_dir() else HERE.parents[2]


def main() -> None:
    status = json.loads((ROOT / "17_FINAL_STATUS" / "FINAL_STATUS.json").read_text())
    with (ROOT / "17_FINAL_STATUS" / "ALL_GATES.csv").open(
        newline="", encoding="utf-8"
    ) as stream:
        gates = {row["gate"]: row["status"] for row in csv.DictReader(stream)}
    certificate = json.loads(
        (ROOT / "05_THEORY" / "LOCAL_TERMINAL_INCOMPATIBILITY_CERTIFICATE.json").read_text()
    )
    assert status["final_research_status"] == "LOCAL_TERMINAL_MODEL_NOT_CERTIFIABLE"
    assert status["final_seeds_consumed"] is False
    assert gates["G0"] == "PASS" and gates["G1"] == "PASS" and gates["G2"] == "FAIL"
    assert all(gates[f"G{i}"] == "NOT_EVALUATED" for i in range(3, 9))
    assert certificate["all_registered_terminal_metrics_incompatible"] is True
    result = {
        "final_status": status["final_research_status"],
        "g2_gate": gates["G2"],
        "local_terminal_one_step_compatible": status["local_terminal_one_step_compatible"],
        "final_seeds_consumed": status["final_seeds_consumed"],
        "known": status["known_results"],
        "ood": status["ood_results"],
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
