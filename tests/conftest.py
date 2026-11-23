"""Gemeinsame Test-Helfer. Nur synthetische Platzhalterdaten (Guardrail G4)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest

from sni.catalog.store import ConceptStore

SNAPSHOT_ID = "sia:catalog/test@1.0.0"
CONCEPT_A = "sia:concept/geschossflaeche"
CONCEPT_B = "sia:concept/nutzflaeche"
PLACEHOLDER_DEFINITION = "Synthetischer Testbegriff (Platzhalter, kein Norminhalt)."


def make_concept(
    concept_id: str,
    snapshot_id: str = SNAPSHOT_ID,
    definition: str = PLACEHOLDER_DEFINITION,
) -> dict[str, object]:
    """Erzeugt ein schemakonformes Concept (synthetisch)."""
    return {
        "id": concept_id,
        "name": {"de": concept_id.rsplit("/", 1)[-1].replace("-", " ").title()},
        "definition": {"de": definition},
        "catalog_snapshot": snapshot_id,
    }


def make_snapshot(
    snapshot_id: str = SNAPSHOT_ID,
    concept_ids: tuple[str, ...] = (CONCEPT_A, CONCEPT_B),
) -> dict[str, object]:
    """Erzeugt einen synthetischen CatalogSnapshot (JSON-Struktur)."""
    return {
        "snapshot_id": snapshot_id,
        "concepts": [make_concept(cid, snapshot_id) for cid in concept_ids],
    }


def concept_at(snap: dict[str, object], index: int) -> dict[str, object]:
    """Indexierter Zugriff auf concepts (mit Typ, für mypy --strict)."""
    return cast(list[dict[str, object]], snap["concepts"])[index]


def concepts_of(snap: dict[str, object]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], snap["concepts"])


@pytest.fixture
def synthetic_snapshot() -> dict[str, object]:
    return make_snapshot()


@pytest.fixture
def snapshot_with_relations() -> dict[str, object]:
    snap = make_snapshot()
    concept_at(snap, 0)["relations"] = [{"type": "related_to", "target": CONCEPT_B}]
    return snap


@pytest.fixture
def concept_store(tmp_path: Path) -> Iterator[ConceptStore]:
    store = ConceptStore(tmp_path / "catalog.db")
    yield store
    store.close()
