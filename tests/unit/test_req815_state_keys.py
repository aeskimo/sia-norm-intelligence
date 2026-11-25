"""REQ-815: 256-Bit-Statusschlüssel (Port der Java-Provider).

Umgebungsvariable ``SIA_STATE_KEY_B64`` zuerst, danach OS-Keyring
(Account ``state-key``, gleiches Layout wie Java); Kette wie
``ChainedStateKeyProvider`` (Java-Referenz).
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from sni.secrets.keyring_store import (
    ACCOUNT_STATE_KEY,
    SERVICE,
    FakeFileKeyringBackend,
    StateKeyError,
    StateKeyStore,
)
from sni.state.keys import (
    ChainedStateKeyProvider,
    EnvironmentStateKeyProvider,
    KeyringStateKeyProvider,
)

KEY = bytes(range(1, 33))


class _BrokenProvider:
    """Quelle, deren ``available()`` wirft (Kette muss weiterlaufen)."""

    def available(self) -> bool:
        raise RuntimeError("defekte Quelle")

    def load(self) -> bytes:
        raise RuntimeError("defekte Quelle")


# ------------------------------------------------------------------ Env-Provider


def test_req815_env_provider_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIA_STATE_KEY_B64", raising=False)
    provider = EnvironmentStateKeyProvider()
    assert provider.available() is False
    with pytest.raises(RuntimeError, match="SIA_STATE_KEY_B64 ist nicht gesetzt"):
        provider.load()


def test_req815_env_provider_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIA_STATE_KEY_B64", "   ")
    provider = EnvironmentStateKeyProvider()
    assert provider.available() is False


def test_req815_env_provider_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIA_STATE_KEY_B64", base64.b64encode(KEY).decode("ascii"))
    provider = EnvironmentStateKeyProvider()
    assert provider.available() is True
    assert provider.load() == KEY


def test_req815_env_provider_wrong_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Java 1:1: available() prüft nur Vorhandensein; load() validiert.
    monkeypatch.setenv("SIA_STATE_KEY_B64", base64.b64encode(b"1" * 16).decode("ascii"))
    provider = EnvironmentStateKeyProvider()
    assert provider.available() is True
    with pytest.raises(ValueError, match="Statusschlüssel muss 32 Bytes lang sein"):
        provider.load()


def test_req815_env_provider_invalid_base64(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIA_STATE_KEY_B64", "!!!keine-base64!!!")
    provider = EnvironmentStateKeyProvider()
    assert provider.available() is True
    with pytest.raises(ValueError):
        provider.load()


# ------------------------------------------------------------------ Keyring-Provider


def _keyring_provider(tmp_path: Path) -> tuple[KeyringStateKeyProvider, StateKeyStore]:
    store = StateKeyStore(backend=FakeFileKeyringBackend(tmp_path))
    return KeyringStateKeyProvider(store=store), store


def test_req815_keyring_provider_empty(tmp_path: Path) -> None:
    provider, _store = _keyring_provider(tmp_path)
    assert provider.available() is False


def test_req815_keyring_provider_roundtrip(tmp_path: Path) -> None:
    provider, store = _keyring_provider(tmp_path)
    store.store(KEY)
    assert provider.available() is True
    assert provider.load() == KEY


def test_req815_keyring_provider_wrong_length_rejected(tmp_path: Path) -> None:
    _provider, store = _keyring_provider(tmp_path)
    with pytest.raises(ValueError, match="Statusschlüssel muss 32 Bytes lang sein"):
        store.store(b"1" * 16)


def test_req815_keyring_provider_invalid_payload(tmp_path: Path) -> None:
    backend = FakeFileKeyringBackend(tmp_path)
    backend.set(SERVICE, ACCOUNT_STATE_KEY, "kein-base64")
    provider = KeyringStateKeyProvider(store=StateKeyStore(backend=backend))
    with pytest.raises(StateKeyError, match="gültiges Base64"):
        provider.load()


# ------------------------------------------------------------------ Kette


def test_req815_chain_env_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_key = bytes(range(33, 65))
    monkeypatch.setenv("SIA_STATE_KEY_B64", base64.b64encode(env_key).decode("ascii"))
    provider, store = _keyring_provider(tmp_path)
    store.store(KEY)  # Keyring hat einen anderen Schlüssel — muss verloren bleiben.
    chain = ChainedStateKeyProvider(EnvironmentStateKeyProvider(), provider)
    assert chain.available() is True
    assert chain.load() == env_key


def test_req815_chain_keyring_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIA_STATE_KEY_B64", raising=False)
    provider, store = _keyring_provider(tmp_path)
    store.store(KEY)
    chain = ChainedStateKeyProvider(EnvironmentStateKeyProvider(), provider)
    assert chain.available() is True
    assert chain.load() == KEY


def test_req815_chain_no_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIA_STATE_KEY_B64", raising=False)
    provider, _store = _keyring_provider(tmp_path)
    chain = ChainedStateKeyProvider(EnvironmentStateKeyProvider(), provider)
    assert chain.available() is False
    with pytest.raises(RuntimeError, match="Kein Statusschlüssel verfügbar"):
        chain.load()


def test_req815_chain_broken_source_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SIA_STATE_KEY_B64", base64.b64encode(KEY).decode("ascii"))
    chain = ChainedStateKeyProvider(_BrokenProvider(), EnvironmentStateKeyProvider())
    assert chain.available() is True
    assert chain.load() == KEY
