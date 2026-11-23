"""REQ-701: Regel -> IDS 1.0-Spezifikation, sonst GapReport (Export-Modul, ADR-0005)."""

from typing import cast

import pytest

from sni.export.ids import IdsExportError, export_ids, ifc_mapping

DISCLAIMER = "DISCLAIMER"
PLACEHOLDER = "Synthetischer Testbegriff (Platzhalter, kein Norminhalt)."
SNAPSHOT = "sia:catalog/test@1.0.0"
IFC = {"entity": "IfcSpace", "property_set": "Pset_SpaceCommon", "base_name": "NetFloorArea"}
ZONE_A = "sia:concept/zona-a"
ZONE_B = "sia:concept/zona-b"
ZONE_OUT = "sia:concept/zona-gesamt"
RULE = "sia:rule/syn1-2020/zone-summe"
OTHER_RULE = "sia:rule/syn1-2020/zone-produkt"


def _concept(concept_id: str, ifc: dict[str, str] | None = IFC) -> dict[str, object]:
    """Synthetisches Concept (G4: Platzhalter-Werte, kein Norminhalt)."""
    concept: dict[str, object] = {
        "id": concept_id,
        "name": {"de": concept_id.rsplit("/", 1)[-1].replace("-", " ").title()},
        "definition": {"de": PLACEHOLDER},
        "catalog_snapshot": SNAPSHOT,
    }
    if ifc is not None:
        concept["mappings"] = {"ifc": ifc}
    return concept


def _mappable_concepts() -> dict[str, dict[str, object]]:
    return {cid: _concept(cid) for cid in (ZONE_A, ZONE_B, ZONE_OUT)}


def _rule(rule_id: str = RULE, status: str = "approved") -> dict[str, object]:
    return {
        "id": rule_id,
        "derived_from": ["sia:statement/syn1-2020/4.1/1"],
        "inputs": [
            {"concept": ZONE_A, "unit": "m2"},
            {"concept": ZONE_B, "unit": "m2"},
        ],
        "output": {"concept": ZONE_OUT, "unit": "m2"},
        "expression": "zona_a + zona_b",
        "applicability": "Synthetische Bedingung (Platzhalter, kein Norminhalt).",
        "review_status": status,
    }


def test_req701_ifc_mapping_returns_complete_triple() -> None:
    assert ifc_mapping(_concept(ZONE_A)) == ("IfcSpace", "Pset_SpaceCommon", "NetFloorArea")


def test_req701_ifc_mapping_none_concept_is_none() -> None:
    assert ifc_mapping(None) is None


def test_req701_ifc_mapping_without_mappings_is_none() -> None:
    assert ifc_mapping(_concept(ZONE_A, ifc=None)) is None


@pytest.mark.parametrize(
    "ifc",
    [
        pytest.param({"bsdd": "Raum"}, id="no-ifc-key"),
        pytest.param(
            {"entity": "IfcSpace", "property_set": "Pset_SpaceCommon"}, id="missing-base-name"
        ),
        pytest.param({"entity": "", "property_set": "P", "base_name": "B"}, id="empty-entity"),
        pytest.param({"entity": 5, "property_set": "P", "base_name": "B"}, id="entity-not-string"),
        pytest.param({"entity": "IfcSpace", "property_set": "P", "base_name": None}, id="bn-none"),
    ],
)
def test_req701_ifc_mapping_incomplete_is_none(ifc: dict[str, object]) -> None:
    concept = _concept(ZONE_A, ifc=None)
    concept["mappings"] = {"ifc": ifc}
    assert ifc_mapping(concept) is None


def test_req701_export_ids_mappable_rule_produces_ids_xml() -> None:
    result = export_ids([_rule()], _mappable_concepts(), None, DISCLAIMER)
    xml = cast(str, result["ids_xml"])
    assert xml.startswith("<?xml")
    assert '<ids xmlns="http://standards.buildingsmart.org/IDS">' in xml
    # <info>: Titel, Version, Disclaimer; kein author (XSD-E-Mail-Muster)
    assert "<title>SIA Norm Intelligence - IDS Export</title>" in xml
    assert "<version>1.0.0</version>" in xml
    assert DISCLAIMER in xml
    assert "<author" not in xml
    # Specification: Attribute gemäss ADR-0005
    assert 'ifcVersion="IFC4"' in xml
    assert f'name="{RULE}"' in xml
    assert f'identifier="{RULE}"' in xml
    # applicability = entity-Facet des Output-Concepts
    assert "<name>IfcSpace</name>" in xml
    # requirements = property-Facet je Input- und Output-Concept (3x, cardinality required)
    assert xml.count("<propertySet>Pset_SpaceCommon</propertySet>") == 3
    assert xml.count("<baseName>NetFloorArea</baseName>") == 3
    assert xml.count('<cardinality value="required" />') == 3
    assert result["gaps"] == []
    assert result["disclaimer"] == DISCLAIMER


