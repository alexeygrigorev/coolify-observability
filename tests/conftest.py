"""Shared fixtures for alert fault-injection drills."""
from __future__ import annotations

import os
import subprocess
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(__file__))
COMPOSE_FILE = os.path.join(ROOT, "docker-compose.test.yml")
ALERT_EMAIL = "dev@dtcdev.click"
MAILPIT = os.environ.get("MAILPIT_URL", "http://127.0.0.1:8025")


@pytest.fixture(scope="session")
def compose_file() -> str:
    return COMPOSE_FILE


@pytest.fixture(scope="session")
def alert_email() -> str:
    return ALERT_EMAIL


def _compose(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "compose", "-f", COMPOSE_FILE, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="session")
def drill_stack():
    """Bring up OO + Mailpit + targets + alerter for the session."""
    up = _compose("up", "-d", "--wait", "openobserve", "mailpit")
    if up.returncode != 0:
        pytest.skip(f"compose up core failed: {up.stderr[-500:]}")
    targets = _compose("--profile", "targets", "up", "-d", "--wait", "target-http", "target-pg", "drill-alerter")
    if targets.returncode != 0:
        # still try without wait
        _compose("--profile", "targets", "up", "-d", "target-http", "target-pg", "drill-alerter")
        time.sleep(5)
    # clear mailpit
    try:
        req = urllib.request.Request(f"{MAILPIT}/api/v1/messages", method="DELETE")
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass
    yield
    _compose("--profile", "targets", "down", "-v")


def wait_mail(subject_substr: str, timeout: float = 45.0) -> dict:
    import json

    deadline = time.time() + timeout
    while time.time() < deadline:
        with urllib.request.urlopen(f"{MAILPIT}/api/v1/messages", timeout=5) as r:
            data = json.load(r)
        for m in data.get("messages", []):
            subj = m.get("Subject") or ""
            tos = " ".join(
                (m.get("To") or [{}])[0].get("Address", "")
                if isinstance(m.get("To"), list)
                else []
            )
            # Mailpit To format varies
            to_raw = str(m.get("To"))
            if subject_substr in subj and (ALERT_EMAIL in to_raw or ALERT_EMAIL.split("@")[0] in to_raw):
                return m
            if subject_substr in subj:
                return m
        time.sleep(2)
    raise AssertionError(f"no mail with subject containing {subject_substr!r} within {timeout}s")
