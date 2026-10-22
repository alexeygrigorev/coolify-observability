from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = str(ROOT / "docker-compose.test.yml")
MAILPIT = os.environ.get("MAILPIT_URL", "http://127.0.0.1:8025")
ALERT_EMAILS = ["dev@dtcdev.click"]
ALERT_EMAIL = ALERT_EMAILS[0]


def _compose(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "compose", "-f", COMPOSE_FILE, *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="session")
def alert_email() -> str:
    return ALERT_EMAIL


@pytest.fixture(scope="session")
def alert_emails() -> list[str]:
    return list(ALERT_EMAILS)


@pytest.fixture(scope="session")
def drill_stack():
    if os.environ.get("SKIP_DRILLS") == "1":
        pytest.skip("SKIP_DRILLS=1")
    try:
        subprocess.run(["docker", "info"], capture_output=True, check=True)
    except Exception:
        pytest.skip("docker not available")
    r = _compose("--profile", "full", "up", "-d", "--wait")
    if r.returncode != 0:
        r = _compose("--profile", "full", "up", "-d")
        assert r.returncode == 0, r.stderr + r.stdout
        time.sleep(8)
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{MAILPIT}/api/v1/info", timeout=2):
                break
        except Exception:
            time.sleep(1)
    else:
        _compose("--profile", "full", "down", "-v")
        pytest.fail("mailpit not ready")
    yield {"mailpit": MAILPIT}
    if os.environ.get("KEEP_DRILLS") != "1":
        _compose("--profile", "full", "down", "-v")


def wait_mail(needle: str, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with urllib.request.urlopen(f"{MAILPIT}/api/v1/messages", timeout=5) as r:
            data = json.load(r)
        for m in data.get("messages", []):
            blob = json.dumps(m)
            if needle in blob:
                return m
        time.sleep(2)
    raise AssertionError(f"mail with {needle!r} not found in {timeout}s")


def clear_mail() -> None:
    req = urllib.request.Request(f"{MAILPIT}/api/v1/messages", method="DELETE")
    urllib.request.urlopen(req, timeout=5)
