"""Deterministische PDF-Extraktion: document.pdf → document.draft.json (M9, ADR-0010).

Stufe 1 des Extraktionswegs für echte Normdokumente (OQ-003). Die Maschine
belegt nur das Ziffern-Skelett und den extrahierten Ziffern-Text (lokal, nur
für die Vervollständigung in Stufe 2). Fachliche Felder (statement_type,
obligation, summary, concepts) bleiben leer – G1: keine fachlichen Inhalte
erfinden. Tabellen und Formeln werden in v1 nicht automatisch erkannt
(ADR-0010).

Heuristik (Pilot-Korrektur, ADR-0010): Kandidat ist eine Zeile, deren
(gestrippter) Text mit einer Ziffernnummer beginnt – mit Titel oder karg
(ganze Zeile ist die Ziffer). Zeilen entstehen aus den pypdf-Visitor-Chunks
(Chunk-Konkatenation == ``extract_text()``-Output, auf dem Pilot-Dokument
verifiziert). Abgewiesen werden Kandidaten mit:
- F1: nicht boldem erstem Segment, sofern das Dokument Bold kennt
  (Ueberschriften sind bold; TOC- und Tabellenzeilen sind regulär)
- F2: 0-Komponenten oder führenden Nullen ("0.8", "4.3.0", "08")
- F3: einstufige Ziffer == Seitenzahl im unteren Seitenrand-Band
  (Laufzeile: Seitenzahl + Dokumententitel)
- F4: gleicher (Ziffer, Restlaenge) auf 2+ Seiten (Mehreseiten-
  Tabellenzeilenkopf)
- F5: Inhaltsverzeichnis-Punktgürtel im Rest (Verteidigung in der Tiefe)
- F6: Ziffernfolge setzt die visuelle Lesereihenfolge nicht fort (letztes
  Gate; geprüft nach (Seite, -y, x) – bewusst nicht in
  Content-Stream-Reihenfolge, Pilot-Befund Seite 15)
Karge Ziffernnummern sind nur im linken Randbereich (x ≤ 120 Punkte)
Kandidaten. Ohne Bold im Dokument bleibt F1 inaktiv (Fallback: Zahlen-
regeln und Sequenz-Check wie vor der Pilot-Korrektur). Der Entwurf wird
am Ende nach der Ziffernnummer sortiert.

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

from pypdf import PageObject, PdfReader
from pypdf.generic import IndirectObject

from sni.core.schemas import make_validator
from sni.ingest.pipeline import _SAFE_ID_RE, default_norms_dir

SOURCE_FILENAME = "document.pdf"
DRAFT_FILENAME = "document.draft.json"

# Ziffernnummer am Zeilenanfang: 1–2 Ziffern pro Komponente, max. 4 Komponenten
# ("3.1", "4.2.1"), danach Leerzeichen. Vierstellige Jahreszahlen ("2003")
# matchen nicht.
_CLAUSE_LINE_RE = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,3})[ \t]+(.*)$")
# Karge Ziffernnummer: die ganze Zeile ist eine Ziffernnummer (Ueberschrift
# ohne Titel).
_BARE_NUMBER_RE = re.compile(r"^\d{1,2}(?:\.\d{1,2}){0,3}$")
# Inhaltsverzeichnis-Einträge: Punktgürtel oder Auslassungspunkte.
_TOC_LEADER_RE = re.compile(r"\.{2,}|…")

# Unteres Seitenrand-Band (Punkte), in dem Laufzeilen sitzen (Pilot: y ≈ 34).
_EDGE_BAND = 60.0
# Max. device-x für karge Ziffernnummern (Ueberschriften stehen am linken
# Rand; Tabellenzellen deutlicher weiter rechts).
_BARE_MAX_X = 120.0


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


@dataclass(frozen=True)
class _Segment:
    text: str
    x: float
    y: float
    bold: bool


@dataclass(frozen=True)
class _Line:
    page: int
    text: str
    x0: float
    y0: float
    first_bold: bool


@dataclass
class _Candidate:
    line_index: int
    page: int
    number: str
    rest: str
    restlen: int
    x0: float
    y0: float
    first_bold: bool
    bare: bool
    accepted: bool = False


def extract_pdf(norm_id: str, norms_dir: Path | None = None) -> ExtractResult:
    """Liest ``document.pdf`` und schreibt ``document.draft.json`` (atomar, G4)."""
    if norms_dir is None:
        norms_dir = default_norms_dir()
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
    lines: list[_Line] = []
    pages = 0
    try:
        reader = PdfReader(str(pdf_path))
        if reader.is_encrypted:
            errors.append(f"PDF {pdf_path.name} ist verschlüsselt (nicht unterstützt in v1)")
        else:
            pages = len(reader.pages)
            for pno, page in enumerate(reader.pages, start=1):
                lines.extend(_page_lines(pno, page))
    except Exception as exc:  # pypdf wirft verschiedene Typen; G4: nur der Typname.
        errors.append(f"PDF {pdf_path.name} nicht lesbar ({type(exc).__name__})")
    if not lines:
        errors.append(
            f"PDF {pdf_path.name}: kein extrahierbarer Text"
            " (gescanntes PDF? OCR ist v1-ausserhalb, ADR-0010)"
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


def _page_lines(pno: int, page: PageObject) -> list[_Line]:
    """Rekonstruiert die Zeilen einer Seite aus den Visitor-Chunks.

    Zeilengrenzen sind die ``\\n``-Zeichen in den Chunk-Texten (identisch mit
    ``extract_text()``-Output, Pilot-verifiziert). Position und Bold-Flag
    stammen vom Chunk-Anfang (Textmatrix, device-Koordinaten).
    """
    page_lines: list[list[_Segment]] = []

    def visit(text: str, cm: object, tm: object, font_dict: object, font_size: float) -> None:
        if not isinstance(tm, (list, tuple)) or len(tm) < 6:
            return
        if not isinstance(cm, (list, tuple)) or len(cm) < 6:
            cm = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        x, y = _device_coords(tm, cm)
        bold = _is_bold_font(font_dict)
        for i, part in enumerate(text.split("\n")):
            if i > 0:
                page_lines.append([])
            if part:
                if not page_lines:
                    page_lines.append([])
                page_lines[-1].append(_Segment(text=part, x=x, y=y, bold=bold))

    page.extract_text(visitor_text=visit)
    result: list[_Line] = []
    for segments in page_lines:
        text = "".join(seg.text for seg in segments).strip()
        if not text:
            continue
        result.append(
            _Line(
                page=pno,
                text=text,
                x0=segments[0].x,
                y0=segments[0].y,
                first_bold=segments[0].bold,
            )
        )
    return result


def _device_coords(tm: object, cm: object) -> tuple[float, float]:
    """Device-Koordinaten des Textursprungs: Textmatrix × CTM."""
    if not isinstance(tm, (list, tuple)) or len(tm) < 6:
        raise ValueError("Textmatrix unvollstaendig")
    if not isinstance(cm, (list, tuple)) or len(cm) < 6:
        raise ValueError("CTM unvollstaendig")
    x = float(tm[4]) * float(cm[0]) + float(tm[5]) * float(cm[2]) + float(cm[4])
    y = float(tm[4]) * float(cm[1]) + float(tm[5]) * float(cm[3]) + float(cm[5])
    return x, y


def _is_bold_font(font_dict: object) -> bool:
    """Bold, wenn der /BaseFont-Name (nach Substitutions-Plus) „Bold" enthält."""
    base = _font_base_name(font_dict)
    return "Bold" in base.split("+")[-1]


