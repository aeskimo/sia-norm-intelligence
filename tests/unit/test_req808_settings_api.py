"""REQ-808: Einstellungen — ``GET/PUT /v1/settings`` (09 §6.2).

GET liefert die Java-1:1-Defaults + Status-Felder (``gibb_key_set``,
``state_key_set``, ``data_dir``); der gibb-Key ist nie Teil der Antwort
(G4). PUT aktualisiert eine Teilmenge atomar; ``gibb_key`` (nicht-leer)
geht in den OS-Keyring (kein Lösch-Weg in v1); ``gibb_base_url`` ist
HTTPS-only (http nur Loopback, 1:1 Provider-Regel). Synthetische
Testdaten (G4).
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient

from sni.app.server import build_app
from sni.app.shop import ShopState
from sni.secrets.keyring_store import GibbApiKeyStore
from sni.state.settings import update_settings
from sni.state.workspace import load_workspace_json, save_workspace_json

TOKEN = "app-test-token"
BASE = "http://127.0.0.1:8142"
HDRS = {"x-sia-token": TOKEN}


def _build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, ShopState]:
    monkeypatch.setenv("SIA_FAKE_KEYCHAIN", str(tmp_path / "keychain"))
    monkeypatch.delenv("SIA_STATE_KEY_B64", raising=False)
    shop = ShopState(data_dir=tmp_path / "data")
    app = build_app(
        db_path=tmp_path / "catalog.db",
        knowledge_dir=tmp_path / "extracted",
        rules_dir=tmp_path / "rules",
        sia_token=TOKEN,
        mode="window",
        port=8142,
        shop=shop,
    )
    return TestClient(app, base_url=BASE), shop


def _settings(client: TestClient) -> dict[str, object]:
    res = client.get("/v1/settings", headers=HDRS)
    assert res.status_code == 200, res.text
    return cast("dict[str, object]", res.json())


# ------------------------------------------------------------------ GET


def test_req808_settings_get_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, shop = _build(tmp_path, monkeypatch)
    data = _settings(client)
    assert data["generation_model"] == "qwen3:4b"  # Java-1:1-Defaults
    assert data["embedding_model"] == "embeddinggemma"
    assert data["provider"] == "ollama"
    assert data["gibb_base_url"] == "https://chat.gibb.ch/api"
    assert data["gibb_model"] == ""
    assert data["approval_name"] == ""
    assert data["gibb_key_set"] is False
    assert data["state_key_set"] is False
    assert data["data_dir"] == str(shop.data_dir)
    assert data["disclaimer"]
    assert "gibb_key" not in data  # G4: Key nie in der Antwort


def test_req808_settings_get_reflects_saved_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, shop = _build(tmp_path, monkeypatch)
    save_workspace_json(
        {
            "generation_model": "qwen3:8b",
            "provider": "gibb",
            "gibb_model": "gibb-m1",
            "approval_name": "Test-Freigabe",
        },
        shop.data_dir,
    )
    data = _settings(client)
    assert data["generation_model"] == "qwen3:8b"
    assert data["provider"] == "gibb"
    assert data["gibb_model"] == "gibb-m1"
    assert data["approval_name"] == "Test-Freigabe"


def test_req808_settings_state_key_set_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    monkeypatch.setenv("SIA_STATE_KEY_B64", base64.b64encode(b"\x00" * 32).decode("ascii"))
    assert _settings(client)["state_key_set"] is True


# ------------------------------------------------------------------ PUT


def test_req808_settings_put_partial_persists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, shop = _build(tmp_path, monkeypatch)
    res = client.put("/v1/settings", headers=HDRS, json={"generation_model": "qwen3:8b"})
    assert res.status_code == 200, res.text
    body = cast("dict[str, object]", res.json())
    assert body["generation_model"] == "qwen3:8b"
    assert body["embedding_model"] == "embeddinggemma"  # Rest unverändert
    state = load_workspace_json(shop.data_dir)
    assert state is not None
    assert state["generation_model"] == "qwen3:8b"
    assert "gibb_key" not in state


def test_req808_settings_put_all_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, shop = _build(tmp_path, monkeypatch)
    res = client.put(
        "/v1/settings",
        headers=HDRS,
        json={
            "generation_model": "qwen3:8b",
            "embedding_model": "nomic-embed",
            "provider": "gibb",
            "gibb_base_url": "https://chat.gibb.ch/api",
            "gibb_model": "gibb-m1",
            "approval_name": "SIA Test",
        },
    )
    assert res.status_code == 200, res.text
    data = _settings(client)
    assert data["provider"] == "gibb"
    assert data["gibb_model"] == "gibb-m1"
    assert data["approval_name"] == "SIA Test"
    assert data["generation_model"] == "qwen3:8b"


def test_req808_settings_put_unknown_provider_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    res = client.put("/v1/settings", headers=HDRS, json={"provider": "azure"})
    assert res.status_code == 400
    assert "Unbekannter Provider" in res.json()["error"]
    assert _settings(client)["provider"] == "ollama"  # nichts persistiert


def test_req808_settings_put_non_http_gibb_url_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    res = client.put("/v1/settings", headers=HDRS, json={"gibb_base_url": "http://example.com/v1"})
    assert res.status_code == 400
    assert "Nur HTTPS-Endpunkte erlaubt" in res.json()["error"]


def test_req808_settings_put_loopback_http_gibb_url_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # http nur auf Loopback (1:1 OpenAiCompatibleProvider-Regel; Dev-Setup).
    client, _ = _build(tmp_path, monkeypatch)
    res = client.put(
        "/v1/settings", headers=HDRS, json={"gibb_base_url": "http://127.0.0.1:9911/v1"}
    )
    assert res.status_code == 200
    assert _settings(client)["gibb_base_url"] == "http://127.0.0.1:9911/v1"


def test_req808_settings_put_non_string_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    res = client.put("/v1/settings", headers=HDRS, json={"generation_model": 42})
    assert res.status_code == 422  # Pydantic-Typprüfung


def test_req808_settings_put_gibb_key_to_keyring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, shop = _build(tmp_path, monkeypatch)
    res = client.put("/v1/settings", headers=HDRS, json={"gibb_key": "sk-test-123"})
    assert res.status_code == 200, res.text
    body = cast("dict[str, object]", res.json())
    assert body["gibb_key_set"] is True
    assert "gibb_key" not in body
    state = load_workspace_json(shop.data_dir)
    assert state is None or "gibb_key" not in state  # Key nie in workspace.json
    assert GibbApiKeyStore().load() == "sk-test-123"  # Keyring (Fake-Backend)


def test_req808_settings_put_empty_gibb_key_is_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # v1 ohne Lösch-Weg: leerer Wert = unverändert (G4).
    client, _ = _build(tmp_path, monkeypatch)
    GibbApiKeyStore().store("sk-bestehend")
    res = client.put("/v1/settings", headers=HDRS, json={"gibb_key": "   "})
    assert res.status_code == 200
    assert cast("dict[str, object]", res.json())["gibb_key_set"] is True
    assert GibbApiKeyStore().load() == "sk-bestehend"


# ------------------------------------------------------------------ update_settings (Modul)


def test_req808_update_settings_rejects_unknown_key(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unbekanntes Einstellungsfeld"):
        update_settings(tmp_path, {"bogus": "x"})
    assert load_workspace_json(tmp_path) is None  # nichts persistiert


def test_req808_update_settings_rejects_non_string(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="muss ein Textfeld"):
        update_settings(tmp_path, {"generation_model": 42})
