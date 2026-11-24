"""REQ-803: Download-Jobs (``sni.documents.downloads``).

Orchestrierungs-Tests: ``SiaProductService.download`` →
``SessionDocumentCache`` → ``LocalDocumentRegistry`` (Status
``CACHED``/``ERROR``) sowie die Queue-Semantik nach
09_CONSUMER_APP.md §6.2 (max. 1 paralleler Job, Polling-Ablichtung).
Vollkette mit synthetischen .mro/.srd (G4).
"""

from __future__ import annotations

import itertools
import threading
import time
from collections.abc import Callable

import pytest

from sni.documents.downloads import DownloadService, Job, JobKind, JobStatus
from sni.documents.pdfcache import SessionDocumentCache
from sni.documents.registry import LocalDocumentRegistry, LocalDocumentStatus
from sni.shop.catalog import CatalogStore
from sni.shop.models import DocumentResult, LoginResult
from sni.shop.service import LicenseSession, SessionCredentials, SiaProductService
from tests.conftest import (
    LICENSE_XML,
    FakeSoapClient,
    document_result_ok,
    login_result_ok,
    make_mro,
    make_pdf,
    make_srd,
)


class _BlockingFakeClient(FakeSoapClient):
    """Client, dessen ``get_document`` auf ein Event wartet (Queue-Tests)."""

    def __init__(
        self,
        gate: threading.Event,
        login_result: LoginResult,
        license_bytes: bytes | None = None,
        document_result: DocumentResult | None = None,
        srd_bytes: bytes | None = None,
    ) -> None:
        super().__init__(login_result, license_bytes, document_result, srd_bytes)
        self._gate = gate

    def get_document(
        self,
        produkt_id: str,
        customer_number_or_username: str,
        password: str,
        device_id: str,
    ) -> DocumentResult:
        self._gate.wait(10)
        return super().get_document(produkt_id, customer_number_or_username, password, device_id)


def _job(downloads: DownloadService, job_id: str) -> Job:
    job = downloads.get(job_id)
    assert job is not None
    return job


