"""Frozen-Bootstrap (M8.6, REQ-813): schreibbarer Kerndaten-Mount.

Dev-Modus (Repository-Checkout): die SNI-Kerndaten liegen in ``<repo>/data``
(lokaler Mount, ADR-0009) — alles bleibt wie gehabt.

Frozen App (PyInstaller-Bundle): ``data/`` wäre im Bündel read-only, und die
Review-Freigabe schreibt dorthin (``review_queue/`` → ``extracted/``).
Deshalb liegt der Kerndaten-Mount im User-Verzeichnis:
``<user_data_dir>/data/`` (``SIA_CORE_DATA_DIR``), beim ersten Start aus den
mit der App gebündelten Pilot-Snapshots gesättigt (Seed).

Das Seeding ist idempotent: ``ConceptStore.import_snapshot`` importiert
nur neue/veränderte Objekte (REQ-100/101), jeder Start läuft es deshalb
einfach erneut durch — kein Marker, keine Drift-Erkennung nötig.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sni.catalog.snapshot import load_snapshot
from sni.catalog.store import ConceptStore
from sni.state.paths import user_data_dir

#: Sub-Verzeichnisse des Kerndaten-Mounts (1:1 mit ``<repo>/data``).
CORE_SUBDIRS = ("catalog", "extracted", "norms", "review_queue", "rules")


def frozen() -> bool:
    """True, wenn aus einem PyInstaller-Bündel gestartet wird."""
    return bool(getattr(sys, "frozen", False))


def core_data_dir() -> Path:
    """Schreibbarer Kerndaten-Mount der frozen App: ``<user_data_dir>/data``."""
    return user_data_dir() / "data"


def bundle_data_dir() -> Path | None:
    """Mit der App gebündelter Daten-Verzeichnis (``--add-data sni_data``).

    None, wenn nicht frozen oder das Verzeichnis fehlt (z. B. Build ohne
    Pilot-Snapshots) — das Seeding erzeugt dann nur die leere Struktur.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if not isinstance(meipass, str):
        return None
    candidate = Path(meipass) / "sni_data"
    return candidate if candidate.is_dir() else None


def seed_core_data(target: Path, source: Path | None) -> int:
    """Erzeugt den Kerndaten-Mount unter ``target`` und importiert Snapshots.

    ``source``: gebündeltes Daten-Verzeichnis (``source/catalog/snapshots/
    *.json``), None = leere Struktur. Liefert die Anzahl neu importierter
    Concepts (0 bei Re-Run, idempotent).

    Ungültige gebündelte Snapshots werfen (fatal): ein kaputtes Bündel darf
    nicht stillschweigend mit leerem Katalog starten.
    """
    for sub in CORE_SUBDIRS:
        (target / sub).mkdir(parents=True, exist_ok=True)
    snapshots: list[Path] = []
    if source is not None and source.is_dir():
        snapshots = sorted((source / "catalog" / "snapshots").glob("*.json"))
    store = ConceptStore(target / "catalog" / "catalog.db")
    try:
        imported = 0
        for path in snapshots:
            raw: object = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError(f"Snapshot ist kein JSON-Objekt: {path.name}")
            imported += store.import_snapshot(load_snapshot(raw))
        return imported
    finally:
        store.close()
