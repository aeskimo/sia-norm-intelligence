"""REQ-816: App-API-Sicherheit (Session-Token, Host- und Origin-Validierung).

Das Middleware schützt die App im App-Modus vor anderen lokalen
Prozessen und Browser-Tabs (CSRF, DNS-Rebinding). Die Kern-API ohne
Middleware bleibt unverändert (Rückwärtskompatibilität).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sni.api.main import DISCLAIMER, create_app
from sni.app.security import (
    TOKEN_HEADER,
    LoopbackSecurityMiddleware,
    is_loopback_host,
    is_same_origin,
    new_session_token,
)

TOKEN = "test-token-123"
BASE = "http://127.0.0.1:8123"


@pytest.fixture
def secured_app(tmp_path: Path) -> LoopbackSecurityMiddleware:
    """Kern-API (leere Daten, tmp) + LoopbackSecurityMiddleware mit TOKEN."""
    core = create_app(
        db_path=tmp_path / "catalog.db",
        knowledge_dir=tmp_path / "extracted",
        rules_dir=tmp_path / "rules",
    )
    return LoopbackSecurityMiddleware(core, TOKEN)


def test_req816_token_via_query_passes_security(secured_app: LoopbackSecurityMiddleware) -> None:
    # Given eine App im App-Modus When /v1 mit gültigem Query-Token
    # Then die Sicherheitsschicht lässt durch (404 aus dem Kern, kein 401/403)
    client = TestClient(secured_app, base_url=BASE)
    res = client.get("/v1/concepts/sia:concept/geschossflaeche", params={"sia_token": TOKEN})
    assert res.status_code == 404


def test_req816_token_via_header_passes_security(secured_app: LoopbackSecurityMiddleware) -> None:
    # Given eine App im App-Modus When /v1 mit gültigem Header-Token
    # Then die Sicherheitsschicht lässt durch
    client = TestClient(secured_app, base_url=BASE)
    res = client.get("/v1/concepts/sia:concept/geschossflaeche", headers={TOKEN_HEADER: TOKEN})
    assert res.status_code == 404


def test_req816_missing_token_rejected_401(secured_app: LoopbackSecurityMiddleware) -> None:
    # Given eine App im App-Modus When /v1 ohne Token Then 401
    client = TestClient(secured_app, base_url=BASE)
    res = client.get("/v1/concepts/sia:concept/geschossflaeche")
    assert res.status_code == 401
    assert "error" in res.json()


def test_req816_wrong_token_rejected_401(secured_app: LoopbackSecurityMiddleware) -> None:
    # Given eine App im App-Modus When /v1 mit falschem Token Then 401
    client = TestClient(secured_app, base_url=BASE)
    res = client.get("/v1/concepts/sia:concept/geschossflaeche", params={"sia_token": "falsch"})
    assert res.status_code == 401


def test_req816_healthz_open_without_token(secured_app: LoopbackSecurityMiddleware) -> None:
    # Given eine App im App-Modus When /healthz ohne Token Then 200 (Liveness)
    client = TestClient(secured_app, base_url=BASE)
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_req816_non_loopback_host_rejected_403(secured_app: LoopbackSecurityMiddleware) -> None:
    # Given eine App im App-Modus When Host-Header ist keine Loopback-Domain
    # (DNS-Rebinding-Simulation) Then 403 — auch für /healthz, auch mit Token
    client = TestClient(secured_app, base_url="http://evil.example:8123")
    res = client.get("/healthz", params={"sia_token": TOKEN})
    assert res.status_code == 403


def test_req816_localhost_host_accepted(secured_app: LoopbackSecurityMiddleware) -> None:
    # Given eine App im App-Modus When Host ist localhost Then 200
    client = TestClient(secured_app, base_url="http://localhost:8123")
    res = client.get("/healthz")
    assert res.status_code == 200


def test_req816_foreign_origin_rejected_403(secured_app: LoopbackSecurityMiddleware) -> None:
    # Given eine App im App-Modus When POST mit fremdem Origin (CSRF-Simulation)
    # Then 403 — auch mit gültigem Token
    client = TestClient(secured_app, base_url=BASE)
    res = client.post(
        "/v1/answer",
        json={"question": "Wie viel muss die Feuerwiderstandsdauer?"},
        params={"sia_token": TOKEN},
        headers={"origin": "http://evil.example"},
    )
    assert res.status_code == 403


def test_req816_same_origin_accepted(secured_app: LoopbackSecurityMiddleware) -> None:
    # Given eine App im App-Modus When Origin ist same-origin Then Durchlass
    client = TestClient(secured_app, base_url=BASE)
    res = client.get(
        "/v1/concepts/sia:concept/geschossflaeche",
        params={"sia_token": TOKEN},
        headers={"origin": BASE},
    )
    assert res.status_code == 404  # 404 aus dem Kern, kein 401/403


def test_req816_deny_carries_disclaimer(secured_app: LoopbackSecurityMiddleware) -> None:
    # Given eine App im App-Modus When ein Request abgelehnt wird
    # Then die Fehlerantwort trägt den Disclaimer (G6-Konvention)
    client = TestClient(secured_app, base_url=BASE)
    res = client.get("/v1/concepts/sia:concept/geschossflaeche")
    assert res.json()["disclaimer"] == DISCLAIMER


def test_req816_core_api_without_middleware_unchanged(tmp_path: Path) -> None:
    # Given die Kern-API OHNE Middleware (Dev/CLI, REQ-000…702)
    # When /v1 ohne Token und beliebiger Host Then keine 401/403
    core = create_app(
        db_path=tmp_path / "catalog.db",
        knowledge_dir=tmp_path / "extracted",
        rules_dir=tmp_path / "rules",
    )
    client = TestClient(core)
    res = client.get("/v1/concepts/sia:concept/geschossflaeche")
    assert res.status_code == 404


def test_req816_new_session_token_is_random_ascii() -> None:
    # Given der Token-Generator When zweifach aufgerufen Then zwei
    # verschiedene, ASCII-URL-sichere Tokens
    a = new_session_token()
    b = new_session_token()
    assert a != b
    assert a.isascii() and len(a) == 43


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1:8123", True),
        ("127.0.0.1", True),
        ("localhost:8123", True),
        ("[::1]:8123", True),
        ("::1", True),
        ("evil.example:8123", False),
        ("192.168.1.5:80", False),
        ("127.0.0.2:80", False),
        ("", False),
    ],
)
def test_req816_is_loopback_host_matrix(host: str, expected: bool) -> None:
    # Given ein Host-Header When geprüft Then loopback-Namen akzeptiert
    assert is_loopback_host(host) is expected


def test_req816_is_same_origin_matrix() -> None:
    # Given Host + Origin When verglichen Then nur gleiche Origin passt
    assert is_same_origin("127.0.0.1:8123", "http://127.0.0.1:8123")
    assert not is_same_origin("127.0.0.1:8123", "http://127.0.0.1:9999")
    assert not is_same_origin("127.0.0.1:8123", "http://localhost:8123")
