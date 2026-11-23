"""Normalisierte Projektwerte (M5, REQ-500).

Beide Adapter (IFC, CSV) liefern ``ProjectValue``: einen typisierten Wert
mit Einheit und Herkunft (``Provenance``: Datei + Locator GUID/Zeile).
Die Herkunft ist Grundlage der Nachvollziehbarkeit (docs/00_VISION.md) und
der Prüfergebnisse (REQ-501).

Einheiten werden von den Adaptern nur normalisiert (z. B. IFC-Einheitenum
-> "m2"); die Einheiten-Diziplin (Übereinstimmung mit der Regel) bleibt
Aufgabe der Regel-Engine (REQ-302).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Provenance:
    """Herkunft eines Projektwerts: Datei + Locator (IFC: GUID, CSV: Zeile)."""

    file: str
    locator: str


@dataclass(frozen=True)
class ProjectValue:
    """Normalisierter Projektwert: Concept-ID, Zahl, Einheit, Herkunft."""

    concept: str
    value: float
    unit: str
    provenance: Provenance


class ProjectDataError(ValueError):
    """Projektdaten-Datei ungültig; ``report`` enthält alle gesammelten Fehler."""

    def __init__(self, report: list[str]) -> None:
        super().__init__("; ".join(report))
        self.report = report
