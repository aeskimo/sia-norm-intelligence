"""FastAPI-Endpunkte (M1: GET /v1/concepts/{id}; Fachlogik bleibt in sni.catalog).

Hinweis G6: Jede fachliche API-Antwort trägt das Feld ``disclaimer``.
``/healthz`` ist ein reiner Liveness-Check ohne fachlichen Inhalt.
"""

from __future__ import annotations

import atexit
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from sni.catalog.store import ConceptStore

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = ROOT / "data" / "catalog" / "catalog.db"
DISCLAIMER = "Keine Rechtsauskunft. Grundlage: geladener Katalog-Snapshot (Feld catalog_snapshot)."


def create_app(db_path: Path | None = None) -> FastAPI:
    """Erzeugt die Anwendung; ``db_path`` standardmässig data/catalog/catalog.db."""
    app = FastAPI(title="SIA Norm Intelligence", version="0.1.0")
    app.state.store = ConceptStore(db_path or DEFAULT_DB_PATH)

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

    return app


app = create_app()
atexit.register(app.state.store.close)  # sauberes Schliessen der DB-Connection
