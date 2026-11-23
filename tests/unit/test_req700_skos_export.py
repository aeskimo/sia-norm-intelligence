"""REQ-700: Katalog-Export als JSON und Turtle/SKOS (Export-Modul, ADR-0005)."""

from typing import cast

import pytest

from sni.export.skos import (
    CatalogExportError,
    catalog_json,
    catalog_ttl,
    id_to_iri,
    snapshot_ids_in,
)

SNAPSHOT = "sia:catalog/test@1.0.0"
OTHER_SNAPSHOT = "sia:catalog/other@2.0.0"
PLACEHOLDER = "Synthetischer Testbegriff (Platzhalter, kein Norminhalt.)."
NS = "https://sia-norm-intelligence.dev/sia/"


def _concept(concept_id: str, snapshot: str = SNAPSHOT) -> dict[str, object]:
    return {
        "id": concept_id,
        "name": {"de": concept_id.rsplit("/", 1)[-1].replace("-", " ").title()},
        "definition": {"de": PLACEHOLDER},
        "catalog_snapshot": snapshot,
    }


def _rich_concept() -> dict[str, object]:
    """Synthetisches Concept mit allen Feldern (G4: keine echten Inhalte)."""
    concept = _concept("sia:concept/raum")
    concept["name"] = {"de": "Raum", "fr": "Espace"}
    concept["abbreviation"] = "Rm"
    concept["quantity_type"] = "Flaeche"
    concept["unit"] = "m2"
    concept["relations"] = [
        {"type": "part_of", "target": "sia:concept/bauwerk"},
        {"type": "has_part", "target": "sia:concept/zone"},
        {"type": "specialization_of", "target": "sia:concept/flaeche"},
        {"type": "derived_from", "target": "sia:statement/syn1-2020/4.1/1"},
        {"type": "related_to", "target": "sia:concept/nutzflaeche"},
    ]
    concept["mappings"] = {
        "ifc": {
            "entity": "IfcSpace",
            "property_set": "Pset_SpaceCommon",
            "base_name": "NetFloorArea",
        },
        "bsdd": "Raum",
    }
    return concept


def _two_snapshots() -> list[dict[str, object]]:
    return [_concept("sia:concept/a", SNAPSHOT), _concept("sia:concept/b", OTHER_SNAPSHOT)]


def test_req700_id_to_iri_maps_prefix_to_sia_namespace() -> None:
    assert id_to_iri("sia:concept/raum") == f"{NS}concept/raum"
    assert id_to_iri("sia:catalog/test@1.0.0") == f"{NS}catalog/test@1.0.0"


def test_req700_id_to_iri_rejects_ids_without_prefix() -> None:
    with pytest.raises(CatalogExportError):
        id_to_iri("kein-praefix")


def test_req700_catalog_json_returns_concepts_and_disclaimer() -> None:
    body = catalog_json([_concept("sia:concept/a"), _rich_concept()], None, "DISCLAIMER")
    assert body["disclaimer"] == "DISCLAIMER"
    concepts = cast(list[dict[str, object]], body["concepts"])
    assert [c["id"] for c in concepts] == ["sia:concept/a", "sia:concept/raum"]


def test_req700_catalog_json_filters_by_snapshot() -> None:
    body = catalog_json(_two_snapshots(), SNAPSHOT, "D")
    concepts = cast(list[dict[str, object]], body["concepts"])
    assert [c["id"] for c in concepts] == ["sia:concept/a"]


def test_req700_catalog_json_unknown_snapshot_raises() -> None:
    with pytest.raises(CatalogExportError) as excinfo:
        catalog_json(_two_snapshots(), "sia:catalog/fehlend@9.9.9", "D")
    assert SNAPSHOT in str(excinfo.value)  # vorhandene Snapshots werden genannt


def test_req700_snapshot_ids_in_lists_unique_sorted() -> None:
    assert snapshot_ids_in(_two_snapshots()) == [OTHER_SNAPSHOT, SNAPSHOT]


def test_req700_ttl_contains_prefixes_scheme_and_disclaimer() -> None:
    ttl = catalog_ttl([_rich_concept()], None, "Keine Rechtsauskunft.")
    assert "@prefix sia: <https://sia-norm-intelligence.dev/sia/> ." in ttl
    assert "@prefix sni: <https://sia-norm-intelligence.dev/ns/> ." in ttl
    assert "@prefix skos: <http://www.w3.org/2004/02/skos/core#> ." in ttl
    assert "@prefix dcterms: <http://purl.org/dc/terms/> ." in ttl
    assert "@prefix prov: <http://www.w3.org/ns/prov#> ." in ttl
    assert "a skos:ConceptScheme ;" in ttl
    assert f'dcterms:title "{SNAPSHOT}"' in ttl
    assert "Keine Rechtsauskunft." in ttl  # G6 als Kommentarzeile


def test_req700_ttl_maps_name_definition_and_abbreviation() -> None:
    ttl = catalog_ttl([_rich_concept()], None, "D")
    assert 'skos:prefLabel "Raum"@de' in ttl
    assert 'skos:prefLabel "Espace"@fr' in ttl
    assert f'skos:definition "{PLACEHOLDER}"@de' in ttl
    assert 'skos:altLabel "Rm"' in ttl


def test_req700_ttl_maps_all_relation_types() -> None:
    ttl = catalog_ttl([_rich_concept()], None, "D")
    assert f"dcterms:isPartOf <{NS}concept/bauwerk>" in ttl
    assert f"dcterms:hasPart <{NS}concept/zone>" in ttl
    assert f"skos:broader <{NS}concept/flaeche>" in ttl
    assert f"prov:wasDerivedFrom <{NS}statement/syn1-2020/4.1/1>" in ttl
    assert f"skos:related <{NS}concept/nutzflaeche>" in ttl


def test_req700_ttl_maps_sni_fields_and_in_scheme() -> None:
    ttl = catalog_ttl([_rich_concept()], None, "D")
    assert 'sni:unit "m2"' in ttl
    assert 'sni:quantityType "Flaeche"' in ttl
    assert f'sni:catalogSnapshot "{SNAPSHOT}"' in ttl
    assert f"skos:inScheme <{NS}catalog/test@1.0.0>" in ttl
    assert "a skos:Concept" in ttl


def test_req700_ttl_mappings_as_blank_node() -> None:
    ttl = catalog_ttl([_rich_concept()], None, "D")
    assert 'sni:mappings [ sni:bsdd "Raum" ; sni:ifc' in ttl
    # nicht-string Werte (ifc-Tupel) werden JSON-kodiert und escaped
    assert '\\"entity\\": \\"IfcSpace\\"' in ttl
    assert '\\"property_set\\": \\"Pset_SpaceCommon\\"' in ttl


def test_req700_ttl_snapshot_filter_exports_only_that_scheme() -> None:
    concepts = _two_snapshots() + [_rich_concept()]
    ttl = catalog_ttl(concepts, SNAPSHOT, "D")
    assert "<https://sia-norm-intelligence.dev/sia/concept/a>" in ttl
    assert "<https://sia-norm-intelligence.dev/sia/concept/b>" not in ttl
    assert "other@2.0.0" not in ttl
