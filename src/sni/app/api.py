"""App-Router (M8.1 REQ-800, M8.2 REQ-803): App-Zustand + Shop-Endpunkte.

Wird nur im App-Modus von ``sni.app.server.build_app`` gemountet; die
Kern-API (``sni.api.main``) bleibt unverändert (Schichten-Regel).
Alle Antworten tragen den G6-Disclaimer.

Endpunkte (09_CONSUMER_APP.md §6.2): Login/Logout, Katalog, Download
(async Job), lokale Dokumente (Liste, PDF, Entfernen), Jobs, Status.
"""

from __future__ import annotations

import contextlib
import json
import os
import queue
import threading
from collections.abc import Iterator, Mapping
from typing import Literal, cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from sni.api.main import DISCLAIMER
from sni.app import APP_VERSION
from sni.app.shop import (
    ShopBundle,
    ShopLoginError,
    ShopState,
    resolve_provider,
)
from sni.documents.analysis import OLLAMA_URL
from sni.documents.downloads import Job
from sni.documents.pdfcache import CacheIntegrityError
from sni.documents.registry import LocalDocumentState
from sni.rag.grounded import GroundedQa
from sni.rag.model_provider import ModelProvider
from sni.rag.providers.gibb import OpenAiCompatibleProvider
from sni.rag.providers.ollama import OllamaChatProvider
from sni.search.page_source import PageSource
from sni.secrets.keyring_store import GibbApiKeyStore
from sni.shop.catalog_xml import StandardDocument
from sni.state.workspace import (
    DEFAULT_GENERATION_MODEL,
    DEFAULT_GIBB_BASE_URL,
    DEFAULT_PROVIDER,
    load_workspace_json,
)

router = APIRouter(tags=["app"])


class StatusResponse(BaseModel):
    """App-Zustand (Schema ``sni:status``)."""

    version: str
    mode: Literal["window", "browser", "headless"]
    port: int
    login: dict[str, object] | None = None
    ollama: dict[str, object] | None = None
    documents: int = 0
    summary: str
    disclaimer: str


class LoginRequest(BaseModel):
    """Login-Anfrage (09 §6.2); ``remember`` → OS-Keyring (REQ-802)."""

    provider: str
    customer: str
    password: str
    device_id: str
    remember: bool = False


class CatalogItem(BaseModel):
    """Katalogeintragsantwort (Schema ``sni:catalog_item``)."""

    product_id: str
    number: str
    title: str
    description: str
    keywords: str
    language: str
    year: str
    revision: str
    valid_from: str | None
    valid_until: str | None
    remote_filename: str
    view_allowed: bool
    print_allowed: bool
    copy_allowed: bool


class LocalDocument(BaseModel):
    """Lokales Dokument (Schema ``sni:local_document``)."""

    product_id: str
    number: str
    title: str
    language: str
    status: Literal["CACHED", "INDEXING", "FULLTEXT_READY", "HYBRID_READY", "ERROR"]
    status_label: str
    indexed_pages: int
    embeddings_ready: bool
    detail: str
    updated_at: str


class JobOut(BaseModel):
    """Jobsatzantwort (Schema ``sni:job``)."""

    id: str
    kind: Literal["download", "analyze", "pull"]
    document_id: str | None
    status: Literal["queued", "running", "done", "error"]
    progress: str | None
    error: str | None


class DownloadRequest(BaseModel):
    """Download-Anfrage (09 §6.2)."""

    product_id: str


class AnalyzeRequest(BaseModel):
    """Analyse-Anfrage (09 §6.2); ``embedding_model`` leer → nur Volltext."""

    embedding_model: str = ""


class AskScope(BaseModel):
    """RAG-Scope (09 §6.2): Produkt-IDs und/oder Arbeitsset."""

    document_ids: list[str] | None = None
    workset_id: str | None = None


