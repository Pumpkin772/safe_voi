"""The locked 2x2x2 development comparison."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product


@dataclass(frozen=True)
class FactorialCell:
    information_validity_s: float
    observation: str
    acquisition: str

    @property
    def cell_id(self) -> str:
        return (
            f"T{self.information_validity_s:g}_"
            f"{self.observation.upper()}_{self.acquisition.upper()}"
        )


def development_factorial() -> tuple[FactorialCell, ...]:
    return tuple(
        FactorialCell(validity, observation, acquisition)
        for validity, observation, acquisition in product(
            (24.0, 240.0),
            ("scalar", "vector"),
            ("allocation_neutral", "control_aligned"),
        )
    )
