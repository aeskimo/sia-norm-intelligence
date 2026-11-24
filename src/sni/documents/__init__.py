"""Lokale Dokumentverwaltung (M8.2, REQ-803).

Session-PDF-Cache (AES-256-GCM, AAD=Dokument-ID), lokale
Dokument-Registry (Status ``CACHED→INDEXING→FULLTEXT_READY/
HYBRID_READY/ERROR``) und Download-Jobs (``.srd``→DES→PDF).

G4: entschlüsselte Inhalte sind strikt sessionsgebunden und
verbleiben im Prozess (kein Disk-Zwischenspeicher).
"""

from sni.documents.downloads import DownloadService, Job, JobKind, JobStatus
from sni.documents.pdfcache import CacheIntegrityError, SessionCacheError, SessionDocumentCache
from sni.documents.registry import (
    LocalDocumentRegistry,
    LocalDocumentState,
    LocalDocumentStatus,
)

__all__ = [
    "CacheIntegrityError",
    "DownloadService",
    "Job",
    "JobKind",
    "JobStatus",
    "LocalDocumentRegistry",
    "LocalDocumentState",
    "LocalDocumentStatus",
    "SessionCacheError",
    "SessionDocumentCache",
]