class AskRequest(BaseModel):
    """RAG-Frage (09 §6.2); Antwort als SSE-Stream."""

    question: str
    scope: AskScope | None = None


# ------------------------------------------------------------------ Helfer


def _shop(request: Request) -> ShopState:
    return cast(ShopState, request.app.state.shop)


def _error(status_code: int, detail: str, **extra: object) -> JSONResponse:
    """App-Fehlerantwort (Stil wie die REQ-816-Middleware)."""
    body: dict[str, object] = {"error": detail, "disclaimer": DISCLAIMER, **extra}
    return JSONResponse(body, status_code=status_code)


def _require_bundle(request: Request) -> ShopBundle | JSONResponse:
    bundle = _shop(request).bundle
    if bundle is None:
        return _error(401, "Nicht eingeloggt")
    return bundle


def _catalog_item(doc: StandardDocument) -> dict[str, object]:
    return {
        "product_id": doc.product_id,
        "number": doc.number,
        "title": doc.title,
        "description": doc.description,
        "keywords": doc.keywords,
        "language": doc.language,
        "year": doc.year,
        "revision": doc.revision,
        "valid_from": doc.valid_from.isoformat() if doc.valid_from else None,
        "valid_until": doc.valid_until.isoformat() if doc.valid_until else None,
        "remote_filename": doc.remote_filename,
        "view_allowed": doc.view_allowed,
        "print_allowed": doc.print_allowed,
        "copy_allowed": doc.copy_allowed,
    }


def _local_document(state: LocalDocumentState) -> dict[str, object]:
    doc = state.document
    return {
        "product_id": doc.product_id,
        "number": doc.number,
        "title": doc.title,
        "language": doc.language,
        "status": state.status.name,
        "status_label": state.status.label,
        "indexed_pages": state.indexed_pages,
        "embeddings_ready": state.embeddings_ready,
        "detail": state.detail,
        "updated_at": state.updated_at.isoformat(),
    }


def _job(job: Job) -> dict[str, object]:
    return {
        "id": job.id,
        "kind": job.kind.value,
        "document_id": job.document_id,
        "status": job.status.value,
        "progress": job.progress,
        "error": job.error,
    }


def _pdf_filename(bundle: ShopBundle, document_id: str) -> str:
    """Dateiname für ``Content-Disposition`` (sanitisiert, max. 80 Zeichen)."""
    doc = bundle.product_service.catalog.by_id(document_id)
    name = doc.remote_filename if doc is not None and doc.remote_filename else f"{document_id}.pdf"
    name = name.replace("\\", "_").replace("/", "_").replace('"', "")
    return name[-80:] or f"{document_id}.pdf"


def _status_summary(shop: ShopState) -> str:
    bundle = shop.bundle
    if bundle is None:
        return "Bereit. Bitte im Normenkatalog einloggen."
    creds = bundle.session.credentials
    return (
        f"Eingeloggt: {creds.customer} ({bundle.provider.app_name}). "
        f"Katalog: {bundle.product_service.catalog.size()} Normen. "
        f"Lokale Dokumente: {len(bundle.registry.all())}."
    )


def _remember(shop: ShopState, customer: str, password: str) -> str:
    """Merken-Checkbox (REQ-802): Zugangsdaten im OS-Keyring ablegen."""
    try:
        shop.login_store.store(customer.strip(), password)
        return "ok"
    except Exception as exc:  # noqa: BLE001 — Login bleibt Erfolg, UI meldet
        return f"Zugangsdaten konnten nicht gespeichert werden: {exc}"


# ------------------------------------------------------------------ RAG (SSE)


