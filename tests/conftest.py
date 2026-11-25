"""Gemeinsame Test-Helfer. Nur synthetische Platzhalterdaten (Guardrail G4)."""

from __future__ import annotations

import base64
import contextlib
import io
import json
import threading
import zipfile
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast

import pytest

from sni.catalog.snapshot import load_snapshot
from sni.catalog.store import ConceptStore
from sni.rules.engine import InputValue
from sni.shop.decrypt import (
    LEGACY_STATIC_IV,
    LEGACY_STATIC_KEY,
    des_cbc_encrypt,
    wrap_srd_value_for_testing,
)
from sni.shop.models import DISCARD, DocumentResult, LicenseSink, LoginResult, LoginStatus
from sni.shop.soap import SiaSoapClient

SNAPSHOT_ID = "sia:catalog/test@1.0.0"
FIXTURES_DIR = Path(__file__).parent / "fixtures"
CONCEPT_A = "sia:concept/geschossflaeche"
CONCEPT_B = "sia:concept/nutzflaeche"
PLACEHOLDER_DEFINITION = "Synthetischer Testbegriff (Platzhalter, kein Norminhalt)."


def make_concept(
    concept_id: str,
    snapshot_id: str = SNAPSHOT_ID,
    definition: str = PLACEHOLDER_DEFINITION,
) -> dict[str, object]:
    """Erzeugt ein schemakonformes Concept (synthetisch)."""
    return {
        "id": concept_id,
        "name": {"de": concept_id.rsplit("/", 1)[-1].replace("-", " ").title()},
        "definition": {"de": definition},
        "catalog_snapshot": snapshot_id,
    }


def make_snapshot(
    snapshot_id: str = SNAPSHOT_ID,
    concept_ids: tuple[str, ...] = (CONCEPT_A, CONCEPT_B),
) -> dict[str, object]:
    """Erzeugt einen synthetischen CatalogSnapshot (JSON-Struktur)."""
    return {
        "snapshot_id": snapshot_id,
        "concepts": [make_concept(cid, snapshot_id) for cid in concept_ids],
    }


def concept_at(snap: dict[str, object], index: int) -> dict[str, object]:
    """Indexierter Zugriff auf concepts (mit Typ, für mypy --strict)."""
    return cast(list[dict[str, object]], snap["concepts"])[index]


def concepts_of(snap: dict[str, object]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], snap["concepts"])


@pytest.fixture
def synthetic_snapshot() -> dict[str, object]:
    return make_snapshot()


@pytest.fixture
def snapshot_with_relations() -> dict[str, object]:
    snap = make_snapshot()
    concept_at(snap, 0)["relations"] = [{"type": "related_to", "target": CONCEPT_B}]
    return snap


def source_of(candidate: dict[str, object]) -> dict[str, object]:
    """Indexierter Zugriff auf die SourceReference (mit Typ, für mypy --strict)."""
    source = candidate["source"]
    if not isinstance(source, dict):
        raise AssertionError("candidate['source'] fehlt oder ist kein Objekt")
    return source


