"""App-Router (M8.1 REQ-800, M8.2 REQ-803): App-Zustand + Shop-Endpunkte.

Wird nur im App-Modus von ``sni.app.server.build_app`` gemountet; die
Kern-API (``sni.api.main``) bleibt unverändert (Schichten-Regel).
Alle Antworten tragen den G6-Disclaimer.

Endpunkte (09_CONSUMER_APP.md §6.2): Login/Logout, Katalog, Download
(async Job), lokale Dokumente (Liste, PDF, Entfernen), Jobs, Status.
"""

from __future__ import annotations

import contextlib
from typing import Literal, cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from sni.api.main import DISCLAIMER
from sni.app import APP_VERSION
from sni.app.shop import (
    ShopBundle,
    ShopLoginError,
    ShopState,
    resolve_provider,
)
from sni.documents.downloads import Job
from sni.documents.pdfcache import CacheIntegrityError
from sni.documents.registry import LocalDocumentState
from sni.shop.catalog_xml import StandardDocument

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
