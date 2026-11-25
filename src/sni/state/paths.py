"""User-Datenverzeichnis (REQ-815, ADR-0011 Punkt 8, 09 §9.1).

Ein Verzeichnis auf allen drei OS (Migration-kompatibel zu Java):
``~/.sia-normenassistent/``, Override ``SIA_DATA_DIR``.
"""

from __future__ import annotations

import os
from pathlib import Path


def user_data_dir() -> Path:
    """``SIA_DATA_DIR``-Override, sonst ``~/.sia-normenassistent`` (Java 1:1)."""
    override = os.environ.get("SIA_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".sia-normenassistent"


def index_dir() -> Path:
    """Verschlüsselte Index-Dateien (``index/``, 09 §9.1)."""
    return user_data_dir() / "index"


def core_data_dir() -> Path:
    """SNI-Kerndaten-Mount: Katalog/Wissensbasis/Regeln/Queue/Normen (M8.6, REQ-813).

    ``SIA_CORE_DATA_DIR``-Override, sonst das Repository-``data/`` (Dev-Modus).
    Call-time aufgelöst: die frozen App setzt die Variable im Launcher, nach
    den Modul-Imports (REQ-813: im PyInstaller-Bündel wäre ``data/``
    read-only; dort liegt der Mount unter ``<user_data_dir>/data``).
    """
    override = os.environ.get("SIA_CORE_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parents[3] / "data"
