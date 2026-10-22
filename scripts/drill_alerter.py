#!/usr/bin/env python3
"""Thin SMTP alerter for Docker fault-injection drills (A1–A8). Storage = VM/VL."""
from __future__ import annotations

import os
import smtplib
import socket
import time
import urllib.request
from email.message import EmailMessage

ALERT_TO = os.environ.get(
    "ALERT_TO", "dev@dtcdev.click"
)
SMTP_HOST = os.environ.get("SMTP_HOST", "mailpit")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "1025"))
HTTP_URL = os.environ.get("HTTP_URL", "http://target-http/")
PG_HOST = os.environ.get("PG_HOST", "target-pg")
PG_PORT = int(os.environ.get("PG_PORT", "5432"))
STORE_URL = os.environ.get("OO_HEALTH_URL", os.environ.get("STORE_HEALTH_URL", "http://victoria-metrics:8428/health"))
INTERVAL = float(os.environ.get("POLL_INTERVAL", "3"))
STATE: dict[str, bool] = {}


def send(subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = "drill-alerter@coolify-obs.local"
    msg["To"] = ALERT_TO
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as s:
        s.send_message(msg)


def check_http() -> bool:
    try:
        with urllib.request.urlopen(HTTP_URL, timeout=3) as r:
            return 200 <= r.status < 400
    except Exception:
        return False


def check_pg() -> bool:
    try:
        with socket.create_connection((PG_HOST, PG_PORT), timeout=3):
            return True
    except OSError:
        return False


def check_store() -> bool:
    try:
        with urllib.request.urlopen(STORE_URL, timeout=3) as r:
            return 200 <= r.status < 500
    except Exception:
        return False


def edge(name: str, ok: bool) -> None:
    prev = STATE.get(name)
    STATE[name] = ok
    if prev is True and not ok:
        send(f"[drill] FIRE {name}", f"{name} failed; notify {ALERT_TO}")
    elif prev is False and ok:
        send(f"[drill] CLEAR {name}", f"{name} recovered")


def main() -> None:
    STATE["https"] = check_http()
    STATE["postgres"] = check_pg()
    STATE["store"] = check_store()
    while True:
        edge("https", check_http())
        edge("postgres", check_pg())
        edge("store", check_store())
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
