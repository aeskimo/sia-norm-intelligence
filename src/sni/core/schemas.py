"""Laden und Validieren der JSON-Schemas (Draft 2020-12).

Die Dateien in /schemas sind die Quelle der Wahrheit (docs/04_DATA_MODEL.md).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

SCHEMAS_DIR = Path(__file__).resolve().parents[3] / "schemas"
DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"


def schema_files(schemas_dir: Path = SCHEMAS_DIR) -> list[Path]:
    """Alle Schema-Dateien im Verzeichnis, sortiert nach Name."""
    return sorted(schemas_dir.glob("*.json"))


def validate_schema_file(path: Path) -> list[str]:
    """Prüft eine einzelne Datei; liefert Fehlermeldungen (leer = gültig)."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{path.name}: kein gültiges JSON: {exc}"]
    if not isinstance(raw, dict):
        return [f"{path.name}: Schema muss ein JSON-Objekt sein"]
    declared = raw.get("$schema", DRAFT_2020_12)
    if declared != DRAFT_2020_12:
        return [f"{path.name}: unerwartetes $schema {declared!r} (erwartet Draft 2020-12)"]
    try:
        Draft202012Validator.check_schema(raw)
    except SchemaError as exc:
        return [f"{path.name}: ungültiges Draft-2020-12-Schema: {exc.message}"]
    return []


def validate_all(schemas_dir: Path = SCHEMAS_DIR) -> list[str]:
    """Prüft alle Dateien in /schemas; liefert alle Fehlermeldungen."""
    errors: list[str] = []
    for path in schema_files(schemas_dir):
        errors.extend(validate_schema_file(path))
    return errors


def main(schemas_dir: Path = SCHEMAS_DIR) -> int:
    """CLI-Einstiegspunkt (`python -m sni.core.schemas`); 0 = alle gültig."""
    errors = validate_all(schemas_dir)
    if errors:
        for error in errors:
            print(f"FEHLER: {error}")
        return 1
    print(f"OK: {len(schema_files(schemas_dir))} Schema-Dateien gültig (Draft 2020-12)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
