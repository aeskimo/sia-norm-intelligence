"""Workspace-Zustand: Einstellungen + Arbeitssets (REQ-815, ADR-0011).

1:1-Port von ``ch.sia.integration.persistence`` (Java-Referenz:
``WorkspaceCodec``, ``PersistedWorkspace``,
``WorkspacePersistenceService``):

- Zeilenformat mit Base64-URL-Feldern (SIASST1-Inhalt) — in Python nur
  zum **Import** des Java-Stands (``workspace.state``, REQ-815).
- Python-Zielzustand: ``workspace.json`` (non-secret, 09 §9.1),
  atomar geschrieben.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from sni.state.paths import user_data_dir
from sni.state.vault import EncryptedStateVault

#: Java-1:1-Decode-Defaults (``WorkspaceCodec.decode``).
DEFAULT_GENERATION_MODEL = "qwen3:4b"
DEFAULT_EMBEDDING_MODEL = "embeddinggemma"
DEFAULT_PROVIDER = "ollama"
DEFAULT_GIBB_BASE_URL = "https://chat.gibb.ch/api"
DEFAULT_GIBB_MODEL = ""


def _enc(value: str) -> str:
    """Java: ``Base64.getUrlEncoder().withoutPadding()`` (UTF-8)."""
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _dec(value: str) -> str:
    """Java: ``Base64.getUrlDecoder()`` (toleriert fehlendes Padding)."""
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")


@dataclass(frozen=True, slots=True)
class PersistedWorkspace:
    """Einstellungen + Arbeitssets (Java: ``PersistedWorkspace``; keine Normtexte)."""

    generation_model: str
    embedding_model: str
    worksets: Mapping[str, tuple[str, ...]]
    provider: str
    gibb_base_url: str
    gibb_model: str = DEFAULT_GIBB_MODEL


class WorkspaceCodec:
    """Zeilenformat mit Base64-URL-Feldern (Java 1:1)."""

    def encode(self, workspace: PersistedWorkspace) -> bytes:
        lines = [
            "version=1",
            f"generation={_enc(workspace.generation_model)}",
            f"embedding={_enc(workspace.embedding_model)}",
            f"provider={_enc(workspace.provider)}",
            f"gibbbase={_enc(workspace.gibb_base_url)}",
            f"gibbmodel={_enc(workspace.gibb_model)}",
        ]
        for name, doc_ids in workspace.worksets.items():
            for doc_id in doc_ids:
                lines.append(f"workset={_enc(name)}|{_enc(doc_id)}")
        return ("\n".join(lines) + "\n").encode("utf-8")

    def decode(self, data: bytes) -> PersistedWorkspace:
        generation = DEFAULT_GENERATION_MODEL
        embedding = DEFAULT_EMBEDDING_MODEL
        provider = DEFAULT_PROVIDER
        gibb_base = DEFAULT_GIBB_BASE_URL
        gibb_model = DEFAULT_GIBB_MODEL
        worksets: dict[str, list[str]] = {}
        for line in data.decode("utf-8").splitlines():
            if line.startswith("generation="):
                generation = _dec(line[11:])
            elif line.startswith("embedding="):
                embedding = _dec(line[10:])
            elif line.startswith("provider="):
                provider = _dec(line[9:])
            elif line.startswith("gibbbase="):
                gibb_base = _dec(line[9:])
            elif line.startswith("gibbmodel="):
                gibb_model = _dec(line[10:])
            elif line.startswith("workset="):
                parts = line[8:].split("|", 1)  # Java: split("\\|", 2)
                if len(parts) == 2:
                    name = _dec(parts[0])
                    doc_id = _dec(parts[1])
                    docs = worksets.setdefault(name, [])
                    if doc_id not in docs:  # Java: LinkedHashSet
                        docs.append(doc_id)
        return PersistedWorkspace(
            generation_model=generation,
            embedding_model=embedding,
            worksets={name: tuple(docs) for name, docs in worksets.items()},
            provider=provider,
            gibb_base_url=gibb_base,
            gibb_model=gibb_model,
        )


class WorkspacePersistenceService:
    """Lesen/Schreiben des verschlüsselten Java-Stands (SIASST1, Java 1:1)."""

    def __init__(self, vault: EncryptedStateVault) -> None:
        self._vault = vault
        self._codec = WorkspaceCodec()

    def save(self, workspace: PersistedWorkspace) -> None:
        self._vault.save(self._codec.encode(workspace))

    def load(self) -> PersistedWorkspace | None:
        if not self._vault.exists():
            return None
        return self._codec.decode(self._vault.load())


# ---------------------------------------------------------------------------
# Python-Zielzustand workspace.json (non-secret, 09 §9.1)
# ---------------------------------------------------------------------------


def workspace_file(data_dir: Path | None = None) -> Path:
    """Pfad zu ``workspace.json`` (09 §9.1)."""
    return (data_dir if data_dir is not None else user_data_dir()) / "workspace.json"


def load_workspace_json(data_dir: Path | None = None) -> dict[str, object] | None:
    """Liest ``workspace.json``; ``None``, wenn nicht vorhanden."""
    path = workspace_file(data_dir)
    if not path.is_file():
        return None
    return cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))


def save_workspace_json(state: Mapping[str, object], data_dir: Path | None = None) -> None:
    """Schreibt ``workspace.json`` atomar (Temp-Datei + ``os.replace``)."""
    path = workspace_file(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(dict(state), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    fd, tmp_name = tempfile.mkstemp(prefix=".sia-workspace-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as tmp:
            tmp.write(payload)
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.remove(tmp_name)
        raise
    del payload


def is_onboarding_done(data_dir: Path | None = None) -> bool:
    """Onboarding-Flag (M8.6): True, wenn „Erste Schritte“ abgeschlossen."""
    return bool((load_workspace_json(data_dir) or {}).get("onboarding_done"))


def mark_onboarding_done(data_dir: Path | None = None) -> None:
    """Setzt das Onboarding-Flag (übrige Felder bleiben erhalten)."""
    state = load_workspace_json(data_dir) or {}
    state["onboarding_done"] = True
    save_workspace_json(state, data_dir)
