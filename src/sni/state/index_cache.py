"""Verschlüsselter Index-Cache SIAIDX01 (REQ-815, ADR-0011).

1:1-Port von ``ch.sia.integration.indexcache`` (Java-Referenz:
``IndexCacheEntry``, ``IndexCacheCodec``, ``EncryptedIndexCache``):

- Eine Datei pro Norm im Verzeichnis ``index/``:
  ``<stem>.sniidx`` (Java: ``.siaidx`` — gleicher Codec + gleicher
  Schlüssel, nur die Dateinamens-Erweiterung neu, daher ist die
  Migration ein Umbenennen).
- AES-256-GCM: 12-Byte-Nonce je Speicherung, **AAD =
  ``stem(product_id)``** — versehentlich vertauschte Dateien werden
  abgelehnt.
- Zeilenformat mit Base64-URL-Feldern (gleiche Konvention wie
  ``WorkspaceCodec``); Vektoren als IEEE-754 Float-32 Big-Endian
  (halber Speicherbedarf gegenüber Double).
- Ohne Statusschlüssel bleibt der Cache bewusst inaktiv: die Normen
  sind dann nur an die Sitzung gebunden, kein Klartext auf Disk (G4).
"""

from __future__ import annotations

import base64
import contextlib
import os
import re
import struct
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from sni.search.page_source import PageSource
from sni.search.vectors import VectorEntry
from sni.shop.catalog_xml import StandardDocument
from sni.state.keys import StateKeyProvider
from sni.state.paths import index_dir

#: Datei-Magic (Java 1:1, byte-identisch): ``SIAIDX01``.
MAGIC = b"SIAIDX01"
#: AES-GCM-Nonce-Länge.
NONCE_LENGTH = 12
#: AES-GCM-Authentifizierungstag (128 Bit).
TAG_LENGTH = 16
#: Unterstütztes Codec-Format (Java: ``VERSION``).
_VERSION = 1
#: Plausibilitätsgrenzen (Java: ``100_000`` / ``10_000_000``).
_MAX_PAGES = 100_000
_MAX_VECTORS = 10_000_000
#: Java: ``productId.replaceAll("[^A-Za-z0-9._-]", "_")``.
_STEM_RE = re.compile(r"[^A-Za-z0-9._-]")
#: Python-Datei-Erweiterung (Java: ``.siaidx``).
_SUFFIX = ".sniidx"


class IndexCacheError(RuntimeError):
    """Indexdatei zu kurz oder falsches Format (Java: SecurityException)."""


def stem(product_id: str) -> str:
    """Dateiname abgeleitet von der Produkt-ID: nur Dateisystem-sichere Zeichen."""
    return _STEM_RE.sub("_", product_id)


def _enc_bytes(value: bytes) -> str:
    """Base64-URL ohne Padding (Java 1:1)."""
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _dec_bytes(value: str) -> bytes:
    """Java: ``Base64.getUrlDecoder()`` (toleriert fehlendes Padding)."""
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _enc(value: str) -> str:
    return _enc_bytes(value.encode("utf-8"))


def _dec(value: str) -> str:
    return _dec_bytes(value).decode("utf-8")


def _floats(vector: Sequence[float]) -> str:
    """Doubles → IEEE-754 Float-32 (Big-Endian) → Base64-URL (Java 1:1)."""
    raw = struct.pack(f">{len(vector)}f", *(float(v) for v in vector))
    return _enc_bytes(raw)


def _unfloats(value: str) -> tuple[float, ...]:
    """Umgekehrte Operation von :func:`_floats` (Java 1:1)."""
    raw = _dec_bytes(value)
    if not raw or len(raw) % 4 != 0:
        raise ValueError("Vektorlänge unplausibel")
    return struct.unpack(f">{len(raw) // 4}f", raw)


@dataclass(frozen=True, slots=True)
class IndexCacheEntry:
    """Snapshot des lokalen Indexes für eine Norm (Java: ``IndexCacheEntry``).

    Metadaten, Volltextseiten, aktives Embedding-Modell und optionale
    Vektoren — die Einheiten des verschlüsselten Index-Caches.
    """

    document: StandardDocument
    pages: tuple[PageSource, ...] = ()
    embedding_model: str = ""
    vectors: tuple[VectorEntry, ...] = ()


