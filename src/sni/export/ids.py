"""IDS 1.0-Export (M7, REQ-701, ADR-0005).

Eine Regel ist abbildbar, wenn jedes Input-Concept UND das
Output-Concept ein vollständiges ``mappings.ifc``-Tupel
(``entity``, ``property_set``, ``base_name``, IFC4) tragen. Alle
übrigen approved Regeln erzeugen einen GapReport
``not_ids_expressible`` (G5: keine Teilabbildung). Das XML wird
handgeschrieben mit ``xml.etree.ElementTree`` (stdlib-only) im
Namespace ``http://standards.buildingsmart.org/IDS`` (Default-Prefix,
wie in den buildingSMART-Beispieldateien).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping, Sequence

from jsonschema.exceptions import ValidationError

from sni.core.schemas import make_validator

IDS_NS = "http://standards.buildingsmart.org/IDS"
IDS_TITLE = "SIA Norm Intelligence - IDS Export"
IFC_VERSION = "IFC4"
IDS_VERSION = "1.0.0"

_GAP_ID_RE = re.compile(r"^GAP-(\d{4})$")


class IdsExportError(ValueError):
    """Export-Request ungültig (unbekannte oder nicht-approved Regel)."""


class IdsValidationError(RuntimeError):
    """Ergebnis nicht schemakonform (interner Fehler)."""


def ifc_mapping(concept: Mapping[str, object] | None) -> tuple[str, str, str] | None:
    """``mappings.ifc`` als (entity, property_set, base_name); sonst None (G5)."""
    if concept is None:
        return None
    mappings: object = concept.get("mappings")
    if not isinstance(mappings, Mapping):
        return None
    ifc: object = mappings.get("ifc")
    if not isinstance(ifc, Mapping):
        return None
    entity: object = ifc.get("entity")
    property_set: object = ifc.get("property_set")
    base_name: object = ifc.get("base_name")
    if not isinstance(entity, str) or not entity:
        return None
    if not isinstance(property_set, str) or not property_set:
        return None
    if not isinstance(base_name, str) or not base_name:
        return None
    return entity, property_set, base_name


def _rule_id(rule: Mapping[str, object]) -> str:
    rule_id: object = rule.get("id")
    return rule_id if isinstance(rule_id, str) else "<unbekannt>"


def _is_approved(rule: Mapping[str, object]) -> bool:
    """G3: nur freigegebene Regeln werden exportiert."""
    return rule.get("review_status") == "approved"


def _declared_output_concept(rule: Mapping[str, object]) -> str | None:
    output: object = rule.get("output")
    if isinstance(output, Mapping):
        concept = output.get("concept")
        if isinstance(concept, str):
            return concept
    return None


def _concepts_of_rule(rule: Mapping[str, object]) -> list[str]:
    """Input- plus Output-Concepts der Regel (Deklarationsreihenfolge, dedupliziert)."""
    concepts: list[str] = []
    raw_inputs: object = rule.get("inputs")
    if isinstance(raw_inputs, list):
        for item in raw_inputs:
            if isinstance(item, Mapping):
                concept = item.get("concept")
                if isinstance(concept, str) and concept not in concepts:
                    concepts.append(concept)
    output_concept = _declared_output_concept(rule)
    if output_concept is not None and output_concept not in concepts:
        concepts.append(output_concept)
    return concepts


def _problem_concepts(
    rule: Mapping[str, object], concept_by_id: Mapping[str, Mapping[str, object]]
) -> list[str]:
    """Concepts ohne vollständiges ifc-Mapping (oder nicht im Katalog)."""
    return [
        concept_id
        for concept_id in _concepts_of_rule(rule)
        if ifc_mapping(concept_by_id.get(concept_id)) is None
    ]


def _select_rules(
    rules: Sequence[Mapping[str, object]], rule_ids: Sequence[str] | None
) -> list[Mapping[str, object]]:
    if rule_ids is None:
        return sorted((rule for rule in rules if _is_approved(rule)), key=_rule_id)
    by_id = {_rule_id(rule): rule for rule in rules}
    available = ", ".join(sorted(by_id)) or "(keine)"
    selected: list[Mapping[str, object]] = []
    seen: set[str] = set()
    for rule_id in rule_ids:
        if rule_id in seen:
            continue
        seen.add(rule_id)
        rule = by_id.get(rule_id)
        if rule is None:
            raise IdsExportError(f"Regel {rule_id!r} nicht gefunden (vorhanden: {available})")
        if not _is_approved(rule):
            status: object = rule.get("review_status")
            raise IdsExportError(f"Regel {rule_id!r} nicht approved (review_status={status!r}, G3)")
        selected.append(rule)
    return sorted(selected, key=_rule_id)


def _gap_reports(
    unmapped: Sequence[tuple[Mapping[str, object], list[str]]],
    existing_gap_ids: Iterable[str],
) -> list[dict[str, object]]:
    next_free = _next_gap_number(existing_gap_ids)
    gaps: list[dict[str, object]] = []
    for rule, problems in unmapped:
        rule_id = _rule_id(rule)
        gaps.append(
            {
                "id": f"GAP-{next_free:04d}",
                "gap_type": "not_ids_expressible",
                "target_layer": "mapping",
                "description": (
                    f"Regel nicht in IDS abbildbar (fehlendes oder unvollständiges "
                    f"ifc-Mapping): {', '.join(problems)}"
                ),
                "evidence": [rule_id],
                "priority": "medium",
                "status": "open",
            }
        )
        next_free += 1
    return gaps


def _next_gap_number(existing: Iterable[str]) -> int:
    """Eine Nummer höher als die höchste vorhandene GAP-####-ID (M2-Muster)."""
    highest = 0
    for raw in existing:
        match = _GAP_ID_RE.fullmatch(raw)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def _validate_gaps(gaps: list[dict[str, object]]) -> None:
    """DoD (AGENTS.md §6): GapReports müssen gegen das Schema validieren."""
    validator = make_validator("gap_report.schema.json")
    for gap in gaps:
        try:
            validator.validate(gap)
        except ValidationError as exc:
            raise IdsValidationError(
                f"GapReport nicht schemakonform: {gap.get('id')}: {exc.message}"
            ) from exc


