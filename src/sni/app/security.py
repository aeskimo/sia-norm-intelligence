"""App-API-Sicherheit für den Consumer-App-Modus (REQ-816, ADR-0007).

`127.0.0.1` schützt nicht vor anderen lokalen Prozessen und nicht vor
Browser-Tabs (CSRF, DNS-Rebinding). Das Middleware schützt deshalb:

- Host-Check: der ``Host``-Header muss loopback sein (Schutz gegen
  DNS-Rebinding — eine Angreifer-Domain, die auf 127.0.0.1 zeigt,
  taucht im Host-Header unter ihrem Namen auf)
- Origin-Check: ein vorhandener ``Origin``-Header muss same-origin
  sein (Schutz gegen CSRF via fremder Webseite)
- Token-Check: alle ``/v1/*``-Endpunkte verlangen das Session-Token
  (Query-Parameter ``sia_token`` oder Header ``x-sia-token``)

Nur im App-Modus aktiv: der Launcher (``sni.app``) legt das Middleware
um die Kern-API; die Kern-API selbst bleibt unverändert
(Rückwärtskompatibilität). ``/healthz`` und die Static-UI bleiben offen
(das Token kommt über die UI-URL).
"""

from __future__ import annotations

import secrets
from urllib.parse import parse_qs

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from sni.api.main import DISCLAIMER

TOKEN_HEADER = "x-sia-token"
TOKEN_QUERY = "sia_token"
_LOOPBACK_NAMES = frozenset({"127.0.0.1", "localhost", "::1"})


def new_session_token() -> str:
    """Erzeugt ein zufälliges Session-Token (lebts bis zum App-Neustart)."""
    return secrets.token_urlsafe(32)


def is_loopback_host(host: str) -> bool:
    """True, wenn der Host-Header loopback ist (127.0.0.1/localhost/::1).

    Akzeptiert optionalen Port-Suffix (``:8123``) und IPv6-Klammern
    (``[::1]:8123``).
    """
    if host == "::1":
        return True
    name = host
    if ":" in host:
        prefix, _, suffix = host.rpartition(":")
        if suffix.isdigit():  # Port-Suffix abschneiden
            name = prefix
    if name.startswith("[") and name.endswith("]"):
        name = name[1:-1]
    return name in _LOOPBACK_NAMES


def is_same_origin(host: str, origin: str) -> bool:
    """True, wenn der Origin-Header zum Request-Host passt (same-origin)."""
    return origin == f"http://{host}"


def _token_from_query(query: bytes) -> str | None:
    """Extrahiert den ``sia_token``-Query-Parameter (erster Wert)."""
    parsed = parse_qs(query.decode("utf-8", errors="replace"), keep_blank_values=True)
    values = parsed.get(TOKEN_QUERY)
    return values[0] if values else None


class LoopbackSecurityMiddleware:
    """REQ-816: Host-Check, Origin-Check und Session-Token-Check (ASGI)."""

    def __init__(self, app: ASGIApp, sia_token: str) -> None:
        self._app = app
        self._token = sia_token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        host = headers.get("host", "")
        if not is_loopback_host(host):
            await self._deny(scope, receive, send, 403, "Host ist nicht Loopback (G4)")
            return
        origin = headers.get("origin")
        if origin is not None and not is_same_origin(host, origin):
            await self._deny(scope, receive, send, 403, "Origin ist nicht same-origin")
            return
        path: str = scope.get("path", "")
        if path.startswith("/v1/") and not self._token_ok(headers, scope):
            await self._deny(scope, receive, send, 401, "Session-Token fehlt oder ist ungültig")
            return
        await self._app(scope, receive, send)

    def _token_ok(self, headers: Headers, scope: Scope) -> bool:
        supplied: str | None = headers.get(TOKEN_HEADER)
        if supplied is None:
            supplied = _token_from_query(scope.get("query_string", b""))
        if supplied is None or not supplied.isascii():
            return False
        return secrets.compare_digest(supplied, self._token)

    async def _deny(
        self, scope: Scope, receive: Receive, send: Send, status: int, detail: str
    ) -> None:
        response = JSONResponse({"error": detail, "disclaimer": DISCLAIMER}, status_code=status)
        await response(scope, receive, send)
