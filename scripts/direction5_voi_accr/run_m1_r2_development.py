"""Launch the second post-M2 development split through the common engine."""

from pathlib import Path

import run_m1_r1_development as engine


REPO = Path(__file__).resolve().parents[2]
engine.SEARCH_PATH = REPO / "configs/direction5_voi_accr/m1_r2_development_search.yaml"
engine.OUTPUT = REPO / "research_outputs_working/M1_R2_POST_M2"
engine.PROGRESS = REPO / "progress_direction5_voi_accr/M1_R2.json"


if __name__ == "__main__":
    engine.main()
