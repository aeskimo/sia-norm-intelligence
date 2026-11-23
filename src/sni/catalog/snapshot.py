"""Laden und Validieren von CatalogSnapshots (M1, REQ-100/REQ-101).

Consumer-Seiten-Kontrakt (siehe OQ-002 in OPEN_QUESTIONS.md):
    {"snapshot_id": "<string>", "concepts": [Concept, ...]}
Jedes Concept wird gegen schemas/concept.schema.json (Draft 2020-12) validiert.
Alle Fehler werden gesammelt und als Bericht geliefert (KBOB-Muster, 08_REFERENCES.md).
"""

from __future__ import annotations

from dataclasses import dataclass

from sni.core.schemas import make_validator

_CONCEPT_VALIDATOR = make_validator("concept.schema.json")


class SnapshotValidationError(ValueError):
    """Snapshot ist ungültig; ``report`` enthält alle gefundenen Fehler."""

    def __init__(self, report: list[str]) -> None:
        super().__init__("; ".join(report))
        self.report = report


@dataclass(frozen=True)
class CatalogSnapshot:
    """Validierter Katalog-Snapshot (append-only Quelle der Concepts)."""

    snapshot_id: str
    concepts: tuple[dict[str, object], ...]


def load_snapshot(data: dict[str, object]) -> CatalogSnapshot:
    """Validiert die Rohdaten eines CatalogSnapshots und sammelt alle Fehler."""
    errors: list[str] = []

    raw_snapshot_id: object = data.get("snapshot_id")
    if isinstance(raw_snapshot_id, str) and raw_snapshot_id:
        snapshot_id = raw_snapshot_id
    else:
        errors.append("snapshot_id fehlt oder ist keine nicht-leere Zeichenkette")
        snapshot_id = ""  # Platzhalter; bei Fehlern bricht die Funktion ab

    concepts_raw = data.get("concepts")
    if not isinstance(concepts_raw, list):
        errors.append("concepts fehlt oder ist keine Liste")
        concepts_list: list[object] = []
    else:
        concepts_list = concepts_raw

    seen: set[str] = set()
    concepts: list[dict[str, object]] = []
    for index, concept in enumerate(concepts_list):
        label = f"concepts[{index}]"
        if not isinstance(concept, dict):
            errors.append(f"{label}: kein JSON-Objekt")
            continue
        for error in _CONCEPT_VALIDATOR.iter_errors(concept):
            location = "/".join(str(part) for part in error.absolute_path)
            detail = f"{location}: {error.message}" if location else error.message
            errors.append(f"{label}: ungültiges Concept ({detail})")
        concept_id = concept.get("id")
        if isinstance(concept_id, str):
            if concept_id in seen:
                errors.append(f"{label}: doppelte Concept-ID {concept_id!r}")
            seen.add(concept_id)
            if snapshot_id:
                declared = concept.get("catalog_snapshot")
                if declared != snapshot_id:
                    errors.append(
                        f"{label}: catalog_snapshot {declared!r} passt nicht zu "
                        f"snapshot_id {snapshot_id!r}"
                    )
        concepts.append(concept)

    if errors:
        raise SnapshotValidationError(errors)
    return CatalogSnapshot(snapshot_id=snapshot_id, concepts=tuple(concepts))
