"""Antwort-Service: Normfragen -> schemakonforme Answers (M4, REQ-400/401/403).

Deterministische Pipeline (03_ARCHITECTURE.md, "deterministisch vor generativ"):
1. Frage -> relevante Concepts (strukturiertes Matching auf Concept-IDs und
   deutsche Namen, umlautunabhängig; kein Vektor)
2. Projektdaten vorhanden und genau eine approved Rule ausführbar ->
   Regel-Engine (M3) -> ``abgeleitet``
3. Sonst: passende approved NormStatements -> ``normativ_belegt``
4. Kein Beleg, Regel nicht ausführbar, Widerspruch oder Verifier-Fehler ->
   ``nicht_eindeutig`` (G5: im Zweifel die schwächere Klasse)

Kein LLM in v1: Der Antworttext wird deterministisch aus approved Objekten
generiert (G1: keine erfundenen Norminhalte). Der Verifier (REQ-401) prüft
jede Behauptung gegen die Wissensbasis und stuft bei Fehlschlag herab.
REQ-403: Jede Antwort trägt Fundstellen (Norm + Ausgabe + Ziffer) oder eine
begründete Enthaltung (``missing_information``).
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass

from jsonschema.exceptions import ValidationError

from sni.catalog.store import ConceptStore
from sni.core.schemas import make_validator
from sni.knowledge.store import KnowledgeBase
from sni.rules.engine import InputValue, evaluate

CLASS_NORMATIV_BELEGT = "normativ_belegt"
CLASS_ABGELEITET = "abgeleitet"
CLASS_NICHT_EINDEUTIG = "nicht_eindeutig"

DISCLAIMER = (
    "Keine Rechtsauskunft. Grundlage: freigegebene Objekte der Wissensbasis "
    "(data/extracted/); nicht freigegebene Objekte werden nie zitiert."
)


class AnswerError(ValueError):
    """Antwort konnte nicht gebaut oder nicht als schemakonform validiert werden."""


class AnswerInputError(ValueError):
    """Ungültige Projektdaten (REQ-400)."""


@dataclass(frozen=True)
class AnswerRequest:
    """Eingabe des Antwort-Service: Frage plus optionale Projektdaten.

    ``project_data``: Concept-ID -> ``{"value": Zahl, "unit": "..."}``.
    """

    question: str
    project_data: Mapping[str, Mapping[str, object]] | None = None


def answer(
    request: AnswerRequest,
    kb: KnowledgeBase,
    catalog: ConceptStore,
) -> dict[str, object]:
    """Baut eine schemakonforme Answer (REQ-400) mit Verifier (REQ-401)."""
    question = request.question.strip()
    if not question:
        raise AnswerError("Frage fehlt oder ist leer")
    inputs = _to_input_values(request.project_data)
    matched = _match_concepts(question, catalog)
    if request.project_data:
        rule_draft = _rule_path(kb, inputs, matched)
        if rule_draft is not None:
            return _finalize(question, rule_draft, kb)
    return _finalize(question, _statement_path(kb, matched), kb)


def verify_answer(draft: dict[str, object], kb: KnowledgeBase) -> dict[str, object]:
    """REQ-401: prüft jede Behauptung gegen die Wissensbasis.

    Eine Behauptung ist verifiziert nur, wenn alle IDs in ``supported_by``
    existieren und ``approved`` sind (G3). Fundstellen von
    ``normativ_belegt``/``abgeleitet`` müssen von approved NormStatements
    stammen; ``normativ_belegt`` verlangt zusätzlich ``source.verified``
    (04_DATA_MODEL.md). Scheitert die Prüfung, wird die Klasse auf
    ``nicht_eindeutig`` herabgestuft (G5).
    """
    final = dict(draft)
    problems: list[str] = []
    approved_sources: list[str] = []
    claims_out: list[dict[str, object]] = []
    raw_claims: object = draft.get("claims", [])
    claims = raw_claims if isinstance(raw_claims, list) else []
    for raw_claim in claims:
        if not isinstance(raw_claim, dict):
            claims_out.append({"claim": "", "supported_by": [], "verified": False})
            problems.append("Behauptung ist kein gültiges Objekt")
            continue
        claim_text: object = raw_claim.get("claim", "")
        raw_supported: object = raw_claim.get("supported_by", [])
        supported_list = raw_supported if isinstance(raw_supported, list) else []
        supported = [s for s in supported_list if isinstance(s, str)]
        verified = bool(supported)
        for obj_id in supported:
            obj = kb.object(obj_id)
            if obj is None:
                verified = False
                problems.append(f"Behauptung referenziert unbekanntes Objekt: {obj_id}")
            elif obj.get("review_status") != "approved":
                verified = False
                problems.append(f"Behauptung referenziert nicht freigegebenes Objekt: {obj_id}")
            else:
                source = obj.get("source")
                if isinstance(source, dict):
                    approved_sources.append(_canon(source))
        claims_out.append(
            {
                "claim": claim_text if isinstance(claim_text, str) else "",
                "supported_by": supported,
                "verified": verified,
            }
        )
    final["claims"] = claims_out

    answer_class: object = draft.get("answer_class")
    if answer_class in (CLASS_NORMATIV_BELEGT, CLASS_ABGELEITET):
        raw_sources: object = draft.get("sources", [])
        sources = raw_sources if isinstance(raw_sources, list) else []
        source_ok = bool(sources)
        for source in sources:
            if not isinstance(source, dict) or _canon(source) not in approved_sources:
                source_ok = False
                problems.append("Fundstelle stammt nicht von einem freigegebenen Beleg")
                break
        if answer_class == CLASS_NORMATIV_BELEGT:
            for source in sources:
                if not isinstance(source, dict) or source.get("verified") is not True:
                    source_ok = False
                    problems.append(
                        "normativ_belegt verlangt verifizierte Fundstellen (source.verified)"
                    )
                    break
        claims_verified = bool(claims_out) and all(c["verified"] is True for c in claims_out)
        if not (source_ok and claims_verified):
            final["answer_class"] = CLASS_NICHT_EINDEUTIG
            problems.append("Verifier: nicht alle Behauptungen belegt -> nicht_eindeutig (G5)")
    if problems:
        raw_missing: object = draft.get("missing_information", [])
        missing_list = raw_missing if isinstance(raw_missing, list) else []
        missing = [m for m in missing_list if isinstance(m, str)]
        missing.extend(problems)
        final["missing_information"] = missing
        final["text"] = "Antwort wurde vom Verifier herabgestuft: " + "; ".join(problems) + "."
    return final


def _finalize(question: str, draft: dict[str, object], kb: KnowledgeBase) -> dict[str, object]:
    draft["question"] = question
    draft["disclaimer"] = DISCLAIMER
    final = verify_answer(draft, kb)
    _check_source_or_abstention(final)
    try:
        make_validator("answer.schema.json").validate(final)
    except ValidationError as exc:
        raise AnswerError(f"Antwort nicht schemakonform: {exc.message}") from exc
    return final


def _check_source_or_abstention(final: dict[str, object]) -> None:
    """REQ-403: jede Antwort enthält Norm + Ausgabe + Ziffer oder begründete Enthaltung."""
    raw_sources: object = final.get("sources", [])
    sources = raw_sources if isinstance(raw_sources, list) else []
    raw_missing: object = final.get("missing_information", [])
    missing = raw_missing if isinstance(raw_missing, list) else []
    if sources:
        for source in sources:
            if not isinstance(source, dict):
                raise AnswerError("Fundstelle ist kein gültiges Objekt (REQ-403)")
            for field_name in ("norm", "edition", "clause"):
                value: object = source.get(field_name, "")
                if not isinstance(value, str) or not value.strip():
                    raise AnswerError(f"Fundstelle ohne {field_name} (REQ-403)")
    elif not missing:
        raise AnswerError("Weder Fundstelle noch begründete Enthaltung (REQ-403)")


def _draft(
    answer_class: str,
    text: str,
    claims: list[dict[str, object]],
    sources: list[dict[str, object]],
    missing_information: list[str] | None = None,
) -> dict[str, object]:
    return {
        "answer_class": answer_class,
        "text": text,
        "claims": claims,
        "sources": sources,
        "missing_information": missing_information or [],
    }


def _abstain(reason: str, details: list[str] | None = None) -> dict[str, object]:
    return _draft(
        CLASS_NICHT_EINDEUTIG,
        f"Nicht eindeutig beantwortbar: {reason}",
        [],
        [],
        [reason, *(details or [])],
    )


def _rule_path(
    kb: KnowledgeBase, inputs: Mapping[str, InputValue], matched: list[str]
) -> dict[str, object] | None:
    """Wählt die Regel für Projektdaten aus; None = Statement-Pfad."""
    executable = sorted(
        rule_id
        for rule_id, rule in kb.rules.items()
        if _is_approved(rule) and set(_required_input_concepts(rule)) <= set(inputs)
    )
    if len(executable) > 1:
        return _abstain(
            "Mehrere approved Regeln sind mit den Projektdaten ausführbar (mehrdeutig)."
        )
    if len(executable) == 1:
        return _evaluate_rule(kb, executable[0], inputs)
    relevant = sorted(
        rule_id
        for rule_id, rule in kb.rules.items()
        if _is_approved(rule) and set(_rule_concepts(rule)) & set(matched)
    )
    if not relevant:
        return None
    if len(relevant) == 1:
        rule_id = relevant[0]
        missing = [c for c in _required_input_concepts(kb.rules[rule_id]) if c not in inputs]
        return _abstain(
            f"Projektdaten für Regel {rule_id} sind unvollständig.",
            [f"Fehlender Projektwert: {concept}" for concept in missing],
        )
    return _abstain(
        "Mehrere approved Regeln passen zur Frage, aber keine ist vollständig ausführbar."
    )


def _evaluate_rule(
    kb: KnowledgeBase, rule_id: str, inputs: Mapping[str, InputValue]
) -> dict[str, object]:
    rule = kb.rules[rule_id]
    result = evaluate(rule, inputs)
    if result.status == "ok":
        supports: list[str] = [rule_id]
        sources: list[dict[str, object]] = []
        derived_from: object = rule.get("derived_from")
        if isinstance(derived_from, list):
            for ref in derived_from:
                if isinstance(ref, str) and ref in kb.statements:
                    supports.append(ref)
                    source = _source_of(kb.statements[ref])
                    if source is not None:
                        sources.append(source)
        value_text = f"{result.value:g} {result.unit or ''}".strip()
        claim = f"Berechneter Wert: {value_text} (Regel {rule_id})"
        text = f"Berechnet nach approved Regel {rule_id}: {value_text}."
        return _draft(
            CLASS_ABGELEITET,
            text,
            [{"claim": claim, "supported_by": supports, "verified": True}],
            sources,
        )
    if result.status == "insufficient_data":
        return _abstain(
            f"Projektdaten für Regel {rule_id} sind unvollständig.",
            [f"Fehlender Projektwert: {concept}" for concept in result.missing_inputs],
        )
    return _abstain(
        f"Regelauswertung von {rule_id} fehlgeschlagen.",
        [f"Regel {rule_id}: {line}" for line in result.report],
    )


def _statement_path(kb: KnowledgeBase, matched: list[str]) -> dict[str, object]:
    matched_set = set(matched)
    approved = sorted(
        statement_id
        for statement_id, statement in kb.statements.items()
        if _is_approved(statement) and set(_statement_concepts(statement)) & matched_set
    )
    if approved:
        claims: list[dict[str, object]] = []
        sentences: list[str] = []
        sources: list[dict[str, object]] = []
        for statement_id in approved:
            statement = kb.statements[statement_id]
            source = _source_of(statement)
            summary: object = statement.get("summary", "")
            norm: object = source.get("norm") if source is not None else "?"
            edition: object = source.get("edition") if source is not None else "?"
            clause: object = source.get("clause") if source is not None else "?"
            prefix = f"Gemäss {norm} ({edition}), Ziffer {clause}:"
            sentence = (
                f"{prefix} {summary}" if isinstance(summary, str) and summary else f"{prefix}"
            )
            claims.append({"claim": sentence, "supported_by": [statement_id], "verified": True})
            sentences.append(sentence)
            if source is not None:
                sources.append(source)
        return _draft(CLASS_NORMATIV_BELEGT, " ".join(sentences) + ".", claims, sources)
    non_approved = sorted(
        statement_id
        for statement_id, statement in kb.statements.items()
        if not _is_approved(statement) and set(_statement_concepts(statement)) & matched_set
    )
    if non_approved:
        return _abstain(
            "Passende NormStatements existieren, sind aber nicht freigegeben "
            "(review_status nicht approved) – kein belastbarer Beleg."
        )
    if matched:
        return _abstain(
            f"Kein approved NormStatement für die passenden Konzepte ({', '.join(matched)})."
        )
    return _abstain("Kein Konzept im Katalog passt zur Frage.")


def _match_concepts(question: str, catalog: ConceptStore) -> list[str]:
    """Strukturiertes Matching: Concept-Slug oder deutscher Name (Glossar)."""
    normalized_question = _normalize(question)
    matched: list[str] = []
    for concept_id in catalog.concept_ids():
        concept = catalog.get_concept(concept_id)
        if concept is None:
            continue
        slug = concept_id.rsplit("/", 1)[-1]
        if _contains(normalized_question, slug):
            matched.append(concept_id)
            continue
        name: object = concept.get("name")
        name_de: object = name.get("de") if isinstance(name, dict) else None
        if isinstance(name_de, str) and _contains(normalized_question, _normalize(name_de)):
            matched.append(concept_id)
    return matched


def _normalize(text: str) -> str:
    """Kleinschreibung ohne Umlaute (NFD-Zerlegung) für umlautunabhängiges Matching."""
    decomposed = unicodedata.normalize("NFD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _contains(haystack: str, needle: str) -> bool:
    """Wortbegrenztes Matching (mind. 3 Zeichen, keine Teiltreffer in Komposita)."""
    if len(needle) < 3:
        return False
    pattern = r"(?<![a-z0-9_])" + re.escape(needle) + r"(?![a-z0-9])"
    return re.search(pattern, haystack) is not None


def _to_input_values(
    project_data: Mapping[str, Mapping[str, object]] | None,
) -> dict[str, InputValue]:
    if project_data is None:
        return {}
    inputs: dict[str, InputValue] = {}
    for concept_id, raw in project_data.items():
        value: object = raw.get("value")
        unit: object = raw.get("unit")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise AnswerInputError(f"Projektwert {concept_id}: 'value' muss eine Zahl sein")
        if not isinstance(unit, str) or not unit.strip():
            raise AnswerInputError(
                f"Projektwert {concept_id}: 'unit' muss eine nicht leere Zeichenkette sein"
            )
        inputs[concept_id] = InputValue(float(value), unit)
    return inputs


def _is_approved(obj: Mapping[str, object]) -> bool:
    return obj.get("review_status") == "approved"


def _required_input_concepts(rule: Mapping[str, object]) -> list[str]:
    raw: object = rule.get("inputs")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        concept: object = item.get("concept")
        required: object = item.get("required", True)
        if isinstance(concept, str) and required is not False:
            out.append(concept)
    return out


def _rule_concepts(rule: Mapping[str, object]) -> list[str]:
    raw: object = rule.get("inputs")
    out: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and isinstance(item.get("concept"), str):
                out.append(str(item.get("concept")))
    output: object = rule.get("output")
    if isinstance(output, dict) and isinstance(output.get("concept"), str):
        out.append(str(output.get("concept")))
    return out


def _statement_concepts(statement: Mapping[str, object]) -> list[str]:
    raw: object = statement.get("concepts")
    if not isinstance(raw, list):
        return []
    return [c for c in raw if isinstance(c, str)]


def _source_of(obj: Mapping[str, object]) -> dict[str, object] | None:
    source: object = obj.get("source")
    return source if isinstance(source, dict) else None


def _canon(source: Mapping[str, object]) -> str:
    return json.dumps(dict(source), sort_keys=True, ensure_ascii=False)
