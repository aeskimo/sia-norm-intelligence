"""Dokument-Download-Jobs (REQ-803): ``.srd`` → DES → PDF im Session-Cache.

Orchestriert den Download-Flow: ``SiaProductService.download`` (SOAP +
DES-Dekodierung + PDF-Signaturcheck) → ``SessionDocumentCache.put``
(AES-256-GCM) → ``LocalDocumentRegistry.cached`` (Status ``CACHED``);
Fehler → ``LocalDocumentRegistry.error`` (Status ``ERROR``).

Job-Vertrag nach 09_CONSUMER_APP.md §6.2: eine Queue, max. 1 paralleler
Job (Consumer-Maschine), Status ``queued|running|done|error``, Abfrage
per Polling (UI pollt alle 2 s). Java-Referenz:
``SiaProductService.download`` (synchron im GUI-Thread) — der asynchrone
Job ist die App-Erweiterung, die Download-Logik bleibt 1:1.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import StrEnum

from sni.documents.analysis import DocumentAnalysisPipeline
from sni.documents.pdfcache import SessionDocumentCache
from sni.documents.registry import LocalDocumentRegistry
from sni.shop.catalog_xml import StandardDocument
from sni.shop.service import LicenseSession, SiaProductService


class JobKind(StrEnum):
    """Job-Art (Schema ``sni:job``; ``analyze``/``pull`` ab M8.3/M8.4)."""

    DOWNLOAD = "download"
    ANALYZE = "analyze"
    PULL = "pull"


class JobStatus(StrEnum):
    """Job-Status (Schema ``sni:job``)."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Job:
    """Jobsatz (Schema ``sni:job``)."""

    id: str
    kind: JobKind
    document_id: str | None
    status: JobStatus = JobStatus.QUEUED
    progress: str | None = None
    error: str | None = None


