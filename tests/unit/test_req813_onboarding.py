"""M8.6 (Onboarding, 09 §2): „Erste Schritte“-View.

Erster Lauf → Onboarding (SIA-Login, optional: Ollama-Erkennung, optional:
gibb-API-Key). ``GET /v1/onboarding`` (nur Bool-Status, G4) +
``POST /v1/onboarding/complete`` (Flag in ``workspace.json``, andere
Felder bleiben erhalten). UI: View mit 3 Kacheln, Auto-Redirect beim
ersten Start (ohne Deep Link), über die Einstellungen wieder erreichbar.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sni.app.server import build_app
from sni.app.shop import ShopState
from sni.models.ollama_manager import OllamaModelManager
from sni.secrets.keyring_store import GibbApiKeyStore
from sni.state import workspace
from tests.conftest import (
    LICENSE_XML,
    FakeSoapClient,
    document_result_ok,
    login_result_ok,
    make_mro,
    make_pdf,
    make_srd,
)

TOKEN = "app-test-token"
BASE = "http://127.0.0.1:8127"
HDRS = {"x-sia-token": TOKEN}

STATIC = Path(__file__).resolve().parents[2] / "src" / "sni" / "app" / "static"

PDF = make_pdf(["Testzeile für das Onboarding-Testdokument."])


def _build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    login: bool = False,
) -> tuple[TestClient, ShopState]:
    monkeypatch.setenv("SIA_FAKE_KEYCHAIN", str(tmp_path / "keychain"))
    monkeypatch.delenv("SIA_STATE_KEY_B64", raising=False)
    monkeypatch.delenv("GIBB_API_KEY", raising=False)
    # Ollama hermetisch: Healthcheck darf nie ins Netzwerk gehen
    monkeypatch.setattr(OllamaModelManager, "available", lambda self: False)
    client = FakeSoapClient(
        login_result_ok(),
        make_mro(LICENSE_XML),
        document_result_ok("101_2020_dSIA.srd"),
        make_srd("prod-101", PDF),
    )
    shop = ShopState(client_factory=lambda profile: client, data_dir=tmp_path / "data")
    app = build_app(
        db_path=tmp_path / "catalog.db",
        knowledge_dir=tmp_path / "extracted",
        rules_dir=tmp_path / "rules",
        sia_token=TOKEN,
        mode="window",
        port=8127,
        shop=shop,
    )
    test_client = TestClient(app, base_url=BASE)
    if login:
        res = test_client.post(
            "/v1/session/login",
            headers=HDRS,
            json={
                "provider": "sia",
                "customer": "kunde1",
                "password": "geheim",
                "device_id": "dev-1",
                "remember": False,
            },
        )
        assert res.status_code == 200, res.text
    return test_client, shop


# -------------------------------------------------
# GET /v1/onboarding
# -------------------------------------------------


def test_req813_onboarding_initial_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    res = client.get("/v1/onboarding", headers=HDRS)
    assert res.status_code == 200
    assert res.json() == {
        "done": False,
        "shop_logged_in": False,
        "ollama_available": False,
        "gibb_key_set": False,
    }


def test_req813_onboarding_shop_logged_in(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build(tmp_path, monkeypatch, login=True)
    assert client.get("/v1/onboarding", headers=HDRS).json()["shop_logged_in"] is True


def test_req813_onboarding_gibb_key_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    GibbApiKeyStore().store("test-key")
    assert client.get("/v1/onboarding", headers=HDRS).json()["gibb_key_set"] is True


# -------------------------------------------------
# POST /v1/onboarding/complete
# -------------------------------------------------


def test_req813_onboarding_complete_persists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, shop = _build(tmp_path, monkeypatch)
    res = client.post("/v1/onboarding/complete", headers=HDRS)
    assert res.status_code == 200
    assert res.json() == {"done": True}
    assert client.get("/v1/onboarding", headers=HDRS).json()["done"] is True
    assert workspace.is_onboarding_done(shop.data_dir) is True


def test_req813_onboarding_complete_preserves_other_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, shop = _build(tmp_path, monkeypatch)
    assert (
        client.put("/v1/settings", headers=HDRS, json={"approval_name": "Max"}).status_code == 200
    )
    assert client.post("/v1/onboarding/complete", headers=HDRS).status_code == 200
    state = workspace.load_workspace_json(shop.data_dir) or {}
    assert state["onboarding_done"] is True
    assert state["approval_name"] == "Max"


# -------------------------------------------------
# workspace-Helper
# -------------------------------------------------


def test_req813_onboarding_flag_helpers(tmp_path: Path) -> None:
    assert workspace.is_onboarding_done(tmp_path) is False
    workspace.mark_onboarding_done(tmp_path)
    assert workspace.is_onboarding_done(tmp_path) is True
    state = workspace.load_workspace_json(tmp_path) or {}
    assert state == {"onboarding_done": True}
    # Idempotent
    workspace.mark_onboarding_done(tmp_path)
    assert workspace.load_workspace_json(tmp_path) == {"onboarding_done": True}


# -------------------------------------------------
# UI-Gerüst (statische Dateien)
# -------------------------------------------------


def test_req813_onboarding_view_in_index() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="view-onboarding"' in html
    for chip in ("onboard-shop-chip", "onboard-ollama-chip", "onboard-gibb-chip"):
        assert f'id="{chip}"' in html, f"Kachel-Chip fehlt: {chip}"
    assert 'id="onboard-finish"' in html
    # Wiedererreichbar über die Einstellungen
    assert 'href="#/onboarding"' in html
    # REQ-814: keine externen URLs (auch in den Onboarding-Texten)
    for line in html.splitlines():
        assert "http://" not in line and "https://" not in line


def test_req813_onboarding_js_wired() -> None:
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert '"onboarding"' in js  # im VIEWS-Array (Routing)
    assert "function checkFirstRun()" in js
    assert "function refreshOnboarding()" in js
    assert '"/v1/onboarding"' in js
    assert '"/v1/onboarding/complete"' in js