def _font_base_name(font_dict: object) -> str:
    """Der /BaseFont-Name des Chunk-Fonts ('' wenn nicht ermittelbar)."""
    target: object = font_dict
    if isinstance(target, IndirectObject):
        target = target.get_object()
    if isinstance(target, dict):
        base = target.get("/BaseFont")
        if isinstance(base, str):
            return base
    return ""


def _detect_clauses(lines: list[_Line]) -> list[_Clause]:
    """Erkennt Ziffernnummern (deterministisch, Zwei-Pass, ADR-0010).

    1. Kandidaten sammeln (Zeile beginnt mit Ziffernnummer, mit oder ohne Titel)
    2. Typografie-Filter F1–F5 pro Kandidat (Two-Pass: F4 zaehlt alle Kandidaten)
    3. Sequenz-Check F6 in visueller Lesereihenfolge (Seite, -y, x)
    4. Text-Zuordnung in Strom-Reihenfolge; Ausgabe nach Ziffernnummer sortiert
    """
    candidates: list[_Candidate] = []
    for index, line in enumerate(lines):
        candidate = _candidate(line, index)
        if candidate is not None:
            candidates.append(candidate)

    has_bold = any(line.first_bold for line in lines)
    page_counts: dict[tuple[str, int], set[int]] = {}
    for c in candidates:
        page_counts.setdefault((c.number, c.restlen), set()).add(c.page)

    for c in candidates:
        c.accepted = _passes_filters(c, has_bold, page_counts)

    # F6: Sequenz-Check in Lesereihenfolge. y wird auf 5-Punkte-Gitter
    # quantisiert, damit zwei Ueberschriften auf derselben Zeile (gleiche y)
    # nach x sortiert werden.
    ordered = sorted(
        (c for c in candidates if c.accepted),
        key=lambda c: (c.page, -int(c.y0 // 5.0), c.x0),
    )
    last_parts: tuple[int, ...] | None = None
    for c in ordered:
        if _advance(last_parts, _parts(c.number)):
            last_parts = _parts(c.number)
        else:
            c.accepted = False

    # Text-Zuordnung in Strom-Reihenfolge (Content-Stream-Ordnung).
    accepted_by_line: dict[int, _Candidate] = {c.line_index: c for c in candidates if c.accepted}
    clauses: list[_Clause] = []
    current: _Clause | None = None
    for index, line in enumerate(lines):
        hit = accepted_by_line.get(index)
        if hit is not None:
            current = _Clause(number=hit.number, text_lines=[hit.rest] if hit.rest else [])
            clauses.append(current)
            continue
        if line.text and current is not None:
            current.text_lines.append(line.text)
    clauses.sort(key=lambda cl: _parts(cl.number))
    return clauses


def _candidate(line: _Line, index: int) -> _Candidate | None:
    """Kandidaten-Daten, falls die Zeile mit einer Ziffernnummer beginnt (oder ist)."""
    bare_match = _BARE_NUMBER_RE.fullmatch(line.text)
    if bare_match is not None:
        number, rest, bare = bare_match.group(0), "", True
    else:
        line_match = _CLAUSE_LINE_RE.match(line.text)
        if line_match is None:
            return None
        number, rest, bare = line_match.group(1), line_match.group(2).strip(), False
    return _Candidate(
        line_index=index,
        page=line.page,
        number=number,
        rest=rest,
        restlen=len(rest),
        x0=line.x0,
        y0=line.y0,
        first_bold=line.first_bold,
        bare=bare,
    )


def _passes_filters(
    c: _Candidate,
    has_bold: bool,
    page_counts: dict[tuple[str, int], set[int]],
) -> bool:
    """F1–F5: Typografie- und Zahlenregeln (alle muss gelten, ADR-0010)."""
    if not _valid_number(c.number):
        return False  # F2: 0-Komponente / führende Null -> Wert, keine Ziffer
    if has_bold and not c.first_bold:
        return False  # F1: Ueberschrift ist bold (sofern das Dokument Bold kennt)
    if _TOC_LEADER_RE.search(c.rest):
        return False  # F5: Inhaltsverzeichnis-Eintrag
    if len(_parts(c.number)) == 1 and int(c.number) == c.page and c.y0 < _EDGE_BAND:
        return False  # F3: Laufzeile (Seitenzahl) im unteren Rand-Band
    if c.bare and c.x0 > _BARE_MAX_X:
        return False  # kare Ziffer nur im linken Randbereich
    return len(page_counts[(c.number, c.restlen)]) < 2  # F4: wiederholte Tabellenzeile


def _valid_number(number: str) -> bool:
    """Ziffernnummer: keine 0-Komponente, keine führenden Nullen (F2)."""
    parts = number.split(".")
    if any(part != str(int(part)) for part in parts):
        return False  # führende Null ("08", "1.05"): Wert, keine Ziffernnummer
    return all(int(part) >= 1 for part in parts)


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