def test_req701_export_ids_mixed_mappable_and_gap() -> None:
    concepts = _mappable_concepts()
    unmapped_target = "sia:concept/keine-ifc"
    concepts[unmapped_target] = _concept(unmapped_target, ifc=None)
    unmappable = _rule(OTHER_RULE)
    unmappable["output"] = {"concept": unmapped_target, "unit": "m2"}
    result = export_ids([_rule(), unmappable], concepts, None, DISCLAIMER)
    xml = cast(str, result["ids_xml"])
    assert f'name="{RULE}"' in xml
    assert OTHER_RULE not in xml  # keine Teilabbildung (G5)
    gaps = cast(list[dict[str, object]], result["gaps"])
    assert len(gaps) == 1
    gap = gaps[0]
    assert gap["gap_type"] == "not_ids_expressible"
    assert gap["target_layer"] == "mapping"
    assert gap["evidence"] == [OTHER_RULE]
    assert gap["priority"] == "medium"
    assert gap["status"] == "open"
    assert gap["id"] == "GAP-0001"
    assert unmapped_target in str(gap["description"])


def test_req701_export_ids_no_mappable_rules_yields_null_xml() -> None:
    concepts = _mappable_concepts()
    concepts[ZONE_A] = _concept(ZONE_A, ifc=None)  # Input-Concept ohne ifc-Mapping
    result = export_ids([_rule()], concepts, None, DISCLAIMER)
    assert result["ids_xml"] is None  # IDS verlangt mind. 1 Specification
    gaps = cast(list[dict[str, object]], result["gaps"])
    assert len(gaps) == 1
    assert gaps[0]["evidence"] == [RULE]


def test_req701_export_ids_gap_numbering_continues_existing() -> None:
    concepts = _mappable_concepts()
    concepts[ZONE_A] = _concept(ZONE_A, ifc=None)
    result = export_ids([_rule()], concepts, None, DISCLAIMER, existing_gap_ids=("GAP-0007",))
    gaps = cast(list[dict[str, object]], result["gaps"])
    assert gaps[0]["id"] == "GAP-0008"


def test_req701_export_ids_default_ignores_non_approved() -> None:
    result = export_ids(
        [_rule(), _rule(OTHER_RULE, status="reviewed")],
        _mappable_concepts(),
        None,
        DISCLAIMER,
    )
    xml = cast(str, result["ids_xml"])
    assert f'name="{RULE}"' in xml
    assert OTHER_RULE not in xml  # G3: nicht approved wird weder exportiert noch Gap
    assert result["gaps"] == []


def test_req701_export_ids_explicit_rule_ids_select_subset() -> None:
    third = _rule("sia:rule/syn1-2020/zone-differenz")
    result = export_ids(
        [_rule(), _rule(OTHER_RULE), third],
        _mappable_concepts(),
        [OTHER_RULE, RULE],
        DISCLAIMER,
    )
    xml = cast(str, result["ids_xml"])
    assert f'name="{RULE}"' in xml
    assert f'name="{OTHER_RULE}"' in xml
    assert "zone-differenz" not in xml
    assert result["gaps"] == []


def test_req701_export_ids_unknown_rule_id_raises() -> None:
    with pytest.raises(IdsExportError, match="unknown/x"):
        export_ids([_rule()], _mappable_concepts(), ["sia:rule/unknown/x"], DISCLAIMER)


def test_req701_export_ids_non_approved_explicit_rule_raises() -> None:
    with pytest.raises(IdsExportError, match="reviewed"):
        export_ids(
            [_rule(OTHER_RULE, status="reviewed")],
            _mappable_concepts(),
            [OTHER_RULE],
            DISCLAIMER,
        )
