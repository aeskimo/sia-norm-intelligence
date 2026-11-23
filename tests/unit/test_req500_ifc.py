"""REQ-500: IFC-Adapter liefert normalisierte Werte mit Herkunft (Datei, GUID)."""

from pathlib import Path
from typing import Any

import ifcopenshell
import ifcopenshell.api
import ifcopenshell.api.owner
import pytest

from sni.projectdata.ifc_adapter import read_ifc
from sni.projectdata.models import ProjectDataError

MAPPING = {
    "GrossArea": "sia:concept/geschossflaeche",
    "Length": "sia:concept/waende-laenge",
    "Count": "sia:concept/anzahl",
}


def _bare_model() -> Any:
    """IFC4-Modell mit Project, aber ohne IfcUnitAssignment."""
    f = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcProject", name="Testprojekt")
    return f


def _base_model() -> Any:
    """Modell mit IfcUnitAssignment (METRE für LENGTH und AREA)."""
    f = _bare_model()
    length = ifcopenshell.api.run("unit.add_si_unit", f, unit_type="LENGTHUNIT")
    area = ifcopenshell.api.run("unit.add_si_unit", f, unit_type="AREAUNIT")
    ifcopenshell.api.run("unit.assign_unit", f, units=[length, area])
    return f


def _add_wall(f: Any, name: str, quantities: dict[str, Any]) -> Any:
    wall = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcWall", name=name)
    if quantities:
        qto = ifcopenshell.api.run("pset.add_qto", f, product=wall, name="Qto_WallBaseQuantities")
        ifcopenshell.api.run("pset.edit_qto", f, qto=qto, properties=quantities)
    return wall


def _write_model(tmp_path: Path, model: Any, name: str = "modell.ifc") -> Path:
    path = tmp_path / name
    model.write(str(path))
    return path


def test_req500_ifc_values_with_provenance(tmp_path: Path) -> None:
    f = _base_model()
    wall = _add_wall(f, "Wand 1", {"GrossArea": 150.0, "Length": 5.0, "Count": 3})
    ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcSlab", name="Platte 1")
    path = _write_model(tmp_path, f)

    values = read_ifc(path, MAPPING)

    assert len(values) == 3  # Platte ohne Mengen wird ignoriert
    by_concept = {v.concept: v for v in values}
    area = by_concept["sia:concept/geschossflaeche"]
    assert area.value == 150.0
    assert area.unit == "m2"
    assert area.provenance.file == "modell.ifc"
    assert area.provenance.locator == wall.GlobalId  # GUID des Bauelements
    assert by_concept["sia:concept/waende-laenge"].unit == "m"
    count = by_concept["sia:concept/anzahl"]
    assert count.value == 3.0
    assert count.unit == "ea"


def test_req500_ifc_unmapped_quantities_ignored(tmp_path: Path) -> None:
    f = _base_model()
    _add_wall(f, "Wand 1", {"GrossArea": 150.0, "Length": 5.0})
    path = _write_model(tmp_path, f)

    values = read_ifc(path, {"GrossArea": "sia:concept/geschossflaeche"})

    assert [v.concept for v in values] == ["sia:concept/geschossflaeche"]


def test_req500_ifc_prefix_from_unit_assignment(tmp_path: Path) -> None:
    f = _bare_model()
    mm = ifcopenshell.api.run("unit.add_si_unit", f, unit_type="LENGTHUNIT", prefix="MILLI")
    ifcopenshell.api.run("unit.assign_unit", f, units=[mm])
    _add_wall(f, "Wand 1", {"Length": 5000.0})
    path = _write_model(tmp_path, f)

    values = read_ifc(path, {"Length": "sia:concept/waende-laenge"})

    assert len(values) == 1
    assert values[0].value == 5000.0
    assert values[0].unit == "mm"


def test_req500_ifc_conflicting_units_rejected(tmp_path: Path) -> None:
    f = _bare_model()
    metre = ifcopenshell.api.run("unit.add_si_unit", f, unit_type="LENGTHUNIT")
    ifcopenshell.api.run("unit.assign_unit", f, units=[metre])
    mm = ifcopenshell.api.run("unit.add_si_unit", f, unit_type="LENGTHUNIT", prefix="MILLI")
    f.create_entity("IfcUnitAssignment", Units=[mm])
    _add_wall(f, "Wand 1", {"Length": 5.0})
    path = _write_model(tmp_path, f)

    with pytest.raises(ProjectDataError, match="widerspr.*Einheiten"):
        read_ifc(path, {"Length": "sia:concept/waende-laenge"})


def test_req500_ifc_no_unit_assignment_rejected(tmp_path: Path) -> None:
    f = _bare_model()
    _add_wall(f, "Wand 1", {"GrossArea": 150.0})
    path = _write_model(tmp_path, f)

    with pytest.raises(ProjectDataError, match="keine Einheit"):
        read_ifc(path, MAPPING)


def test_req500_ifc_multiple_elements_own_guids(tmp_path: Path) -> None:
    f = _base_model()
    wall1 = _add_wall(f, "Wand 1", {"GrossArea": 100.0})
    wall2 = _add_wall(f, "Wand 2", {"GrossArea": 50.0})
    path = _write_model(tmp_path, f)

    values = read_ifc(path, {"GrossArea": "sia:concept/geschossflaeche"})

    assert len(values) == 2
    assert {v.provenance.locator for v in values} == {wall1.GlobalId, wall2.GlobalId}
    assert {v.value for v in values} == {100.0, 50.0}


def test_req500_ifc_null_value_rejected(tmp_path: Path) -> None:
    f = _base_model()
    wall = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcWall", name="Wand 1")
    quantity = f.create_entity("IfcQuantityArea", Name="GrossArea", AreaValue=None)
    qto = f.create_entity(
        "IfcElementQuantity",
        GlobalId=ifcopenshell.guid.new(),
        OwnerHistory=ifcopenshell.api.owner.create_owner_history(f),
        Name="Qto_WallBaseQuantities",
    )
    qto.Quantities = [quantity]
    f.create_entity(
        "IfcRelDefinesByProperties",
        GlobalId=ifcopenshell.guid.new(),
        OwnerHistory=ifcopenshell.api.owner.create_owner_history(f),
        RelatedObjects=[wall],
        RelatingPropertyDefinition=qto,
    )
    path = _write_model(tmp_path, f)

    with pytest.raises(ProjectDataError, match="gültigen Wert"):
        read_ifc(path, MAPPING)


def test_req500_ifc_missing_file_rejected(tmp_path: Path) -> None:
    with pytest.raises(ProjectDataError, match="nicht lesbar"):
        read_ifc(tmp_path / "existiert-nicht.ifc", MAPPING)


def test_req500_ifc_invalid_file_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.ifc"
    bad.write_text("definitiv kein IFC", encoding="utf-8")

    with pytest.raises(ProjectDataError, match="ungültige IFC"):
        read_ifc(bad, MAPPING)
