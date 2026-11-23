"""CSV-Adapter: Flächenlisten (CSV) -> normalisierte Projektwerte (M5, REQ-500).

Format (v1): CSV (UTF-8, optional mit BOM) mit Kopfzeile
``concept,value,unit``, ein Wert pro Zeile:

    concept,value,unit
    sia:concept/teilsflaeche-a,100,m2
    sia:concept/teilsflaeche-b,50,m2

Herkunft (Provenance): Dateiname + physikalische Zeilennummer (Kopfzeile =
Zeile 1). Leere Zeilen werden ignoriert.

Das Laden ist atomar (KBOB-Muster, wie M1–M4): alle Zeilen werden gelesen,
alle Fehler gesammelt; bei Fehlern wird nichts geliefert
(``ProjectDataError`` mit voller Fehlerliste).

Einheiten werden unverändert durchgereicht; die Einheiten-Diziplin
(geliefert vs. deklariert) prüft die Regel-Engine (REQ-302).
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

from sni.projectdata.models import ProjectDataError, ProjectValue, Provenance

HEADER = ("concept", "value", "unit")


def read_csv(path: Path) -> list[ProjectValue]:
    """Liest eine Projektdaten-CSV (REQ-500); wirft ``ProjectDataError`` bei Fehlern."""
    errors: list[str] = []
    values: list[ProjectValue] = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            for line_no, row in enumerate(reader, start=1):
                if line_no == 1:
                    if [col.strip().lower() for col in row] != list(HEADER):
                        errors.append(f"{path.name}:1: Kopfzeile muss '{','.join(HEADER)}' sein")
                    continue
                if not row or all(not col.strip() for col in row):
                    continue  # leere Zeile
                errors.extend(_parse_row(path.name, line_no, row, values))
    except OSError as exc:
        errors.append(f"{path.name}: Datei nicht lesbar: {exc}")
    except csv.Error as exc:
        errors.append(f"{path.name}: ungültige CSV: {exc}")
    if errors:
        raise ProjectDataError(errors)
    return values


def _parse_row(file: str, line_no: int, row: list[str], out: list[ProjectValue]) -> list[str]:
    if len(row) != 3:
        return [f"{file}:{line_no}: genau 3 Spalten erwartet (concept,value,unit)"]
    concept, raw_value, unit = (col.strip() for col in row)
    errors: list[str] = []
    if not concept:
        errors.append(f"{file}:{line_no}: Concept fehlt")
    if not unit:
        errors.append(f"{file}:{line_no}: Einheit fehlt")
    try:
        value = float(raw_value)
    except ValueError:
        return [f"{file}:{line_no}: Wert '{raw_value}' ist keine Zahl"]
    if not math.isfinite(value):
        return [f"{file}:{line_no}: Wert muss endlich sein (kein nan/inf)"]
    if not errors:
        out.append(
            ProjectValue(
                concept=concept,
                value=value,
                unit=unit,
                provenance=Provenance(file=file, locator=f"Zeile {line_no}"),
            )
        )
    return errors
