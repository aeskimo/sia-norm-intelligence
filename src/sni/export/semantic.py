"""Deterministischer Semantik-Export (REQ-810; 1:1 Java ``SemanticExporter``).

Erzeugt aus den Volltextseiten einer indexierten Norm das ``document.json``-
Format für die SNI-Ingest-Pipeline (``data/norms/<norm-id>/document.json``)
und liefert nur Zählungen + Übersprungs-Gründe (kein Normtext, G4).

Regeln (kein LLM, keine erfundenen Inhalte, G1):

- Ziffer = Zeile mit mindestens zweistufiger Nummer ("4.1", "4.1.2");
  Inhalt = Überschrift plus Text bis zur nächsten Ziffer/Tabelle.
- Obligation: Wortbegrenzungs-Suche muss > soll > kann, sonst informativ.
- Aussageklasse: deterministische Heuristik — "siehe"/"vgl." = reference,
  "ausnahme" = exception, "heisst"/"bedeutet"/"ist definiert" = definition,
  mit Modalverb = requirement; Tabellen sind classification;
  alles andere wird übersprungen (nie geraten).
- Konzepte: Katalog-Concepts, deren Name oder ID-Slug wortbegrenzt (und
  umlautunabhängig, wie im SNI-Answerer) im Ziffer-Text vorkommt; Ziffern
  ohne Konzept werden übersprungen (die Ingest-Pipeline würde sie sonst
  still verwerfen).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from sni.search.page_source import PageSource

CLAUSE = re.compile(r"\s*(\d+(?:\.\d+){1,3})\s+(\S.*)$")
TABLE = re.compile(r"\s*Tabelle\s+(\d+[a-z]?)\b\s*(.*)$")
# Java 1:1: ``String.split("\R")`` — alle Zeilenumbrüche (inkl. Unicode).
_LINE_BREAK = re.compile(r"\r\n|[\n\x0b\x0c\r\x85\u2028\u2029]")

_UMLAUTS = (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"))


@dataclass
class Unit:
    """Eine Einheit (Ziffer, Tabelle) im ``document.json``-Format."""

    number: str
    statement_type: str
    obligation: str
    summary: str
    concepts: list[str]
    tables: list[Unit] = field(default_factory=list)


@dataclass(frozen=True)
class ExportResult:
    """Ergebnis eines Exportlaufs (ohne Norminhalte, nur Zählungen, G4)."""

    norm_id: str
    document_file: Path
    clauses: int
    tables: int
    skipped: int
    skipped_reasons: list[str]


def normalize(text: str) -> str:
    """Kleinschreibung + Umlaut-Umstellung (wie der SNI-Answerer)."""
    result = text.lower()
    for original, replacement in _UMLAUTS:
        result = result.replace(original, replacement)
    return result


def normalize_text(text: str) -> str:
    """Zeilenumbrüche und Mehrfach-Leerzeichen zu einem Einzeiler (Summary)."""
    return re.sub(r"[ \t]{2,}", " ", text.replace("\n", " ")).strip()


def word_contains(normalized_haystack: str, normalized_needle: str) -> bool:
    """Wortbegrenzungs-Suche im normalisierten Text (Needle ≥ 3 Zeichen)."""
    if not normalized_needle or len(normalized_needle) < 3:
        return False
    pattern = f"(?<![a-z0-9]){re.escape(normalized_needle)}(?![a-z0-9])"
    return re.search(pattern, normalized_haystack) is not None


def norm_id_for(number: str, year: str) -> str:
    """Maschinenlesbare Norm-ID für den Mount: "SIA 416" + 2003 → "sia416-2003"."""
    slug = re.sub(r"[^a-z0-9]", "", number.lower())
    if not slug:
        raise ValueError(f"Normnummer nicht verwertbar: {number!r}")
    cleaned_year = year.strip()
    return f"{slug}-{cleaned_year}" if cleaned_year else slug


def obligation_of(text: str) -> str:
    """Obligation aus Modalverben (Wortbegrenzung, inkl. Plural); muss > soll > kann."""
    t = normalize(text)
    if word_contains(t, "muss") or word_contains(t, "muessen"):
        return "muss"
    if word_contains(t, "soll") or word_contains(t, "sollen"):
        return "soll"
    if word_contains(t, "kann") or word_contains(t, "koennen"):
        return "kann"
    return "informativ"


def statement_type_of(text: str) -> str | None:
    """Deterministische Aussageklasse; ``None`` = nicht sicher klassifizierbar.

    ``None`` bedeutet: überspringen, nie raten (G5).
    """
    t = normalize(text)
    if word_contains(t, "siehe") or word_contains(t, "vgl"):
        return "reference"
    if word_contains(t, "ausnahme") or word_contains(t, "ausgenommen"):
        return "exception"
    if (
        word_contains(t, "heisst")
        or word_contains(t, "bedeutet")
        or word_contains(t, "ist definiert")
        or word_contains(t, "istdefiniert")
    ):
        return "definition"
    if obligation_of(text) != "informativ":
        return "requirement"
    return None


def matched_concepts(normalized_text: str, concepts: list[tuple[str, str]]) -> list[str]:
    """Katalog-Concepts, deren Name oder Slug wortbegrenzt im Text vorkommt.

    ``concepts``: ``(concept_id, name_de)``-Paare (wie ``IntelligenceClient.Concept``).
    """
    out: list[str] = []
    for concept_id, name in concepts:
        if not concept_id:
            continue
        slug = concept_id.rsplit("/", 1)[-1]
        name_normalized = normalize(name or "")
        if word_contains(normalized_text, name_normalized) or word_contains(
            normalized_text, normalize(slug)
        ):
            out.append(concept_id)
    return out


def clause_numbers(page_text: str) -> list[str]:
    """Erkannte Ziffer-Nummern in einem Seitentext (Testzugang wie Java)."""
    return [
        match.group(1)
        for line in _LINE_BREAK.split(page_text)
        if (match := CLAUSE.fullmatch(line)) is not None
    ]


def export(
    norms_dir: Path,
    number: str,
    year: str,
    pages: list[PageSource],
    concepts: list[tuple[str, str]],
) -> ExportResult:
    """Erzeugt ``document.json`` unter ``norms_dir/<norm-id>/`` (G4: lokaler Mount).

    Liefert Zählungen und Übersprungs-Gründe ohne Norminhalte.
    """
    norm_id = norm_id_for(number, year)
    edition = year.strip()
    lines: list[str] = []
    for page in sorted(pages, key=lambda p: p.page):
        lines.extend(_LINE_BREAK.split(page.text))

    boundaries: list[tuple[int, bool, str, str]] = []
    for index, line in enumerate(lines):
        clause_match = CLAUSE.fullmatch(line)
        if clause_match is not None:
            boundaries.append((index, False, clause_match.group(1), clause_match.group(2).strip()))
            continue
        table_match = TABLE.fullmatch(line)
        if table_match is not None:
            boundaries.append((index, True, table_match.group(1), table_match.group(2).strip()))

    clauses = 0
    tables = 0
    skipped = 0
    reasons: list[str] = []
    clause_units: list[Unit] = []
    pending_tables: list[Unit] = []  # nur falls keine Ziffer vorangeht
    last_clause = -1

    for b, (line_no, is_table, number_, title) in enumerate(boundaries):
        end = boundaries[b + 1][0] if b + 1 < len(boundaries) else len(lines)
        body = lines[line_no:end]
        if is_table:
            scope = title + " " + " ".join(body[:5])
            matched = matched_concepts(normalize(scope), concepts)
            if not matched:
                skipped += 1
                reasons.append(f"Tabelle {number_} übersprungen: kein Katalog-Konzept im Titel")
                continue
            summary = f"Tabelle {number_}" + ("" if not title.strip() else f": {title}")
            table = Unit(f"T {number_}", "classification", "informativ", summary, matched, [])
            if last_clause >= 0:
                # Tabelle folgt im SIA-Layout dem zugehörigen Ziffer-Text.
                clause_units[last_clause].tables.append(table)
                tables += 1
            else:
                pending_tables.append(table)
        else:
            # Die Ziffer-Nummer steht bereits im Feld "number"; der Summary
            # wird sie aus der Überschriftzeile gestrichen (Original-Text bleibt sonst).
            clause_body = list(body)
            first = CLAUSE.fullmatch(clause_body[0])
            if first is not None:
                clause_body[0] = first.group(2).strip()
            text = normalize_text("\n".join(clause_body))
            statement_type = statement_type_of(text)
            if statement_type is None:
                skipped += 1
                reasons.append(f"Ziffer {number_} übersprungen: keine eindeutige Aussageklasse")
                continue
            matched = matched_concepts(normalize(text), concepts)
            if not matched:
                skipped += 1
                reasons.append(f"Ziffer {number_} übersprungen: kein Katalog-Konzept im Text")
                continue
            clause_units.append(
                Unit(number_, statement_type, obligation_of(text), text, matched, [])
            )
            last_clause = len(clause_units) - 1
            clauses += 1

    if pending_tables:
        skipped += len(pending_tables)
        reasons.append(f"{len(pending_tables)} Tabelle(n) ohne vorangehende Ziffer übersprungen")

    directory = Path(norms_dir) / norm_id
    directory.mkdir(parents=True, exist_ok=True)
    document_file = directory / "document.json"
    document = {
        "norm": number,
        "norm_id": norm_id,
        "edition": edition,
        "clauses": [
            {
                "number": unit.number,
                "statement_type": unit.statement_type,
                "obligation": unit.obligation,
                "summary": unit.summary,
                "concepts": unit.concepts,
                "tables": [
                    {
                        "number": table.number,
                        "statement_type": table.statement_type,
                        "obligation": table.obligation,
                        "summary": table.summary,
                        "concepts": table.concepts,
                        "tables": table.tables,
                    }
                    for table in unit.tables
                ],
            }
            for unit in clause_units
        ],
    }
    document_file.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return ExportResult(norm_id, document_file, clauses, tables, skipped, reasons)
