from __future__ import annotations

import json
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
FIG = ROOT / "figures_closure" / "C4"
DATA = ROOT / "research_outputs_closure" / "04_FIGURES" / "SOURCE_DATA"


def test_complete_figure_set_and_formats() -> None:
    progress = json.loads((ROOT / "progress_closure/C4.json").read_text(encoding="utf-8"))
    assert progress["status"] == "PASS"
    assert progress["figures"] >= 11
    stems = {path.stem for path in FIG.glob("*.png")}
    assert len(stems) == progress["figures"]
    for stem in stems:
        assert (FIG / f"{stem}.svg").stat().st_size > 1000
        assert (FIG / f"{stem}.pdf").stat().st_size > 1000
        assert (DATA / f"{stem}.csv").stat().st_size > 20
        assert (DATA / f"{stem}.txt").stat().st_size > 20


def test_pngs_are_publication_resolution() -> None:
    for path in FIG.glob("*.png"):
        with Image.open(path) as image:
            assert image.width >= 3000
            assert image.height >= 1800
            dpi = image.info.get("dpi", (0, 0))
            assert min(dpi) >= 590
