"""App-Shop-Zustand (M8.2): Login-Sitzung + lokale Dokumente.

Verbindet die Kernkomponenten (``sni.shop``, ``sni.documents``,
``sni.secrets``) für die App-API (09_CONSUMER_APP.md §6.2). Die
Bundle-Lebenszeit ist die Login-Sitzung (G4: PDFs sind sessionsgebunden):
Login erzeugt Produkt-Service, Session-PDF-Cache, Dokument-Registry und
Download-Queue; Logout wirft alles weg (Zeroing).

Der SOAP-Client ist pro Provider konstruiert (``SiaSoapClient.for_provider``);
``client_factory`` ist der Test-Injection-Punkt (Fake-Client, REQ-803).
"""

from __future__ import annotations

import contextlib
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from sni.documents.analysis import OLLAMA_URL, DocumentAnalysisPipeline
from sni.documents.downloads import DownloadService, Job, JobKind, JobStatus
from sni.documents.pdfcache import SessionDocumentCache
from sni.documents.registry import LocalDocumentRegistry
from sni.models.ollama_manager import OllamaModelManager
from sni.secrets.keyring_store import SialLoginStore
from sni.shop.catalog import CatalogStore
from sni.shop.providers import PHGR, SIA, SWKI, VSS, ProviderProfile
from sni.shop.service import LicenseSession, LoginOutcome, SessionCredentials, SiaProductService
from sni.shop.soap import SiaSoapClient
from sni.state.index_cache import EncryptedIndexCache
from sni.state.keys import ChainedStateKeyProvider, default_state_keys
from sni.state.paths import index_dir

#: App-Provider (09 §6.2: ``{provider, ...}`` — kurze, klein geschriebene Keys).
PROVIDERS: dict[str, ProviderProfile] = {
    "sia": SIA,
    "vss": VSS,
    "phgr": PHGR,
    "swki": SWKI,
}

#: Produktions-Timeouts, 1:1 zu ``SiaProductService._production_client``.
CONNECT_TIMEOUT = 10.0
REQUEST_TIMEOUT = 30.0


class ShopLoginError(RuntimeError):
    """Login fehlgeschlagen — 1:1-Meldung und Protokollcode (G6)."""

    def __init__(self, message: str, protocol: str | None) -> None:
        super().__init__(message)
        self.message = message
        self.protocol = protocol


def resolve_provider(name: str) -> ProviderProfile:
    """Provider-Name → Profil; ``ValueError`` bei unbekanntem Namen."""
    profile = PROVIDERS.get(name.strip().lower())
    if profile is None:
        raise ValueError(f"Unbekannter Provider: {name!r}")
    return profile


@dataclass(frozen=True, slots=True)
class ShopBundle:
    """Alle Shop-Komponenten einer Login-Sitzung (Bundle == Sitzung, G4)."""

    provider: ProviderProfile
    product_service: SiaProductService
    session: LicenseSession
    cache: SessionDocumentCache
    registry: LocalDocumentRegistry
    pipeline: DocumentAnalysisPipeline
    downloads: DownloadService