def _wait_for(
    downloads: DownloadService, job_id: str, wanted: set[JobStatus], timeout: float = 10.0
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _job(downloads, job_id).status in wanted:
            return
        time.sleep(0.01)
    pytest.fail(f"Job {job_id} nicht in Zielstatus nach {timeout} s")


class _Stack:
    """Test-Setup: Service + Cache + Registry + Download-Service."""

    def __init__(
        self, client: FakeSoapClient, job_id_factory: Callable[[], str] | None = None
    ) -> None:
        self.service = SiaProductService(CatalogStore(), lambda: client)
        self.cache = SessionDocumentCache()
        self.registry = LocalDocumentRegistry()
        self.downloads = DownloadService(
            self.service, self.cache, self.registry, job_id_factory=job_id_factory
        )

    def login(self) -> LicenseSession:
        credentials = SessionCredentials("kunde1", "geheim", "dev-1")
        outcome = self.service.login(credentials)
        assert outcome.success and outcome.session is not None
        return outcome.session

    def close(self) -> None:
        self.downloads.close()
        self.cache.close()


def test_req803_download_success_full_chain() -> None:
    pdf = make_pdf(["SYN 1  Testnorm"])
    stack = _Stack(
        FakeSoapClient(
            login_result_ok(),
            make_mro(LICENSE_XML),
            document_result_ok("101.srd"),
            make_srd("prod-101", pdf),
        )
    )
    try:
        session = stack.login()
        job = stack.downloads.submit(session, "prod-101")
        assert job.kind is JobKind.DOWNLOAD
        assert job.document_id == "prod-101"
        assert job.status is JobStatus.QUEUED

        _wait_for(stack.downloads, job.id, {JobStatus.DONE, JobStatus.ERROR})
        final = _job(stack.downloads, job.id)
        assert final.status is JobStatus.DONE
        assert final.error is None
        assert stack.cache.get("prod-101") == pdf  # PDF im Session-Cache
        state = stack.registry.get("prod-101")
        assert state is not None
        assert state.status is LocalDocumentStatus.CACHED  # Statusfluss: CACHED
    finally:
        stack.close()


def test_req803_download_unknown_product_errors_without_registry_entry() -> None:
    stack = _Stack(FakeSoapClient(login_result_ok(), make_mro(LICENSE_XML)))
    try:
        session = stack.login()
        job = stack.downloads.submit(session, "unbekannt")
        _wait_for(stack.downloads, job.id, {JobStatus.DONE, JobStatus.ERROR})
        final = _job(stack.downloads, job.id)
        assert final.status is JobStatus.ERROR
        assert final.error == "Produkt nicht im Katalog"
        assert stack.registry.all() == []  # kein Katalog-Dokument → kein Eintrag
    finally:
        stack.close()


def test_req803_download_view_not_allowed_marks_registry_error() -> None:
    stack = _Stack(FakeSoapClient(login_result_ok(), make_mro(LICENSE_XML)))
    try:
        session = stack.login()
        job = stack.downloads.submit(session, "prod-102")  # Recht_View=0
        _wait_for(stack.downloads, job.id, {JobStatus.DONE, JobStatus.ERROR})
        final = _job(stack.downloads, job.id)
        assert final.status is JobStatus.ERROR
        assert final.error == "Anzeige laut Lizenz nicht erlaubt"
        state = stack.registry.get("prod-102")
        assert state is not None
        assert state.status is LocalDocumentStatus.ERROR
        assert state.detail == "Anzeige laut Lizenz nicht erlaubt"
    finally:
        stack.close()


def test_req803_download_closed_session_errors_job() -> None:
    stack = _Stack(FakeSoapClient(login_result_ok(), make_mro(LICENSE_XML)))
    try:
        session = stack.login()
        session.close()
        job = stack.downloads.submit(session, "prod-101")
        _wait_for(stack.downloads, job.id, {JobStatus.DONE, JobStatus.ERROR})
        final = _job(stack.downloads, job.id)
        assert final.status is JobStatus.ERROR
        assert final.error is not None and final.error.startswith("RuntimeError:")
        state = stack.registry.get("prod-101")
        assert state is not None and state.status is LocalDocumentStatus.ERROR
    finally:
        stack.close()


def test_req803_download_queue_max_one_parallel() -> None:
    gate = threading.Event()
    pdf = make_pdf(["SYN 1  Testnorm"])
    stack = _Stack(
        _BlockingFakeClient(
            gate,
            login_result_ok(),
            make_mro(LICENSE_XML),
            document_result_ok("101.srd"),
            make_srd("prod-101", pdf),
        )
    )
    try:
        session = stack.login()
        job1 = stack.downloads.submit(session, "prod-101")
        _wait_for(stack.downloads, job1.id, {JobStatus.RUNNING, JobStatus.ERROR})
        assert _job(stack.downloads, job1.id).status is JobStatus.RUNNING  # Gate zu

        job2 = stack.downloads.submit(session, "prod-102")
        assert _job(stack.downloads, job2.id).status is JobStatus.QUEUED  # 1 parallel

        gate.set()
        _wait_for(stack.downloads, job1.id, {JobStatus.DONE, JobStatus.ERROR})
        _wait_for(stack.downloads, job2.id, {JobStatus.DONE, JobStatus.ERROR})
        assert _job(stack.downloads, job1.id).status is JobStatus.DONE
        assert _job(stack.downloads, job2.id).status is JobStatus.ERROR  # view
        state = stack.registry.get("prod-101")
        assert state is not None and state.status is LocalDocumentStatus.CACHED
    finally:
        stack.close()


def test_req803_download_jobs_listing_in_submit_order() -> None:
    counter = itertools.count(1)
    client = FakeSoapClient(login_result_ok(), make_mro(LICENSE_XML), None, None)
    stack = _Stack(client, job_id_factory=lambda: f"job-{next(counter)}")
    try:
        session = stack.login()
        job1 = stack.downloads.submit(session, "prod-101")
        job2 = stack.downloads.submit(session, "unbekannt")
        _wait_for(stack.downloads, job1.id, {JobStatus.DONE, JobStatus.ERROR})
        _wait_for(stack.downloads, job2.id, {JobStatus.DONE, JobStatus.ERROR})
        assert [j.id for j in stack.downloads.jobs()] == ["job-1", "job-2"]
        assert stack.downloads.get("unbekannt-job") is None
    finally:
        stack.close()


def test_req803_download_close_waits_for_running_job() -> None:
    gate = threading.Event()
    pdf = make_pdf(["SYN 1  Testnorm"])
    stack = _Stack(
        _BlockingFakeClient(
            gate,
            login_result_ok(),
            make_mro(LICENSE_XML),
            document_result_ok("101.srd"),
            make_srd("prod-101", pdf),
        )
    )
    try:
        session = stack.login()
        job = stack.downloads.submit(session, "prod-101")
        _wait_for(stack.downloads, job.id, {JobStatus.RUNNING, JobStatus.ERROR})
        assert _job(stack.downloads, job.id).status is JobStatus.RUNNING

        threading.Timer(0.1, gate.set).start()
        stack.downloads.close()  # wartet auf den laufenden Job
        assert _job(stack.downloads, job.id).status is JobStatus.DONE
    finally:
        stack.close()
