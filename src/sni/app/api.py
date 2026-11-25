"""App-Router (M8.1 REQ-800, M8.2 REQ-803): App-Zustand + Shop-Endpunkte.

Wird nur im App-Modus von ``sni.app.server.build_app`` gemountet; die
Kern-API (``sni.api.main``) bleibt unverändert (Schichten-Regel).
Alle Antworten tragen den G6-Disclaimer.

Endpunkte (09_CONSUMER_APP.md §6.2): Login/Logout, Katalog, Download
(async Job), lokale Dokumente (Liste, PDF, Entfernen), Ollama-Modelle
(Liste, Pull, Delete), RAG-Fragen (SSE), Jobs, Status.
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
from sni.catalog.store import ConceptStore
from sni.documents.analysis import OLLAMA_URL
from sni.documents.downloads import Job
from sni.documents.pdfcache import CacheIntegrityError
from sni.documents.registry import LocalDocumentState
from sni.export.semantic import export as semantic_export
from sni.ingest.pipeline import (
    IngestError,
    default_norms_dir,
    default_queue_dir,
    ingest_document,
    load_document,
)
from sni.models.ollama_manager import OllamaModelManager
from sni.rag.grounded import GroundedQa
from sni.rag.model_provider import ModelProvider
from sni.rag.providers.gibb import OpenAiCompatibleProvider
from sni.rag.providers.ollama import OllamaChatProvider
from sni.review.service import ReviewError, list_queue
from sni.review.service import approve as review_approve
from sni.review.service import reject as review_reject
from sni.search.page_source import PageSource
from sni.secrets.keyring_store import GibbApiKeyStore, KeyringUnavailableError
from sni.shop.catalog_xml import StandardDocument
from sni.state.paths import user_data_dir
from sni.state.settings import load_settings, update_settings
from sni.state.worksets import valid_document_id, valid_name
from sni.state.workspace import (
    DEFAULT_GENERATION_MODEL,
    DEFAULT_GIBB_BASE_URL,
    DEFAULT_PROVIDER,
    is_onboarding_done,
    load_workspace_json,
    mark_onboarding_done,
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


class OnboardingStatus(BaseModel):
    """„Erste Schritte“ (M8.6, 09 §2): Kachel-Status für das Onboarding.

    Keine Norm- oder Kundendaten (G4) — nur Bool-Status pro Schritt.
    """

    done: bool
    shop_logged_in: bool
    ollama_available: bool
    gibb_key_set: bool


class LoginRequest(BaseModel):
    """Login-Anfrage (09 §6.2); ``remember`` → OS-Keyring (REQ-802)."""

    provider: str
    customer: str
    password: str
    device_id: str
    remember: bool = False


class SettingsRequest(BaseModel):
    """Einstellungen-Update (09 §6.2); alle Felder optional (Teilmenge).

    ``gibb_key`` (nicht-leer) wird in den OS-Keyring gespeichert und nie
    zurückgeliefert; leer = unverändert (v1 ohne Lösch-Weg, G4).
    """

    generation_model: str | None = None
    embedding_model: str | None = None
    provider: str | None = None
    gibb_base_url: str | None = None
    gibb_model: str | None = None
    approval_name: str | None = None
    gibb_key: str | None = None


class WorksetCreateRequest(BaseModel):
    """Arbeitsset anlegen (09 §6.2; idempotent wie Java ``computeIfAbsent``)."""

    name: str


class WorksetUpdateRequest(BaseModel):
    """Arbeitsset: Dokument-Liste ersetzen (09 §6.2)."""

    document_ids: list[str]


class SemanticExportRequest(BaseModel):
    """Semantik-Export (09 §6.2): ``norm_id`` = product_id des lokalen Dokuments."""

    norm_id: str


class ReviewApproveRequest(BaseModel):
    """Kandidat freigeben (09 §6.2, ADR-0008).

    ``approved_by``: Override aus dem Freigabe-Dialog; fehlt es, wird die
    konfigurierte Freigabeperson (Settings ``approval_name``) verwendet.
    """

    approved_by: str | None = None


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


def _ollama_status(shop: ShopState) -> dict[str, object]:
    """REQ-806: Ollama-Status für ``sni:status`` (Erreichbarkeit + aktives Modell)."""
    try:
        reachable = OllamaModelManager(OLLAMA_URL).available()
    except PermissionError:
        reachable = False  # Host-Check im Konstruktor (konfigurierter Remote-Host)
    state = load_workspace_json(shop.data_dir) or {}
    model: str | None = None
    if str(state.get("provider") or DEFAULT_PROVIDER) == "ollama":
        model = str(state.get("generation_model") or DEFAULT_GENERATION_MODEL) or None
    return {"reachable": reachable, "model": model}


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
        ollama=_ollama_status(shop),
        documents=documents,
        summary=_status_summary(shop),
        disclaimer=DISCLAIMER,
    )


@router.get("/onboarding", response_model=OnboardingStatus)
def onboarding_status(request: Request) -> OnboardingStatus:
    """M8.6: Onboarding-Status (09 §2): SIA-Login, Ollama (optional), gibb-Key (optional)."""
    shop = _shop(request)
    try:
        ollama_available = OllamaModelManager(OLLAMA_URL).available()
    except PermissionError:
        ollama_available = False  # Host-Check im Konstruktor (konfigurierter Remote-Host)
    return OnboardingStatus(
        done=is_onboarding_done(shop.data_dir),
        shop_logged_in=shop.bundle is not None,
        ollama_available=ollama_available,
        gibb_key_set=GibbApiKeyStore().load() is not None,
    )


@router.post("/onboarding/complete")
def onboarding_complete(request: Request) -> dict[str, object]:
    """M8.6: „Fertig“ — Onboarding-Flag setzen (Überspringen erlaubt)."""
    shop = _shop(request)
    mark_onboarding_done(shop.data_dir)
    return {"done": True}


def _login_diagnostic(customer: str, password: str, device_id: str) -> str:
    """G4-sichere Login-Diagnose für die UI (A/B-Befund: Portal lehnt ab).

    Zeigt exakt, was eingereicht wurde — aber nur Nicht-Geheimnis:
    Kundennummer und Device-ID im Klartext (beide werden auch im
    Erfolgs-Payload zurückgeliefert), das Passwort nur als Länge +
    Zeichengruppen (Gross/klein/Ziffer/Sonder), nie das Passwort selbst.
    Wird nicht geloggt (G4), nur im 401-Payload zurückgeliefert.
    """
    classes = [
        name
        for name, check in (
            ("Gross", any(c.isupper() for c in password)),
            ("klein", any(c.islower() for c in password)),
            ("Ziffer", any(c.isdigit() for c in password)),
            ("Sonder", any(not c.isalnum() for c in password)),
        )
        if check
    ]
    return (
        f"Eingereicht: Kunde='{customer.strip()}' (Länge {len(customer.strip())}), "
        f"Passwort: Länge {len(password)} ({', '.join(classes) or 'leer'}), "
        f"Device='{device_id.strip()}'"
    )


@router.post("/session/login")
def session_login(payload: LoginRequest, request: Request) -> JSONResponse:
    """09 §6.2: ECHO + Login; ``remember`` → Keyring; Fehler-Codes 1:1.

    Bei ``ShopLoginError``: 401 mit ``protocol`` (1:1-Servercode) und
    G4-sicherer ``diagnostic`` (eingereichte Werte ohne Passwort-Bytes).
    """
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
        return _error(
            401,
            exc.message,
            protocol=exc.protocol,
            diagnostic=_login_diagnostic(payload.customer, payload.password, payload.device_id),
        )
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
    """09 §6.2: Cache + Index entfernen (Zeroing); Arbeitssets aktualisieren."""
    bundle = _require_bundle(request)
    if isinstance(bundle, JSONResponse):
        return bundle
    if bundle.registry.get(document_id) is None:
        return _error(404, "Dokument nicht in der lokalen Registry")
    with contextlib.suppress(ValueError):
        bundle.cache.delete(document_id)
    bundle.registry.remove(document_id)
    # REQ-808 (Java: WorksetStore.removeDocumentEverywhere): die Id verliert
    # ihre Referenz in allen Arbeitssets.
    shop = _shop(request)
    shop.worksets.remove_document_everywhere(document_id)
    shop.save_worksets()
    return JSONResponse(
        {"status": "ok", "message": "Dokument entfernt (Cache + Index).", "disclaimer": DISCLAIMER}
    )


@router.get("/jobs")
def jobs(request: Request) -> list[dict[str, object]]:
    """09 §6.2: Job-Queue (``[sni:job]``); UI pollt alle 2 s.

    Bundle-Jobs (Download/Analyse, nur eingeloggt) + Modell-Pull-Jobs
    (Login-unabhängig, REQ-806).
    """
    shop = _shop(request)
    bundle_jobs = shop.bundle.downloads.jobs() if shop.bundle is not None else []
    return [_job(job) for job in [*bundle_jobs, *shop.pull_jobs()]]


@router.get("/models/ollama")
def models_ollama() -> dict[str, object]:
    """09 §6.2: Ollama-Modellliste (``GET /api/tags`` weiterreichen, REQ-806)."""
    try:
        models = OllamaModelManager(OLLAMA_URL).list_installed()
    except Exception:  # noqa: BLE001 — Ollama abwesend/fehlerhaft → available=false
        return {"available": False, "models": []}
    return {
        "available": True,
        "models": [
            {"name": m.name, "size_bytes": m.size_bytes, "modified_at": m.modified_at}
            for m in models
        ],
    }


@router.post("/models/ollama/{name}/pull")
def models_ollama_pull(name: str, request: Request) -> JSONResponse:
    """09 §6.2: Modell-Download als async Job (2-h-Timeout wie Java, REQ-806)."""
    try:
        OllamaModelManager._require_model(name)
    except ValueError as exc:
        return _error(400, str(exc))
    shop = _shop(request)
    job = shop.submit_pull(name, OllamaModelManager(OLLAMA_URL))
    return JSONResponse(
        {"status": "accepted", "job": _job(job), "disclaimer": DISCLAIMER},
        status_code=202,
    )


@router.delete("/models/ollama/{name}")
def models_ollama_delete(name: str) -> JSONResponse:
    """09 §6.2: lokales Modell löschen (REQ-806)."""
    try:
        OllamaModelManager(OLLAMA_URL).delete(name)
    except (ValueError, PermissionError) as exc:
        return _error(400, str(exc))
    except Exception as exc:  # noqa: BLE001 — Ollama-Fehler → 502
        return _error(502, f"Modell konnte nicht gelöscht werden: {exc}")
    return JSONResponse({"ok": True, "disclaimer": DISCLAIMER})


@router.get("/models/gibb")
def models_gibb(request: Request) -> dict[str, object]:
    """09 §6.2: gibb-Modellliste (OpenAI ``/models``, Bearer aus Keyring, REQ-807).

    1:1 wie der Java-«Modelle auflisten»-Button: nötig sind nur der
    API-Key (Keyring) und die Basis-URL aus den Einstellungen; das
    Modell-Parameter ist der Java-Platzhalter ``"temp"``, weil der
    Listen-Aufruf es nicht benutzt — die Liste ist damit schon vor der
    Modellauswahl verfügbar. Ohne Keyring-Key oder bei
    Erreichbarkeitsfehler: ``{"available": false, "models": []}``.
    """
    shop = _shop(request)
    settings = load_settings(shop.data_dir)
    api_key = GibbApiKeyStore().load()
    if api_key is None:
        return {"available": False, "models": []}
    try:
        # Java: new OpenAiCompatibleProvider(base, key, "temp")
        provider = OpenAiCompatibleProvider(str(settings["gibb_base_url"]), api_key, "temp")
        return {"available": True, "models": provider.list_models()}
    except Exception:  # noqa: BLE001 — gibb abwesend/falsch konfiguriert
        return {"available": False, "models": []}


# ------------------------------------------------------------------ Einstellungen (REQ-808)


def _settings_payload(shop: ShopState, data: dict[str, object]) -> dict[str, object]:
    """GET/PUT-Antwort (``sni:settings``): Status-Felder + G6-Disclaimer.

    Der gibb-Key selbst kommt nie in die Antwort (G4).
    """
    data["gibb_key_set"] = GibbApiKeyStore().load() is not None
    data["state_key_set"] = shop.state_keys.available()
    data["data_dir"] = str(shop.data_dir if shop.data_dir is not None else user_data_dir())
    data["disclaimer"] = DISCLAIMER
    return data


@router.get("/settings")
def settings_get(request: Request) -> dict[str, object]:
    """09 §6.2: Einstellungen (``sni:settings``); gibb-Key nie als Antwort."""
    shop = _shop(request)
    return _settings_payload(shop, load_settings(shop.data_dir))


@router.put("/settings")
def settings_put(payload: SettingsRequest, request: Request) -> JSONResponse:
    """09 §6.2: Einstellungen aktualisieren (Teilmenge); gibb-Key → Keyring.

    Reihenfolge: Keyring-Vorgang erst, dann Persistenz — bei Keyring-
    Fehler (500) bleibt ``workspace.json`` unverändert.
    """
    shop = _shop(request)
    updates = {
        key: value
        for key, value in payload.model_dump().items()
        if value is not None and key != "gibb_key"
    }
    try:
        if payload.gibb_key is not None and payload.gibb_key.strip():
            GibbApiKeyStore().store(payload.gibb_key)
        data = update_settings(shop.data_dir, updates)
    except ValueError as exc:
        return _error(400, str(exc))
    except KeyringUnavailableError as exc:
        return _error(500, str(exc))
    return JSONResponse(_settings_payload(shop, data))


# ------------------------------------------------------------------ Arbeitssets (REQ-808)


@router.get("/worksets")
def worksets_list(request: Request) -> list[dict[str, object]]:
    """09 §6.2: Arbeitssets → ``[sni:workset]`` (Einfüge-Reihenfolge)."""
    store = _shop(request).worksets
    return [{"name": name, "document_ids": list(store.documents(name))} for name in store.names()]


@router.post("/worksets")
def worksets_create(payload: WorksetCreateRequest, request: Request) -> JSONResponse:
    """09 §6.2: Arbeitsset anlegen (idempotent wie Java ``computeIfAbsent``)."""
    shop = _shop(request)
    try:
        name = valid_name(payload.name)
        shop.worksets.create(name)
    except ValueError as exc:
        return _error(400, str(exc))
    shop.save_worksets()
    return JSONResponse(
        {
            "name": name,
            "document_ids": list(shop.worksets.documents(name)),
            "disclaimer": DISCLAIMER,
        }
    )


@router.put("/worksets/{name}")
def worksets_update(name: str, payload: WorksetUpdateRequest, request: Request) -> JSONResponse:
    """09 §6.2: Dokument-Liste ersetzen (ungültige Id → 400, Liste unverändert)."""
    shop = _shop(request)
    store = shop.worksets
    try:
        workset_name = valid_name(name)
        store.create(workset_name)
        for document_id in payload.document_ids:
            valid_document_id(document_id)
    except ValueError as exc:
        return _error(400, str(exc))
    for document_id in list(store.documents(workset_name)):
        store.remove(workset_name, document_id)
    for document_id in payload.document_ids:
        store.add(workset_name, document_id)
    shop.save_worksets()
    return JSONResponse(
        {
            "name": workset_name,
            "document_ids": list(store.documents(workset_name)),
            "disclaimer": DISCLAIMER,
        }
    )


@router.delete("/worksets/{name}")
def worksets_delete(name: str, request: Request) -> JSONResponse:
    """09 §6.2: Arbeitsset löschen (idempotent wie Java ``remove``)."""
    shop = _shop(request)
    if name in shop.worksets.names():
        shop.worksets.delete(name)
        shop.save_worksets()
    return JSONResponse({"ok": True, "disclaimer": DISCLAIMER})


# ------------------------------------------------------------------ Semantik-Export (REQ-810)


@router.post("/ingest/semantic-export")
def semantic_export_endpoint(payload: SemanticExportRequest, request: Request) -> JSONResponse:
    """09 §6.2: Deterministischer Semantik-Export → ``document.json`` → Ingest in-process.

    1:1 Java ``IntelligencePanel.runExport``: Konzepte aus dem Datenkatalog
    (``ConceptStore``), Volltextseiten aus dem lokalen Index; die Antwort
    enthält nur Norm-ID, Kandidaten-/Gap-IDs, Zählungen und Gründe – nie
    Normtexte (G4).
    """
    bundle = _require_bundle(request)
    if isinstance(bundle, JSONResponse):
        return bundle
    state = bundle.registry.get(payload.norm_id)
    document = state.document if state is not None else None
    if document is None:
        return _error(404, f"Unbekanntes lokales Dokument: {payload.norm_id}")
    store: ConceptStore = request.app.state.store
    concepts: list[tuple[str, str]] = []
    for concept_id in store.concept_ids():
        concept = store.get_concept(concept_id)
        if concept is None:
            continue
        name: object = concept.get("name")
        name_de = str(name.get("de") or "") if isinstance(name, dict) else ""
        concepts.append((concept_id, name_de))
    if not concepts:
        return _error(400, "Katalog ist leer – zuerst Snapshot importieren.")
    pages = bundle.pipeline.pages(payload.norm_id)
    if not pages:
        return _error(400, "Keine Volltextseiten: Norm zuerst indexieren.")
    try:
        result = semantic_export(
            default_norms_dir(), document.number, document.year, list(pages), concepts
        )
    except ValueError as exc:
        return _error(400, str(exc))
    try:
        document_json = load_document(result.norm_id)
        ingested = ingest_document(document_json, store, default_queue_dir())
    except IngestError as exc:
        return _error(400, exc.report[0] if exc.report else str(exc))
    return JSONResponse(
        {
            "norm_id": result.norm_id,
            "candidates": [str(candidate["id"]) for candidate in ingested.candidates],
            "skipped": list(result.skipped_reasons),
            "gaps": [str(gap["id"]) for gap in ingested.gap_reports],
            "disclaimer": DISCLAIMER,
        }
    )


# ------------------------------------------------------------------ Review-Queue (REQ-809)


@router.get("/review/queue")
def review_queue_list(request: Request) -> JSONResponse:
    """09 §6.2: Review-Queue — Kandidaten (``review_status=candidate``) + offene Gaps."""
    candidates, gaps = list_queue()
    return JSONResponse({"candidates": candidates, "gaps": gaps, "disclaimer": DISCLAIMER})


@router.post("/review/{obj_id:path}/approve")
def review_approve_endpoint(
    obj_id: str, payload: ReviewApproveRequest, request: Request
) -> JSONResponse:
    """09 §6.2: Kandidat freigeben (G3: menschlicher Akt, ADR-0008).

    ``approved_by``: explizit im Request (Override im Dialog) oder die
    konfigurierte Freigabeperson (Settings ``approval_name``); fehlt
    beides → 400 (die UI fragt dann einmalig nach und speichert sie).
    """
    shop = _shop(request)
    approver = (payload.approved_by or "").strip()
    if not approver:
        approver = str(load_settings(shop.data_dir).get("approval_name") or "").strip()
    try:
        result = review_approve(obj_id, approver)
    except ReviewError as exc:
        return _error(400, str(exc))
    return JSONResponse(
        {
            "id": obj_id,
            "status": "approved",
            "approved_by": str(result.get("approved_by") or ""),
            "approved_at": str(result.get("approved_at") or ""),
            "disclaimer": DISCLAIMER,
        }
    )


@router.post("/review/{obj_id:path}/reject")
def review_reject_endpoint(obj_id: str, request: Request) -> JSONResponse:
    """09 §6.2: Queue-Objekt verwerfen (G3; Java 1:1: Kandidaten und Gaps)."""
    try:
        review_reject(obj_id)
    except ReviewError as exc:
        return _error(400, str(exc))
    return JSONResponse({"id": obj_id, "status": "rejected", "disclaimer": DISCLAIMER})
