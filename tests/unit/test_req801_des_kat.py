"""REQ-801: DES-Kette (SIA-Protokoll) — Known-Answer-Test gegen Java-Referenz.

Die Vektoren wurden 2026-11-24 mit der Java-Referenzimplementierung
(``ch.sia.reader.login.SrdKeyUnwrapper`` plus ``javax.crypto``
``DES/CBC/PKCS5Padding``, JDK 25, ``KatGenerator``) erzeugt — reine
synthetische Testdaten (G4: keine echten Lizenzschlüssel, keine
Normtexte). Der Test sichert die Protokoll-Kompatibilität des 1:1-Ports:
Die TripleDES-24-Byte-Implentation (``k + k + k`` ≡ Single DES,
09_CONSUMER_APP.md §10.5) muss byte-identische Chiffretexte erzeugen.
"""

from __future__ import annotations

import base64
import io
import re
import zipfile

import pytest

from sni.shop.decrypt import (
    LEGACY_STATIC_IV,
    LEGACY_STATIC_KEY,
    SiaShopError,
    decrypt_mro,
    des_cbc_decrypt,
    des_cbc_encrypt,
    extract_individual_key_and_iv,
    srd_decrypt_document,
    srd_read_metadata,
    unwrap_srd_value,
    wrap_srd_value_for_testing,
)

# --- Java-Referenzvektoren (KatGenerator, 2026-11-24, synthetisch) ---
JAVA_WRAPPED_KEY = "HbRKxGMUEBo2yBaSjjLuaw=="
JAVA_WRAPPED_IV = "S415B5c8Jq2orKXAs5octQ=="
JAVA_REAL_KEY = "K3yABCDE"
JAVA_REAL_IV = "IvFGHIJK"
JAVA_MRO = base64.b64decode(
    "UEsDBBQACAgIAEyjeF0AAAAAAAAAAAAAAAAdAAAAREVWLUtBVC0wMDAxX0xpemVuel9EYXRlaS5t"
    "cm8B4AAf/ydXsDbEaJlb+Q8gm5SNnzuFUC6O7BPXjSyMzGLOPjsyhVZ/iZrJY0axImp5lrP1hlDm"
    "upoWRY7WWMifYMkAmkMGHJ3Q8mpAkUSAuKi9N069jSGsofA8+MLyFSjJCq/ohBfHi3OTk0xc8BTc"
    "orRwO/xAqOXQd58TF404AqSDKpCzIsuAjEzAXnB9ju6EXIZACio2qWftYYhdta/nAbxAAWfrO6OM"
    "PigkoZPGtc9WrP6uKePy1UD9+29euEY1indrarDTxzLMeO0epfEFknT0XSN3ExNATHQa9hvCB+Dl"
    "OqwkUEsHCDs4uWHlAAAA4AAAAFBLAQIUABQACAgIAEyjeF07OLlh5QAAAOAAAAAdAAAAAAAAAAAA"
    "AAAAAAAAAABERVYtS0FULTAwMDFfTGl6ZW56X0RhdGVpLm1yb1BLBQYAAAAAAQABAEsAAAAwAQAA"
    "AAA="
)
JAVA_MRO_XML = (
    '<?xml version="1.0"?>'
    "<dsSecureReaderLizenz>"
    "<Konfiguration>"
    f"<SRD_KEY>{JAVA_WRAPPED_KEY}</SRD_KEY>"
    f"<SRD_IV>{JAVA_WRAPPED_IV}</SRD_IV>"
    "<Geraete_ID>DEV-KAT-0001</Geraete_ID>"
    "</Konfiguration>"
    "</dsSecureReaderLizenz>"
)
JAVA_SRD = base64.b64decode(
    "UEsDBBQACAgIAEyjeF0AAAAAAAAAAAAAAAAaAAAAa2F0LWlkLTAwMDFfTm9ybV9EYXRlaS5zcmR1"
    "kVtvgkAQhf+K4ZXAqq3pJesaL20k1V4UMTQmhrIjEtxdWJai/voKsUpJ+jjznTNnJoN7e7ZrfINM"
    "Q8G7Wstsaj2CafoqJHsOd9A4YZ52ta1S8SNCeZ6bEujUmIuNyj0Jpi8YmoOfSZiBR0Giq9fcp1Qj"
    "eCT8jAFXBFsjEnnKCKnRbDZbGJ1q/CbDYD3yFITcY1BwfrKbMd1gVGMVbbzxKHnp26ti0KqqLMlZ"
    "KaIyOJAC0hRIp/MrrAH8LgXNon82PEOeMQayCG2U6G8bD+AIob/lGQ8KjWFDWl6CUZVcbLUV10N5"
    "iBVQstD5h2OxsXLc+GHifDoJHTxF1r3ut73bhYwGx/5EtnXn6wYl/gLZwzu9w8eHJBgv7eNyO0vc"
    "SExduotdq1u79pKB0fUllXeRH1BLBwgz4uKUMQEAAAwCAABQSwECFAAUAAgICABMo3hdM+LilDEB"
    "AAAMAgAAGgAAAAAAAAAAAAAAAAAAAAAAa2F0LWlkLTAwMDFfTm9ybV9EYXRlaS5zcmRQSwUGAAAA"
    "AAEAAQBIAAAAeQEAAAAA"
)
JAVA_SRD_PDF = b"%PDF-1.4 KAT-Test-PDF-Inhalt fuer REQ-801 (synthetisch)"


def test_req801_kat_unwrap_java_wrapped_key_iv() -> None:
    assert unwrap_srd_value(JAVA_WRAPPED_KEY) == JAVA_REAL_KEY
    assert unwrap_srd_value(JAVA_WRAPPED_IV) == JAVA_REAL_IV


