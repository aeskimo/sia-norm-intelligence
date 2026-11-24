"""Einstiegspunkt: ``python -m sni.app`` (Logik in :mod:`sni.app.launcher`)."""

from __future__ import annotations

import sys

from sni.app.launcher import main

if __name__ == "__main__":
    sys.exit(main())
