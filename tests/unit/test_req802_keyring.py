"""REQ-802: Keyring-Store (Credentials + Statusschlüssel).

1:1-Tests des Java-Ports von ``ch.sia.integration.persistence``
(``CredentialStore``, ``GibbApiKeyStore``, ``KeychainStateKeyProvider``):
Service/Accounts und Payload-Formate müssen exakt denen der Java-App
entsprechen (gegenseitige Lesbarkeit auf macOS, Migration REQ-802).

Alles läuft gegen den dateibasierten Fake-Keyring (``SIA_FAKE_KEYCHAIN``
im Java-Testskript: ein File pro ``<service>/<account>``) — dadurch sind
die Tests OS-neutral (3-OS-CI) und berühren nie den echten Keychain.
Reine synthetische Testdaten (G4).
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from sni.secrets import keyring_store as ks
from sni.secrets.keyring_store import (
    ACCOUNT_GIBB_API_KEY,
    ACCOUNT_SIA_LOGIN,
    ACCOUNT_STATE_KEY,
    FAKE_KEYCHAIN_ENV,
    SERVICE,
    FakeFileKeyringBackend,
    GibbApiKeyStore,
    KeyringUnavailableError,
    SialLoginStore,
    StateKeyError,
    StateKeyStore,
    StoredCredentials,
)


def _b64url_nopad(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


@pytest.fixture
def fake(tmp_path: Path) -> FakeFileKeyringBackend:
    return FakeFileKeyringBackend(tmp_path / "keychain")


# ---------------------------------------------------------------- Konstanten


def test_req802_service_and_accounts_match_java() -> None:
    assert SERVICE == "ch.sia.normenassistent"
    assert ACCOUNT_SIA_LOGIN == "sia-login"
    assert ACCOUNT_GIBB_API_KEY == "gibb-api-key"
    assert ACCOUNT_STATE_KEY == "state-key"
    assert FAKE_KEYCHAIN_ENV == "SIA_FAKE_KEYCHAIN"


# -------------------------------------------------------------- sia-login


def test_req802_sia_login_roundtrip(fake: FakeFileKeyringBackend) -> None:
    store = SialLoginStore(fake)
    store.store("123456", "geheim")
    loaded = store.load()
    assert loaded is not None
    assert loaded == StoredCredentials(customer="123456", password="geheim")
    assert store.is_available


def test_req802_sia_login_payload_java_compatible(fake: FakeFileKeyringBackend) -> None:
    # Raw-Payload exakt im Java-Format: b64url(customer)|b64url(password),
    # URL-safe, ohne Padding — so kann die Java-App es lesen (und umgekehrt).
    SialLoginStore(fake).store("Kundé 42", "p@ss/wörd+=~")
    payload = (fake._root / SERVICE / ACCOUNT_SIA_LOGIN).read_text(encoding="utf-8")
    assert payload == f"{_b64url_nopad('Kundé 42')}|{_b64url_nopad('p@ss/wörd+=~')}"
    assert "=" not in payload


def test_req802_sia_login_reads_java_style_payload(fake: FakeFileKeyringBackend) -> None:
    # Von Java geschriebener Eintrag (b64url ohne Padding) muss lesbar sein.
    path = fake._root / SERVICE / ACCOUNT_SIA_LOGIN
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"{_b64url_nopad('7654321')}|{_b64url_nopad('JavaPasswort')}",
        encoding="utf-8",
    )
    loaded = SialLoginStore(fake).load()
    assert loaded == StoredCredentials(customer="7654321", password="JavaPasswort")


def test_req802_sia_login_missing_returns_none(fake: FakeFileKeyringBackend) -> None:
    assert SialLoginStore(fake).load() is None


@pytest.mark.parametrize(
    "payload",
    ["ohne-trenner", "!!!nicht-base64!!!|abc", "abc|!!!nicht-base64!!!", ""],
)
def test_req802_sia_login_malformed_payload_returns_none(
    fake: FakeFileKeyringBackend, payload: str
) -> None:
    path = fake._root / SERVICE / ACCOUNT_SIA_LOGIN
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    assert SialLoginStore(fake).load() is None


def test_req802_sia_login_remove(fake: FakeFileKeyringBackend) -> None:
    store = SialLoginStore(fake)
    store.store("123456", "geheim")
    store.remove()
    assert store.load() is None
    store.remove()  # zweites Remove: ohne Fehler (Ziel-Zustand erreicht)


def test_req802_sia_login_store_unavailable_raises() -> None:
    class _NoneBackend:
        kind = "none"

        def get(self, service: str, account: str) -> str | None:
            raise KeyringUnavailableError("unverfügbar")

        def set(self, service: str, account: str, payload: str) -> None:
            raise KeyringUnavailableError("unverfügbar")

        def delete(self, service: str, account: str) -> None:
            raise KeyringUnavailableError("unverfügbar")

    store = SialLoginStore(_NoneBackend())
    assert not store.is_available
    with pytest.raises(KeyringUnavailableError):
        store.store("123456", "geheim")
    # load() bleibt bei Fehlern still (Java: Optional.empty).
    assert store.load() is None
    store.remove()  # ebenfalls still


# ------------------------------------------------------------- gibb-api-key


def test_req802_gibb_key_roundtrip(fake: FakeFileKeyringBackend) -> None:
    store = GibbApiKeyStore(fake)
    store.store("gibb-key-abc123")
    assert store.load() == "gibb-key-abc123"


def test_req802_gibb_key_payload_java_compatible(fake: FakeFileKeyringBackend) -> None:
    GibbApiKeyStore(fake).store("gibb-key-abc123")
    payload = (fake._root / SERVICE / ACCOUNT_GIBB_API_KEY).read_text(encoding="utf-8")
    assert payload == _b64url_nopad("gibb-key-abc123")
    assert "=" not in payload


def test_req802_gibb_key_rejects_blank(fake: FakeFileKeyringBackend) -> None:
    with pytest.raises(ValueError, match="darf nicht leer sein"):
        GibbApiKeyStore(fake).store("   ")


def test_req802_gibb_key_rejects_too_long(fake: FakeFileKeyringBackend) -> None:
    with pytest.raises(ValueError, match="zu lang"):
        GibbApiKeyStore(fake).store("x" * 4001)
    # Exakt 4000 ist erlaubt (Java: > 4000 wirft).
    GibbApiKeyStore(fake).store("x" * 4000)


def test_req802_gibb_key_missing_and_remove(fake: FakeFileKeyringBackend) -> None:
    store = GibbApiKeyStore(fake)
    assert store.load() is None
    store.store("gibb-key-abc123")
    store.remove()
    assert store.load() is None
    store.remove()  # still


# --------------------------------------------------------------- state-key


def _key() -> bytes:
    return bytes(range(32))


def test_req802_state_key_roundtrip(fake: FakeFileKeyringBackend) -> None:
    store = StateKeyStore(fake)
    store.store(_key())
    assert store.load() == _key()
    # Standard-Base64 (Java: Base64.getDecoder() — normales Alphabet).
    payload = (fake._root / SERVICE / ACCOUNT_STATE_KEY).read_text(encoding="utf-8")
    assert payload == base64.b64encode(_key()).decode("ascii")


def test_req802_state_key_missing_raises(fake: FakeFileKeyringBackend) -> None:
    with pytest.raises(StateKeyError, match="Kein Statusschlüssel"):
        StateKeyStore(fake).load()


def test_req802_state_key_wrong_length_rejected_on_store(
    fake: FakeFileKeyringBackend,
) -> None:
    with pytest.raises(ValueError, match="32 Bytes"):
        StateKeyStore(fake).store(b"zu kurz")


def test_req802_state_key_wrong_length_rejected_on_load(
    fake: FakeFileKeyringBackend,
) -> None:
    path = fake._root / SERVICE / ACCOUNT_STATE_KEY
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(base64.b64encode(b"falsche-laenge-16").decode("ascii"), encoding="utf-8")
    with pytest.raises(StateKeyError, match="32 Bytes"):
        StateKeyStore(fake).load()


def test_req802_state_key_has_key_lifecycle(fake: FakeFileKeyringBackend) -> None:
    store = StateKeyStore(fake)
    assert not store.has_key()
    store.store(_key())
    assert store.has_key()
    store.remove()
    assert not store.has_key()
    store.remove()  # still


def test_req802_state_key_store_unavailable_raises() -> None:
    class _NoneBackend:
        kind = "none"

        def get(self, service: str, account: str) -> str | None:
            raise KeyringUnavailableError("unverfügbar")

        def set(self, service: str, account: str, payload: str) -> None:
            raise KeyringUnavailableError("unverfügbar")

        def delete(self, service: str, account: str) -> None:
            raise KeyringUnavailableError("unverfügbar")

    with pytest.raises(KeyringUnavailableError):
        StateKeyStore(_NoneBackend()).store(_key())


# --------------------------------------------------------------- Backend-Wahl


def test_req802_fake_backend_selected_via_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(FAKE_KEYCHAIN_ENV, str(tmp_path / "kc"))
    backend = ks.default_backend()
    assert isinstance(backend, FakeFileKeyringBackend)
    assert backend.kind == "fake"
    assert ks.current_backend_kind() == "fake"


def test_req802_fake_backend_roundtrip_via_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(FAKE_KEYCHAIN_ENV, str(tmp_path / "kc"))
    store = SialLoginStore()  # Default-Backend = Fake (Env gesetzt)
    store.store("123456", "geheim")
    assert store.load() == StoredCredentials(customer="123456", password="geheim")
    # Layout wie im Java-Testskript: <root>/<service>/<account>.
    assert (tmp_path / "kc" / SERVICE / ACCOUNT_SIA_LOGIN).is_file()


def test_req802_without_env_uses_library_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(FAKE_KEYCHAIN_ENV, raising=False)
    backend = ks.default_backend()
    assert type(backend).__name__ == "LibraryKeyringBackend"
    # Der konkrete Typ hängt vom Host ab (native/file/none) — aber gültig.
    assert ks.current_backend_kind() in {"native", "file", "none"}
