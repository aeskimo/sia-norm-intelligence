"""REQ-800: Launcher-CLI — Argument-Parsing und Port-Auflösung (reine Logik)."""

from __future__ import annotations

import pytest

from sni.app.launcher import parse_args, resolve_headless_port


def test_req800_default_mode_is_window() -> None:
    # Given keine Argumente When geparsed Then Fenster-Modus (Default, REQ-800)
    args = parse_args([])
    assert args.browser is False
    assert args.headless is False
    assert args.port is None


def test_req800_browser_and_headless_flags() -> None:
    # Given --browser bzw. --headless When geparsed Then gesetzt
    assert parse_args(["--browser"]).browser is True
    assert parse_args(["--headless"]).headless is True


def test_req800_port_flag_parsed() -> None:
    # Given --port 9123 When geparsed Then als Integer
    assert parse_args(["--headless", "--port", "9123"]).port == 9123


def test_req800_headless_port_default_8000(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given kein --port und kein PORT When aufgelöst Then 8000 (REQ-816)
    monkeypatch.delenv("PORT", raising=False)
    assert resolve_headless_port(None) == 8000


def test_req800_headless_port_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given PORT=9123 When aufgelöst Then 9123
    monkeypatch.setenv("PORT", "9123")
    assert resolve_headless_port(None) == 9123


def test_req800_headless_port_flag_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given --port und PORT When aufgelöst Then --port gewinnt
    monkeypatch.setenv("PORT", "9123")
    assert resolve_headless_port(7777) == 7777


def test_req800_headless_port_invalid_env_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given PORT=abc (ungültig) When aufgelöst Then 8000 (kein Crash)
    monkeypatch.setenv("PORT", "abc")
    assert resolve_headless_port(None) == 8000
