"""Katalog-Export als JSON und Turtle/SKOS (M7, REQ-700).

Gemäss ADR-0005 (OQ-007, Option A): Standardvokabular (SKOS, Dublin
Core, PROV-O), wo eine 1:1-Semantik besteht, sonst `sni:`. Turtle wird
handgeschrieben (keine neuen Laufzeit-Abhängigkeiten, ADR-0002).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

SIA_NS = "https://sia-norm-intelligence.dev/sia/"
SNI_NS = "https://sia-norm-intelligence.dev/ns/"
SKOS_NS = "http://www.w3.org/2004/02/skos/core#"
DCTERMS_NS = "http://purl.org/dc/terms/"
PROV_NS = "http://www.w3.org/ns/prov#"

_TURTLE_PREFIXES = (
    ("sia", SIA_NS),
    ("sni", SNI_NS),
    ("skos", SKOS_NS),
    ("dcterms", DCTERMS_NS),
    ("prov", PROV_NS),
)

# Relationstyp -> (Namespace, Prädikat) gemäss ADR-0005 Punkt 3.
RELATION_PREDICATES: dict[str, tuple[str, str]] = {
    "specialization_of": ("skos", "broader"),
    "part_of": ("dcterms", "isPartOf"),
    "has_part": ("dcterms", "hasPart"),
    "derived_from": ("prov", "wasDerivedFrom"),
    "related_to": ("skos", "related"),
}


class CatalogExportError(ValueError):
    """Katalog kann nicht exportiert werden (unbekanntes Format/Snapshot)."""


def id_to_iri(system_id: str) -> str:
    """System-ID `<pfx>:rest` -> IRI unter dem `sia:`-Namespace (ADR-0005)."""
    _prefix, sep, rest = system_id.partition(":")
    if not sep or not rest:
        raise CatalogExportError(f"Ungültige System-ID (erwartet <pfx>:rest): {system_id}")
    return SIA_NS + rest


def snapshot_ids_in(concepts: Sequence[Mapping[str, object]]) -> list[str]:
    """Alle Snapshot-IDs der Concepts, sortiert und entdupidelt."""
    return sorted({str(c["catalog_snapshot"]) for c in concepts})


def _select(
    concepts: Sequence[Mapping[str, object]], snapshot: str | None
) -> list[Mapping[str, object]]:
    if snapshot is None:
        return list(concepts)
    available = snapshot_ids_in(concepts)
    if snapshot not in available:
        raise CatalogExportError(
            f"Snapshot {snapshot!r} nicht im Katalog (vorhanden: {', '.join(available)})"
        )
    return [c for c in concepts if c.get("catalog_snapshot") == snapshot]


def catalog_json(
    concepts: Sequence[Mapping[str, object]],
    snapshot: str | None,
    disclaimer: str,
) -> dict[str, object]:
    """JSON-Export (REQ-700): schemakonforme Concepts + G6-Disclaimer."""
    selected = _select(concepts, snapshot)
    return {"concepts": selected, "disclaimer": disclaimer}


def _turtle_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _literal(value: object) -> str:
    """Turtle-Literal; Nicht-Strings werden JSON-kodiert (v1-Limitation)."""
    if isinstance(value, str):
        return f'"{_turtle_escape(value)}"'
    return f'"{_turtle_escape(json.dumps(value, ensure_ascii=False, sort_keys=True))}"'


def _ml_literals(ml: object) -> list[str]:
    """Sprachgetaggte Literale (de/fr/it, fixe Reihenfolge)."""
    if not isinstance(ml, Mapping):
        return []
    parts: list[str] = []
    for lang in ("de", "fr", "it"):
        value = ml.get(lang)
        if isinstance(value, str):
            parts.append(f'"{_turtle_escape(value)}"@{lang}')
    return parts


def _relation_clauses(relations: object) -> list[str]:
    clauses: list[str] = []
    if not isinstance(relations, list):
        return clauses
    for item in relations:
        if not isinstance(item, Mapping):
            continue
        rel_type = item.get("type")
        target = item.get("target")
        predicate = RELATION_PREDICATES.get(rel_type) if isinstance(rel_type, str) else None
        if predicate is None or not isinstance(target, str):
            continue
        namespace, local = predicate
        clauses.append(f"{namespace}:{local} <{id_to_iri(target)}>")
    return clauses


def _mappings_clause(mappings: object) -> str | None:
    """Blank-Node `sni:mappings [ ... ]` mit je einer Property pro Key."""
    if not isinstance(mappings, Mapping) or not mappings:
        return None
    inner = " ; ".join(f"sni:{key} {_literal(value)}" for key, value in sorted(mappings.items()))
    return f"sni:mappings [ {inner} ]"


def concept_ttl(concept: Mapping[str, object], scheme_iri: str) -> str:
    """Ein Concept als Turtle-Komplex (inklusive Abschlusspunkt)."""
    clauses: list[str] = ["a skos:Concept", f"skos:inScheme <{scheme_iri}>"]
    clauses.extend(f"skos:prefLabel {lit}" for lit in _ml_literals(concept.get("name")))
    clauses.extend(f"skos:definition {lit}" for lit in _ml_literals(concept.get("definition")))
    abbreviation = concept.get("abbreviation")
    if isinstance(abbreviation, str):
        clauses.append(f'skos:altLabel "{_turtle_escape(abbreviation)}"')
    clauses.extend(_relation_clauses(concept.get("relations")))
    unit = concept.get("unit")
    if isinstance(unit, str):
        clauses.append(f"sni:unit {_literal(unit)}")
    quantity_type = concept.get("quantity_type")
    if isinstance(quantity_type, str):
        clauses.append(f"sni:quantityType {_literal(quantity_type)}")
    mappings_clause = _mappings_clause(concept.get("mappings"))
    if mappings_clause is not None:
        clauses.append(mappings_clause)
    snapshot_id = concept.get("catalog_snapshot")
    if isinstance(snapshot_id, str):
        clauses.append(f'sni:catalogSnapshot "{_turtle_escape(snapshot_id)}"')
    subject = f"<{id_to_iri(str(concept['id']))}>"
    return f"{subject} " + " ;\n    ".join(clauses) + " ."


def catalog_ttl(
    concepts: Sequence[Mapping[str, object]],
    snapshot: str | None,
    disclaimer: str,
) -> str:
    """Turtle-Export (REQ-700); SKOS-Mapping gemäss ADR-0005 Punkt 3."""
    selected = sorted(_select(concepts, snapshot), key=lambda c: str(c.get("id", "")))
    lines: list[str] = [f"# {disclaimer.replace('#', '\\#')}"]
    lines.extend(f"@prefix {prefix}: <{ns}> ." for prefix, ns in _TURTLE_PREFIXES)
    lines.append("")
    for scheme_id in sorted(
        {str(c.get("catalog_snapshot")) for c in selected if c.get("catalog_snapshot") is not None}
    ):
        lines.append(f"<{id_to_iri(scheme_id)}> a skos:ConceptScheme ;")
        lines.append(f'    dcterms:title "{_turtle_escape(scheme_id)}" .')
        lines.append("")
    for concept in selected:
        scheme_id = str(concept.get("catalog_snapshot", ""))
        lines.append(concept_ttl(concept, id_to_iri(scheme_id)))
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"
