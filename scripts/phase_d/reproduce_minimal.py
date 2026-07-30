"""Cross-platform minimal reproduction for the binding Direction1 result."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def run(*args: str) -> None:
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True)


def main() -> int:
    run("-m", "pytest", "tests/phase_d", "-q")
    status = json.loads((ROOT / "research_outputs_phase_d" / "final" / "FINAL_STATUS.json").read_text(encoding="utf-8"))
    assert status["final_research_status"] == "PASSIVE_CAPABILITY_SET_NOT_SUPPORTED"
    print(json.dumps({"minimal_reproduction": "PASS", "research_status": status["final_research_status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