class ShopState:
    """App-Shop-Zustand (``app.state.shop``); pro App-Prozess eine Instanz."""

    def __init__(
        self,
        client_factory: Callable[[ProviderProfile], SiaSoapClient] | None = None,
        login_store: SialLoginStore | None = None,
        data_dir: Path | None = None,
        state_keys: ChainedStateKeyProvider | None = None,
    ) -> None:
        self._client_factory = client_factory or _production_client
        self._login_store = login_store if login_store is not None else SialLoginStore()
        self._data_dir = data_dir
        self._state_keys = state_keys if state_keys is not None else default_state_keys()
        self._bundle: ShopBundle | None = None
        # REQ-806: Modell-Pull-Jobs (eigene Queue, Login-unabhängig — Java
        # verwaltete Modelle in separater App/Queue; max. 1 paralleler Pull).
        self._pull_jobs: dict[str, Job] = {}
        self._pull_lock = threading.RLock()
        self._pull_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sni-model-pull")

    # ------------------------------------------------------------------ Zugriff

    @property
    def bundle(self) -> ShopBundle | None:
        """Aktives Sitzungs-Bundle; ``None``, wenn nicht eingeloggt."""
        return self._bundle

    @property
    def is_logged_in(self) -> bool:
        return self._bundle is not None

    @property
    def login_store(self) -> SialLoginStore:
        """Keyring-Store für ``remember`` (Merken-Checkbox, REQ-802)."""
        return self._login_store

    @property
    def data_dir(self) -> Path | None:
        """User-Datenverzeichnis (``SIA_DATA_DIR``/Injektion); ``None`` = Default."""
        return self._data_dir

    # ------------------------------------------------------------------ Modell-Pull (REQ-806)

    def submit_pull(
        self,
        model: str,
        manager: OllamaModelManager | None = None,
    ) -> Job:
        """Reicht einen Modell-Download-Job ein (2-h-Timeout wie Java).

        Login-unabhängig (lokale Modelle); max. 1 paralleler Pull-Job.
        NDJSON-Statuszeilen → ``Job.progress`` (UI pollt ``/v1/jobs``).
        """
        job = Job(id=uuid.uuid4().hex, kind=JobKind.PULL, document_id=None)
        with self._pull_lock:
            self._pull_jobs[job.id] = job
        self._pull_executor.submit(self._run_pull, job.id, model, manager)
        return job

    def pull_jobs(self) -> list[Job]:
        """Pull-Jobs in Einreichungs-Reihenfolge (``/v1/jobs``-Quelle)."""
        with self._pull_lock:
            return list(self._pull_jobs.values())

    def _run_pull(
        self,
        job_id: str,
        model: str,
        manager: OllamaModelManager | None,
    ) -> None:
        self._update_pull(job_id, status=JobStatus.RUNNING, progress="Modell wird geladen …")
        try:
            mgr = manager if manager is not None else OllamaModelManager(OLLAMA_URL)
            mgr.pull(model, progress=lambda status: self._update_pull(job_id, progress=status))
            self._update_pull(job_id, status=JobStatus.DONE, progress="Modell lokal installiert")
        except Exception as exc:  # noqa: BLE001 — Job-Endzustand, nie Crash
            self._update_pull(job_id, status=JobStatus.ERROR, error=f"{type(exc).__name__}: {exc}")

    def _update_pull(
        self,
        job_id: str,
        status: JobStatus | None = None,
        progress: str | None = None,
        error: str | None = None,
    ) -> None:
        with self._pull_lock:
            job = self._pull_jobs.get(job_id)
            if job is None:
                return
            self._pull_jobs[job_id] = Job(
                id=job.id,
                kind=job.kind,
                document_id=job.document_id,
                status=status if status is not None else job.status,
                progress=progress if progress is not None else job.progress,
                error=error if error is not None else job.error,
            )

    # ------------------------------------------------------------------ Sitzung

    def login(
        self,
        profile: ProviderProfile,
        customer: str,
        password: str,
        device_id: str,
    ) -> tuple[ShopBundle, LoginOutcome]:
        """Login (ECHO + SOAP + .mro); wirft ``ShopLoginError`` (1:1-Protokoll).

        Ein erneuter Login wirft die vorherige Sitzung weg (Zeroing).
        """
        self.logout()
        service = SiaProductService(CatalogStore(), lambda: self._client_factory(profile))
        credentials = SessionCredentials(customer, password, device_id)
        outcome = service.login(credentials)
        if not outcome.success or outcome.session is None:
            raise ShopLoginError(outcome.message, _protocol_of(outcome))
        session = outcome.session
        cache = SessionDocumentCache()
        registry = LocalDocumentRegistry()
        pipeline = DocumentAnalysisPipeline()
        index_cache = EncryptedIndexCache(
            (self._data_dir / "index") if self._data_dir is not None else index_dir(),
            self._state_keys,
        )
        pipeline.attach_index_cache(index_cache)
        bundle = ShopBundle(
            provider=profile,
            product_service=service,
            session=session,
            cache=cache,
            registry=registry,
            pipeline=pipeline,
            downloads=DownloadService(service, cache, registry, pipeline=pipeline),
        )
        self._bundle = bundle
        return bundle, outcome

    def logout(self) -> None:
        """Sitzung verwerfen (Zeroing): Session, PDF-Cache, Registry, Queue.

        Laufende Jobs werden nicht abgewartet; sie enden selbstständig
        (geschlossene Session → Download wirft). Eingereihte Jobs werden
        abgebrochen (cancel_futures).
        """
        bundle = self._bundle
        self._bundle = None
        if bundle is None:
            return
        with contextlib.suppress(Exception):
            bundle.downloads.close(wait=False, cancel_futures=True)
            bundle.session.close()  # Credentials + SRD-Key/IV (Zeroing)
            bundle.cache.close()  # PDFs + Sitzungsschlüssel (Zeroing)
        for state in list(bundle.registry.all()):
            bundle.registry.remove(state.document.product_id)


def _protocol_of(outcome: LoginOutcome) -> str | None:
    """SIA-Protokollcode 1:1 (09 §6.2), z. B. ``Fail_Wrong_PWD``."""
    if outcome.status is None:
        return None
    return outcome.status.server_code


def _production_client(profile: ProviderProfile) -> SiaSoapClient:
    """Produktions-Client (Java: ``new SiaSoapClient(provider, "https", 10s, 30s)``)."""
    return SiaSoapClient.for_provider(profile, "https", CONNECT_TIMEOUT, REQUEST_TIMEOUT)