def _spec_description(rule: Mapping[str, object], disclaimer: str) -> str:
    expression: object = rule.get("expression")
    expression_text = expression if isinstance(expression, str) else ""
    derived: object = rule.get("derived_from")
    refs: list[str] = []
    if isinstance(derived, list):
        refs = [ref for ref in derived if isinstance(ref, str)]
    parts = [f"expression: {expression_text}"]
    if refs:
        parts.append(f"Fundstelle: {', '.join(refs)}")
    parts.append(disclaimer)
    return "; ".join(parts)


def _spec_instructions(rule: Mapping[str, object]) -> str:
    applicability: object = rule.get("applicability")
    text = applicability if isinstance(applicability, str) else ""
    return f"applicability: {text}"


def _ids_xml(
    rules: Sequence[Mapping[str, object]],
    concept_by_id: Mapping[str, Mapping[str, object]],
    disclaimer: str,
) -> str:
    ET.register_namespace("", IDS_NS)
    root = ET.Element(f"{{{IDS_NS}}}ids")
    info = ET.SubElement(root, f"{{{IDS_NS}}}info")
    ET.SubElement(info, f"{{{IDS_NS}}}title").text = IDS_TITLE
    ET.SubElement(info, f"{{{IDS_NS}}}version").text = IDS_VERSION
    ET.SubElement(
        info, f"{{{IDS_NS}}}description"
    ).text = f"IDS-Spezifikationen für Regeln von {IDS_TITLE}. {disclaimer}"
    specifications = ET.SubElement(root, f"{{{IDS_NS}}}specifications")
    for rule in rules:
        rule_id = _rule_id(rule)
        spec = ET.SubElement(
            specifications,
            f"{{{IDS_NS}}}specification",
            {
                "ifcVersion": IFC_VERSION,
                "name": rule_id,
                "identifier": rule_id,
                "description": _spec_description(rule, disclaimer),
                "instructions": _spec_instructions(rule),
            },
        )
        output_concept = _declared_output_concept(rule)
        output_mapping = ifc_mapping(concept_by_id.get(output_concept)) if output_concept else None
        if output_mapping is None:
            raise IdsValidationError(f"Regel {rule_id!r} ohne ifc-Mapping des Outputs (intern)")
        applicability = ET.SubElement(spec, f"{{{IDS_NS}}}applicability")
        entity = ET.SubElement(applicability, f"{{{IDS_NS}}}entity")
        ET.SubElement(entity, f"{{{IDS_NS}}}name").text = output_mapping[0]
        requirements = ET.SubElement(spec, f"{{{IDS_NS}}}requirements")
        for concept_id in _concepts_of_rule(rule):
            mapping = ifc_mapping(concept_by_id.get(concept_id))
            if mapping is None:
                raise IdsValidationError(
                    f"Regel {rule_id!r} ohne ifc-Mapping für '{concept_id}' (intern)"
                )
            property_el = ET.SubElement(requirements, f"{{{IDS_NS}}}property")
            ET.SubElement(property_el, f"{{{IDS_NS}}}propertySet").text = mapping[1]
            ET.SubElement(property_el, f"{{{IDS_NS}}}baseName").text = mapping[2]
            ET.SubElement(property_el, f"{{{IDS_NS}}}cardinality", {"value": "required"})
    xml_bytes = ET.tostring(root, encoding="UTF-8", xml_declaration=True)
    if not isinstance(xml_bytes, bytes):
        raise IdsValidationError("Unerwarteter Serialisierungs-Typ (intern)")
    return xml_bytes.decode("utf-8")


