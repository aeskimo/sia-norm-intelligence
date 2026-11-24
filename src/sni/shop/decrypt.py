"""SIA-Protokoll-Krypto (REQ-801): DES-CBC-Kette der Java-Referenz.

1:1-Port von ``ch.sia.reader.login`` (``MroLicenseDecryptor``,
``SrdKeyUnwrapper``, ``SrdDocumentDecryptor``). Die Kette ist einseitig
nicht änderbar (shop.sia.ch, SIA-Reader 2, Bytecode 2015):

- ``.mro`` (Lizenzdatei): ZIP (1 Eintrag) → Rohtext → DES/CBC/PKCS5 mit
  statischem 2015er-Schlüssel → Klartext-XML (Root: dsSecureReaderLizenz).
- ``SRD_KEY``/``SRD_IV`` im Lizenz-XML:
  ``Base64(DES_static(echter 8-Byte-Key/IV))``; Unwrap = Base64-Decode +
  DES-Entschlüsselung mit dem statischen Schlüssel.
- ``.srd`` (Dokumentdatei): ZIP (1 XML-Eintrag) → Metadaten plus
  ``Orig_Dokument_Crypted`` = ``Base64(DES_individuell(Dokument))`` →
  PDF-Bytes.

Implementierungsnotiz (cryptography-Pin, 09_CONSUMER_APP.md §10.5):
pyca/cryptography bietet keinen öffentlichen Single-DES; die dokumentierte
Äquivalente ist ``TripleDES`` mit 24-Byte-Schlüssel ``k + k + k`` (EDE mit
identischen Teilkeys ≡ Single DES). 8-/16-Byte-Keys sind seit 45.0.0
deprecated, 24-Byte-Keys sind der stabile, nicht-deprecate Pfad. Die
Protokoll-Kompatibilität sichert der Known-Answer-Test gegen
Java-Referenzwerte (``tests/unit/test_req801_des_kat.py``).
"""

from __future__ import annotations

import base64
import binascii
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass

from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, modes

#: Aus res.Config (SIA-Reader 2, 2015) rekonstruierter statischer DES-Schlüssel.
LEGACY_STATIC_KEY = "w%=0Rr,5"
#: Aus res.Config (SIA-Reader 2, 2015) rekonstruierter statischer DES-IV.
LEGACY_STATIC_IV = "ha2x2;76"

_DOCTYPE_RE = re.compile(r"<!DOCTYPE", re.IGNORECASE)


class SiaShopError(ValueError):
    """Fehler bei der SIA-Protokoll-Krypto (falscher Schlüssel, kaputtes Format)."""


def _ascii8(value: str, what: str) -> bytes:
    """Validiert einen 8-Byte-ASCII-Wert (Java: ``US_ASCII``, exakt 8 Bytes)."""
    data = value.encode("ascii")
    if len(data) != 8:
        raise SiaShopError(f"{what} muss exakt 8 ASCII-Bytes sein (gefunden: {len(data)})")
    return data


def des_cbc_encrypt(data: bytes, key: str, iv: str) -> bytes:
    """DES/CBC/PKCS5-Verschlüsselung (Java: ``DES/CBC/PKCS5Padding``, ENCRYPT)."""
    padder = padding.PKCS7(64).padder()
    padded = padder.update(data) + padder.finalize()
    cipher = Cipher(TripleDES(_ascii8(key, "DES-Schlüssel") * 3), modes.CBC(_ascii8(iv, "DES-IV")))
    encryptor = cipher.encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def des_cbc_decrypt(data: bytes, key: str, iv: str) -> bytes:
    """DES/CBC/PKCS5-Entschlüsselung (Java: ``DES/CBC/PKCS5Padding``, DECRYPT)."""
    if not data or len(data) % 8 != 0:
        raise SiaShopError(
            f"DES-Ciphertext muss nicht leer und ein Vielfaches von 8 Byte sein"
            f" (gefunden: {len(data)})"
        )
    cipher = Cipher(TripleDES(_ascii8(key, "DES-Schlüssel") * 3), modes.CBC(_ascii8(iv, "DES-IV")))
    decryptor = cipher.decryptor()
    padded = decryptor.update(data) + decryptor.finalize()
    unpadder = padding.PKCS7(64).unpadder()
    try:
        return unpadder.update(padded) + unpadder.finalize()
    except ValueError as exc:
        raise SiaShopError(
            "DES-Entschlüsselung fehlgeschlagen — falscher Schlüssel/IV oder kein DES-CBC-PKCS5"
        ) from exc