def load_synthetic_norm() -> dict[str, object]:
    """Lädt das synthetische Test-Normdokument (G4: keine echten Norminhalte)."""
    raw: object = json.loads((FIXTURES_DIR / "synthetic_norm.json").read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise AssertionError("synthetic_norm.json muss ein JSON-Objekt sein")
    return raw


@pytest.fixture
def synthetic_norm() -> dict[str, object]:
    return load_synthetic_norm()


def load_synthetic_rule() -> dict[str, object]:
    """Lädt die synthetische Test-Regel (G4: keine echten Norminhalte)."""
    raw: object = json.loads((FIXTURES_DIR / "synthetic_rule.json").read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise AssertionError("synthetic_rule.json muss ein JSON-Objekt sein")
    return raw


@pytest.fixture
def synthetic_rule() -> dict[str, object]:
    return load_synthetic_rule()


def rule_full_inputs() -> dict[str, InputValue]:
    """Volle Inputs für die synthetische Regel (beide Pflicht-Concepts)."""
    return {
        "sia:concept/teilsflaeche-a": InputValue(100.0, "m2"),
        "sia:concept/teilsflaeche-b": InputValue(50.0, "m2"),
    }


@pytest.fixture
def concept_store(tmp_path: Path) -> Iterator[ConceptStore]:
    store = ConceptStore(tmp_path / "catalog.db")
    yield store
    store.close()


@pytest.fixture
def catalog_store(tmp_path: Path) -> Iterator[ConceptStore]:
    """Katalog mit den Standard-Test-Concepts (CONCEPT_A, CONCEPT_B) importiert."""
    store = ConceptStore(tmp_path / "catalog.db")
    store.import_snapshot(load_snapshot(make_snapshot()))
    yield store
    store.close()


def synthetic_pdf_lines() -> list[str]:
    """Zeilen einer synthetischen Testnorm (G4: keine echten Norminhalte).

    Enthaltene Fehlpunkte, die KEINE Ziffernnummern sein duerfen:
    TOC-Zeilen mit Punktguertel, das Jahr "2003", der Dezimalwert "1.5 m"
    und "0.8" (führende Null) am Zeilenanfang.
    """
    return [
        "SYN 1  Testnorm (synthetisch)",
        "Inhalt",
        "1 Ziel .......... 2",
        "2 Nachweise .......... 3",
        "1 Ziel",
        "Diese synthetische Norm regelt Testfaelle.",
        "1.1 Anwendungsbereich",
        "Sie gilt fuer alle Testgebaeude.",
        "2 Nachweise",
        "Jeder Nachweis ist zu dokumentieren.",
        "1.5 m Abstand zwischen Kanten.",
        "2003 war eine alte Fassung.",
        "2.1 Groessen",
        "0.8 kg pro Flaeche maximal.",
        "3 Grenzwerte",
        "3.1 Flaeche",
        "Testgrenzwert fuer die Testflaeche.",
    ]


def _pdf_escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


# Zeilen-Spezifikation für make_pdf: str (regulär), (text, bold) oder
# (text, bold, x) mit absolutem device-x.
PdfLine = str | tuple[str, bool] | tuple[str, bool, float]


def _resolve_line(line: PdfLine, x: float) -> tuple[str, bool, float]:
    """(Text, Bold, device-x) aus einer Zeilenspezifikation (Standard-x für str)."""
    if isinstance(line, str):
        return line, False, x
    if len(line) == 3:
        return line
    return line + (x,)


def make_pdf(
    pages: Sequence[PdfLine] | Sequence[Sequence[PdfLine]],
    line_height: float = 14.0,
    start_x: float = 72.0,
    start_y: float = 800.0,
) -> bytes:
    """Baut ein minimales PDF (Helvetica + Helvetica-Bold, Base-14) aus Zeilen.

    Argument ist eine Zeilenliste (eine Seite) oder eine Liste von
    Zeilenlisten (mehrere Seiten). Eine Zeile ist ``str`` (regulär),
    ``(text, bold)`` oder ``(text, bold, x)`` (absolutes device-x).
    ``line_height``, ``start_x``, ``start_y`` steuern die Position in
    device-Punkten (Ursprung unten links). Nur synthetische Testdaten (G4).
    pypdf liest den Text der Base-14-Schriften (/F1 regulär, /F2 bold)
    aus dem Content-Stream.
    """
    if not pages:
        raise ValueError("make_pdf braucht mindestens eine Seite")
    first = pages[0]
    if isinstance(first, (str, tuple)):
        single = cast("Sequence[PdfLine]", pages)
        page_lists: list[list[PdfLine]] = [list(single)]
    else:
        many = cast("Sequence[Sequence[PdfLine]]", pages)
        page_lists = [list(page) for page in many]
    n = len(page_lists)

    content_streams: list[bytes] = []
    for page_lines in page_lists:
        ops = ["BT /F1 11 Tf"]
        font = "F1"
        prev: tuple[float, float] | None = None
        for index, raw_line in enumerate(page_lines):
            text, bold, lx = _resolve_line(raw_line, start_x)
            ly = start_y - index * line_height
            if prev is None:
                ops.append(f"{lx:.2f} {ly:.2f} Td")
            else:
                ops.append(f"{lx - prev[0]:.2f} {ly - prev[1]:.2f} Td")
            prev = (lx, ly)
            want = "F2" if bold else "F1"
            if want != font:
                ops.append(f"/{want} 11 Tf")
                font = want
            ops.append(f"({_pdf_escape(text)}) Tj")
        ops.append("ET")
        content_streams.append("\n".join(ops).encode("cp1252", "replace"))

    objects: list[tuple[int, bytes]] = []
    kids = " ".join(f"{5 + i} 0 R" for i in range(n))
    objects.append((1, b"<< /Type /Catalog /Pages 2 0 R >>"))
    objects.append((2, f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode("ascii")))
    objects.append((3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"))
    objects.append((4, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"))
    for i in range(n):
        objects.append(
            (
                5 + i,
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                b"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents "
                + str(5 + n + i).encode("ascii")
                + b" 0 R >>",
            )
        )
    for i, stream in enumerate(content_streams):
        header = b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n"
        objects.append((5 + n + i, header + stream + b"\nendstream"))

    body = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for num, payload in objects:
        offsets[num] = len(body)
        body += f"{num} 0 obj\n".encode("ascii") + payload + b"\nendobj\n"
    total = 4 + 2 * n
    xref_pos = len(body)
    xref = [f"xref\n0 {total + 1}\n", "0000000000 65535 f \n"]
    for num in range(1, total + 1):
        xref.append(f"{offsets[num]:010d} 00000 n \n")
    xref.append(f"trailer\n<< /Size {total + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n")
    body += "".join(xref).encode("ascii")
    return bytes(body)


def write_norm_pdf(
    norm_id: str,
    norms_dir: Path,
    pages: Sequence[PdfLine] | Sequence[Sequence[PdfLine]] | None = None,
    line_height: float = 14.0,
    start_x: float = 72.0,
    start_y: float = 800.0,
) -> Path:
    """Schreibt ``document.pdf`` in den lokalen Mount (Test-Helfer, M9)."""
    norm_dir = norms_dir / norm_id
    norm_dir.mkdir(parents=True)
    if pages is None:
        pages = synthetic_pdf_lines()
    path = norm_dir / "document.pdf"
    path.write_bytes(make_pdf(pages, line_height=line_height, start_x=start_x, start_y=start_y))
    return path


def load_draft(norm_id: str, norms_dir: Path) -> dict[str, object]:
    """Lädt ``document.draft.json`` aus dem Mount (Test-Helfer, M9)."""
    raw: object = json.loads(
        (norms_dir / norm_id / "document.draft.json").read_text(encoding="utf-8")
    )
    if not isinstance(raw, dict):
        raise AssertionError("document.draft.json muss ein JSON-Objekt sein")
    return raw


def clauses_of(draft: dict[str, object]) -> list[dict[str, object]]:
    """Indexierter Zugriff auf die Ziffern des Entwurfs (mit Typ, für mypy --strict)."""
    return cast(list[dict[str, object]], draft["clauses"])


def clause_text(clause: dict[str, object]) -> str:
    """Extrahierter Ziffern-Text einer Ziffer (mit Typ, für mypy --strict)."""
    return cast(str, clause["text"])


# ---------------------------------------------------------------------------
# SIA-Shop-Fakes (REQ-801/803): synthetische .mro/.srd + Client-Double (G4)
# ---------------------------------------------------------------------------

SHOP_NS = "http://www.redMSoftware.ch/Secure_Webservice"
SRD_KEY = "k1234567"  # 8 ASCII-Bytes (Java: char[] → individueller DES-Schlüssel)
SRD_IV = "i1234567"

LICENSE_XML = f"""<?xml version="1.0"?>
<dsSecureReaderLizenz>
  <Konfiguration>
    <SRD_KEY>{wrap_srd_value_for_testing(SRD_KEY)}</SRD_KEY>
    <SRD_IV>{wrap_srd_value_for_testing(SRD_IV)}</SRD_IV>
  </Konfiguration>
  <Produkt>
    <ID>prod-101</ID>
    <Produktnummer>SIA 101</Produktnummer>
    <Bezeichnung>Testnorm</Bezeichnung>
    <Dateiname>101_2020_dSIA.srd</Dateiname>
    <Recht_View>1</Recht_View>
  </Produkt>
  <Produkt>
    <ID>prod-102</ID>
    <Produktnummer>SIA 102</Produktnummer>
    <Bezeichnung>Nur-Metadaten-Norm</Bezeichnung>
    <Dateiname>102_2020_dSIA.srd</Dateiname>
    <Recht_View>0</Recht_View>
  </Produkt>
  <Produkt>
    <Bezeichnung>Ohne ID</Bezeichnung>
  </Produkt>
</dsSecureReaderLizenz>
"""


def _zip_one(name: str, data: bytes | str) -> bytes:
    payload = data.encode("utf-8") if isinstance(data, str) else data
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, payload)
    return buffer.getvalue()


def make_mro(license_xml: str) -> bytes:
    """Synthetische .mro: ZIP(DES_static(Lizenz-XML)) (G4)."""
    encrypted = des_cbc_encrypt(license_xml.encode("utf-8"), LEGACY_STATIC_KEY, LEGACY_STATIC_IV)
    return _zip_one("lizenz.xml", encrypted)


def make_srd(product_id: str, document: bytes, crypted_b64: str | None = None) -> bytes:
    """Synthetische .srd: ZIP(XML mit Base64(DES_individuell(Dokument))) (G4)."""
    if crypted_b64 is None:
        crypted_b64 = base64.b64encode(des_cbc_encrypt(document, SRD_KEY, SRD_IV)).decode("ascii")
    xml = (
        '<?xml version="1.0"?>'
        "<SRDDokument>"
        f"<ID>{product_id}</ID>"
        f"<Orig_Dateiname>{product_id}.srd</Orig_Dateiname>"
        f"<Orig_Dokument_Crypted>{crypted_b64}</Orig_Dokument_Crypted>"
        "</SRDDokument>"
    )
    return _zip_one("dokument.xml", xml)


def login_result_ok() -> LoginResult:
    return LoginResult(True, 200, LoginStatus.SUCCESS, "OK", None, 123, 5, None, 1)


def login_result_failure(status: LoginStatus, message: str) -> LoginResult:
    return LoginResult(True, 200, status, status.server_code, message, 0, 5, None, 1)


def document_result_ok(filename: str) -> DocumentResult:
    return DocumentResult(True, "OK", None, filename, 999, 5, None, 1)


def document_result_failure(
    server_code: str | None,
    message: str | None,
    filename: str | None,
    diagnostic: str | None,
) -> DocumentResult:
    return DocumentResult(False, server_code, message, filename, 0, 5, diagnostic, 1)


class FakeSoapClient(SiaSoapClient):
    """Client-Double: Testkonstruktor + Override der Netzwerk-Methoden."""

    def __init__(
        self,
        login_result: LoginResult,
        license_bytes: bytes | None = None,
        document_result: DocumentResult | None = None,
        srd_bytes: bytes | None = None,
    ) -> None:
        super().__init__(
            "http://127.0.0.1/echo",
            "http://127.0.0.1/lizenz",
            "http://127.0.0.1/dokument",
            SHOP_NS,
            "Test",
            1.0,
            1.0,
        )
        self._fake_login_result = login_result
        self._fake_license_bytes = license_bytes
        self._fake_document_result = document_result
        self._fake_srd_bytes = srd_bytes

    def login(
        self,
        customer_number_or_username: str,
        password: str,
        device_id: str,
        sink: LicenseSink = DISCARD,
    ) -> LoginResult:
        if self._fake_login_result.is_success and self._fake_license_bytes is not None:
            sink.accept(self._fake_license_bytes)
        return self._fake_login_result

    def get_document(
        self,
        produkt_id: str,
        customer_number_or_username: str,
        password: str,
        device_id: str,
    ) -> DocumentResult:
        result = self._fake_document_result
        if result is None:
            raise AssertionError("get_document wurde unerwartet aufgerufen")
        if result.success and self._fake_srd_bytes is not None:
            self._last_document_base64 = base64.b64encode(self._fake_srd_bytes).decode("ascii")
        return result


# ---------------------------------------------------------------------------
# Lokaler Test-HTTP-Server (09_CONSUMER_APP.md §12: nur Mocks, 127.0.0.1:0)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LoopbackServer:
    """Handle für den lokalen Test-HTTP-Server (ephemeraler Port)."""

    url: str


def _not_found(_payload: bytes) -> tuple[int, str]:
    return 404, '{"error":"not found"}'


class _LoopbackHttpServer(ThreadingHTTPServer):
    """ThreadingHTTPServer mit Pfade-Handler-Tabelle (``server.handlers``)."""

    def __init__(self, handlers: dict[str, Callable[[bytes], tuple[int, str]]]) -> None:
        super().__init__(("127.0.0.1", 0), _LoopbackRequestHandler)
        self.handlers = handlers


class _LoopbackRequestHandler(BaseHTTPRequestHandler):
    """Leitet GET/POST an ``handlers[path]`` weiter (Mock-Endpunkte)."""

    def log_message(self, format: str, *args: object) -> None:
        pass  # Test-Ausgabe sauber halten

    def do_GET(self) -> None:
        self._dispatch(b"")

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        self._dispatch(self.rfile.read(length))

    def _dispatch(self, payload: bytes) -> None:
        handlers = cast("_LoopbackHttpServer", self.server).handlers
        status, body = handlers.get(self.path, _not_found)(payload)
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@contextlib.contextmanager
def loopback_server(
    handlers: dict[str, Callable[[bytes], tuple[int, str]]],
) -> Iterator[LoopbackServer]:
    """Startet einen lokalen HTTP-Mock auf 127.0.0.1 mit ephemeralem Port.

    ``handlers`` mappt Pfad → ``fn(payload) -> (status, json-String)``.
    Kein echter Dienst (09 §12): nur Loopback, kein Poppler, kein Ollama.
    """
    server = _LoopbackHttpServer(handlers)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield LoopbackServer(url=f"http://127.0.0.1:{server.server_address[1]}")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5.0)
