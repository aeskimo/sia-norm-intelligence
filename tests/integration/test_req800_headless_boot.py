"""REQ-800: ``python -m sni.app --headless`` — echter Boot (Subprocess, End-to-End)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

from sni.app.server import HOST, pick_free_port, wait_ready

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_req800_headless_subprocess_boots(tmp_path: Path) -> None:
    # Given `python -m sni.app --headless` (Subprocess) When /v1/status mit Token
    # Then 200 — der Launcher funktioniert End-to-End (REQ-800)
    # Isolation: eigene User-Daten + Fake-Keyring, damit der Boot weder die
    # reale `~/.sia-normenassistent` noch den echten Keychain antastet.
    port = pick_free_port()
    env = dict(os.environ)
    env["SIA_DATA_DIR"] = str(tmp_path / "data")
    env["SIA_FAKE_KEYCHAIN"] = str(tmp_path / "keychain")
    proc = subprocess.Popen(
        [sys.executable, "-m", "sni.app", "--headless", "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
    )
    assert proc.stdout is not None
    try:
        token = None
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            if not line:
                break
            if line.startswith("sia_token: "):
                token = line[len("sia_token: ") :].strip()
                break
        assert token, "Startzeile mit Token nicht erhalten"
        wait_ready(port, timeout=15.0)
        with httpx.Client(base_url=f"http://{HOST}:{port}", timeout=5.0) as client:
            assert client.get("/healthz").status_code == 200
            res = client.get("/v1/status", headers={"x-sia-token": token})
            assert res.status_code == 200
            data = res.json()
            assert data["mode"] == "headless"
            assert data["port"] == port
            # ohne Token → 401 (REQ-816)
            assert client.get("/v1/status").status_code == 401
    finally:
        proc.terminate()
        proc.wait(timeout=10)
