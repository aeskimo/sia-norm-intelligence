#!/usr/bin/env python3
"""PyInstaller-Einstiegspunkt (M8.6, REQ-813): SIA-Normenassistent (Consumer).

Delegiert 1:1 an ``sni.app.launcher.main`` (Default: Fenster-Modus;
CLI identisch zu ``python -m sni.app``, z. B. ``--headless --port 8000``).
Der frozen-Bootstrap (``launcher._frozen_core_data_dir``) säumt den
schreibbaren Kerndaten-Mount (``<user_data_dir>/data``) aus den
gebündelten Pilot-Snapshots (``sni_data/catalog/snapshots``, siehe
``--add-data`` in ``scripts/make.py``), bevor der Server startet.

Build: ``make package`` (OS-spezifisch: .app / .exe / onedir).
"""

from __future__ import annotations

import sys

from sni.app.launcher import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
