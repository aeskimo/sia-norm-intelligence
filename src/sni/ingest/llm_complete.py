"""Stufe 3 (M13, ADR-0010): LLM-gestuetzte Vervollstaendigung der Fachfelder.

Voraussetzung: ADR-0003 (akzeptiert, 2026-11-26) — ausschliesslich
freigegebene Modelle/Endpunkte, Konfiguration ueber die
Umgebungsvariablen ``SNI_LLM_ENDPOINT`` (Basis-URL des
OpenAI-kompatiblen Endpunkts, z. B. ``https://chat.gibb.ch/api``),
``SNI_LLM_MODEL`` (Modell-ID) und ``SNI_LLM_API_KEY`` (Bearer-Schluessel;
Fallback: Keychain-Account ``gibb-api-key``, dieselbe opt-in-Ablage wie
die Einstellungen-UI).

Ablauf (``make llm NORM=<norm-id>``):
- Input: ``document.draft.json`` (Stufe 1, lokale Extraktion); pro Ziffer
  wird ausschliesslich der lokal extrahierte Ziffern-Text an den
  konfigurierten Endpunkt gesendet (REQ-1301: der Normtext verlaesst die
  lokale Umgebung nur Richtung dieses Endpunkts).
- Vorschlaege des Modells: Aussageklasse (``statement_type``), Obligation,
  Zusammenfassung (eigene, kein Normzitat) und Concepts (nur IDs aus dem
  vorgelegten Katalog).
- Output: ``document.llm.json`` im Norm-Verzeichnis — ein Vorschlag im
  document.json-Format, validiert gegen den document.json-Vertrag
  (Ingest-Pipeline gegen eine temporäre Queue). ``document.json`` wird
  vom Tool nie angefasst (G3: die Uebernahme als ``document.json`` bleibt
  ein menschlicher Akt; danach ``make ingest``).

Guardrails:
- G1: das Modell darf nichts ausserhalb des vorgelegten Texts belegen —
  Aussageklasse/Obligation werden gegen die Schema-Enums geprueft,
  Concepts gegen den Katalog (unbekannte ID = Erfindung → Fehler).
  Ziffern ohne Text erhalten keine Vorschlaege; bereits manuell
  vollstaendig belegte Ziffern ueberschreibt das Tool nicht.
- G3: nur Vorschlag, keine Freigabe; nichts wird als ``document.json``
  geschrieben, die echte Review Queue bleibt unberuehrt.
- G4: Fehlerbericht und CLI-Ausgabe enthalten nur Norm-ID, Ziffern,
  Feldnamen, Concept-IDs und Zaehlungen — nie Ziffern- oder
  Zusammenfassungstexte.
- KBOB: alle Fehler werden gesammelt (auch Modellanfrage-Fehler: HTTP-
  Status, Netzwerk); bei Fehlern wird nichts geschrieben.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

import httpx

from sni.catalog.store import ConceptStore
from sni.core.schemas import load_schema, make_validator
from sni.ingest.pipeline import (
    _SAFE_ID_RE,
    IngestError,
    default_norms_dir,
    ingest_document,
)
from sni.rag.providers.gibb import OpenAiCompatibleProvider
from sni.secrets.keyring_store import GibbApiKeyStore

#: Name des Vorschlags im Mount-Verzeichnis ``data/norms/<norm-id>/``.
PROPOSAL_FILENAME = "document.llm.json"
#: Name des Stufen-1-Entwurfs (wie ``sni.ingest.pdf_extract.DRAFT_FILENAME``).
DRAFT_FILENAME = "document.draft.json"

#: Umgebungsvariablen (ADR-0003: Konfiguration ueber ``SNI_LLM_ENDPOINT``).
ENV_ENDPOINT = "SNI_LLM_ENDPOINT"
ENV_MODEL = "SNI_LLM_MODEL"
ENV_API_KEY = "SNI_LLM_API_KEY"


class LlmCompleteError(RuntimeError):
    """Stufe 3 fehlgeschlagen; ``report`` enthaelt alle gesammelten Fehler."""

    def __init__(self, report: list[str]) -> None:
        super().__init__("; ".join(report))
        self.report = report


@dataclass(frozen=True)
class LlmCompleteResult:
    """Ergebnis eines Stufe-3-Laufs."""

    norm_id: str
    #: Ziffern, fuer die das Modell Fachfelder vorgeschlagen hat.
    clauses_suggested: int
    #: Ziffern, die bereits manuell vollstaendig belegt waren (uebernommen).
    clauses_kept: int
    #: Geschriebene Vorschlagsdatei (``document.llm.json``).
    proposal_path: Path


@dataclass(frozen=True)
class CompletedDraft:
    """``complete_draft``-Ergebnis: document.json-Vorschlag + Zaehler."""

    document: dict[str, object]
    clauses_suggested: int
    clauses_kept: int


class LlmClient(Protocol):
    """Chat-Endpunkt-Abstraktion fuer Tests (Implementierung:
    :class:`sni.rag.providers.gibb.OpenAiCompatibleProvider`)."""

    def generate(self, system: str, prompt: str) -> str | None: ...


_SYSTEM_PROMPT = (
    "Du bist ein Experte fuer SIA-Normen. Belege ausschliesslich auf Grundlage "
    "des vorgelegten Ziffern-Textes die Fachfelder der Ziffer. Erfinde nichts, "
    "was nicht im Text steht. Antworte ausschliesslich mit einem JSON-Objekt "
    '(kein anderer Text) mit den Feldern "statement_type" (Aussageklasse), '
    '"obligation" (Obligation), "summary" (eigene Zusammenfassung, kein '
    'Normzitat) und "concepts" (JSON-Array mit Concept-IDs aus dem '
    "vorgelegten Katalog; leeres Array, wenn kein Konzept passt)."
)


def load_draft(norm_id: str, norms_dir: Path | None = None) -> dict[str, object]:
    """Lädt ``document.draft.json`` (Stufe 1) und validiert es (G4)."""
    if norms_dir is None:
        norms_dir = default_norms_dir()
    if not _SAFE_ID_RE.fullmatch(norm_id) or ".." in norm_id:
        raise LlmCompleteError(
            [f"Ungültige Norm-ID {norm_id!r} (erlaubt: Buchstaben, Ziffern, '.', '_', '-')"]
        )
    path = norms_dir / norm_id / DRAFT_FILENAME
    if not path.is_file():
        raise LlmCompleteError(
            [f"Entwurf nicht gefunden: {path} (erst: make extract NORM={norm_id})"]
        )
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LlmCompleteError([f"Entwurf {path.name} ist kein gültiges JSON: {exc}"]) from exc
    if not isinstance(raw, dict):
        raise LlmCompleteError([f"Entwurf {path.name} muss ein JSON-Objekt sein"])
    doc_id: object = raw.get("norm_id")
    if not isinstance(doc_id, str) or doc_id != norm_id:
        raise LlmCompleteError(
            [f"Norm-ID im Entwurf ({doc_id!r}) passt nicht zum Mount-Verzeichnis ({norm_id!r})"]
        )
    for error in make_validator("document_draft.schema.json").iter_errors(raw):
        where = "/".join(str(part) for part in error.absolute_path)
        raise LlmCompleteError(
            [f"Entwurf {path.name}: ungültig ({where or 'Dokument'}: {error.message})"]
        )
    return raw


def complete_draft(
    draft: dict[str, object],
    catalog: ConceptStore,
    client: LlmClient,
) -> CompletedDraft:
    """Erzeugt aus dem Entwurf den document.json-Vorschlag (KBOB).

    Wirft :class:`LlmCompleteError` mit allen gesammelten Fehlern, wenn der
    Vorschlag nicht erzeugt werden kann.
    """
    statement_schema = load_schema("norm_statement.schema.json")
    allowed_types = _enum_values(statement_schema, "statement_type")
    allowed_obligations = _enum_values(statement_schema, "obligation")

    errors: list[str] = []
    norm_id_raw: object = draft.get("norm_id")
    if not isinstance(norm_id_raw, str) or not norm_id_raw:
        errors.append("Entwurf: Feld 'norm_id' fehlt oder ist leer")
    norm = _identity_field(draft, "norm", errors)
    edition = _identity_field(draft, "edition", errors)
    clauses_raw: object = draft.get("clauses")
    if not isinstance(clauses_raw, list) or not clauses_raw:
        errors.append("Entwurf: Feld 'clauses' fehlt oder ist leer")
        clauses_raw = []

    catalog_lines = _catalog_lines(catalog)
    out_clauses: list[dict[str, object]] = []
    suggested = 0
    kept = 0
    for index, clause_raw in enumerate(clauses_raw):
        label = f"clauses[{index}]"
        if not isinstance(clause_raw, dict):
            errors.append(f"{label}: kein JSON-Objekt")
            continue
        number = _str_field(clause_raw, "number", f"{label} (Ziffer)", errors)
        if number is None:
            continue
        unit = _complete_unit(
            f"Ziffer {number}",
            clause_raw,
            client,
            catalog,
            catalog_lines,
            allowed_types,
            allowed_obligations,
            errors,
        )
        if unit is None:
            continue
        fields, was_suggested = unit
        suggested += 1 if was_suggested else 0
        kept += 0 if was_suggested else 1
        clause_out: dict[str, object] = {"number": number, **fields}
        for sub_key in ("tables", "formulas"):
            subs_raw: object = clause_raw.get(sub_key)
            if subs_raw is None:
                continue
            if not isinstance(subs_raw, list):
                errors.append(f"Ziffer {number}: Feld '{sub_key}' ist keine Liste")
                continue
            subs_out: list[dict[str, object]] = []
            sub_kind = "Tabelle" if sub_key == "tables" else "Formel"
            for sub_index, sub_raw in enumerate(subs_raw):
                sub_label = f"Ziffer {number}: {sub_key}[{sub_index}]"
                if not isinstance(sub_raw, dict):
                    errors.append(f"{sub_label}: kein JSON-Objekt")
                    continue
                sub_number = _str_field(sub_raw, "number", sub_label, errors)
                if sub_number is None:
                    continue
                before = len(errors)
                sub_fields = _human_fields_only(
                    sub_label,
                    sub_raw,
                    allowed_types,
                    allowed_obligations,
                    errors,
                )
                if sub_fields is None:
                    if len(errors) <= before:
                        # v1: LLM verarbeitet ausschliesslich Ziffern; eine
                        # nicht belegte Tabelle/Formel darf nicht
                        # verschwinden (G1: kein stiller Inhalt-Verlust).
                        errors.append(
                            f"{sub_label} ({sub_kind} {sub_number}): Fachfelder "
                            "nicht belegt — manuell belegen (Stufe 2); das "
                            "LLM-Tool verarbeitet v1 nur Ziffern"
                        )
                    continue
                subs_out.append({"number": sub_number, **sub_fields})
            clause_out[sub_key] = subs_out
        out_clauses.append(clause_out)

    if errors or norm is None or edition is None or not isinstance(norm_id_raw, str):
        raise LlmCompleteError(errors or ["Unerwarteter interner Zustand"])
    return CompletedDraft(
        document={
            "norm": norm,
            "norm_id": norm_id_raw,
            "edition": edition,
            "clauses": out_clauses,
        },
        clauses_suggested=suggested,
        clauses_kept=kept,
    )


def run_llm_complete(
    norm_id: str,
    norms_dir: Path,
    catalog_db: Path,
    env: Mapping[str, str],
    *,
    client: LlmClient | None = None,
) -> LlmCompleteResult:
    """Führt Stufe 3 aus: Entwurf → LLM-Vorschlag → ``document.llm.json``.

    ``client=None`` → Provider aus den Umgebungsvariablen (REQ-1301).
    Der Vorschlag wird erst geschrieben, wenn er gegen den
    document.json-Vertrag validiert ist (Ingest gegen temporäre Queue).
    """
    if client is None:
        client = _provider_from_env(env)
    catalog = ConceptStore(catalog_db)
    try:
        draft = load_draft(norm_id, norms_dir)
        completed = complete_draft(draft, catalog, client)
        _validate_against_contract(completed.document, catalog)
    except IngestError as exc:
        raise LlmCompleteError(exc.report) from exc
    finally:
        catalog.close()
    proposal_path = norms_dir / norm_id / PROPOSAL_FILENAME
    proposal_path.write_text(
        json.dumps(completed.document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return LlmCompleteResult(
        norm_id=norm_id,
        clauses_suggested=completed.clauses_suggested,
        clauses_kept=completed.clauses_kept,
        proposal_path=proposal_path,
    )


def _provider_from_env(env: Mapping[str, str]) -> OpenAiCompatibleProvider:
    """REQ-1301: ausschliesslich der konfigurierte (freigegebene) Endpunkt.

    Schluesselaufloesung: ``SNI_LLM_API_KEY``, dann Keychain-Account
    ``gibb-api-key`` (dieselbe opt-in-Ablage wie die Einstellungen-UI).
    Der Provider erzwingt HTTPS (HTTP ausschliesslich Loopback, Tests).
    """
    endpoint = env.get(ENV_ENDPOINT, "").strip()
    if not endpoint:
        raise LlmCompleteError(
            [
                f"{ENV_ENDPOINT} fehlt — freigegebener Endpunkt (ADR-0003) setzen, "
                "z. B. https://chat.gibb.ch/api"
            ]
        )
    model = env.get(ENV_MODEL, "").strip()
    if not model:
        raise LlmCompleteError([f"{ENV_MODEL} fehlt — Modell-ID des Endpunkts setzen"])
    api_key = env.get(ENV_API_KEY, "").strip()
    if not api_key:
        api_key = GibbApiKeyStore().load() or ""
    if not api_key:
        raise LlmCompleteError(
            [
                f"API-Schlüssel fehlt — {ENV_API_KEY} setzen oder Keychain-Account "
                "'gibb-api-key' hinterlegen (Einstellungen)"
            ]
        )
    try:
        return OpenAiCompatibleProvider(endpoint, api_key, model)
    except (PermissionError, ValueError) as exc:
        raise LlmCompleteError([str(exc)]) from exc


def _validate_against_contract(document: dict[str, object], catalog: ConceptStore) -> None:
    """Validiert den Vorschlag gegen den document.json-Vertrag.

    Der autoritative Check ist die Ingest-Pipeline (``ingest_document``);
    sie laeuft gegen eine temporäre Queue, deren Inhalt verworfen wird —
    die echte Review Queue wird von Stufe 3 nie angeruehrt (G3).
    """
    with tempfile.TemporaryDirectory(prefix="sni-llm-") as tmp:
        ingest_document(document, catalog, Path(tmp))


def _catalog_lines(catalog: ConceptStore) -> str:
    """Katalogliste "ID — Name" fuer den Prompt (sortiert nach ID)."""
    lines: list[str] = []
    for concept_id in catalog.concept_ids():
        name = concept_id
        concept = catalog.get_concept(concept_id)
        if isinstance(concept, dict):
            raw_name: object = concept.get("name")
            if isinstance(raw_name, dict):
                de: object = raw_name.get("de")
                if isinstance(de, str) and de:
                    name = de
        lines.append(f"{concept_id} — {name}")
    return "\n".join(lines)


def _user_prompt(
    number: str,
    text: str,
    allowed_types: tuple[str, ...],
    allowed_obligations: tuple[str, ...],
    catalog_lines: str,
) -> str:
    return (
        f"Ziffernnummer: {number}\n"
        f"Ziffern-Text:\n{text}\n\n"
        "Erlaubte Werte:\n"
        f"- statement_type: {' | '.join(allowed_types)}\n"
        f"- obligation: {' | '.join(allowed_obligations)}\n\n"
        "Concept-Katalog (ID — Name):\n"
        f"{catalog_lines}\n\n"
        "Antworte ausschliesslich mit dem JSON-Objekt."
    )


def _complete_unit(
    label: str,
    clause_raw: dict[str, object],
    client: LlmClient,
    catalog: ConceptStore,
    catalog_lines: str,
    allowed_types: tuple[str, ...],
    allowed_obligations: tuple[str, ...],
    errors: list[str],
) -> tuple[dict[str, object], bool] | None:
    """Belegt die Fachfelder einer Ziffer: manuell vollstaendig → uebernehmen,
    sonst LLM-Vorschlag. Liefert (Felder, wurde_vorgeschlagen) oder None."""
    before = len(errors)
    human = _human_fields_only(label, clause_raw, allowed_types, allowed_obligations, errors)
    if human is not None:
        return human, False
    if len(errors) > before:
        # Teilweise/ungültig belegt → Fehler gemeldet; LLM ueberschreibt
        # menschliche Eintraege nicht (G1).
        return None
    text_raw: object = clause_raw.get("text")
    text = text_raw if isinstance(text_raw, str) else ""
    number = str(clause_raw.get("number") or "?")
    if not text.strip():
        errors.append(
            f"{label}: kein extrahierter Text — Vorschlag unmoeglich (G1); "
            "Fachfelder in Stufe 2 manuell belegen"
        )
        return None
    try:
        response = client.generate(
            _SYSTEM_PROMPT,
            _user_prompt(number, text, allowed_types, allowed_obligations, catalog_lines),
        )
    except RuntimeError as exc:
        # gibb.py: RuntimeError mit G4-sicherer Meldung (HTTP-Status, kein Normtext).
        errors.append(f"{label}: {exc}")
        return None
    except httpx.HTTPError as exc:
        errors.append(f"{label}: Netzwerkfehler bei der Modellanfrage ({exc})")
        return None
    if response is None:
        errors.append(f"{label}: Modellantwort enthielt keinen Inhalt")
        return None
    parsed = _parse_json_object(response)
    if parsed is None:
        errors.append(f"{label}: Modellantwort ist kein gültiges JSON-Objekt")
        return None
    fields = _checked_llm_fields(label, parsed, catalog, allowed_types, allowed_obligations, errors)
    if fields is None:
        return None
    return fields, True


def _human_fields_only(
    label: str,
    spec: dict[str, object],
    allowed_types: tuple[str, ...],
    allowed_obligations: tuple[str, ...],
    errors: list[str],
) -> dict[str, object] | None:
    """Prüft, ob die Fachfelder bereits (manuell) vollstaendig belegt sind.

    "Belegt" = nicht leer gesetzt. Vollstaendig und erlaubt → Felder werden
    uebernommen (menschliche Belegung geht vor). Alle vier leer → ``None``
    ohne Fehler (LLM-Pfad). Teilweise belegt oder ungültige Werte → Fehler.
    """
    st: object = spec.get("statement_type")
    obl: object = spec.get("obligation")
    summary: object = spec.get("summary")
    concepts: object = spec.get("concepts")
    st_set = isinstance(st, str) and bool(st.strip())
    obl_set = isinstance(obl, str) and bool(obl.strip())
    summary_set = isinstance(summary, str) and bool(summary.strip())
    concepts_set = isinstance(concepts, list) and len(concepts) > 0
    if not (st_set or obl_set or summary_set or concepts_set):
        return None  # alles leer → LLM-Pfad
    st_valid = st_set and st in allowed_types
    obl_valid = obl_set and obl in allowed_obligations
    concepts_valid = isinstance(concepts, list) and all(isinstance(c, str) and c for c in concepts)
    if st_valid and obl_valid and summary_set and concepts_valid:
        return {
            "statement_type": st,
            "obligation": obl,
            "summary": summary,
            "concepts": cast(list[str], concepts),
        }
    problems: list[str] = []
    if not st_valid:
        problems.append("statement_type")
    if not obl_valid:
        problems.append("obligation")
    if not summary_set:
        problems.append("summary")
    if not concepts_valid:
        problems.append("concepts")
    errors.append(
        f"{label}: Fachfelder teilweise oder ungültig belegt ({', '.join(problems)}) — "
        "vollstaendig manuell (Stufe 2) oder alle Fachfelder leeren, dann "
        "LLM-Vervollstaendigung wiederholen"
    )
    return None


def _checked_llm_fields(
    label: str,
    parsed: dict[str, object],
    catalog: ConceptStore,
    allowed_types: tuple[str, ...],
    allowed_obligations: tuple[str, ...],
    errors: list[str],
) -> dict[str, object] | None:
    """Validiert das Modell-JSON gegen G1 (keine Erfindung) und den Vertrag."""
    st: object = parsed.get("statement_type")
    if not (isinstance(st, str) and st in allowed_types):
        errors.append(
            f"{label}: statement_type fehlt oder ungültig (erlaubt: {', '.join(allowed_types)})"
        )
        return None
    obl: object = parsed.get("obligation")
    if not (isinstance(obl, str) and obl in allowed_obligations):
        errors.append(
            f"{label}: obligation fehlt oder ungültig (erlaubt: {', '.join(allowed_obligations)})"
        )
        return None
    summary: object = parsed.get("summary")
    if not (isinstance(summary, str) and summary.strip()):
        errors.append(f"{label}: summary fehlt oder ist leer")
        return None
    concepts_raw: object = parsed.get("concepts")
    if not isinstance(concepts_raw, list) or not all(
        isinstance(c, str) and c for c in concepts_raw
    ):
        errors.append(f"{label}: 'concepts' ist keine Liste von Concept-IDs")
        return None
    # G1: nur Concept-IDs aus dem Katalog; eine fremde ID ist eine Erfindung.
    unknown = [c for c in concepts_raw if catalog.get_concept(c) is None]
    if unknown:
        errors.append(f"{label}: Concept-ID(s) nicht im Katalog (G1): {', '.join(unknown)}")
        return None
    return {
        "statement_type": st,
        "obligation": obl,
        "summary": summary,
        "concepts": cast(list[str], concepts_raw),
    }


def _parse_json_object(raw: str) -> dict[str, object] | None:
    """Parst das Modell-JSON (toleriert Code-Zaenum und Randtext)."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed: object = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _identity_field(draft: dict[str, object], field: str, errors: list[str]) -> str | None:
    """Normname/Edition: Identitaet ist keine Ziffern-Text-Aussage — das Tool
    rueckt sie nicht nach (G1); sie ist in Stufe 2 manuell zu belegen."""
    value: object = draft.get(field)
    if isinstance(value, str) and value.strip():
        return value
    errors.append(
        f"Entwurf: Feld '{field}' fehlt oder ist leer — manuell belegen (Stufe 2), "
        "dann LLM-Vervollstaendigung wiederholen"
    )
    return None


def _str_field(spec: dict[str, object], field: str, label: str, errors: list[str]) -> str | None:
    value: object = spec.get(field)
    if isinstance(value, str) and value:
        return value
    errors.append(f"{label}: Feld '{field}' fehlt oder ist keine nicht-leere Zeichenkette")
    return None


def _enum_values(schema: dict[str, object], prop: str) -> tuple[str, ...]:
    """Erlaubt-Werte einer Eigenschaft aus dem Schema (Quelle der Wahrheit)."""
    properties: object = schema.get("properties")
    if not isinstance(properties, dict):
        return ()
    prop_spec: object = properties.get(prop)
    if not isinstance(prop_spec, dict):
        return ()
    enum: object = prop_spec.get("enum")
    if not isinstance(enum, list):
        return ()
    return tuple(value for value in enum if isinstance(value, str))
