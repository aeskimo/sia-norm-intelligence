"""GapReports für fehlende Projektdaten (M5, REQ-502).

Fehlende Projektdaten erzeugen GapReport ``missing_project_data``:
pro fehlendem, von Regeln gefordertem Concept genau ein GapReport mit
den Regel-IDs als Evidence (KBOB-Muster: fehlende Daten werden
nachvollziehbar dokumentiert, nie stillschweigend ignoriert).

Die Gap-IDs setzen die höchste bereits vergebene Nummer fort
(``GAP-####``, M2-Muster). Der Aufrufer übergibt die bereits vergebenen
IDs (z. B. aus ``data/review_queue/``); die Zuordnung zu Regeln und
Projektdaten bleibt Schicht ``projectdata``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence

_GAP_ID_RE = re.compile(r"^GAP-(\d{4})$")


def missing_project_data_gaps(
    rules: Sequence[Mapping[str, object]],
    available_concepts: Iterable[str],
    existing_gap_ids: Iterable[str] = (),
) -> list[dict[str, object]]:
    """Erzeugt pro fehlendem Pflicht-Concept einen GapReport (REQ-502).

    ``rules``: Regel-Objekte (wie von ``sni.rules.engine.load_rules``
    geladen, validiert gegen ``rule.schema.json``). ``available_concepts``:
    Concept-IDs, für die Projektdaten geliefert wurden (Adapter-Output,
    REQ-500, bzw. API-Request). Die Herkunft (Provenance) der Werte gehört
    zur Werteseite und fliesst in die GapReports nicht ein.
    """
    available = set(available_concepts)
    needed: dict[str, set[str]] = {}
    for rule in rules:
        rule_id = rule.get("id")
        if not isinstance(rule_id, str):
            continue
        for concept in _required_input_concepts(rule):
            if concept not in available:
                needed.setdefault(concept, set()).add(rule_id)

    next_free = _next_gap_number(existing_gap_ids)
    gaps: list[dict[str, object]] = []
    for concept in sorted(needed):
        rule_ids = sorted(needed[concept])
        gaps.append(
            {
                "id": f"GAP-{next_free:04d}",
                "gap_type": "missing_project_data",
                "target_layer": "projektdaten",
                "description": (
                    f"Keine Projektdaten für '{concept}' geliefert; "
                    f"benötigt von: {', '.join(rule_ids)}"
                ),
                "evidence": rule_ids,
                "priority": "medium",
                "status": "open",
            }
        )
        next_free += 1
    return gaps


def _required_input_concepts(rule: Mapping[str, object]) -> list[str]:
    """Concept-IDs der Pflicht-Inputs einer Regel (``required`` default true)."""
    raw = rule.get("inputs", [])
    if not isinstance(raw, list):
        return []
    concepts: list[str] = []
    for item in raw:
        if not isinstance(item, Mapping) or item.get("required", True) is False:
            continue
        concept = item.get("concept")
        if isinstance(concept, str):
            concepts.append(concept)
    return concepts


def _next_gap_number(existing: Iterable[str]) -> int:
    """Eine Nummer höher als die höchste vorhandene GAP-####-ID."""
    highest = 0
    for raw in existing:
        match = _GAP_ID_RE.fullmatch(raw)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1
