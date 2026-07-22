"""Phase 0 package smoke tests."""

from __future__ import annotations

import importlib


def test_package_import() -> None:
    package = importlib.import_module("d5freq")

    assert package.__version__ == "0.1.0"