class IndexCacheCodec:
    """Zeilenformat mit Base64-URL-Feldern (Java: ``IndexCacheCodec``)."""

    def encode(self, entry: IndexCacheEntry) -> bytes:
        doc = entry.document
        lines = [f"version={_VERSION}"]
        lines.append(
            "doc="
            + "|".join(
                (
                    _enc(doc.product_id),
                    _enc(doc.number),
                    _enc(doc.title),
                    _enc(doc.description),
                    _enc(doc.keywords),
                    _enc(doc.language),
                    _enc(doc.year),
                    _enc(doc.revision),
                    _enc("" if doc.valid_from is None else doc.valid_from.isoformat()),
                    _enc("" if doc.valid_until is None else doc.valid_until.isoformat()),
                    _enc(doc.remote_filename),
                    "1" if doc.view_allowed else "0",
                    "1" if doc.print_allowed else "0",
                    "1" if doc.copy_allowed else "0",
                )
            )
        )
        lines.append(f"pages={len(entry.pages)}")
        for page in entry.pages:
            lines.append(
                "page="
                + "|".join(
                    (
                        _enc(page.document_id),
                        _enc(page.standard),
                        _enc(page.edition),
                        str(page.page),
                        _enc(page.section),
                        _enc(page.text),
                    )
                )
            )
        lines.append(f"model={_enc(entry.embedding_model)}")
        lines.append(f"vectors={len(entry.vectors)}")
        for item in entry.vectors:
            source = item.source
            lines.append(
                "vector="
                + "|".join(
                    (
                        _enc(source.document_id),
                        _enc(source.standard),
                        _enc(source.edition),
                        str(source.page),
                        _enc(source.section),
                        _enc(source.text),
                        _floats(item.vector),
                    )
                )
            )
        return ("\n".join(lines) + "\n").encode("utf-8")

    def decode(self, data: bytes) -> IndexCacheEntry:
        g = num = title = desc = kw = lang = year = rev = ""
        valid_from: date | None = None
        valid_until: date | None = None
        filename = ""
        view = print_ = copy_ = False
        version = 0
        pages: list[PageSource] = []
        model = ""
        vectors: list[VectorEntry] = []
        page_count = -1
        vector_count = -1
        for line in data.decode("utf-8").splitlines():
            if not line:
                continue
            eq = line.find("=")
            if eq < 0:
                raise ValueError("Ungültige Indexcache-Zeile")
            key, value = line[:eq], line[eq + 1 :]
            if key == "version":
                version = int(value)
            elif key == "doc":
                parts = value.split("|")
                if len(parts) != 14:
                    raise ValueError("Dokumentenfeld unvollständig")
                g = _dec(parts[0])
                num = _dec(parts[1])
                title = _dec(parts[2])
                desc = _dec(parts[3])
                kw = _dec(parts[4])
                lang = _dec(parts[5])
                year = _dec(parts[6])
                rev = _dec(parts[7])
                valid_from = None if parts[8] == "" else date.fromisoformat(_dec(parts[8]))
                valid_until = None if parts[9] == "" else date.fromisoformat(_dec(parts[9]))
                filename = _dec(parts[10])
                view = parts[11] == "1"
                print_ = parts[12] == "1"
                copy_ = parts[13] == "1"
            elif key == "pages":
                count = int(value)
                if count < 0 or count > _MAX_PAGES:
                    raise ValueError("Seitenzahl unplausibel")
                page_count = count
            elif key == "page":
                parts = value.split("|")
                if len(parts) != 6:
                    raise ValueError("Seitenfeld unvollständig")
                pages.append(
                    PageSource(
                        _dec(parts[0]),
                        _dec(parts[1]),
                        _dec(parts[2]),
                        int(parts[3]),
                        _dec(parts[4]),
                        _dec(parts[5]),
                    )
                )
            elif key == "model":
                model = _dec(value)
            elif key == "vectors":
                count = int(value)
                if count < 0 or count > _MAX_VECTORS:
                    raise ValueError("Vektoranzahl unplausibel")
                vector_count = count
            elif key == "vector":
                parts = value.split("|")
                if len(parts) != 7:
                    raise ValueError("Vektorfeld unvollständig")
                source = PageSource(
                    _dec(parts[0]),
                    _dec(parts[1]),
                    _dec(parts[2]),
                    int(parts[3]),
                    _dec(parts[4]),
                    _dec(parts[5]),
                )
                vectors.append(VectorEntry(source, _unfloats(parts[6])))
            else:
                raise ValueError(f"Unbekanntes Indexcache-Feld: {key}")
        if version != _VERSION:
            raise ValueError("Unterstütztes Indexcache-Format erwartet")
        if page_count != len(pages):
            raise ValueError("Seitenanzahl stimmt nicht überein")
        if vector_count != len(vectors):
            raise ValueError("Vektoranzahl stimmt nicht überein")
        if not g:
            raise ValueError("Dokumentenfeld fehlt")
        document = StandardDocument(
            g,
            num,
            title,
            desc,
            kw,
            lang,
            year,
            rev,
            valid_from,
            valid_until,
            filename,
            view,
            print_,
            copy_,
        )
        return IndexCacheEntry(document, tuple(pages), model, tuple(vectors))