def export_ids(
    rules: Sequence[Mapping[str, object]],
    concept_by_id: Mapping[str, Mapping[str, object]],
    rule_ids: Sequence[str] | None = None,
    disclaimer: str = "",
    existing_gap_ids: Iterable[str] = (),
) -> dict[str, object]:
    """Approved Regeln als IDS 1.0-Dokument exportieren (ADR-0005, Punkt 5).

    ``rules``: Regel-Objekte (wie von ``sni.rules.engine.load_rules``
    geladen). ``concept_by_id``: Concept-IDs des Katalogs. ``rule_ids``:
    explizite Auswahl; ``None`` = alle approved Regeln (G3).
    ``existing_gap_ids``: bereits vergebene GAP-IDs (Fortzählung).

    Wirft ``IdsExportError`` bei unbekannten oder nicht-approved
    Regeln und ``IdsValidationError``, wenn ein erzeugter GapReport
    nicht schemakonform ist. Liefert ``{"ids_xml": str | None,
    "gaps": [...], "disclaimer": ...}``; ``ids_xml`` ist ``None``,
    wenn keine Regel abbildbar ist (IDS verlangt mindestens eine
    Specification).
    """
    selected = _select_rules(rules, rule_ids)
    mappable: list[Mapping[str, object]] = []
    unmapped: list[tuple[Mapping[str, object], list[str]]] = []
    for rule in selected:
        problems = _problem_concepts(rule, concept_by_id)
        if problems:
            unmapped.append((rule, problems))
        else:
            mappable.append(rule)
    gaps = _gap_reports(unmapped, existing_gap_ids)
    _validate_gaps(gaps)
    ids_xml = _ids_xml(mappable, concept_by_id, disclaimer) if mappable else None
    return {"ids_xml": ids_xml, "gaps": gaps, "disclaimer": disclaimer}
