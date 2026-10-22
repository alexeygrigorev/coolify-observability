"""Shared fixtures for alert fault-injection drills.

Compose file: docker-compose.test.yml
Mail capture: Mailpit at http://127.0.0.1:8025 (when profile is up).
"""

from __future__ import annotations

import os

import pytest

COMPOSE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "docker-compose.test.yml"
)
ALERT_EMAIL = "dev@dtcdev.click"


@pytest.fixture(scope="session")
def compose_file() -> str:
    return COMPOSE_FILE


@pytest.fixture(scope="session")
def alert_email() -> str:
    return ALERT_EMAIL
