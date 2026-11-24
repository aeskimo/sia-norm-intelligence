"""REQ-800: App-Shell — Server-Zusammensetzung (Static UI, /v1/status, Sicherheit)."""

from __future__ import annotations

import json
import socket
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from sni.api.main import DISCLAIMER
from sni.app.server import HOST, build_app, pick_free_port, ui_url

TOKEN = "test-token"
BASE = "http://127.0.0.1:8123"
SCHEMAS = Path(__file__).resolve().parents[2] / "schemas"


@pytest.fixture
def app_server(tmp_path: Path) -> Iterator[TestClient]:
    """Kern-API + Static-UI + App-Router + Sicherheit (Fenster-Modus)."""
    app = build_app(
        db_path=tmp_path / "catalog.db",
        knowledge_dir=tmp_path / "extracted",
        rules_dir=tmp_path / "rules",
        sia_token=TOKEN,
        mode="window",
        port=8123,
    )
    with TestClient(app, base_url=BASE) as client:
        yield client


def test_req800_index_served_at_root(app_server: TestClient) -> None:
    # Given der App-Modus When GET / Then die UI (index.html) wird ausgeliefert
    res = app_server.get("/")
    assert res.status_code == 200
    assert "SIA-Normenassistent" in res.text


def test_req800_static_assets_served(app_server: TestClient) -> None:
    # Given der App-Modus When GET /static/* Then die UI-Assets werden ausgeliefert
    for path in ("/static/sia.css", "/static/app.js", "/static/index.html"):
        assert app_server.get(path).status_code == 200


def test_req800_status_returns_app_state(app_server: TestClient) -> None:
    # Given der App-Modus When GET /v1/status (mit Token) Then der App-Zustand
    res = app_server.get("/v1/status", headers={"x-sia-token": TOKEN})
    assert res.status_code == 200
    data = res.json()
    assert data["version"]
    assert data["mode"] == "window"
    assert data["port"] == 8123
    assert data["login"] is None  # M8.2
    assert data["ollama"] is None  # M8.4
    assert data["documents"] == 0
    assert data["summary"] == "Bereit."
    assert data["disclaimer"] == DISCLAIMER


def test_req800_status_payload_validates_against_schema(app_server: TestClient) -> None:
    # Given das Schema sni:status When die echte Status-Antwort geprüft Then gültig
    schema = json.loads((SCHEMAS / "status.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    res = app_server.get("/v1/status", headers={"x-sia-token": TOKEN})
    Draft202012Validator(schema).validate(res.json())


def test_req800_status_requires_token(app_server: TestClient) -> None:
    # Given der App-Modus When GET /v1/status ohne Token Then 401 (REQ-816)
    assert app_server.get("/v1/status").status_code == 401


def test_req800_core_endpoints_still_reachable(app_server: TestClient) -> None:
    # Given der App-Modus When ein Kern-API-Endpunkt (mit Token)
    # Then 404 aus dem Kern — nicht 401/403 (Kern bleibt unverändert)
    res = app_server.get("/v1/concepts/sia:concept/geschossflaeche", headers={"x-sia-token": TOKEN})
    assert res.status_code == 404


def test_req800_pick_free_port_is_free() -> None:
    # Given der Launcher When Port gewählt Then frei (noch bindbar, REQ-816)
    port = pick_free_port()
    assert 0 < port < 65536
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, port))


def test_req800_ui_url_carries_token() -> None:
    # Given der Launcher When UI-URL gebildet Then Token als Query-Parameter (REQ-816)
    assert ui_url(8123, "abc") == "http://127.0.0.1:8123/?sia_token=abc"
