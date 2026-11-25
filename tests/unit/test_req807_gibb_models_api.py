"""REQ-807: gibb-Modellliste — ``GET /v1/models/gibb`` (09 §6.2).

OpenAI-kompatibler ``/models``-Aufruf mit Bearer aus dem OS-Keyring
(Java-1:1 ``OpenAiCompatibleProvider.listModels``). Ohne Key oder ohne
konfiguriertes gibb-Modell sowie bei Erreichbarkeitsfehler:
``{"available": false, "models": []}``. Loopback-Mock (kein echter gibb,
09 §12). Synthetische Testdaten (G4).
"""

from __future__ import annotations

import socket
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient

from sni.app.server import build_app
from sni.app.shop import ShopState
from sni.secrets.keyring_store import GibbApiKeyStore
from tests.conftest import loopback_server

TOKEN = "app-test-token"
BASE = "http://127.0.0.1:8143"
HDRS = {"x-sia-token": TOKEN}

MODELS_BODY = '{"object":"list","data":[{"id":"gibb-m1"},{"id":"gibb-m2"}]}'


def _build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, ShopState]:
    monkeypatch.setenv("SIA_FAKE_KEYCHAIN", str(tmp_path / "keychain"))
    monkeypatch.delenv("SIA_STATE_KEY_B64", raising=False)
    monkeypatch.delenv("GIBB_API_KEY", raising=False)
    shop = ShopState(data_dir=tmp_path / "data")
    app = build_app(
        db_path=tmp_path / "catalog.db",
        knowledge_dir=tmp_path / "extracted",
        rules_dir=tmp_path / "rules",
        sia_token=TOKEN,
        mode="window",
        port=8143,
        shop=shop,
    )
    return TestClient(app, base_url=BASE), shop


def _gibb_models(client: TestClient) -> dict[str, object]:
    res = client.get("/v1/models/gibb", headers=HDRS)
    assert res.status_code == 200, res.text
    return cast("dict[str, object]", res.json())


def _configure_gibb(client: TestClient, server_url: str) -> None:
    res = client.put(
        "/v1/settings",
        headers=HDRS,
        json={
            "gibb_base_url": f"{server_url}/v1",
            "gibb_model": "gibb-m1",
            "gibb_key": "sk-test-123",
        },
    )
    assert res.status_code == 200, res.text


def test_req807_gibb_models_without_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    assert _gibb_models(client) == {"available": False, "models": []}


def test_req807_gibb_models_without_configured_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    GibbApiKeyStore().store("sk-test-123")
    with loopback_server({"/v1/models": lambda _body: (200, MODELS_BODY)}) as server:
        client.put(
            "/v1/settings",
            headers=HDRS,
            json={"gibb_base_url": f"{server.url}/v1"},  # gibb_model bleibt leer
        )
        assert _gibb_models(client) == {"available": False, "models": []}


def test_req807_gibb_models_lists_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    with loopback_server({"/v1/models": lambda _body: (200, MODELS_BODY)}) as server:
        _configure_gibb(client, server.url)
        assert _gibb_models(client) == {"available": True, "models": ["gibb-m1", "gibb-m2"]}


def test_req807_gibb_models_error_available_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    with loopback_server({"/v1/models": lambda _body: (500, "kaputt")}) as server:
        _configure_gibb(client, server.url)
        assert _gibb_models(client) == {"available": False, "models": []}


def test_req807_gibb_models_unreachable_available_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    GibbApiKeyStore().store("sk-test-123")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed_url = f"http://127.0.0.1:{probe.getsockname()[1]}/v1"
    client.put(
        "/v1/settings",
        headers=HDRS,
        json={"gibb_base_url": closed_url, "gibb_model": "gibb-m1"},
    )
    assert _gibb_models(client) == {"available": False, "models": []}
