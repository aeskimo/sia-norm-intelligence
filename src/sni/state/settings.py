"""Einstellungen (REQ-808): ``workspace.json`` lesen/schreiben (09 §6.2).

Komplementär zu :mod:`sni.state.workspace` (Java-Referenz
``PersistedWorkspace``): dieselben Felder, zusätzlich der G3-
Vorbereitung-Schlüssel ``approval_name`` — Zugriff über
``GET/PUT /v1/settings`` mit Validierung.

- ``gibb_base_url`` unterliegt derselben Sicherheitsregel wie
  :class:`sni.rag.providers.gibb.OpenAiCompatibleProvider`: HTTPS nur
  (http ausschliesslich Loopback).
- Der gibb-API-Key lebt ausschliesslich im OS-Keyring
  (:class:`sni.secrets.keyring_store.GibbApiKeyStore`); er ist nie
  Teil von ``workspace.json`` oder einer Antwort (G4). v1 hat keinen
  Lösch-Weg (leerer Wert = unverändert).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlparse

from sni.state.workspace import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_GENERATION_MODEL,
    DEFAULT_GIBB_BASE_URL,
    DEFAULT_GIBB_MODEL,
    DEFAULT_PROVIDER,
    load_workspace_json,
    save_workspace_json,
)

#: Schreibbare Einstellungen (``PUT /v1/settings``); ``gibb_key`` wird
#: separat im Keyring behandelt und gehört nicht zu ``workspace.json``.
SETTING_KEYS = (
    "generation_model",
    "embedding_model",
    "provider",
    "gibb_base_url",
    "gibb_model",
    "approval_name",
)

#: Bekannte Antwort-Provider (09 §5.1: lokal Ollama / gibb).
KNOWN_PROVIDERS = ("ollama", "gibb")


def load_settings(data_dir: Path | None = None) -> dict[str, object]:
    """Einstellungen mit Java-1:1-Defaults (fehlende Felder → Default)."""
    state = load_workspace_json(data_dir) or {}
    return {
        "generation_model": str(state.get("generation_model") or DEFAULT_GENERATION_MODEL),
        "embedding_model": str(state.get("embedding_model") or DEFAULT_EMBEDDING_MODEL),
        "provider": str(state.get("provider") or DEFAULT_PROVIDER),
        "gibb_base_url": str(state.get("gibb_base_url") or DEFAULT_GIBB_BASE_URL),
        "gibb_model": str(state.get("gibb_model") or DEFAULT_GIBB_MODEL),
        "approval_name": str(state.get("approval_name") or ""),
    }


def _check_gibb_base_url(url: str) -> None:
    """HTTPS-Zwang (1:1-Regel von ``OpenAiCompatibleProvider``)."""
    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "").lower()
    host = parsed.hostname or ""
    loopback = host == "127.0.0.1" or host.lower() == "localhost" or host == "::1"
    if not (scheme == "https" or (loopback and scheme == "http")):
        raise ValueError("Nur HTTPS-Endpunkte erlaubt (http ausschliesslich Loopback)")


def update_settings(data_dir: Path | None, updates: Mapping[str, object]) -> dict[str, object]:
    """Teilmenge der Einstellungen aktualisieren (atomar) und neu laden.

    Unbekannte Felder, nicht-Text-Werte, fremde Provider und nicht-HTTPS
    gibb-URLs werfen ``ValueError`` — nichts wird dann persistiert.
    """
    state = load_workspace_json(data_dir) or {}
    for key, value in updates.items():
        if key not in SETTING_KEYS:
            raise ValueError(f"Unbekanntes Einstellungsfeld: {key!r}")
        if not isinstance(value, str):
            raise ValueError(f"Einstellung {key!r} muss ein Textfeld sein")
        if key == "provider" and value.strip() not in KNOWN_PROVIDERS:
            raise ValueError(f"Unbekannter Provider: {value!r}")
        if key == "gibb_base_url":
            _check_gibb_base_url(value)
    state.update(updates)
    save_workspace_json(state, data_dir)
    return load_settings(data_dir)