def _sse(event: str, data: Mapping[str, object]) -> bytes:
    """Ein SSE-Ereignis (09 §6.2): ``event:``-Zeile + ``data:``-JSON."""
    payload = json.dumps(dict(data), ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n".encode()


def _source_block(source: PageSource) -> dict[str, object]:
    """Quellenblock (09 §6.2): vollständige Seite bleibt in der Übersicht."""
    return {
        "source_id": source.source_id(),
        "standard": source.standard,
        "edition": source.edition,
        "page": source.page,
        "section": source.section,
        "text": source.text,
    }


def _ask_scope(
    shop: ShopState, bundle: ShopBundle, scope: AskScope | None
) -> set[str] | None | JSONResponse:
    """Scope-Prüfung: Produkt-IDs und/oder Arbeitsset (aus workspace.json)."""
    if scope is None:
        return None
    ids = {doc_id.strip() for doc_id in scope.document_ids or [] if doc_id.strip()}
    workset_id = (scope.workset_id or "").strip()
    if workset_id:
        state = load_workspace_json(shop.data_dir) or {}
        raw_worksets = state.get("worksets")
        worksets = raw_worksets if isinstance(raw_worksets, dict) else {}
        docs = worksets.get(workset_id)
        if not isinstance(docs, list):
            return _error(400, f"Arbeitsset unbekannt: {workset_id!r}")
        ids.update(str(doc_id) for doc_id in docs)
    return ids or None


def _ask_model_provider(shop: ShopState) -> ModelProvider:
    """Antwortmodell aus workspace.json (REQ-805); Standard: lokales Ollama.

    gibb: Bearer aus Umgebungsvariable ``GIBB_API_KEY`` oder Keyring
    (``gibb-api-key``); der Key wird nie an die UI ausgeliefert.
    """
    state = load_workspace_json(shop.data_dir) or {}
    provider = str(state.get("provider") or DEFAULT_PROVIDER)
    if provider == "gibb":
        base_url = str(state.get("gibb_base_url") or DEFAULT_GIBB_BASE_URL)
        model = str(state.get("gibb_model") or "").strip()
        if not model:
            raise RuntimeError("gibb-Modell ist nicht konfiguriert")
        api_key = os.environ.get("GIBB_API_KEY", "").strip()
        if not api_key:
            api_key = GibbApiKeyStore().load() or ""
        if not api_key:
            raise RuntimeError("gibb-API-Key fehlt (Umgebungsvariable GIBB_API_KEY oder Keyring)")
        return OpenAiCompatibleProvider(base_url, api_key, model)
    model = str(state.get("generation_model") or DEFAULT_GENERATION_MODEL)
    return OllamaChatProvider(OLLAMA_URL, model)


def _ask_events(
    shop: ShopState, bundle: ShopBundle, question: str, scope: set[str] | None
) -> Iterator[bytes]:
    """SSE-Stream (09 §6.2): ``token`` → ``sources`` → ``answer`` bzw. ``error``.

    Die (blockierende) Generierung läuft im Worker-Thread; Token werden
    über eine Queue in den Stream geschleust, damit ``StreamingResponse``
    sie sofort an die UI liefern kann.
    """
    out: queue.Queue[tuple[str, Mapping[str, object]] | None] = queue.Queue()

    def run() -> None:
        try:
            provider = _ask_model_provider(shop)
            qa = GroundedQa(bundle.pipeline.rag_search(), provider)

            def on_token(chunk: str) -> None:
                out.put(("token", {"text": chunk}))

            answer = qa.ask(question, scope, on_token=on_token)
            sources = [_source_block(source) for source in answer.sources]
            out.put(("sources", {"sources": sources}))
            out.put(
                (
                    "answer",
                    {
                        "text": answer.text,
                        "status": answer.status,
                        "sources": sources,
                        "model_id": answer.model_id,
                        "disclaimer": DISCLAIMER,
                    },
                )
            )
            out.put(None)
        except Exception as exc:  # noqa: BLE001 — Fehler als SSE-``error``-Event
            out.put(
                (
                    "error",
                    {"error": f"{type(exc).__name__}: {exc}", "disclaimer": DISCLAIMER},
                )
            )
            out.put(None)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    while True:
        item = out.get()
        if item is None:
            break
        yield _sse(item[0], item[1])
    worker.join()


# ------------------------------------------------------------------ Endpunkte


@router.get("/status", response_model=StatusResponse)
def status(request: Request) -> StatusResponse:
    """REQ-800: App-Zustand für die Statuszeile in allen 6 Views."""
    shop = _shop(request)
    bundle = shop.bundle
    login: dict[str, object] | None = None
    documents = 0
    if bundle is not None:
        creds = bundle.session.credentials
        login = {
            "provider": bundle.provider.app_name,
            "customer": creds.customer,
            "device_id": creds.device_id,
        }
        documents = len(bundle.registry.all())
    return StatusResponse(
        version=APP_VERSION,
        mode=request.app.state.app_mode,
        port=request.app.state.app_port,
        login=login,
        documents=documents,
        summary=_status_summary(shop),
        disclaimer=DISCLAIMER,
    )


@router.post("/session/login")
def session_login(payload: LoginRequest, request: Request) -> JSONResponse:
    """09 §6.2: ECHO + Login; ``remember`` → Keyring; Fehler-Codes 1:1."""
    shop = _shop(request)
    try:
        profile = resolve_provider(payload.provider)
    except ValueError as exc:
        return _error(400, str(exc))
    if not (payload.customer.strip() and payload.password and payload.device_id.strip()):
        return _error(400, "Kundennummer, Passwort und Device-ID sind erforderlich.")
    try:
        bundle, outcome = shop.login(profile, payload.customer, payload.password, payload.device_id)
    except ShopLoginError as exc:
        return _error(401, exc.message, protocol=exc.protocol)
    keyring: str | None = None
    if payload.remember:
        keyring = _remember(shop, payload.customer, payload.password)
    return JSONResponse(
        {
            "status": "ok",
            "message": outcome.message,
            "provider": bundle.provider.app_name,
            "customer": payload.customer.strip(),
            "device_id": payload.device_id.strip(),
            "catalog": [_catalog_item(doc) for doc in bundle.product_service.catalog.all()],
            "keyring": keyring,
            "disclaimer": DISCLAIMER,
        }
    )


@router.post("/session/logout")
def session_logout(request: Request) -> JSONResponse:
    """09 §6.2: Sitzungs-Authentifizierung verwerfen (Zeroing)."""
    _shop(request).logout()
    return JSONResponse(
        {"status": "ok", "message": "Sitzung beendet (Zeroing).", "disclaimer": DISCLAIMER}
    )


@router.get("/catalog", response_model=None)
def catalog(request: Request) -> list[dict[str, object]] | JSONResponse:
    """09 §6.2: Katalog der aktuellen Sitzung (``[sni:catalog_item]``)."""
    bundle = _require_bundle(request)
    if isinstance(bundle, JSONResponse):
        return bundle
    return [_catalog_item(doc) for doc in bundle.product_service.catalog.all()]


@router.post("/documents/download")
def documents_download(payload: DownloadRequest, request: Request) -> JSONResponse:
    """09 §6.2: async Download-Job (``.srd`` → DES → PDF im Session-Cache)."""
    bundle = _require_bundle(request)
    if isinstance(bundle, JSONResponse):
        return bundle
    if not payload.product_id.strip():
        return _error(400, "product_id darf nicht leer sein.")
    job = bundle.downloads.submit(bundle.session, payload.product_id.strip())
    return JSONResponse(
        {"status": "accepted", "job": _job(job), "disclaimer": DISCLAIMER},
        status_code=202,
    )


@router.get("/documents")
def documents(request: Request) -> list[dict[str, object]]:
    """09 §6.2: lokale Registry (``[sni:local_document]``); ohne Login: leer."""
    bundle = _shop(request).bundle
    if bundle is None:
        return []
    return [_local_document(state) for state in bundle.registry.all()]


@router.get("/documents/{document_id}/pdf")
def document_pdf(document_id: str, request: Request) -> Response:
    """09 §6.2: Session-PDF-Bytes (``application/pdf``) — nur während Sitzung."""
    bundle = _require_bundle(request)
    if isinstance(bundle, JSONResponse):
        return bundle
    try:
        pdf = bundle.cache.get(document_id)
    except ValueError:
        return _error(404, "Dokument nicht im Sitzungscache")
    except CacheIntegrityError:
        return _error(500, "Cache beschädigt")
    if pdf is None:
        return _error(404, "Dokument nicht im Sitzungscache")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{_pdf_filename(bundle, document_id)}"'
        },
    )