def unwrap_srd_value(wrapped_b64: str) -> str:
    """Entpackt ein SRD_KEY-/SRD_IV-Feld (Java: ``SrdKeyUnwrapper.unwrap``)."""
    try:
        encoded = base64.b64decode(wrapped_b64.strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SiaShopError("SRD_KEY/SRD_IV: ungültiges Base64") from exc
    plain = des_cbc_decrypt(encoded, LEGACY_STATIC_KEY, LEGACY_STATIC_IV)
    try:
        return plain.decode("ascii")
    except UnicodeDecodeError as exc:
        raise SiaShopError(
            "SRD_KEY/SRD_IV: Klartext nicht ASCII — falscher Schlüssel/Format"
        ) from exc


def wrap_srd_value_for_testing(plaintext: str) -> str:
    """Kehrfunktion zu :func:`unwrap_srd_value` (nur Tests, Java: ``wrapForTesting``)."""
    cipher = des_cbc_encrypt(plaintext.encode("ascii"), LEGACY_STATIC_KEY, LEGACY_STATIC_IV)
    return base64.b64encode(cipher).decode("ascii")


def read_single_zip_entry(data: bytes) -> tuple[str, bytes]:
    """Liest den ersten (einzig erwarteten) ZIP-Eintrag (Java: ``getNextEntry``)."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise SiaShopError("kein gültiges ZIP-Archiv — keine .mro/.srd-Datei") from exc
    with archive:
        names = archive.namelist()
        if not names:
            raise SiaShopError("ZIP-Archiv enthält kein lesbares Element")
        return names[0], archive.read(names[0])


def parse_guarded_xml(xml_bytes: bytes, what: str) -> ET.Element:
    """XML-Parser mit DOCTYPE-Guard (Java: ``disallow-doctype-decl=true``)."""
    try:
        text = xml_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SiaShopError(f"{what}: XML ist kein gültiges UTF-8") from exc
    if _DOCTYPE_RE.search(text):
        raise SiaShopError(f"{what}: DOCTYPE-Deklaration nicht erlaubt (XXE-Guard)")
    try:
        return ET.fromstring(text)
    except ET.ParseError as exc:
        raise SiaShopError(f"{what}: ungültiges XML: {exc}") from exc


def _first_text_local(root: ET.Element, local_name: str) -> str | None:
    """Erster Text eines Elements mit lokalem Namen, namespace-agnostisch.

    Entspricht ``getElementsByTagNameNS("*", name)`` der Java-Referenz.
    """
    for element in root.iter():
        tag = element.tag
        if isinstance(tag, str) and tag.rsplit("}", 1)[-1] == local_name:
            return "".join(element.itertext())
    return None


def decrypt_mro(mro_bytes: bytes) -> str:
    """Entschlüsselt eine .mro-Lizenzdatei zum Klartext-XML.

    Java: ``MroLicenseDecryptor.decryptToXml`` (ZIP → DES mit statischem
    Schlüssel → XML-Validierung inkl. DOCTYPE-Guard).
    """
    _name, encrypted = read_single_zip_entry(mro_bytes)
    xml_bytes = des_cbc_decrypt(encrypted, LEGACY_STATIC_KEY, LEGACY_STATIC_IV)
    parse_guarded_xml(xml_bytes, ".mro")  # Validierung: UTF-8, DOCTYPE-Guard, wohlgeformt
    return xml_bytes.decode("utf-8")


def extract_individual_key_and_iv(license_xml: str) -> tuple[str, str]:
    """Entpackt den individuellen SRD-Schlüssel/IV aus Lizenz-XML.

    Java: ``MroLicenseDecryptor.extractIndividualKeyAndIv``.
    """
    root = parse_guarded_xml(license_xml.encode("utf-8"), "Lizenz-XML")
    wrapped_key = _first_text_local(root, "SRD_KEY")
    wrapped_iv = _first_text_local(root, "SRD_IV")
    if wrapped_key is None or wrapped_iv is None:
        raise SiaShopError("SRD_KEY/SRD_IV nicht im Lizenz-XML gefunden")
    return unwrap_srd_value(wrapped_key), unwrap_srd_value(wrapped_iv)


@dataclass(frozen=True, slots=True)
class SrdMetadata:
    """Metadaten einer .srd-Datei (Java: ``SrdDocumentDecryptor.Metadata``)."""

    id: str
    dateiname: str
    produktnummer: str
    bezeichnung: str
    crypted_length: int


def srd_read_metadata(srd_bytes: bytes) -> SrdMetadata:
    """Liest die Metadaten aus einer .srd (Java: ``SrdDocumentDecryptor.readMetadata``)."""
    _name, xml_bytes = read_single_zip_entry(srd_bytes)
    root = parse_guarded_xml(xml_bytes, ".srd")
    crypted = _first_text_local(root, "Orig_Dokument_Crypted") or ""
    return SrdMetadata(
        id=_first_text_local(root, "ID") or "",
        dateiname=_first_text_local(root, "Orig_Dateiname") or "",
        produktnummer=_first_text_local(root, "Produktnummer") or "",
        bezeichnung=_first_text_local(root, "Bezeichnung") or "",
        crypted_length=len(crypted),
    )


def srd_decrypt_document(srd_bytes: bytes, key: str, iv: str) -> bytes:
    """Entschlüsselt das Dokument (meist PDF) mit dem individuellen Schlüssel.

    Java: ``SrdDocumentDecryptor.decryptDocument`` (Base64-MIME-Decode +
    DES mit individuellem Schlüssel/IV).
    """
    _name, xml_bytes = read_single_zip_entry(srd_bytes)
    root = parse_guarded_xml(xml_bytes, ".srd")
    crypted_b64 = _first_text_local(root, "Orig_Dokument_Crypted")
    if crypted_b64 is None:
        raise SiaShopError(".srd: Element 'Orig_Dokument_Crypted' nicht gefunden")
    try:
        # Java: Base64.getMimeDecoder() — MIME-tolerant (Zeilenumbrüche, Leerzeichen).
        cipher_bytes = base64.b64decode(crypted_b64.strip())
    except (binascii.Error, ValueError) as exc:
        raise SiaShopError(".srd: 'Orig_Dokument_Crypted' ist kein gültiges Base64") from exc
    return des_cbc_decrypt(cipher_bytes, key, iv)
