"""Projektdaten-Upload: Datei-Inhalt (Bytes) -> normalisierte Projektwerte.

ADR-0006: Format-Erkennung ausschliesslich per Dateierweiterung (``.csv``,
``.ifc``); IFC verlangt ein Quantity-Mapping (Mengen-Name -> Concept-ID),
CSV braucht keines. Die Adapter (``csv_adapter``, ``ifc_adapter``,
REQ-500) lesen von einem Pfad, daher wird der Inhalt in ein temporäres
Verzeichnis geschrieben und danach gelöscht. Der Dateiname wird auf den
Basisnamen reduziert (keine Pfadkomponenten, G4).

Keine Catalog-Zugriffe (Schichten-Regel, 03_ARCHITECTURE.md): das
Mapping für IFC wird von der API-Seite bereitgestellt (explizit oder
dort aus dem Katalog abgeleitet).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from jsonschema.exceptions import ValidationError

from sni.core.schemas import make_validator
from sni.projectdata.csv_adapter import read_csv
from sni.projectdata.ifc_adapter import read_ifc
from sni.projectdata.models import ProjectValue

#: Maximale Upload-Grösse in Bytes (v1-Wert, ADR-0006).
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

_FORMATS: dict[str, str] = {".csv": "csv", ".ifc": "ifc"}


class UploadError(ValueError):
    """Upload-Request ungültig (Format, Grösse, fehlendes Mapping)."""


class UploadServiceError(RuntimeError):
    """Ergebnis nicht schemakonform (interner Fehler)."""


@dataclass(frozen=True)
class UploadResult:
    """Normalisierte Projektwerte inkl. Format-, Datei- und Mapping-Nachweis."""

    format: str
    file: str
    values: tuple[ProjectValue, ...]
    quantity_mapping: Mapping[str, str] | None


def load_upload(
    filename: str,
    data: bytes,
    quantity_mapping: Mapping[str, str] | None,
    tmp_dir: Path,
) -> UploadResult:
    """Liest einen Upload (Bytes) und liefert normalisierte Projektwerte.

    Wirft ``UploadError`` bei unbekannten Formaten, übergrosser Datei oder
    fehlendem IFC-Mapping und ``ProjectDataError`` (vollständiger KBOB-
    Bericht) bei fehlerhafter Dateiinhalte.
    """
    ext = Path(filename).suffix.lower()
    fmt = _FORMATS.get(ext)
    if fmt is None:
        raise UploadError(f"Datei-Format unbekannt (Endung {ext!r}); unterstützt: .csv, .ifc")
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadError(f"Datei zu gross ({len(data)} Bytes, maximal {MAX_UPLOAD_BYTES})")
    safe_name = Path(filename).name
    if not safe_name:
        raise UploadError("Dateiname fehlt oder ist leer")
    path = tmp_dir / safe_name
    path.write_bytes(data)
    try:
        if fmt == "csv":
            values = read_csv(path)
            mapping: Mapping[str, str] | None = None
        else:
            if quantity_mapping is None:
                raise UploadError(
                    f"{safe_name}: IFC-Modell ohne Quantity-Mapping – "
                    "Mapping explizit übergeben (quantity_mapping) oder "
                    "Konzepte mit IFC-Mapping in den Katalog importieren"
                )
            values = read_ifc(path, quantity_mapping)
            mapping = dict(quantity_mapping)
    finally:
        path.unlink(missing_ok=True)
    return UploadResult(fmt, safe_name, tuple(values), mapping)


def projectdata_response(result: UploadResult, disclaimer: str) -> dict[str, object]:
    """Antwort-Dict für ``POST /v1/projectdata`` (Schema ``sni:project_values``).

    Wird gegen das Schema validiert, bevor es geliefert wird (DoD,
    AGENTS.md §6, wie ``sni.service.checker``).
    """
    mapping: Mapping[str, str] | None = (
        dict(result.quantity_mapping) if result.quantity_mapping is not None else None
    )
    payload: dict[str, object] = {
        "format": result.format,
        "file": result.file,
        "values": [
            {
                "concept": value.concept,
                "value": value.value,
                "unit": value.unit,
                "provenance": {
                    "file": value.provenance.file,
                    "locator": value.provenance.locator,
                },
            }
            for value in result.values
        ],
        "quantity_mapping": mapping,
        "disclaimer": disclaimer,
    }
    try:
        make_validator("project_values.schema.json").validate(payload)
    except ValidationError as exc:
        raise UploadServiceError(
            f"Projektwerte-Antwort nicht schemakonform: {exc.message}"
        ) from exc
    return payload
