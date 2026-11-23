"""Gemeinsame Test-Helfer. Nur synthetische Platzhalterdaten (Guardrail G4)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest

from sni.catalog.snapshot import load_snapshot
from sni.catalog.store import ConceptStore
from sni.rules.engine import InputValue

SNAPSHOT_ID = "sia:catalog/test@1.0.0"
FIXTURES_DIR = Path(__file__).parent / "fixtures"
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


def source_of(candidate: dict[str, object]) -> dict[str, object]:
    """Indexierter Zugriff auf die SourceReference (mit Typ, für mypy --strict)."""
    source = candidate["source"]
    if not isinstance(source, dict):
        raise AssertionError("candidate['source'] fehlt oder ist kein Objekt")
    return source


def load_synthetic_norm() -> dict[str, object]:
    """Lädt das synthetische Test-Normdokument (G4: keine echten Norminhalte)."""
    raw: object = json.loads((FIXTURES_DIR / "synthetic_norm.json").read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise AssertionError("synthetic_norm.json muss ein JSON-Objekt sein")
    return raw


@pytest.fixture
def synthetic_norm() -> dict[str, object]:
    return load_synthetic_norm()


def load_synthetic_rule() -> dict[str, object]:
    """Lädt die synthetische Test-Regel (G4: keine echten Norminhalte)."""
    raw: object = json.loads((FIXTURES_DIR / "synthetic_rule.json").read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise AssertionError("synthetic_rule.json muss ein JSON-Objekt sein")
    return raw


@pytest.fixture
def synthetic_rule() -> dict[str, object]:
    return load_synthetic_rule()


def rule_full_inputs() -> dict[str, InputValue]:
    """Volle Inputs für die synthetische Regel (beide Pflicht-Concepts)."""
    return {
        "sia:concept/teilsflaeche-a": InputValue(100.0, "m2"),
        "sia:concept/teilsflaeche-b": InputValue(50.0, "m2"),
    }


@pytest.fixture
def concept_store(tmp_path: Path) -> Iterator[ConceptStore]:
    store = ConceptStore(tmp_path / "catalog.db")
    yield store
    store.close()


@pytest.fixture
def catalog_store(tmp_path: Path) -> Iterator[ConceptStore]:
    """Katalog mit den Standard-Test-Concepts (CONCEPT_A, CONCEPT_B) importiert."""
    store = ConceptStore(tmp_path / "catalog.db")
    store.import_snapshot(load_snapshot(make_snapshot()))
    yield store
    store.close()