def test_req801_kat_mro_decrypt_to_xml() -> None:
    assert decrypt_mro(JAVA_MRO) == JAVA_MRO_XML


def test_req801_kat_mro_individual_key_iv() -> None:
    key, iv = extract_individual_key_and_iv(JAVA_MRO_XML)
    assert (key, iv) == (JAVA_REAL_KEY, JAVA_REAL_IV)


def test_req801_kat_srd_metadata() -> None:
    meta = srd_read_metadata(JAVA_SRD)
    assert meta.id == "kat-id-0001"
    assert meta.dateiname == "katnorm.pdf"
    assert meta.produktnummer == "KAT 001"
    assert meta.bezeichnung == "KAT-Testnorm"
    assert meta.crypted_length > 0


def test_req801_kat_srd_decrypt_document() -> None:
    document = srd_decrypt_document(JAVA_SRD, JAVA_REAL_KEY, JAVA_REAL_IV)
    assert document == JAVA_SRD_PDF


def test_req801_encrypt_direction_matches_java() -> None:
    # Python-Verschlüsselung muss den Java-Referenz-Chiffretext exakt treffen.
    cipher = des_cbc_encrypt(JAVA_REAL_KEY.encode("ascii"), LEGACY_STATIC_KEY, LEGACY_STATIC_IV)
    assert base64.b64encode(cipher).decode("ascii") == JAVA_WRAPPED_KEY
    assert wrap_srd_value_for_testing(JAVA_REAL_KEY) == JAVA_WRAPPED_KEY


def test_req801_kat_des_cbc_roundtrip() -> None:
    data = des_cbc_encrypt(b"Synthetischer Klartext 0123456789", JAVA_REAL_KEY, JAVA_REAL_IV)
    assert (
        des_cbc_decrypt(data, JAVA_REAL_KEY, JAVA_REAL_IV) == b"Synthetischer Klartext 0123456789"
    )


def test_req801_des_cbc_decrypt_wrong_key_raises() -> None:
    with pytest.raises(SiaShopError):
        des_cbc_decrypt(base64.b64decode(JAVA_WRAPPED_KEY), "xxxxxxxx", LEGACY_STATIC_IV)


def test_req801_des_cbc_encrypt_rejects_short_key() -> None:
    with pytest.raises(SiaShopError, match="8 ASCII-Bytes"):
        des_cbc_encrypt(b"x", "kurz", LEGACY_STATIC_IV)


def test_req801_des_cbc_decrypt_rejects_bad_length() -> None:
    with pytest.raises(SiaShopError, match="Vielfaches von 8"):
        des_cbc_decrypt(b"1234567", LEGACY_STATIC_KEY, LEGACY_STATIC_IV)


def test_req801_unwrap_rejects_invalid_base64() -> None:
    with pytest.raises(SiaShopError, match="Base64"):
        unwrap_srd_value("definitely not base64!!!")


def test_req801_unwrap_non_ascii_reports_sizes_only() -> None:
    # Given ein Wrapped-Wert mit nicht-ASCII-Klartext (simuliert ein
    # formatseitig verändertes Server-Wrapping) When entpackt Then enthält
    # die Fehlermeldung nur die Zählungen (G4) — keine Schlüssel-Bytes.
    wrapped = base64.b64encode(
        des_cbc_encrypt(b"\x80\x81\x82\x83\x84\x85\x86\x87", LEGACY_STATIC_KEY, LEGACY_STATIC_IV)
    ).decode("ascii")
    with pytest.raises(SiaShopError) as excinfo:
        unwrap_srd_value(wrapped)
    message = str(excinfo.value)
    assert "Ciphertext: 16 Bytes" in message
    assert "Klartext: 8 Bytes" in message
    assert "\x80" not in message
    # Ciphertext-Fingerabdruck (SHA-256, 16 Hex) für Lizenz-Vergleiche (G4)
    assert re.search(r"FPA [0-9a-f]{16}\)", message)


def test_req801_mro_rejects_non_zip() -> None:
    with pytest.raises(SiaShopError, match="ZIP"):
        decrypt_mro(b"kein ZIP hier")


def test_req801_mro_rejects_doctype_declaration() -> None:
    # XXE-Guard: DOCTYPE-Deklaration im Klartext-XML wird abgewiesen
    # (Java: disallow-doctype-decl=true).
    xml = (
        '<?xml version="1.0"?><!DOCTYPE foo SYSTEM "http://evil.example/x"><dsSecureReaderLizenz/>'
    )
    payload = des_cbc_encrypt(xml.encode("utf-8"), LEGACY_STATIC_KEY, LEGACY_STATIC_IV)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("x_Lizenz_Datei.mro", payload)
    with pytest.raises(SiaShopError, match="DOCTYPE"):
        decrypt_mro(buf.getvalue())


def test_req801_srd_rejects_missing_crypted_element() -> None:
    xml = '<?xml version="1.0"?><dsNormFile><Document><ID>x</ID></Document></dsNormFile>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("x_Norm_Datei.srd", xml.encode("utf-8"))
    with pytest.raises(SiaShopError, match="Orig_Dokument_Crypted"):
        srd_decrypt_document(buf.getvalue(), JAVA_REAL_KEY, JAVA_REAL_IV)


def test_req801_mro_rejects_missing_srd_fields() -> None:
    xml = '<?xml version="1.0"?><dsSecureReaderLizenz><Konfiguration/></dsSecureReaderLizenz>'
    with pytest.raises(SiaShopError, match="SRD_KEY/SRD_IV"):
        extract_individual_key_and_iv(xml)
