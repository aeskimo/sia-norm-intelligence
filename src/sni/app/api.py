"""App-Router (M8.1, REQ-800): App-Zustand für die UI-Statuszeile.

Wird nur im App-Modus von ``sni.app.server.build_app`` gemountet; die
Kern-API (``sni.api.main``) bleibt unverändert (Schichten-Regel).
Alle Antworten tragen den G6-Disclaimer.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from sni.api.main import DISCLAIMER
from sni.app import APP_VERSION

router = APIRouter(tags=["app"])


class StatusResponse(BaseModel):
    """App-Zustand (Schema ``sni:status``).

    M8.1: ``login``/``ollama`` sind noch null (M8.2/M8.4); ``documents``
    kommt in M8.3 mit der Dokument-Registry.
    """

    version: str
    mode: Literal["window", "browser", "headless"]
    port: int
    login: dict[str, object] | None = None
    ollama: dict[str, object] | None = None
    documents: int = 0
    summary: str
    disclaimer: str


@router.get("/status", response_model=StatusResponse)
def status(request: Request) -> StatusResponse:
    """REQ-800: App-Zustand für die Statuszeile in allen 6 Views."""
    return StatusResponse(
        version=APP_VERSION,
        mode=request.app.state.app_mode,
        port=request.app.state.app_port,
        summary="Bereit.",
        disclaimer=DISCLAIMER,
    )
