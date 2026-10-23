"""A1–A8 Docker fault-injection against thin drill-alerter + Mailpit."""
from __future__ import annotations

import json
import re
import subprocess
import urllib.request

import pytest

from conftest import COMPOSE_FILE, MAILPIT, ROOT, clear_mail, wait_mail


def _compose(*args: str) -> None:
    r = subprocess.run(
        ["docker", "compose", "-f", COMPOSE_FILE, "--profile", "full", *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr + r.stdout


def test_matrix_ids_complete(request):
    """Require one collected drill or explicit placeholder for every matrix ID."""
    ids = []
    for item in request.session.items:
        if item.path != request.node.path:
            continue
        match = re.match(r"test_(A[1-8])_", item.originalname or item.name)
        if match:
            ids.append(match.group(1))
        elif getattr(item, "callspec", None):
            case_id = item.callspec.params.get("case_id")
            if case_id:
                ids.append(case_id)
    assert sorted(ids) == [f"A{i}" for i in range(1, 9)], ids


@pytest.mark.usefixtures("drill_stack")
def test_A1_https_endpoint_down():
    clear_mail()
    _compose("stop", "target-http")
    try:
        wait_mail("FIRE https")
    finally:
        _compose("start", "target-http")
        wait_mail("CLEAR https")


@pytest.mark.usefixtures("drill_stack")
def test_A4_postgres_unreachable():
    clear_mail()
    _compose("stop", "target-pg")
    try:
        wait_mail("FIRE postgres")
    finally:
        _compose("start", "target-pg")
        wait_mail("CLEAR postgres")


@pytest.mark.usefixtures("drill_stack")
def test_A6_store_gap():
    clear_mail()
    _compose("stop", "victoria-metrics")
    try:
        wait_mail("FIRE store", timeout=60)
    finally:
        _compose("start", "victoria-metrics")
        wait_mail("CLEAR store")


@pytest.mark.usefixtures("drill_stack")
def test_A8_alert_email_only_dev_recipient(alert_emails):
    clear_mail()
    _compose("stop", "target-http")
    try:
        message = wait_mail("FIRE https")
    finally:
        _compose("start", "target-http")
    with urllib.request.urlopen(f"{MAILPIT}/api/v1/messages", timeout=5) as r:
        data = json.load(r)
    blob = json.dumps(data)
    assert alert_emails == ["dev@dtcdev.click"]
    assert [recipient["Address"] for recipient in message["To"]] == alert_emails
    for addr in alert_emails:
        assert addr in blob, f"missing recipient {addr} in {blob[:500]}"
    assert "mail.grokbot.com" not in blob, f"grokbot recipient must be absent: {blob[:500]}"


@pytest.mark.usefixtures("drill_stack")
@pytest.mark.parametrize(
    "case_id,reason",
    [
        ("A2", "disk_pressure_injector"),
        ("A3", "ram_pressure_injector"),
        ("A5", "healthcheck_force_unhealthy"),
        ("A7", "log_pipeline_break_vector"),
    ],
)
def test_remaining_documented(case_id, reason, alert_email):
    pytest.xfail(f"{case_id} pending: {reason}; notify {alert_email}")
