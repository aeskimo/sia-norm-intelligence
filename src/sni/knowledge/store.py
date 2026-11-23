"""Wissens-Speicher: freigegebene semantische Objekte (M4, REQ-400).

Approved NormStatements und Rules liegen als JSON-Dateien in
``data/extracted/`` (lokaler Mount, versioniert durch den Freigabeprozess,
siehe 03_ARCHITECTURE.md). Die Freigabe selbst ist ein menschlicher Akt
(Guardrail G3) – der Lader nimmt fertige, freigegebene Objekte auf.

Das Laden ist atomar (KBOB-Muster, wie M1/M2/M3): Alle Dateien werden
verarbeitet, alle Fehler gesammelt, bei Fehlern wird nichts geliefert.

Der Objekttyp leitet sich aus der Objekt-ID ab (Schema-Patterns):
``:statement/`` -> norm_statement.schema.json, ``:rule/`` -> rule.schema.json.
Die ID muss zum Dateinamen passen (sanitisierte ID = Dateiname).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from jsonschema.exceptions import ValidationError
from jsonschema.protocols import Validator

from sni.core.schemas import make_validator

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_KNOWLEDGE_DIR = ROOT / "data" / "extracted"


class KnowledgeLoadError(RuntimeError):
    """Wissens-Ladung fehlgeschlagen; ``report`` enthält alle gesammelten Fehler."""

    def __init__(self, report: list[str]) -> None:
        super().__init__("; ".join(report))
        self.report = report


@dataclass(frozen=True)
class KnowledgeBase:
    """Freigegebene semantische Objekte, indexiert nach Objekt-ID."""

    statements: Mapping[str, dict[str, object]]
    rules: Mapping[str, dict[str, object]]

    def object(self, obj_id: str) -> dict[str, object] | None:
        """Liefert ein NormStatement oder eine Rule per ID (None wenn unbekannt)."""
        statement = self.statements.get(obj_id)
        if statement is not None:
            return statement
        return self.rules.get(obj_id)


def load_knowledge(directory: Path = DEFAULT_KNOWLEDGE_DIR) -> KnowledgeBase:
    """Lädt alle ``*.json`` aus ``directory`` und validiert sie (atomar).

    Fehlendes Verzeichnis = leere Wissensbasis. Bei Validierungsfehlern
    wird nichts geliefert (``KnowledgeLoadError`` mit aller Fehlerliste).
    """
    if not directory.is_dir():
        return KnowledgeBase(statements={}, rules={})
    statement_validator = make_validator("norm_statement.schema.json")
    rule_validator = make_validator("rule.schema.json")
    statements: dict[str, dict[str, object]] = {}
    rules: dict[str, dict[str, object]] = {}
    errors: list[str] = []
    for path in sorted(directory.glob("*.json")):
        errors.extend(_load_one(path, statements, rules, statement_validator, rule_validator))
    if errors:
        raise KnowledgeLoadError(errors)
    return KnowledgeBase(statements=statements, rules=rules)


def _load_one(
    path: Path,
    statements: dict[str, dict[str, object]],
    rules: dict[str, dict[str, object]],
    statement_validator: Validator,
    rule_validator: Validator,
) -> list[str]:
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{path.name}: kein gültiges JSON: {exc}"]
    if not isinstance(raw, dict):
        return [f"{path.name}: Objekt muss ein JSON-Objekt sein"]
    obj_id: object = raw.get("id")
    if not isinstance(obj_id, str):
        return [f"{path.name}: Objekt-ID fehlt"]
    if ":statement/" in obj_id:
        target: dict[str, dict[str, object]] = statements
        validator: Validator = statement_validator
    elif ":rule/" in obj_id:
        target = rules
        validator = rule_validator
    else:
        return [
            f"{path.name}: unbekannter Objekttyp in ID {obj_id!r} (kein :statement/ oder :rule/)"
        ]
    schema_errors = [f"{path.name}: {_error_detail(error)}" for error in validator.iter_errors(raw)]
    if schema_errors:
        return schema_errors
    if _sanitize_id(obj_id) + ".json" != path.name:
        return [f"{path.name}: Objekt-ID {obj_id!r} passt nicht zum Dateinamen"]
    if obj_id in target:
        return [f"{path.name}: doppelte Objekt-ID {obj_id!r}"]
    target[obj_id] = raw
    return []


def _sanitize_id(obj_id: str) -> str:
    """Macht eine Objekt-ID dateisystem-sicher (gleiche Regel wie M2/M3)."""
    return re.sub(r"[:/@]", "_", obj_id)


def _error_detail(error: ValidationError) -> str:
    path = "/".join(str(part) for part in error.absolute_path)
    return f"{path}: {error.message}" if path else error.message