class EncryptedIndexCache:
    """AES-256-GCM-Dateispeicher für lokale Index-Snapshots, eine Datei pro Norm.

    Der Verschlüsselungsschlüssel kommt aus der injizierten
    ``StateKeyProvider``-Kette (Umgebungsvariable, danach Keyring).
    Ohne verfügbaren Schlüssel bleibt der Cache inaktiv: kein
    Klartext auf Disk (G4).
    """

    def __init__(self, directory: Path, keys: StateKeyProvider) -> None:
        self._dir = directory.resolve()
        self._keys = keys
        self._codec = IndexCacheCodec()

    @property
    def directory(self) -> Path:
        return self._dir

    @staticmethod
    def default_directory() -> Path:
        """Java: ``~/.sia-normenassistent/index`` (Python: ``user_data_dir``)."""
        return index_dir()

    def available(self) -> bool:
        """Ohne Schlüssel bleibt der Cache inaktiv (Sitzungsbindung)."""
        try:
            return self._keys.available()
        except Exception:
            return False

    def file(self, product_id: str) -> Path:
        return self._dir / (stem(product_id) + _SUFFIX)

    def exists(self, product_id: str) -> bool:
        return self.available() and self.file(product_id).is_file()

    def save(self, entry: IndexCacheEntry) -> None:
        """Schreibt den Snapshot atomar; ohne Schlüssel bewusste leere Operation."""
        if not self.available():
            return
        aad = stem(entry.document.product_id).encode("utf-8")
        nonce = os.urandom(NONCE_LENGTH)
        plain = self._codec.encode(entry)
        payload = MAGIC + nonce + AESGCM(self._keys.load()).encrypt(nonce, plain, aad)
        self._dir.mkdir(parents=True, exist_ok=True)
        target = self.file(entry.document.product_id)
        fd, tmp_name = tempfile.mkstemp(prefix=".sniidx-", suffix=".tmp", dir=self._dir)
        try:
            with os.fdopen(fd, "wb") as tmp:
                tmp.write(payload)
            os.replace(tmp_name, target)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.remove(tmp_name)
            raise
        # Python-Bytes sind unveränderlich; «Zeroing» = Referenz freigegeben.
        del plain, payload

    def load(self, product_id: str) -> IndexCacheEntry | None:
        """Lädt den Snapshot; ``None``, wenn nicht vorhanden oder kein Schlüssel."""
        if not self.available():
            return None
        target = self.file(product_id)
        if not target.is_file():
            return None
        payload = target.read_bytes()
        try:
            if len(payload) < len(MAGIC) + NONCE_LENGTH + TAG_LENGTH:
                raise IndexCacheError("Indexdatei zu kurz")
            if payload[: len(MAGIC)] != MAGIC:
                raise IndexCacheError("Ungültiges Indexformat")
            nonce = payload[len(MAGIC) : len(MAGIC) + NONCE_LENGTH]
            data = payload[len(MAGIC) + NONCE_LENGTH :]
            aad = stem(product_id).encode("utf-8")
            # AAD-Verstoß / Manipulation → InvalidTag (Java: AEADBadTagException).
            plain = AESGCM(self._keys.load()).decrypt(nonce, data, aad)
            return self._codec.decode(plain)
        finally:
            del payload

    def delete(self, product_id: str) -> None:
        """Löst den Cache-Eintrag für eine Produkt-ID (stille, wenn nicht vorhanden)."""
        with contextlib.suppress(FileNotFoundError):
            self.file(product_id).unlink()

    def list(self) -> list[str]:
        """Alle wiedergewinnbaren Produkt-IDs (Einfüge-/Sortierreihenfolge).

        Die Dateinamen sind nur abgeleitet; die maßgebliche ID steckt im
        entschlüsselten Inhalt. Unlesbare Dateien stören die anderen nicht.
        """
        if not self.available() or not self._dir.is_dir():
            return []
        try:
            entries = sorted(self._dir.iterdir())
        except OSError:
            return []
        ids: list[str] = []
        for path in entries:
            name = path.name
            if not name.endswith(_SUFFIX):
                continue
            derived = name[: -len(_SUFFIX)]
            try:
                entry = self.load(derived)
            except Exception:
                continue  # Unlesbare Datei: überspringen, andere bleiben erhalten.
            if entry is not None:
                ids.append(entry.document.product_id)
        return ids
