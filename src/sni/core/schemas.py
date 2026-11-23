"""Laden und Validieren der JSON-Schemas (Draft 2020-12).

Die Dateien in /schemas sind die Quelle der Wahrheit (docs/04_DATA_MODEL.md).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

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


def load_schema(name: str, schemas_dir: Path = SCHEMAS_DIR) -> dict[str, object]:
    """Lädt eine Schema-Datei aus /schemas (Quelle der Wahrheit)."""
    path = schemas_dir / name
    if not path.is_file():
        raise FileNotFoundError(f"Schema-Datei nicht gefunden: {path}")
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{name}: Schema muss ein JSON-Objekt sein")
    return raw


# Erwarteter Schema-Inhaltstyp laut types-jsonschema (Draft202012Validator).
_CONTENTS = bool | Mapping[str, Any]
_REGISTRY_CACHE: dict[Path, Registry[_CONTENTS]] = {}


def _build_registry(schemas_dir: Path) -> Registry[_CONTENTS]:
    """Registriert jedes Schema unter drei URI-Schlüsseln.

    - ``$id`` (z. B. ``sni:norm_statement``)
    - ``sni:<Dateiname>`` (z. B. ``sni:norm_statement.schema.json``)
    - ``<Dateiname>`` (z. B. ``norm_statement.schema.json``)

    Der dritte Schlüssel ist nötig, weil relative ``$ref``s (z. B.
    ``source_reference.schema.json`` in norm_statement.schema.json) gegen
    die Basis-URI ``sni:norm_statement`` (nur Schema, kein Pfad) auf den
    blossen Dateinamen auflösen.
    """
    pairs: list[tuple[str, Resource[_CONTENTS]]] = []
    for path in schema_files(schemas_dir):
        schema = load_schema(path.name, schemas_dir)
        resource: Resource[_CONTENTS] = DRAFT202012.create_resource(schema)
        declared_id: object = schema.get("$id")
        if isinstance(declared_id, str):
            pairs.append((declared_id, resource))
        pairs.append((f"sni:{path.name}", resource))
        pairs.append((path.name, resource))
    return Registry[_CONTENTS]().with_resources(pairs)


def _registry_for(schemas_dir: Path) -> Registry[_CONTENTS]:
    if schemas_dir not in _REGISTRY_CACHE:
        _REGISTRY_CACHE[schemas_dir] = _build_registry(schemas_dir)
    return _REGISTRY_CACHE[schemas_dir]


def make_validator(schema_name: str, schemas_dir: Path = SCHEMAS_DIR) -> Draft202012Validator:
    """Erzeugt einen Draft-2020-12-Validator mit ``$ref``-Auflösung aus /schemas."""
    schema = load_schema(schema_name, schemas_dir)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, registry=_registry_for(schemas_dir))


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
