"""Alert fault-injection matrix.

These tests document the mandatory drill coverage. They are skipped until
alert rules + injectors exist (after Astra/Argon/Opus plan + Hub child tasks).

When implemented: each case must start a Docker scenario that artificially
causes the condition and assert the alert fires (and recovers where noted).
"""

from __future__ import annotations

import pytest

MATRIX = [
    pytest.param(
        "A1",
        "https_endpoint_down",
        "Stop or blackhole target-http; assert alert; restore and assert clear",
        id="A1-https-down",
    ),
    pytest.param(
        "A2",
        "disk_pressure",
        "Fill bind-mounted volume past threshold; assert alert; cleanup",
        id="A2-disk",
    ),
    pytest.param(
        "A3",
        "ram_pressure",
        "Stress cgroup / OOM path; assert alert",
        id="A3-ram",
    ),
    pytest.param(
        "A4",
        "postgres_unreachable",
        "Stop target-pg or reject network; assert alert; restore",
        id="A4-postgres",
    ),
    pytest.param(
        "A5",
        "app_healthcheck_fail",
        "Force unhealthy healthcheck; assert alert",
        id="A5-healthcheck",
    ),
    pytest.param(
        "A6",
        "metrics_scrape_gap",
        "Pause exporter; assert missing-series / stale alert",
        id="A6-scrape-gap",
    ),
    pytest.param(
        "A7",
        "log_pipeline_stall",
        "Break shipper to VictoriaLogs/Loki; assert pipeline-down alert",
        id="A7-log-pipeline",
    ),
    pytest.param(
        "A8",
        "alert_email_delivery",
        "Fire any alert; assert Mailpit received message for dev@dtcdev.click",
        id="A8-email",
    ),
]


@pytest.mark.parametrize("case_id,name,intent", MATRIX)
def test_alert_drill_placeholder(case_id: str, name: str, intent: str, alert_email: str) -> None:
    """Placeholder until rules + injectors land. Documents required coverage."""
    pytest.skip(
        f"pending implement: {case_id} ({name}) — {intent}; notify {alert_email}"
    )


def test_matrix_covers_mandatory_cases() -> None:
    """Sanity: matrix lists the eight mandatory drill IDs from the README."""
    ids = {p.values[0] for p in MATRIX}
    assert ids == {"A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8"}
