"""f5d8e22b latency: rules + scrape + drill-alerter unit (no docker)."""
from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_rules_have_slowness():
    text = (ROOT / "alerts" / "rules.yaml").read_text()
    assert "A10_service_p95_slow" in text
    assert "A11_probe_ttfb_slow" in text
    assert "for: 10m" in text
    assert "dev@dtcdev.click" in text
    assert "alerts@dtcdev.click" in text
    assert "> 2.5" in text
    assert "> 3" in text


def test_native_vmalert_has_a10():
    text = (ROOT / "configs" / "vmalert" / "rules-vm.yml").read_text()
    assert "obs-a10-slowness" in text
    assert "A10_service_p95_slow" in text
    assert "traefik_service_request_duration_seconds_bucket" in text
    assert "> 2.5" in text
    assert "for: 10m" in text
    assert "class: A10" in text


def test_prometheus_has_traefik_wg():
    text = (ROOT / "configs" / "vm" / "prometheus.yml").read_text()
    assert "job_name: traefik" in text
    assert "10.100.0.1:8082" in text
    assert "10.100.0.2:8082" in text
    lat = (ROOT / "configs" / "vm" / "prometheus.latency.yml").read_text()
    assert "10.100.0.1:8082" in lat


def test_latency_compose_30d_cap():
    for name in ("docker-compose.prod.yml", "docker-compose.yml"):
        text = (ROOT / name).read_text()
        assert "victoria-metrics-latency" in text
        assert "-retentionPeriod=30d" in text
        assert "mem_limit: 256m" in text
        assert ":8429" in text


def test_drill_alerter_latency_path():
    text = (ROOT / "scripts" / "drill_alerter.py").read_text()
    assert "LATENCY_URL" in text
    assert "LATENCY_WARN_SEC" in text
    assert "latency" in text


def test_alb_export_script_readonly():
    text = (ROOT / "scripts" / "latency-alb-export.sh").read_text()
    assert "get-metric-statistics" in text
    assert "TargetResponseTime" in text
    assert "s3 cp" in text
    # no other AWS writes
    assert "put-bucket" not in text
    assert "delete-" not in text
    assert re.search(r"coolify/obs/latency/alb", text)