@router.get("/documents/{document_id}")
def document_detail(document_id: str, request: Request) -> JSONResponse:
    """09 §6.2: Detail inkl. Job-State (alle Jobs mit dieser ``document_id``)."""
    bundle = _require_bundle(request)
    if isinstance(bundle, JSONResponse):
        return bundle
    state = bundle.registry.get(document_id)
    if state is None:
        return _error(404, "Dokument nicht in der lokalen Registry")
    detail = _local_document(state)
    detail["jobs"] = [
        _job(job) for job in bundle.downloads.jobs() if job.document_id == document_id
    ]
    return JSONResponse(detail)


@router.post("/documents/{document_id}/analyze")
def document_analyze(
    document_id: str, request: Request, payload: AnalyzeRequest | None = None
) -> JSONResponse:
    """09 §6.2: async Analyse-Job (Extraktion → Volltext- → Vektorindex)."""
    bundle = _require_bundle(request)
    if isinstance(bundle, JSONResponse):
        return bundle
    if bundle.registry.get(document_id) is None:
        return _error(404, "Dokument nicht in der lokalen Registry")
    model = payload.embedding_model.strip() if payload is not None else ""
    job = bundle.downloads.submit_analyze(document_id, model)
    return JSONResponse(
        {"status": "accepted", "job": _job(job), "disclaimer": DISCLAIMER},
        status_code=202,
    )


