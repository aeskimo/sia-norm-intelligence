"""FastAPI-Endpunkte (M1: GET /v1/concepts/{id}; M4: POST /v1/answer).

Fachlogik bleibt in sni.catalog (Katalog) bzw. sni.service (Antwort-Pipeline).
Hinweis G6: Jede fachliche API-Antwort trägt das Feld ``disclaimer``.
``/healthz`` ist ein reiner Liveness-Check ohne fachlichen Inhalt.
"""

from __future__ import annotations

import atexit
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from sni.catalog.store import ConceptStore
from sni.knowledge.store import DEFAULT_KNOWLEDGE_DIR, KnowledgeBase, load_knowledge
from sni.service.answerer import AnswerError, AnswerInputError, AnswerRequest, answer

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = ROOT / "data" / "catalog" / "catalog.db"
DISCLAIMER = "Keine Rechtsauskunft. Grundlage: geladener Katalog-Snapshot (Feld catalog_snapshot)."


class AnswerPayload(BaseModel):
    """Request-Modell für POST /v1/answer (REQ-400)."""

    question: str
    project_data: dict[str, dict[str, object]] | None = None


def create_app(
    db_path: Path | None = None,
    knowledge_dir: Path | None = None,
) -> FastAPI:
    """Erzeugt die Anwendung.

    ``db_path``: standardmässig data/catalog/catalog.db;
    ``knowledge_dir``: standardmässig data/extracted/ (lokaler Mount, G3/G4).
    """
    app = FastAPI(title="SIA Norm Intelligence", version="0.1.0")
    app.state.store = ConceptStore(db_path or DEFAULT_DB_PATH)
    app.state.knowledge = load_knowledge(knowledge_dir or DEFAULT_KNOWLEDGE_DIR)

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
        knowledge: KnowledgeBase = request.app.state.knowledge
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

    return app


app = create_app()
atexit.register(app.state.store.close)  # sauberes Schliessen der DB-Connection
