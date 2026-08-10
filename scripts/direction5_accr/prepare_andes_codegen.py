"""Regenerate ANDES pycode sequentially under the Direction5 resource guard."""

from __future__ import annotations

import os


def main() -> None:
    if os.environ.get("DIRECTION5_RESOURCE_GUARDED") != "1":
        raise SystemExit("Refusing unguarded ANDES code generation")
    import andes

    # ``nomp=True`` is the decisive safety setting.  ``ncpu=1`` is repeated
    # explicitly so a future ANDES default cannot restore parallel codegen.
    andes.prepare(quick=True, nomp=True, ncpu=1)


if __name__ == "__main__":
    main()