@router.post("/ask", response_model=None)
def ask(payload: AskRequest, request: Request) -> StreamingResponse | JSONResponse:
    """09 §6.2: RAG-Frage als SSE-Stream (``token``/``sources``/``answer``/``error``).

    Das Token kommt über den Query-Parameter ``sia_token`` (EventSource
    kann keine Header setzen). Der Provider (Ollama/gibb) und das Modell
    stammen aus ``workspace.json``; ohne Vektoren bleibt die Suche
    lexikalisch (Volltext).
    """
    bundle = _require_bundle(request)
    if isinstance(bundle, JSONResponse):
        return bundle
    question = payload.question.strip()
    if not question:
        return _error(400, "question darf nicht leer sein.")
    scope = _ask_scope(_shop(request), bundle, payload.scope)
    if isinstance(scope, JSONResponse):
        return scope
    return StreamingResponse(
        _ask_events(_shop(request), bundle, question, scope),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete("/documents/{document_id}")
def document_remove(document_id: str, request: Request) -> JSONResponse:
    """09 §6.2: Cache + Index entfernen (Zeroing)."""
    bundle = _require_bundle(request)
    if isinstance(bundle, JSONResponse):
        return bundle
    if bundle.registry.get(document_id) is None:
        return _error(404, "Dokument nicht in der lokalen Registry")
    with contextlib.suppress(ValueError):
        bundle.cache.delete(document_id)
    bundle.registry.remove(document_id)
    return JSONResponse(
        {"status": "ok", "message": "Dokument entfernt (Cache + Index).", "disclaimer": DISCLAIMER}
    )


@router.get("/jobs")
def jobs(request: Request) -> list[dict[str, object]]:
    """09 §6.2: Job-Queue (``[sni:job]``); UI pollt alle 2 s; ohne Login: leer."""
    bundle = _shop(request).bundle
    if bundle is None:
        return []
    return [_job(job) for job in bundle.downloads.jobs()]
