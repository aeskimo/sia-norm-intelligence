"""REQ-815: Workspace-Codec + Persistenz-Service (Port von
``WorkspaceCodec``/``WorkspacePersistenceService``, Java-Referenz) und
Python-Zielzustand ``workspace.json``.

Zeilenformat mit Base64-URL-Feldern (SIASST1-Inhalt); Decode-Defaults
wie Java (``qwen3:4b``/``embeddinggemma``/``ollama``/
``https://chat.gibb.ch/api``/``""``); kein Klartext im Vault,
Manipulation wird abgelehnt (1:1 ``M2EncryptedPersistenceSelfTest``).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from sni.state.vault import EncryptedStateVault
from sni.state.workspace import (
    DEFAULT_GENERATION_MODEL,
    DEFAULT_GIBB_BASE_URL,
    DEFAULT_PROVIDER,
    PersistedWorkspace,
    WorkspaceCodec,
    WorkspacePersistenceService,
    load_workspace_json,
    save_workspace_json,
    workspace_file,
)

KEY = bytes((7,) * 32)


class _StaticKeys:
    def __init__(self, key: bytes | None) -> None:
        self._key = key

    def load(self) -> bytes:
        if self._key is None:
            raise RuntimeError("kein Schlüssel")
        return self._key

    def available(self) -> bool:
        return self._key is not None


def _workspace() -> PersistedWorkspace:
    return PersistedWorkspace(
        generation_model="qwen3:8b",
        embedding_model="embed-test",
        worksets={"Nassräume": ("sia271", "sia118-271")},
        provider="ollama",
        gibb_base_url="https://chat.gibb.ch/api",
        gibb_model="gibb-model",
    )


# ------------------------------------------------------------------ Codec


def test_req815_workspace_codec_roundtrip() -> None:
    codec = WorkspaceCodec()
    decoded = codec.decode(codec.encode(_workspace()))
    assert decoded == _workspace()


def test_req815_workspace_codec_defaults_on_empty_input() -> None:
    decoded = WorkspaceCodec().decode(b"version=1\n")
    assert decoded.generation_model == DEFAULT_GENERATION_MODEL
    assert decoded.embedding_model == "embeddinggemma"
    assert decoded.provider == DEFAULT_PROVIDER
    assert decoded.gibb_base_url == DEFAULT_GIBB_BASE_URL
    assert decoded.gibb_model == ""
    assert dict(decoded.worksets) == {}


def test_req815_workspace_codec_uses_b64url_fields() -> None:
    encoded = WorkspaceCodec().encode(_workspace()).decode("utf-8")
    # Arbeitsset-Name mit Umlaut ist nie im Klartext im Encoding.
    assert "Nassräume" not in encoded
    assert "qwen3:8b" not in encoded
    assert encoded.startswith("version=1\n")
    lines = encoded.splitlines()
    assert any(line.startswith("workset=") for line in lines)
    # b64url: kein Standard-Base64-Zeichen (+, /, =).
    for line in lines[1:]:
        value = line.split("=", 1)[1]
        assert not any(char in value for char in "+/=")


def test_req815_workspace_codec_ignores_unknown_lines() -> None:
    decoded = WorkspaceCodec().decode(b"version=1\nfoo=bar\nworkset=\n")
    assert dict(decoded.worksets) == {}


def test_req815_workspace_codec_workset_dedup_and_skip_incomplete() -> None:
    # b64url-nopad: "name" → "bmFtZQ", "id1" → "aWQx".
    text = (
        "version=1\n"
        "workset=bmFtZQ|aWQx\n"
        "workset=bmFtZQ|aWQx\n"  # Duplikat → LinkedHashSet-Semantik
        "workset=bmFtZQ\n"  # ohne Pipe → verworfen
    )
    decoded = WorkspaceCodec().decode(text.encode("utf-8"))
    assert dict(decoded.worksets) == {"name": ("id1",)}


# ------------------------------------------------------------------ Persistenz


def _service(tmp_path: Path) -> WorkspacePersistenceService:
    vault = EncryptedStateVault(tmp_path / "workspace.state", _StaticKeys(KEY))
    return WorkspacePersistenceService(vault)


def test_req815_workspace_persistence_roundtrip(tmp_path: Path) -> None:
    service = _service(tmp_path)
    assert service.load() is None
    service.save(_workspace())
    loaded = service.load()
    assert loaded is not None
    assert loaded.generation_model == "qwen3:8b"
    assert loaded.worksets["Nassräume"] == ("sia271", "sia118-271")


def test_req815_workspace_persistence_no_plaintext_and_tamper(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.save(_workspace())
    raw = bytearray(service._vault.file.read_bytes())
    assert "Nassräume".encode() not in bytes(raw)
    assert b"qwen3:8b" not in bytes(raw)
    raw[-1] ^= 1  # Manipulation: GCM-Tag schlägt fehl (Java-Referenz).
    service._vault.file.write_bytes(bytes(raw))
    with pytest.raises(InvalidTag):
        service.load()


# ------------------------------------------------------------------ workspace.json


def test_req815_workspace_json_roundtrip(tmp_path: Path) -> None:
    assert load_workspace_json(tmp_path) is None
    state = {"device_id": "dev-1", "embedding_model": "embed-test", "gibb_key_set": False}
    save_workspace_json(state, tmp_path)
    assert load_workspace_json(tmp_path) == state
    assert (tmp_path / "workspace.json").is_file()


def test_req815_workspace_json_atomic_no_leftovers(tmp_path: Path) -> None:
    save_workspace_json({"a": 1}, tmp_path)
    save_workspace_json({"a": 2}, tmp_path)
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["workspace.json"]


def test_req815_workspace_json_creates_parent(tmp_path: Path) -> None:
    save_workspace_json({"a": 1}, tmp_path / "nested" / "dir")
    assert (tmp_path / "nested" / "dir" / "workspace.json").is_file()


def test_req815_workspace_file_default_uses_user_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SIA_DATA_DIR", str(tmp_path))
    assert workspace_file() == tmp_path / "workspace.json"
