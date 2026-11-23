"""IFC-Adapter: IFC-Modell -> normalisierte Projektwerte (M5, REQ-500).

Liest Mengen (IfcQuantityArea/IfcQuantityLength/IfcQuantityCount) von
Bauelementen, mappt Mengen-Namen auf Concept-IDs (Mapping als Parameter,
z. B. aus dem Datenkatalog) und leitet die Einheit aus den IfcSIUnits
(UnitType + Prefix) der modellweiten IfcUnitAssignment ab.

Weg (IFC4):
    IfcElement
      └─ IsDefinedBy -> IfcRelDefinesByProperties
            └─ RelatingPropertyDefinition -> IfcElementQuantity
                  └─ Quantities -> IfcQuantityArea | IfcQuantityLength | IfcQuantityCount

Einheiten-Auflösung:
- LENGTH/AREA: ein explizites ``quantity.Unit`` (IfcSIUnit) hat Vorrang,
  sonst die modellweite IfcUnitAssignment (IfcSIUnit mit passendem
  UnitType). Keine Einheit auffindbar -> Fehler (nie raten).
- COUNT: fix "ea" (IFC-Stückzahl; das Schema kennt keine Count-Einheit).

Herkunft (Provenance): Dateiname + GlobalId des Bauelements.
Das Laden ist atomar (KBOB-Muster): alle Elemente werden gelesen, alle
Fehler gesammelt; bei Fehlern wird nichts geliefert (``ProjectDataError``).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sni.projectdata.models import ProjectDataError, ProjectValue, Provenance

# IFC-Mengentyp -> (Wert-Attribut, Basis-Einheitstyp)
_QUANTITY_KINDS: dict[str, tuple[str, str]] = {
    "IfcQuantityArea": ("AreaValue", "AREA"),
    "IfcQuantityLength": ("LengthValue", "LENGTH"),
    "IfcQuantityCount": ("CountValue", "COUNT"),
}

# IfcSIUnit.UnitType -> (Basis-Einheitstyp, Basis-Einheit)
_SI_UNIT_TYPES: dict[str, tuple[str, str]] = {
    "LENGTHUNIT": ("LENGTH", "m"),
    "AREAUNIT": ("AREA", "m2"),
}

# IfcSIUnitPrefixEnum -> SI-Vorsilbe (None = keine Vorsilbe)
_PREFIXES: dict[str | None, str] = {
    None: "",
    "NONE": "",
    "MICRO": "u",
    "MILLI": "m",
    "CENTI": "c",
    "DECI": "d",
    "DECA": "da",
    "HECTO": "h",
    "KILO": "k",
    "MEGA": "M",
    "GIGA": "G",
}


def read_ifc(path: Path, quantity_mapping: Mapping[str, str]) -> list[ProjectValue]:
    """Liest ein IFC-Modell (REQ-500); wirft ``ProjectDataError`` bei Fehlern.

    ``quantity_mapping`` mappt IFC-Mengen-Namen (z. B. "GrossArea") auf
    Concept-IDs. Mengen ohne Eintrag im Mapping werden ignoriert
    (nicht angefragtes Konzept).
    """
    ifc = _open_ifc(path)
    errors: list[str] = []
    units = _units_from_assignment(ifc, path.name, errors)
    values: list[ProjectValue] = []
    for element in ifc.by_type("IfcElement") or []:
        _collect_element(element, path.name, quantity_mapping, units, errors, values)
    if errors:
        raise ProjectDataError(errors)
    return values


def _open_ifc(path: Path) -> Any:
    try:
        import ifcopenshell
    except ImportError as exc:
        raise ProjectDataError(
            [f"{path.name}: ifcopenshell ist nicht installiert (pip install ifcopenshell)"]
        ) from exc
    try:
        return ifcopenshell.open(str(path))
    except OSError as exc:
        raise ProjectDataError([f"{path.name}: Datei nicht lesbar: {exc}"]) from exc
    except Exception as exc:  # ifcopenshell-Eigene Datei-Formatfehler
        raise ProjectDataError([f"{path.name}: ungültige IFC-Datei: {exc}"]) from exc


def _units_from_assignment(ifc: Any, file: str, errors: list[str]) -> dict[str, str]:
    """Baut {Einheitstyp: Einheit} aus allen IfcUnitAssignment-Instanzen.

    Widersprüchliche Einheiten desselben Typs im Modell sind ein Fehler
    (Widerspruch, kein Raten).
    """
    units: dict[str, str] = {}
    for assignment in ifc.by_type("IfcUnitAssignment") or []:
        for unit in assignment.Units or []:
            if not unit.is_a("IfcSIUnit"):
                continue  # IfcNamedUnit u. a.: für LENGTH/AREA Mengen nicht nötig
            spec = _SI_UNIT_TYPES.get(unit.UnitType)
            if spec is None:
                continue  # VOLUME/TIME u. a.: für diese Mengen nicht nötig
            base, base_unit = spec
            unit_string = _si_unit_string(unit, base_unit, file, errors)
            if unit_string is None:
                continue
            if units.get(base) not in (None, unit_string):
                errors.append(
                    f"{file}: widersprüchliche Einheiten für {base}: {units[base]} vs {unit_string}"
                )
            else:
                units[base] = unit_string
    return units


def _si_unit_string(unit: Any, base_unit: str, file: str, errors: list[str]) -> str | None:
    prefix = _PREFIXES.get(unit.Prefix)
    if prefix is None:
        errors.append(f"{file}: unbekannter Einheiten-Präfix '{unit.Prefix}'")
        return None
    return prefix + base_unit


def _collect_element(
    element: Any,
    file: str,
    quantity_mapping: Mapping[str, str],
    units: Mapping[str, str],
    errors: list[str],
    values: list[ProjectValue],
) -> None:
    for rel in element.IsDefinedBy or []:
        if not rel.is_a("IfcRelDefinesByProperties"):
            continue
        qto = rel.RelatingPropertyDefinition
        if qto is None or not qto.is_a("IfcElementQuantity"):
            continue
        for quantity in qto.Quantities or []:
            _collect_quantity(quantity, element, file, quantity_mapping, units, errors, values)


def _collect_quantity(
    quantity: Any,
    element: Any,
    file: str,
    quantity_mapping: Mapping[str, str],
    units: Mapping[str, str],
    errors: list[str],
    values: list[ProjectValue],
) -> None:
    kind = _quantity_kind(quantity)
    if kind is None:
        return  # andere Mengentypen: nicht unterstützt, wird ignoriert
    value_attr, base = kind
    name = quantity.Name
    if not name or name not in quantity_mapping:
        return  # Konzept nicht angefragt
    raw_value = getattr(quantity, value_attr, None)
    if not isinstance(raw_value, (int, float)) or not math.isfinite(raw_value):
        errors.append(f"{file} [{element.GlobalId}]: Menge '{name}' hat keinen gültigen Wert")
        return
    unit = _resolve_unit(quantity, base, units, file, errors)
    if unit is None:
        return  # Fehler wurde bereits gesammelt
    values.append(
        ProjectValue(
            concept=quantity_mapping[name],
            value=float(raw_value),
            unit=unit,
            provenance=Provenance(file=file, locator=element.GlobalId),
        )
    )


def _quantity_kind(quantity: Any) -> tuple[str, str] | None:
    for kind, spec in _QUANTITY_KINDS.items():
        if quantity.is_a(kind):
            return spec
    return None


def _resolve_unit(
    quantity: Any, base: str, units: Mapping[str, str], file: str, errors: list[str]
) -> str | None:
    if base == "COUNT":
        return "ea"
    quantity_unit = getattr(quantity, "Unit", None)
    if quantity_unit is not None and quantity_unit.is_a("IfcSIUnit"):
        spec = _SI_UNIT_TYPES.get(quantity_unit.UnitType)
        if spec is None or spec[0] != base:
            errors.append(
                f"{file}: Mengeneinheit {quantity_unit.UnitType} passt nicht zur erwarteten {base}"
            )
            return None
        return _si_unit_string(quantity_unit, spec[1], file, errors)
    if base in units:
        return units[base]
    errors.append(f"{file}: Menge hat keine Einheit im Modell (IfcUnitAssignment unvollständig)")
    return None
