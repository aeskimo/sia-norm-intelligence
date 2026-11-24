"""FastAPI-Endpunkte (M1: GET /v1/concepts/{id}; M4: POST /v1/answer;
M5: POST /v1/check; Integration M3.5: POST /v1/projectdata (ADR-0006);
M7: /v1/export/*).

Fachlogik bleibt in sni.catalog (Katalog), sni.service (Antwort-Pipeline),
sni.projectdata (Projektwerte-Upload, ADR-0006) bzw. sni.export
(Serialisierung, ADR-0005).
Hinweis G6: Jede fachliche API-Antwort trägt das Feld ``disclaimer``.
``/healthz`` ist ein reiner Liveness-Check ohne fachlichen Inhalt.
"""

from __future__ import annotations

import atexit
import json
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from sni.catalog.store import ConceptStore
from sni.export.bcf import BcfExportError, bcf_bytes
from sni.export.ids import IdsExportError, IdsValidationError, export_ids
from sni.export.skos import CatalogExportError, catalog_json, catalog_ttl
from sni.knowledge.store import (
    DEFAULT_KNOWLEDGE_DIR,
    KnowledgeBase,
    KnowledgeLoadError,
    load_knowledge,
)
from sni.projectdata.models import ProjectDataError
from sni.projectdata.upload import (
    UploadError,
    UploadServiceError,
    load_upload,
    projectdata_response,
)
from sni.rules.engine import DEFAULT_RULES_DIR, RuleLoadError, load_rules
from sni.service.answerer import AnswerError, AnswerInputError, AnswerRequest, answer
from sni.service.checker import CheckError, CheckInputError, check

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = ROOT / "data" / "catalog" / "catalog.db"
DISCLAIMER = "Keine Rechtsauskunft. Grundlage: geladener Katalog-Snapshot (Feld catalog_snapshot)."


class AnswerPayload(BaseModel):
    """Request-Modell für POST /v1/answer (REQ-400)."""

    question: str
    project_data: dict[str, dict[str, object]] | None = None


class CheckPayload(BaseModel):
    """Request-Modell für POST /v1/check (REQ-501)."""

    project_data: dict[str, dict[str, object]] | None = None


class IdsPayload(BaseModel):
    """Request-Modell für POST /v1/export/ids (REQ-701)."""

    rule_ids: list[str] | None = None


def _ifc_mapping_from_catalog(store: ConceptStore) -> dict[str, str]:
    """Quantity-Mapping aus dem Katalog (ADR-0006): base_name -> Concept-ID.

    Verwendet alle Concepts mit vollständigem IFC-Mapping
    (``mappings.ifc.base_name``); ohne Mapping ein leeres Dict (die API
    lehnt dann ab – G5: nie raten).
    """
    mapping: dict[str, str] = {}
    for concept_id in store.concept_ids():
        concept = store.get_concept(concept_id)
        if concept is None:
            continue
        raw_mappings: object = concept.get("mappings")
        if not isinstance(raw_mappings, dict):
            continue
        raw_ifc: object = raw_mappings.get("ifc")
        if not isinstance(raw_ifc, dict):
            continue
        base_name: object = raw_ifc.get("base_name")
        if isinstance(base_name, str) and base_name:
            mapping[base_name] = concept_id
    return mapping


