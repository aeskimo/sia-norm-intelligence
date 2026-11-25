"""M8.6 (c) Installer-Basis (REQ-813): frozen-App-Bootstrapping.

``SCHEMAS_DIR`` frozen-aware (``sys._MEIPASS``), PyInstaller-Argumente je
nach OS (``make package``), Auto-Schliessen des Fensters im CI
(``SIA_WINDOW_SECONDS``; Shown-Event-Poll + Backstop, Pattern:
``packaging/hello_window.py``).
"""

from __future__ import annotations

import importlib.util
import os
import sys
import threading
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

from sni.app import launcher
from sni.core import schemas

ROOT = Path(__file__).resolve().parents[2]


def _load_make_module() -> ModuleType:
    """``scripts/make.py`` laden (kein Package-Import, 1:1 wie ``make``)."""
    spec = importlib.util.spec_from_file_location("sia_make", ROOT / "scripts" / "make.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Einmal beim Modul-Import laden (vor jeglichem ``os.name``-Monkeypatching:
# ``Path(__file__)`` würde sonst je nach gepatchtem OS einen WindowsPath
# bauen und auf Nicht-Windows-Systemen scheitern).
MAKE = _load_make_module()


# -------------------------------------------------
# SCHEMAS_DIR (frozen-aware)
# -------------------------------------------------


def test_req813_schemas_dir_dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    expected = Path(schemas.__file__).resolve().parents[3] / "schemas"
    assert schemas._schemas_dir() == expected
    assert expected == schemas.SCHEMAS_DIR


def test_req813_schemas_dir_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "_MEIPASS", "/tmp/_MEI123", raising=False)
    assert schemas._schemas_dir() == Path("/tmp/_MEI123/schemas")


# -------------------------------------------------
# PyInstaller-Argumente (make package)
# -------------------------------------------------


def test_req813_package_args_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(sys, "platform", "darwin")
    args = MAKE._package_args()
    assert "--windowed" in args
    assert "--onefile" not in args  # onedir (Default) → .app
    assert "packaging/icon/app-icon.icns" in args
    for entry in (
        "src/sni/app/static:sni/app/static",
        "schemas:schemas",
        "data/catalog/snapshots:sni_data/catalog/snapshots",
    ):
        assert entry in args, f"add-data fehlt: {entry}"
    collects = [args[i + 1] for i, a in enumerate(args) if a == "--collect-all"]
    assert collects == ["ifcopenshell", "webview"]
    assert args[args.index("--copy-metadata") + 1] == "keyring"
    assert args[-1] == "packaging/app_entry.py"


def test_req813_package_args_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(sys, "platform", "win32")
    args = MAKE._package_args()
    assert "--onefile" in args
    assert "packaging/icon/app-icon.ico" in args
    # add-data-Trenner auf Windows ist ';'
    assert "schemas;schemas" in args
    collects = [args[i + 1] for i, a in enumerate(args) if a == "--collect-all"]
    assert collects == ["ifcopenshell", "webview"]  # kein gi (Linux-GTK)


def test_req813_package_args_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(sys, "platform", "linux")
    args = MAKE._package_args()
    assert "--onefile" not in args
    collects = [args[i + 1] for i, a in enumerate(args) if a == "--collect-all"]
    assert collects == ["ifcopenshell", "webview", "gi"]  # gi: pywebview-GTK
    assert "packaging/icon/app-icon.icns" not in args


def test_req813_package_target_registered() -> None:
    assert "package" in MAKE.TARGETS
    assert MAKE.HANDLERS["package"].__name__ == "cmd_package"


# -------------------------------------------------
# Auto-Schliessen (CI-Smoke, REQ-813)
# -------------------------------------------------


class _FakeShownEvent:
    def __init__(self) -> None:
        self._event = threading.Event()

    def set(self) -> None:
        self._event.set()

    def wait(self, timeout: float) -> bool:
        return self._event.wait(timeout)


class _FakeEvents:
    def __init__(self) -> None:
        self.shown = _FakeShownEvent()


class _FakeWindow:
    def __init__(self, shown: bool) -> None:
        self.events = cast(Any, _FakeEvents())
        self.destroyed = False
        if shown:
            self.events.shown.set()

    def destroy(self) -> None:
        self.destroyed = True


def test_req813_auto_close_destroys_after_shown() -> None:
    window = _FakeWindow(shown=True)
    # destroy_backstop gross (Daemon-Thread): feuert in der Testlaufzeit nie
    launcher._auto_close(window, shown_wait=2.0, destroy_backstop=3600.0)
    assert window.destroyed is True


def test_req813_auto_close_exits_when_not_shown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Exit(RuntimeError):
        def __init__(self, code: int) -> None:
            super().__init__(f"os._exit({code})")
            self.code = code

    def _fake_exit(code: int) -> None:
        raise _Exit(code)

    monkeypatch.setattr(os, "_exit", _fake_exit)
    window = _FakeWindow(shown=False)
    with pytest.raises(_Exit) as excinfo:
        launcher._auto_close(window, shown_wait=0.2)
    assert excinfo.value.code == 1
    assert window.destroyed is False
