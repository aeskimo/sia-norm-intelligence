"""Deterministische PDF-Extraktion: document.pdf → document.draft.json (M8, ADR-0006).

Stufe 1 des Extraktionswegs für echte Normdokumente (OQ-003). Die Maschine
belegt nur das Ziffern-Skelett (Ziffernnummern am Zeilenanfang,
deterministisch) und den extrahierten Ziffern-Text (lokal, nur für die
Vervollständigung in Stufe 2). Fachliche Felder (statement_type, obligation,
summary, concepts) bleiben leer – G1: keine fachlichen Inhalte erfinden.
Tabellen und Formeln werden in v1 nicht automatisch erkannt (ADR-0006).

Guardrails:
- G4: Fehlerbericht und CLI-Ausgabe enthalten nur Norm-ID, Ziffern,
  Feldnamen und Zählungen – nie Normtexte.
- Atomar: alle Fehler werden gesammelt; bei Fehlern wird nichts geschrieben
  (KBOB-Muster, wie Ingest M2).
- Der Entwurf wird gegen schemas/document_draft.schema.json validiert
  (DoD, AGENTS.md §6).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader

from sni.core.schemas import make_validator
from sni.ingest.pipeline import _SAFE_ID_RE, DEFAULT_NORMS_DIR

SOURCE_FILENAME = "document.pdf"
DRAFT_FILENAME = "document.draft.json"

# Ziffernnummer am Zeilenanfang: 1–2 Ziffern pro Komponente, max. 4 Komponenten
# ("3.1", "4.2.1"), danach Leerzeichen. Vierstellige Jahreszahlen ("2003")
# matchen nicht.
_CLAUSE_LINE_RE = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,3})[ \t]+(.*)$")
# Inhaltsverzeichnis-Einträge: Punktgürtel oder Auslassungspunkte (Heuristik).
_TOC_LEADER_RE = re.compile(r"\.{2,}|…")


class PdfExtractError(RuntimeError):
    """Extraktion fehlgeschlagen; ``report`` enthält alle gesammelten Fehler (G4)."""

    def __init__(self, report: list[str]) -> None:
        super().__init__("; ".join(report))
        self.report = report


@dataclass(frozen=True)
class ExtractResult:
    """Ergebnis eines Extraktionslaufs (ohne Normtexte, G4)."""

    norm_id: str
    draft_path: Path
    clauses: int
    pages: int


@dataclass
class _Clause:
    number: str
    text_lines: list[str] = field(default_factory=list)


def extract_pdf(norm_id: str, norms_dir: Path = DEFAULT_NORMS_DIR) -> ExtractResult:
    """Liest ``document.pdf`` und schreibt ``document.draft.json`` (atomar, G4)."""
    if not _SAFE_ID_RE.fullmatch(norm_id) or ".." in norm_id:
        raise PdfExtractError(
            [f"Ungültige Norm-ID {norm_id!r} (erlaubt: Buchstaben, Ziffern, '.', '_', '-')"]
        )
    norm_dir = norms_dir / norm_id
    pdf_path = norm_dir / SOURCE_FILENAME
    draft_path = norm_dir / DRAFT_FILENAME
    if not pdf_path.is_file():
        raise PdfExtractError(
            [f"PDF nicht gefunden: {pdf_path} (lokaler Mount erwartet, Guardrail G4)"]
        )

    errors: list[str] = []
    lines: list[str] = []
    pages = 0
    try:
        reader = PdfReader(str(pdf_path))
        if reader.is_encrypted:
            errors.append(f"PDF {pdf_path.name} ist verschlüsselt (nicht unterstützt in v1)")
        else:
            pages = len(reader.pages)
            for page in reader.pages:
                text: object = page.extract_text()
                if isinstance(text, str) and text:
                    lines.extend(text.splitlines())
    except Exception as exc:  # pypdf wirft verschiedene Typen; G4: nur der Typname.
        errors.append(f"PDF {pdf_path.name} nicht lesbar ({type(exc).__name__})")
    if not lines:
        errors.append(
            f"PDF {pdf_path.name}: kein extrahierbarer Text"
            " (gescanntes PDF? OCR ist v1-ausserhalb, ADR-0006)"
        )

    clauses = _detect_clauses(lines)
    if not clauses:
        errors.append(f"PDF {pdf_path.name}: keine Ziffern erkannt (0 Ziffern)")
    if errors:
        raise PdfExtractError(errors)

    draft = _build_draft(norm_id, pages, clauses)
    for error in make_validator("document_draft.schema.json").iter_errors(draft):
        path = "/".join(str(part) for part in error.absolute_path)
        errors.append(f"Entwurf {path}: {error.message}" if path else f"Entwurf: {error.message}")
    if errors:
        raise PdfExtractError(errors)

    draft_path.write_text(
        json.dumps(draft, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return ExtractResult(norm_id=norm_id, draft_path=draft_path, clauses=len(clauses), pages=pages)


def _detect_clauses(lines: list[str]) -> list[_Clause]:
    """Erkennt Ziffernnummern am Zeilenanfang (deterministisch, ADR-0006).

    Abgewiesen werden Kandidaten mit führender Null (Werte wie "0.8"/"08"),
    Inhaltsverzeichnis-Einträge (Punktgültel) und Nummern, die die
    Ziffernfolge nicht fortsetzen (z. B. "1.5" nach Ziffer "2").
    """
    clauses: list[_Clause] = []
    current: _Clause | None = None
    last_parts: tuple[int, ...] | None = None
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        match = _CLAUSE_LINE_RE.match(line)
        if match is not None and _is_clause_number(match.group(1), match.group(2), last_parts):
            current = _Clause(
                number=match.group(1), text_lines=[match.group(2)] if match.group(2) else []
            )
            clauses.append(current)
            last_parts = _parts(match.group(1))
            continue
        if current is not None:
            current.text_lines.append(line)
    return clauses


def _is_clause_number(number: str, rest: str, last_parts: tuple[int, ...] | None) -> bool:
    parts = _parts(number)
    if parts[0] == 0:
        return False  # "0.x": Wert, keine Ziffernnummer
    if any(part != str(int(part)) for part in number.split(".")):
        return False  # führende Null ("08", "1.05"): Wert, keine Ziffernnummer
    if _TOC_LEADER_RE.search(rest):
        return False  # Inhaltsverzeichnis-Eintrag
    return _advance(last_parts, parts)


def _parts(number: str) -> tuple[int, ...]:
    return tuple(int(part) for part in number.split("."))


def _advance(last: tuple[int, ...] | None, new: tuple[int, ...]) -> bool:
    """Ziffernnummer muss die Folge fortsetzen (tiefer, Geschwister oder nächstes Kapitel)."""
    if last is None:
        return True
    for old, new_part in zip(last, new, strict=False):
        if old == new_part:
            continue
        return new_part > old
    return len(new) > len(last)


def _build_draft(norm_id: str, pages: int, clauses: list[_Clause]) -> dict[str, object]:
    """Erzeugt den Entwurf; Fachfelder bleiben leer (G1)."""
    return {
        "norm_id": norm_id,
        "norm": "",
        "edition": "",
        "source_file": SOURCE_FILENAME,
        "page_count": pages,
        "clauses": [
            {
                "number": clause.number,
                "text": "\n".join(clause.text_lines),
                "statement_type": "",
                "obligation": "",
                "summary": "",
                "concepts": [],
            }
            for clause in clauses
        ],
    }
