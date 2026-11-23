"""Gemeinsame Test-Helfer. Nur synthetische Platzhalterdaten (Guardrail G4)."""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
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


def synthetic_pdf_lines() -> list[str]:
    """Zeilen einer synthetischen Testnorm (G4: keine echten Norminhalte).

    Enthaltene Fehlpunkte, die KEINE Ziffernnummern sein duerfen:
    TOC-Zeilen mit Punktguertel, das Jahr "2003", der Dezimalwert "1.5 m"
    und "0.8" (führende Null) am Zeilenanfang.
    """
    return [
        "SYN 1  Testnorm (synthetisch)",
        "Inhalt",
        "1 Ziel .......... 2",
        "2 Nachweise .......... 3",
        "1 Ziel",
        "Diese synthetische Norm regelt Testfaelle.",
        "1.1 Anwendungsbereich",
        "Sie gilt fuer alle Testgebaeude.",
        "2 Nachweise",
        "Jeder Nachweis ist zu dokumentieren.",
        "1.5 m Abstand zwischen Kanten.",
        "2003 war eine alte Fassung.",
        "2.1 Groessen",
        "0.8 kg pro Flaeche maximal.",
        "3 Grenzwerte",
        "3.1 Flaeche",
        "Testgrenzwert fuer die Testflaeche.",
    ]


def _pdf_escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def make_pdf(pages: Sequence[str] | Sequence[Sequence[str]]) -> bytes:
    """Baut ein minimales PDF (Helvetica, Base-14, kein Embedding) aus Textzeilen.

    Argument ist eine Zeilenliste (eine Seite) oder eine Liste von
    Zeilenlisten (mehrere Seiten). Nur synthetische Testdaten (G4).
    pypdf liest den Text der Base-14-Schrift aus dem Content-Stream.
    """
    if pages and isinstance(pages[0], str):
        single = cast(Sequence[str], pages)
        page_lists = [list(single)]
    else:
        page_lists = [list(page) for page in pages]
    if not page_lists:
        raise ValueError("make_pdf braucht mindestens eine Seite")
    n = len(page_lists)

    content_streams: list[bytes] = []
    for page_lines in page_lists:
        ops = ["BT /F1 11 Tf 14 TL 72 800 Td"]
        for index, line in enumerate(page_lines):
            if index:
                ops.append("T*")
            ops.append(f"({_pdf_escape(line)}) Tj")
        ops.append("ET")
        content_streams.append("\n".join(ops).encode("cp1252", "replace"))

    objects: list[tuple[int, bytes]] = []
    kids = " ".join(f"{4 + i} 0 R" for i in range(n))
    objects.append((1, b"<< /Type /Catalog /Pages 2 0 R >>"))
    objects.append((2, f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode("ascii")))
    objects.append((3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"))
    for i in range(n):
        objects.append(
            (
                4 + i,
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                b"/Resources << /Font << /F1 3 0 R >> >> /Contents "
                + str(4 + n + i).encode("ascii")
                + b" 0 R >>",
            )
        )
    for i, stream in enumerate(content_streams):
        header = b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n"
        objects.append((4 + n + i, header + stream + b"\nendstream"))

    body = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for num, payload in objects:
        offsets[num] = len(body)
        body += f"{num} 0 obj\n".encode("ascii") + payload + b"\nendobj\n"
    total = 3 + 2 * n
    xref_pos = len(body)
    xref = [f"xref\n0 {total + 1}\n", "0000000000 65535 f \n"]
    for num in range(1, total + 1):
        xref.append(f"{offsets[num]:010d} 00000 n \n")
    xref.append(f"trailer\n<< /Size {total + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n")
    body += "".join(xref).encode("ascii")
    return bytes(body)


def write_norm_pdf(
    norm_id: str,
    norms_dir: Path,
    pages: Sequence[str] | Sequence[Sequence[str]] | None = None,
) -> Path:
    """Schreibt ``document.pdf`` in den lokalen Mount (Test-Helfer, M8)."""
    norm_dir = norms_dir / norm_id
    norm_dir.mkdir(parents=True)
    if pages is None:
        pages = synthetic_pdf_lines()
    path = norm_dir / "document.pdf"
    path.write_bytes(make_pdf(pages))
    return path


def load_draft(norm_id: str, norms_dir: Path) -> dict[str, object]:
    """Lädt ``document.draft.json`` aus dem Mount (Test-Helfer, M8)."""
    raw: object = json.loads(
        (norms_dir / norm_id / "document.draft.json").read_text(encoding="utf-8")
    )
    if not isinstance(raw, dict):
        raise AssertionError("document.draft.json muss ein JSON-Objekt sein")
    return raw


def clauses_of(draft: dict[str, object]) -> list[dict[str, object]]:
    """Indexierter Zugriff auf die Ziffern des Entwurfs (mit Typ, für mypy --strict)."""
    return cast(list[dict[str, object]], draft["clauses"])


def clause_text(clause: dict[str, object]) -> str:
    """Extrahierter Ziffern-Text einer Ziffer (mit Typ, für mypy --strict)."""
    return cast(str, clause["text"])