def create_app(
    db_path: Path | None = None,
    knowledge_dir: Path | None = None,
    rules_dir: Path | None = None,
) -> FastAPI:
    """Erzeugt die Anwendung.

    ``db_path``: standardmässig data/catalog/catalog.db;
    ``knowledge_dir``: standardmässig data/extracted/ (lokaler Mount, G3/G4);
    ``rules_dir``: standardmässig data/rules/ (lokaler Mount, G3/G4).
    Regeln und Wissensbasis werden pro Request geladen (lokale Mounts, kein
    Startup-State), damit eine Freigabe in data/extracted/ ohne Neustart wirkt.
    """
    app = FastAPI(title="SIA Norm Intelligence", version="0.1.0")
    app.state.store = ConceptStore(db_path or DEFAULT_DB_PATH)
    app.state.knowledge_dir = knowledge_dir or DEFAULT_KNOWLEDGE_DIR
    app.state.rules_dir = rules_dir or DEFAULT_RULES_DIR

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        """Liveness-Check für `make run` und Monitoring."""
        return {"status": "ok"}

    @app.get("/v1/concepts/{concept_id:path}")
    def get_concept(concept_id: str, request: Request) -> JSONResponse:
        """REQ-102: Concept inkl. Relationen per ID; 404 bei unbekannter ID."""
        store: ConceptStore = request.app.state.store
        concept = store.get_concept(concept_id)
        if concept is None:
            content = {
                "error": f"Concept {concept_id} nicht gefunden",
                "disclaimer": DISCLAIMER,
            }
            return JSONResponse(status_code=404, content=content)
        body = dict(concept)
        body["disclaimer"] = DISCLAIMER
        return JSONResponse(content=body)

    @app.post("/v1/answer")
    def answer_question(payload: AnswerPayload, request: Request) -> JSONResponse:
        """REQ-400: schemakonforme Answer; REQ-403: Fundstelle oder begründete Enthaltung.

        422 = fehlendes Frage-Feld (Pydantic), 400 = leere Frage oder ungültige
        Projektdaten, 500 = interne Antwortfehler (z. B. fehlende Schemakonformität).
        """
        store: ConceptStore = request.app.state.store
        try:
            knowledge: KnowledgeBase = load_knowledge(request.app.state.knowledge_dir)
        except KnowledgeLoadError as exc:
            return JSONResponse(
                status_code=500,
                content={"error": f"Wissensbasis unlesbar: {exc}", "disclaimer": DISCLAIMER},
            )
        if not payload.question.strip():
            return JSONResponse(
                status_code=400,
                content={"error": "Frage fehlt oder ist leer", "disclaimer": DISCLAIMER},
            )
        try:
            result = answer(
                AnswerRequest(payload.question, payload.project_data),
                knowledge,
                store,
            )
        except AnswerInputError as exc:
            return JSONResponse(
                status_code=400, content={"error": str(exc), "disclaimer": DISCLAIMER}
            )
        except AnswerError as exc:
            return JSONResponse(
                status_code=500, content={"error": str(exc), "disclaimer": DISCLAIMER}
            )
        return JSONResponse(content=result)

    @app.post("/v1/check")
    def check_project_data(payload: CheckPayload, request: Request) -> JSONResponse:
        """REQ-501: prüft Projektdaten gegen approved Regeln (ADR-0004).

        400 = ungültige Projektdaten, 500 = unladbare Regeln oder interne
        Fehler. Leeres ``project_data`` ist zulässig (200: alle Regeln
        ``insufficient_data`` + GapReports, REQ-502).
        """
        rules_dir: Path = request.app.state.rules_dir
        try:
            rules = load_rules(rules_dir)
        except RuleLoadError as exc:
            return JSONResponse(
                status_code=500, content={"error": str(exc), "disclaimer": DISCLAIMER}
            )
        try:
            result = check(rules, payload.project_data)
        except CheckInputError as exc:
            return JSONResponse(
                status_code=400, content={"error": str(exc), "disclaimer": DISCLAIMER}
            )
        except CheckError as exc:
            return JSONResponse(
                status_code=500, content={"error": str(exc), "disclaimer": DISCLAIMER}
            )
        return JSONResponse(content=result)

    @app.post("/v1/projectdata")
    async def projectdata_endpoint(
        file: UploadFile,
        request: Request,
        quantity_mapping: Annotated[str | None, Form()] = None,
    ) -> JSONResponse:
        """REQ-500 (ADR-0006): CSV/IFC-Upload -> normalisierte Projektwerte.

        400 = unbekanntes Format (Endung), zu grosse Datei, fehlerhafter
        Inhalt (KBOB-Bericht des Adapters), fehlendes IFC-Mapping oder
        ungültiges Mapping-JSON; 422 = fehlendes ``file``-Feld; 500 =
        nicht schemakonformes internes Ergebnis. 200 = Antwort gegen
        ``project_values.schema.json`` validiert (DoD). G6: Disclaimer.
        """
        if not file.filename:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "Dateiname fehlt (form-data-Feld 'file')",
                    "disclaimer": DISCLAIMER,
                },
            )
        mapping: Mapping[str, str] | None = None
        if Path(file.filename).suffix.lower() == ".ifc":
            if quantity_mapping is not None:
                try:
                    parsed: object = json.loads(quantity_mapping)
                except json.JSONDecodeError as exc:
                    return JSONResponse(
                        status_code=400,
                        content={
                            "error": (f"quantity_mapping ist kein gültiges JSON: {exc}"),
                            "disclaimer": DISCLAIMER,
                        },
                    )
                if not isinstance(parsed, dict) or not all(
                    isinstance(key, str) and isinstance(val, str) for key, val in parsed.items()
                ):
                    return JSONResponse(
                        status_code=400,
                        content={
                            "error": (
                                "quantity_mapping muss ein JSON-Objekt "
                                "{Mengen-Name: Concept-ID} sein"
                            ),
                            "disclaimer": DISCLAIMER,
                        },
                    )
                mapping = {str(k): str(v) for k, v in parsed.items()}
            else:
                mapping = _ifc_mapping_from_catalog(request.app.state.store)
                if not mapping:
                    return JSONResponse(
                        status_code=400,
                        content={
                            "error": (
                                "Kein Quantity-Mapping verfügbar: kein "
                                "IFC-Mapping im Katalog und keine "
                                "quantity_mapping im Request (G5: nie raten)"
                            ),
                            "disclaimer": DISCLAIMER,
                        },
                    )
        data = await file.read()
        try:
            with tempfile.TemporaryDirectory(prefix="sni-upload-") as tmp:
                result = load_upload(file.filename, data, mapping, Path(tmp))
        except (UploadError, ProjectDataError) as exc:
            return JSONResponse(
                status_code=400, content={"error": str(exc), "disclaimer": DISCLAIMER}
            )
        try:
            payload = projectdata_response(result, DISCLAIMER)
        except UploadServiceError as exc:
            return JSONResponse(
                status_code=500, content={"error": str(exc), "disclaimer": DISCLAIMER}
            )
        return JSONResponse(content=payload)

    @app.get("/v1/export/catalog")
    def export_catalog(
        request: Request, format: str = "json", snapshot: str | None = None
    ) -> Response:
        """REQ-700: Katalogausschnitt als JSON oder Turtle/SKOS (ADR-0005).

        400 = unbekanntes Format oder unbekannter Snapshot. G6: beide
        Formate tragen den Disclaimer (JSON-Feld bzw. Kommentarzeile).
        """
        store: ConceptStore = request.app.state.store
        concepts: list[dict[str, object]] = []
        for concept_id in store.concept_ids():
            concept = store.get_concept(concept_id)
            if concept is not None:
                concepts.append(concept)
        try:
            if format == "json":
                return JSONResponse(content=catalog_json(concepts, snapshot, DISCLAIMER))
            if format == "ttl":
                return Response(
                    content=catalog_ttl(concepts, snapshot, DISCLAIMER),
                    media_type="text/turtle",
                )
        except CatalogExportError as exc:
            return JSONResponse(
                status_code=400, content={"error": str(exc), "disclaimer": DISCLAIMER}
            )
        return JSONResponse(
            status_code=400,
            content={
                "error": f"format muss 'json' oder 'ttl' sein (erhalten: {format!r})",
                "disclaimer": DISCLAIMER,
            },
        )

    @app.post("/v1/export/ids")
    def export_ids_endpoint(payload: IdsPayload, request: Request) -> JSONResponse:
        """REQ-701: Regeln als IDS 1.0-Spezifikation, sonst GapReport (ADR-0005).

        400 = unbekannte oder nicht-approved Regel (G3), 500 = unladbare
        Regeln oder nicht schemakonformer Export. ``rule_ids`` leer =
        alle approved Regeln.
        """
        rules_dir: Path = request.app.state.rules_dir
        try:
            rules = load_rules(rules_dir)
        except RuleLoadError as exc:
            return JSONResponse(
                status_code=500, content={"error": str(exc), "disclaimer": DISCLAIMER}
            )
        store: ConceptStore = request.app.state.store
        concept_by_id: dict[str, dict[str, object]] = {}
        for concept_id in store.concept_ids():
            concept = store.get_concept(concept_id)
            if concept is not None:
                concept_by_id[concept_id] = concept
        try:
            result = export_ids(rules, concept_by_id, payload.rule_ids, DISCLAIMER)
        except IdsExportError as exc:
            return JSONResponse(
                status_code=400, content={"error": str(exc), "disclaimer": DISCLAIMER}
            )
        except IdsValidationError as exc:
            return JSONResponse(
                status_code=500, content={"error": str(exc), "disclaimer": DISCLAIMER}
            )
        return JSONResponse(content=result)

    @app.post("/v1/export/bcf")
    def export_bcf_endpoint(payload: CheckPayload, request: Request) -> Response:
        """REQ-702: Projektdaten prüfen, fail-Ergebnisse als BCF 2.1 exportieren.

        400 = ungültige Projektdaten, 500 = unladbare Regeln oder interne
        Fehler. 200 = BCF-ZIP (``application/octet-stream`` als
        Attachment) mit ``bcf.version`` plus je ``fail`` ein Topic;
        ``pass``/``insufficient_data`` enthalten keine Topics. G6: Der
        Disclaimer steht in jeder Topic-Description.
        """
        rules_dir: Path = request.app.state.rules_dir
        try:
            rules = load_rules(rules_dir)
        except RuleLoadError as exc:
            return JSONResponse(
                status_code=500, content={"error": str(exc), "disclaimer": DISCLAIMER}
            )
        try:
            result = check(rules, payload.project_data)
        except CheckInputError as exc:
            return JSONResponse(
                status_code=400, content={"error": str(exc), "disclaimer": DISCLAIMER}
            )
        except CheckError as exc:
            return JSONResponse(
                status_code=500, content={"error": str(exc), "disclaimer": DISCLAIMER}
            )
        raw_checks: object = result["checks"]
        if not isinstance(raw_checks, list):
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Check-Ergebnis ohne checks-Liste (intern)",
                    "disclaimer": DISCLAIMER,
                },
            )
        entries = [entry for entry in raw_checks if isinstance(entry, dict)]
        try:
            data = bcf_bytes(entries, datetime.now(UTC), DISCLAIMER)
        except BcfExportError as exc:
            return JSONResponse(
                status_code=500, content={"error": str(exc), "disclaimer": DISCLAIMER}
            )
        return Response(
            content=data,
            media_type="application/octet-stream",
            headers={"Content-Disposition": 'attachment; filename="sni-checks.bcf"'},
        )

    return app


app = create_app()
atexit.register(app.state.store.close)  # sauberes Schliessen der DB-Connection