class DownloadService:
    """Job-Orchestrierung für Dokument-Downloads (REQ-803).

    ``submit`` legt den Job an (Status ``queued``) und reicht ihn in die
    Queue ein (max. 1 paralleler Job). Das Job-Body ruft
    ``SiaProductService.download`` auf und legt das PDF bei Erfolg im
    Session-Cache ab; die Registry wechselt von ``CACHED`` (Erfolg) zu
    ``ERROR`` (Fehler).
    """

    def __init__(
        self,
        product_service: SiaProductService,
        cache: SessionDocumentCache,
        registry: LocalDocumentRegistry,
        *,
        job_id_factory: Callable[[], str] | None = None,
        pipeline: DocumentAnalysisPipeline | None = None,
    ) -> None:
        self._service = product_service
        self._cache = cache
        self._registry = registry
        self._pipeline = pipeline
        self._job_id_factory: Callable[[], str] = job_id_factory or (lambda: uuid.uuid4().hex)
        self._jobs: dict[str, Job] = {}
        self._lock = threading.RLock()
        # 09 §6.2: max. 1 paralleler Job (Consumer-Maschine).
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sni-download")

    # ------------------------------------------------------------------ öffentlich

    def submit(self, session: LicenseSession, product_id: str) -> Job:
        """Reicht einen Download-Job ein und liefert ihn im Status ``queued``."""
        job = Job(id=self._job_id_factory(), kind=JobKind.DOWNLOAD, document_id=product_id)
        with self._lock:
            self._jobs[job.id] = job
        self._executor.submit(self._run, job.id, session, product_id)
        return job

    def submit_analyze(self, product_id: str, embedding_model: str = "") -> Job:
        """Reicht einen Analyse-Job ein (REQ-804): Extraktion → Volltext → Vektoren.

        Gleiche Queue wie Downloads (09 §6.2: max. 1 paralleler Job);
        ``embedding_model`` leer → nur Volltextindex.
        """
        job = Job(id=self._job_id_factory(), kind=JobKind.ANALYZE, document_id=product_id)
        with self._lock:
            self._jobs[job.id] = job
        self._executor.submit(self._run_analyze, job.id, product_id, embedding_model)
        return job

    def get(self, job_id: str) -> Job | None:
        """Job nach ID (None, wenn unbekannt)."""
        with self._lock:
            return self._jobs.get(job_id)

    def jobs(self) -> list[Job]:
        """Ablichtung aller Jobs in Einreichungs-Reihenfolge (Polling-Quelle)."""
        with self._lock:
            return list(self._jobs.values())

    def close(self, wait: bool = True, cancel_futures: bool = False) -> None:
        """Stoppt die Queue.

        ``wait=True`` (Default): wartet auf den laufenden Job (App-Ende).
        ``cancel_futures=True`` (App-Logout): wartet nicht und bricht
        eingereihte Jobs ab — ein laufender Job endet selbstständig, weil
        die geschlossene Session die Download-Aufrufe wirft.
        """
        self._executor.shutdown(wait=wait, cancel_futures=cancel_futures)

    # ------------------------------------------------------------------ intern

    def _run(self, job_id: str, session: LicenseSession, product_id: str) -> None:
        document = self._service.catalog.by_id(product_id)
        self._update(job_id, status=JobStatus.RUNNING, progress="Lade Dokument …")
        try:
            outcome = self._service.download(session, product_id)
            if not outcome.success or outcome.pdf is None:
                self._fail(job_id, document, outcome.message)
                return
            try:
                self._cache.put(product_id, outcome.pdf)
            finally:
                outcome.wipe()  # Java: Arrays.fill(pdf, 0) nach Übergabe an den Cache
            if document is not None:
                self._registry.cached(document)
            self._update(job_id, status=JobStatus.DONE, progress="PDF im Sitzungscache")
        except Exception as exc:  # noqa: BLE001 — Java: catch (Exception ex)
            self._fail(job_id, document, f"{type(exc).__name__}: {exc}")

    def _run_analyze(self, job_id: str, product_id: str, embedding_model: str) -> None:
        """Analyse-Job (REQ-804): Session-PDF → Pipeline → Registry-Status.

        Fehler (z. B. textloses PDF, OQ-015) landen als ``ERROR`` mit
        Detail in der Registry — UI-sichtbar (Fehlermeldung nie mit
        Schlüsselmaterial, G4).
        """
        pipeline = self._pipeline
        if pipeline is None:
            self._fail(job_id, None, "Analyse-Pipeline ist nicht angeschlossen")
            return
        document = self._service.catalog.by_id(product_id)
        self._update(job_id, status=JobStatus.RUNNING, progress="Dokument wird analysiert …")
        try:
            pdf = self._cache.get(product_id)
            if pdf is None:
                self._fail(job_id, document, "PDF nicht im Sitzungscache")
                return
            if document is None:
                self._fail(job_id, None, "Dokument unbekannt im Katalog")
                return
            self._registry.indexing(document)
            try:
                result = pipeline.index(
                    document,
                    pdf,
                    embedding_model,
                    progress=lambda message: self._update(job_id, progress=message),
                )
            finally:
                # Bytes verbleiben im verschlüsselten Session-Cache (G4).
                del pdf
            self._registry.indexed(document, result.pages, result.embeddings_ready, result.message)
            self._update(job_id, status=JobStatus.DONE, progress=result.message)
        except Exception as exc:  # noqa: BLE001 — Java: catch (Exception ex)
            detail = f"{type(exc).__name__}: {exc}"
            if document is not None:
                self._registry.error(document, detail)
            self._update(job_id, status=JobStatus.ERROR, error=detail)

    def _fail(self, job_id: str, document: StandardDocument | None, message: str | None) -> None:
        """Job und Registry im Fehlerzustand (Fehlermeldung nie mit Schlüsselmaterial, G4)."""
        detail = message if message is not None else "Download fehlgeschlagen"
        if document is not None:
            self._registry.error(document, detail)
        self._update(job_id, status=JobStatus.ERROR, error=detail)

    def _update(
        self,
        job_id: str,
        status: JobStatus | None = None,
        progress: str | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            job = self._jobs[job_id]
            self._jobs[job_id] = Job(
                id=job.id,
                kind=job.kind,
                document_id=job.document_id,
                status=status if status is not None else job.status,
                progress=progress if progress is not None else job.progress,
                error=error if error is not None else job.error,
            )
