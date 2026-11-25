"""256-Bit-Statusschlüssel (REQ-815, ADR-0011 Punkt 6).

1:1-Port von ``ch.sia.integration.persistence`` (Java-Referenz:
``StateKeyProvider``, ``EnvironmentStateKeyProvider``,
``KeychainStateKeyProvider``, ``ChainedStateKeyProvider``): zuerst
Umgebungsvariable ``SIA_STATE_KEY_B64``, danach OS-Keyring (Account
``state-key`` — gleiches Layout wie Java, gegenseitig lesbar).

Ohne verfügbaren Schlüssel bleiben die verschlüsselten Status- und
Index-Store bewusst inaktiv: kein Klartext-Fallback (G4).
"""

from __future__ import annotations

import base64
import os
from typing import Protocol

from sni.secrets.keyring_store import StateKeyStore


class StateKeyProvider(Protocol):
    """Quelle für den 256-Bit-Statusschlüssel (Java: ``StateKeyProvider``)."""

    def load(self) -> bytes:
        """Liefert die 32 rohen Bytes; wirft, wenn keiner vorliegt."""
        ...

    def available(self) -> bool:
        """Prüft, ob ein Schlüssel verfügbar ist, ohne zu laden (wirft nie)."""
        ...


class EnvironmentStateKeyProvider:
    """Liest den Schlüssel aus ``SIA_STATE_KEY_B64`` (Standard-Base64, 32 Bytes).

    Java 1:1: ``available()`` prüft nur Vorhandensein (nicht Länge);
    ``load()`` validiert und wirft sonst.
    """

    ENV_VAR = "SIA_STATE_KEY_B64"

    def available(self) -> bool:
        value = os.environ.get(self.ENV_VAR)
        return value is not None and value.strip() != ""

    def load(self) -> bytes:
        value = os.environ.get(self.ENV_VAR)
        if value is None or not value.strip():
            raise RuntimeError(f"{self.ENV_VAR} ist nicht gesetzt")
        raw = base64.b64decode(value.strip(), validate=True)
        if len(raw) != 32:
            raise ValueError("Statusschlüssel muss 32 Bytes lang sein")
        return raw


class KeyringStateKeyProvider:
    """Liest den Schlüssel aus dem OS-Keyring (Java: ``KeychainStateKeyProvider``)."""

    def __init__(self, store: StateKeyStore | None = None) -> None:
        self._store = store if store is not None else StateKeyStore()

    def available(self) -> bool:
        try:
            return self._store.has_key()
        except Exception:
            return False

    def load(self) -> bytes:
        return self._store.load()


class ChainedStateKeyProvider:
    """Verknüpft mehrere Schlüsselquellen in fester Reihenfolge (Java 1:1).

    Die erste verfügbare Quelle gewinnt; beim Laden wird die gleiche
    Reihenfolge geprüft, damit ``available()`` und ``load()`` konsistent
    bleiben.
    """

    def __init__(self, *providers: StateKeyProvider) -> None:
        self._chain = tuple(providers)

    def available(self) -> bool:
        for provider in self._chain:
            try:
                if provider.available():
                    return True
            except Exception:
                # Quelle defekt: nächste Quelle versuchen.
                continue
        return False

    def load(self) -> bytes:
        last: Exception | None = None
        for provider in self._chain:
            try:
                if provider.available():
                    return provider.load()
            except Exception as exc:
                last = exc
        if last is not None:
            raise last
        raise RuntimeError("Kein Statusschlüssel verfügbar (Umgebungsvariable oder macOS Keychain)")


def default_state_keys() -> ChainedStateKeyProvider:
    """Produktionskette: Umgebungsvariable, dann Keyring (Java 1:1-Reihenfolge)."""
    return ChainedStateKeyProvider(EnvironmentStateKeyProvider(), KeyringStateKeyProvider())
