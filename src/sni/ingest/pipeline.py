"""Ingest-Pipeline: lokales Normdokument -> NormStatement-Kandidaten (M2).

Dokumentformat (synthetischer Platzhalter; ADR-0003 ist "vorgeschlagen",
die Anbindung an reale Normformate und LLM-Extraktion ist OQ-003):

    {
      "norm": "SYN 1",             # Anzeigename (Fundstelle)
      "norm_id": "syn1-2020",      # Maschinelle ID (muss zum Mount-Verzeichnis passen)
      "edition": "2020",
      "clauses": [
        {
          "number": "3.1",
          "statement_type": "requirement",
          "obligation": "muss",
          "summary": "Eigene Zusammenfassung (kein Normzitat)",
          "concepts": ["sia:concept/..."],
          "tables":   [{"number": "T 3", "statement_type": ..., "obligation": ...,
                        "summary": ..., "concepts": [...]}],
          "formulas": [{"number": "G 1", ...}]
        }
      ]
    }

Prinzipien:
- Guardrail G3: Kandidaten erhalten immer review_status="candidate"; die
  Pipeline setzt nie "approved".
- Alle Fehler werden gesammelt und als Bericht geliefert (KBOB-Muster,
  08_REFERENCES.md); bei Fehlern wird nichts geschrieben (atomar).
- Guardrail G4: Fehlermeldungen und Logs enthalten nur IDs, Ziffern und
  Feldnamen, nie Normtexte (summaries).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from jsonschema.exceptions import ValidationError

from sni.catalog.store import ConceptStore
from sni.core.schemas import load_schema, make_validator
from sni.state.paths import core_data_dir


def default_norms_dir() -> Path:
    """``SIA_CORE_DATA_DIR``/norms, sonst ``<repo>/data/norms`` (call-time, M8.6)."""
    return core_data_dir() / "norms"


def default_queue_dir() -> Path:
    """``SIA_CORE_DATA_DIR``/review_queue, sonst ``<repo>/data/review_queue``."""
    return core_data_dir() / "review_queue"


_SAFE_ID_RE = re.compile(r"[A-Za-z0-9._-]+")
_GAP_FILE_RE = re.compile(r"GAP-\d{4}")


@dataclass(frozen=True)
class IngestResult:
    """Ergebnis eines Ingest-Laufs: Kandidaten, GapReports und Queue-Dateien."""

    norm_id: str
    candidates: tuple[dict[str, object], ...]
    gap_reports: tuple[dict[str, object], ...]
    queue_files: tuple[Path, ...]


class IngestError(RuntimeError):
    """Ingest fehlgeschlagen; ``report`` enthält alle gesammelten Fehler."""

    def __init__(self, report: list[str]) -> None:
        super().__init__("; ".join(report))
        self.report = report


@dataclass(frozen=True)
class _Unit:
    """Eine zu extrahierende Einheit: Ziffer, Tabelle oder Formel (REQ-203)."""

    clause_number: str
    kind: str  # "Ziffer" | "Tabelle" | "Formel"
    number: str
    statement_type: str
    obligation: str
    summary: str
    concepts: tuple[str, ...]
    laufnr: int


def load_document(norm_id: str, norms_dir: Path | None = None) -> dict[str, object]:
    """Lädt ``data/norms/<norm-id>/document.json`` (lokaler Mount, G4).

    Die Norm-ID im Dokument muss zum Mount-Verzeichnis passen (Fundstelle).
    """
    if norms_dir is None:
        norms_dir = default_norms_dir()
    if not _SAFE_ID_RE.fullmatch(norm_id) or ".." in norm_id:
        raise IngestError(
            [f"Ungültige Norm-ID {norm_id!r} (erlaubt: Buchstaben, Ziffern, '.', '_', '-')"]
        )
    path = norms_dir / norm_id / "document.json"
    if not path.is_file():
        raise IngestError(
            [f"Normdokument nicht gefunden: {path} (lokaler Mount erwartet, Guardrail G4)"]
        )
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IngestError([f"Normdokument {path.name} ist kein gültiges JSON: {exc}"]) from exc
    if not isinstance(raw, dict):
        raise IngestError([f"Normdokument {path.name} muss ein JSON-Objekt sein"])
    doc_id: object = raw.get("norm_id")
    if not isinstance(doc_id, str) or doc_id != norm_id:
        raise IngestError(
            [f"Norm-ID im Dokument ({doc_id!r}) passt nicht zum Mount-Verzeichnis ({norm_id!r})"]
        )
    return raw


def ingest_document(
    document: dict[str, object],
    catalog: ConceptStore,
    queue_dir: Path,
) -> IngestResult:
    """Verarbeitet ein Normdokument; schreibt Kandidaten + GapReports in die Queue.

    Alle Fehler werden gesammelt; bei Fehlern wird nichts geschrieben
    (atomar, KBOB-Muster).
    """
    statement_schema = load_schema("norm_statement.schema.json")
    candidate_validator = make_validator("norm_statement.schema.json")
    gap_validator = make_validator("gap_report.schema.json")
    allowed_types = _enum_values(statement_schema, "statement_type")
    allowed_obligations = _enum_values(statement_schema, "obligation")

    errors: list[str] = []
    norm = _str_field(document, "norm", "Dokument", errors)
    norm_id = _str_field(document, "norm_id", "Dokument", errors)
    edition = _str_field(document, "edition", "Dokument", errors)
    clauses_raw: object = document.get("clauses")
    if not isinstance(clauses_raw, list):
        errors.append("Dokument: Feld 'clauses' fehlt oder ist keine Liste")
        clauses_raw = []

    units: list[_Unit] = []
    for index, clause_raw in enumerate(clauses_raw):
        label = f"clauses[{index}]"
        if not isinstance(clause_raw, dict):
            errors.append(f"{label}: kein JSON-Objekt")
            continue
        clause_number = _str_field(clause_raw, "number", f"{label} (Ziffer)", errors)
        if clause_number is None:
            continue
        checked = _check_unit(
            f"{label} (Ziffer)", clause_raw, allowed_types, allowed_obligations, errors
        )
        if checked is not None:
            st, obl, summary, concepts = checked
            units.append(
                _Unit(clause_number, "Ziffer", clause_number, st, obl, summary, tuple(concepts), 1)
            )
        laufnr = 2
        for sub_key, kind in (("tables", "Tabelle"), ("formulas", "Formel")):
            subs_raw: object = clause_raw.get(sub_key)
            if subs_raw is None:
                continue
            if not isinstance(subs_raw, list):
                errors.append(f"{label}: Feld {sub_key!r} ist keine Liste")
                continue
            for sub_index, sub_raw in enumerate(subs_raw):
                sub_label = f"{label}: {sub_key}[{sub_index}]"
                if not isinstance(sub_raw, dict):
                    errors.append(f"{sub_label}: kein JSON-Objekt")
                    continue
                sub_number = _str_field(sub_raw, "number", sub_label, errors)
                if sub_number is None:
                    continue
                sub_checked = _check_unit(
                    sub_label, sub_raw, allowed_types, allowed_obligations, errors
                )
                if sub_checked is not None:
                    st, obl, summary, concepts = sub_checked
                    units.append(
                        _Unit(
                            clause_number,
                            kind,
                            sub_number,
                            st,
                            obl,
                            summary,
                            tuple(concepts),
                            laufnr,
                        )
                    )
                laufnr += 1

    if norm is None or norm_id is None or edition is None:
        raise IngestError(errors)
    # Ab hier sind norm, norm_id und edition Strings (mypy narrowing).

    candidates: list[dict[str, object]] = []
    gaps: list[tuple[_Unit, list[str], dict[str, object]]] = []
    for unit in units:
        valid: list[str] = []
        missing: list[str] = []
        for concept_id in unit.concepts:
            (missing if catalog.get_concept(concept_id) is None else valid).append(concept_id)
        source = _source(norm, edition, unit.clause_number, unit.kind, unit.number)
        if valid:
            candidates.append(
                {
                    "id": f"sia:statement/{norm_id}/{unit.clause_number}/{unit.laufnr}",
                    "source": source,
                    "concepts": valid,
                    "statement_type": unit.statement_type,
                    "obligation": unit.obligation,
                    "summary": unit.summary,
                    "review_status": "candidate",  # G3: nie approved
                }
            )
        if missing:
            gaps.append((unit, missing, source))

    if errors:
        raise IngestError(errors)

    gap_reports: list[dict[str, object]] = []
    used_gap_ids: set[str] = set()
    next_free = _highest_gap_number(queue_dir)
    for unit, missing, source in gaps:
        description = (
            f"{_unit_label(unit)} verwendet {len(missing)} Concept-ID(s), die im "
            f"Datenkatalog nicht existieren: {', '.join(missing)}"
        )
        gap_id = _existing_gap_id(queue_dir, "missing_concept", source, description)
        if gap_id is None or gap_id in used_gap_ids:
            next_free += 1
            gap_id = f"GAP-{next_free:04d}"
        used_gap_ids.add(gap_id)
        gap_reports.append(
            {
                "id": gap_id,
                "gap_type": "missing_concept",
                "target_layer": "datenkatalog",
                "source": source,
                "description": description,
                "proposal": (
                    "Fehlende Concepts im Datenkatalog anlegen, Snapshot importieren, "
                    "Ingest wiederholen."
                ),
                # Die ID, die die Ziffer als Kandidat bekommen hätte (bzw. hat).
                "evidence": [f"sia:statement/{norm_id}/{unit.clause_number}/{unit.laufnr}"],
                "priority": "medium",
                "status": "open",
            }
        )

    for candidate in candidates:
        for error in candidate_validator.iter_errors(candidate):
            errors.append(f"Kandidat {candidate['id']}: {_error_detail(error)}")
    for gap_report in gap_reports:
        for error in gap_validator.iter_errors(gap_report):
            errors.append(f"GapReport {gap_report['id']}: {_error_detail(error)}")
    if errors:
        raise IngestError(errors)

    queue_dir.mkdir(parents=True, exist_ok=True)
    planned: dict[Path, dict[str, object]] = {}
    for obj in [*candidates, *gap_reports]:
        obj_id: object = obj["id"]
        if not isinstance(obj_id, str):
            errors.append("Interner Fehler: Objekt ohne ID")
            continue
        path = queue_dir / f"{_sanitize_id(obj_id)}.json"
        if path in planned:
            errors.append(f"Kollidierende Queue-Dateinamen für {obj_id}")
            continue
        planned[path] = obj
    if errors:
        raise IngestError(errors)

    conflicts: list[str] = []
    to_write: list[tuple[Path, dict[str, object]]] = []
    for path, obj in planned.items():
        if path.exists():
            try:
                existing: object = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                conflicts.append(f"{path.name}: existierende Datei nicht lesbar ({exc})")
                continue
            if existing != obj:
                conflicts.append(
                    f"{path.name}: ID {obj['id']} existiert bereits mit anderem Inhalt (Konflikt)"
                )
                continue
        to_write.append((path, obj))
    if conflicts:
        raise IngestError(conflicts)
    for path, obj in to_write:
        path.write_text(
            json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return IngestResult(
        norm_id=norm_id,
        candidates=tuple(candidates),
        gap_reports=tuple(gap_reports),
        queue_files=tuple(planned),
    )


def _source(
    norm: str,
    edition: str,
    clause_number: str,
    kind: str,
    number: str,
) -> dict[str, object]:
    """SourceReference für eine Einheit; ``verified`` bleibt False (G6)."""
    ref: dict[str, object] = {
        "norm": norm,
        "edition": edition,
        "clause": clause_number,
        "verified": False,
    }
    if kind == "Tabelle":
        ref["table"] = number
    elif kind == "Formel":
        ref["formula"] = number
    return ref


def _check_unit(
    label: str,
    spec: dict[str, object],
    allowed_types: tuple[str, ...],
    allowed_obligations: tuple[str, ...],
    errors: list[str],
) -> tuple[str, str, str, list[str]] | None:
    """Prüft die Pflichtfelder einer Einheit (ohne 'number'); Fehler werden gesammelt."""
    st: object = spec.get("statement_type")
    if not (isinstance(st, str) and st in allowed_types):
        errors.append(
            f"{label}: statement_type fehlt oder ungültig (erlaubt: {', '.join(allowed_types)})"
        )
        return None
    obl: object = spec.get("obligation")
    if not (isinstance(obl, str) and obl in allowed_obligations):
        errors.append(
            f"{label}: obligation fehlt oder ungültig (erlaubt: {', '.join(allowed_obligations)})"
        )
        return None
    summary = _str_field(spec, "summary", label, errors)
    concepts_raw: object = spec.get("concepts")
    if not isinstance(concepts_raw, list):
        errors.append(f"{label}: Feld 'concepts' fehlt oder ist keine Liste")
        return None
    concepts = [c for c in concepts_raw if isinstance(c, str) and c]
    if len(concepts) != len(concepts_raw):
        errors.append(f"{label}: 'concepts' enthält Einträge, die keine Concept-IDs sind")
        return None
    if summary is None:
        return None
    return st, obl, summary, concepts


def _str_field(spec: dict[str, object], field: str, label: str, errors: list[str]) -> str | None:
    value: object = spec.get(field)
    if isinstance(value, str) and value:
        return value
    errors.append(f"{label}: Feld {field!r} fehlt oder ist keine nicht-leere Zeichenkette")
    return None


def _enum_values(schema: dict[str, object], prop: str) -> tuple[str, ...]:
    """Erlaubt-Werte einer Eigenschaft aus dem Schema (Quelle der Wahrheit)."""
    properties: object = schema.get("properties")
    if not isinstance(properties, dict):
        return ()
    prop_spec: object = properties.get(prop)
    if not isinstance(prop_spec, dict):
        return ()
    enum: object = prop_spec.get("enum")
    if not isinstance(enum, list):
        return ()
    return tuple(value for value in enum if isinstance(value, str))


def _unit_label(unit: _Unit) -> str:
    if unit.kind == "Ziffer":
        return f"Ziffer {unit.number}"
    return f"{unit.kind} {unit.number} in Ziffer {unit.clause_number}"


def _highest_gap_number(queue_dir: Path) -> int:
    """Höchste vorhandene GAP-####-Nummer in der Queue (0 wenn keine)."""
    highest = 0
    if queue_dir.is_dir():
        for path in queue_dir.glob("GAP-*.json"):
            if _GAP_FILE_RE.fullmatch(path.stem) is not None:
                highest = max(highest, int(path.stem[4:]))
    return highest


def _existing_gap_id(
    queue_dir: Path, gap_type: str, source: dict[str, object], description: str
) -> str | None:
    """ID eines vorhandenen GapReports mit identischem Inhalt (idempotenter Re-Ingest)."""
    if not queue_dir.is_dir():
        return None
    for path in queue_dir.glob("GAP-*.json"):
        try:
            raw: object = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        if raw.get("gap_type") != gap_type or raw.get("source") != source:
            continue
        if raw.get("description") != description:
            continue
        gap_id: object = raw.get("id")
        if isinstance(gap_id, str):
            return gap_id
    return None


def _sanitize_id(obj_id: str) -> str:
    """Macht eine Objekt-ID dateisystem-sicher (Queue-Dateiname, REQ-202)."""
    return re.sub(r"[:/@]", "_", obj_id)


def _error_detail(error: ValidationError) -> str:
    path = "/".join(str(part) for part in error.absolute_path)
    return f"{path}: {error.message}" if path else error.message
