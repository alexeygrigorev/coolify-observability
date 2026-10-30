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


def test_a10_dev_split_and_traffic_floor():
    """t181f4832: dev services downgraded to warning, both rules need a
    real-traffic floor so a handful of slow requests cannot page."""
    import yaml

    raw = (ROOT / "configs" / "vmalert" / "rules-vm.yml").read_text()
    assert 'service!~".*dev.*"' in raw
    assert 'service=~".*dev.*"' in raw
    assert ">= 0.05" in raw
    assert "traefik_service_requests_total" in raw
    assert "A10_dev_service_p95_slow" in raw

    rules = yaml.safe_load(raw)
    group = next(g for g in rules["groups"] if g["name"] == "obs-a10-slowness")
    by_name = {r["alert"]: r for r in group["rules"]}
    assert set(by_name) == {"A10_service_p95_slow", "A10_dev_service_p95_slow"}
    crit, dev = by_name["A10_service_p95_slow"], by_name["A10_dev_service_p95_slow"]
    assert crit["labels"] == {"severity": "critical", "class": "A10"}
    assert dev["labels"] == {"severity": "warning", "class": "A10"}
    assert crit["for"] == dev["for"] == "10m"
    # prod rule still gated on both legs: slow p95 AND traffic floor
    assert 'service!~".*dev.*"' in crit["expr"] and ">= 0.05" in crit["expr"]
    # dev rule never matches the critical rule's service set
    assert 'service=~".*dev.*"' in dev["expr"] and ">= 0.05" in dev["expr"]
    # declarative documentation mirrors the split
    decl = (ROOT / "alerts" / "rules.yaml").read_text()
    assert "A10_dev_service_p95_slow" in decl
    assert 'service=~".*dev.*"' in decl


def test_a10_semantic_unittest_fixture():
    """vmalert-tool unittest: run with
    `vmalert-tool unittest --files tests/fixtures/a10-unittest.yml`
    (engine version matches prod vmalert v1.115.0)."""
    fix = ROOT / "tests" / "fixtures" / "a10-unittest.yml"
    assert fix.exists()
    ftext = fix.read_text()
    assert "../../configs/vmalert/rules-vm.yml" in ftext
    # every scenario the rule split must distinguish
    for service in (
        "web-prod@docker",      # slow + busy -> critical fires
        "web-sandbox@docker",   # slow + trickle -> floor blocks
        "aisl-dev-source-web@file",  # slow + busy -> warning; + trickle -> quiet
        "web-fast@docker",      # fast + busy -> quiet
        "web-hyst@docker",      # slow -> fires -> band (2.0,2.5] stays firing -> fast resolves
    ):
        assert service in ftext
    assert "groupname: obs-a10-slowness" in ftext


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

def test_a10_ac3_dev_only_route_and_hysteresis():
    """f5d8e22b AC3: slowness mail goes ONLY to dev@dtcdev.click from
    alerts@dtcdev.click (never prod-real / global noreply@), and the native
    p95 rules hold a recovery hysteresis band at 2.0s."""
    tmpl = (ROOT / "configs" / "alertmanager" / "alertmanager.yml.template").read_text()
    import yaml

    cfg = yaml.safe_load(tmpl)
    routes = cfg["route"]["routes"]
    a10_routes = [r for r in routes if 'class="A10"' in str(r.get("matchers", []))]
    assert len(a10_routes) == 1, routes
    # first match wins: drills keep precedence over the A10 route
    drill_idx = min(i for i, r in enumerate(routes) if "drill" in str(r.get("matchers", [])))
    assert routes.index(a10_routes[0]) > drill_idx
    # the old alertname route for the dev rule is covered by the class route
    assert not [r for r in routes if 'A10_dev_service_p95_slow' in str(r.get("matchers", []))]

    recv = {r["name"]: r for r in cfg["receivers"]}
    slow = recv["slowness-dev"]
    emails = slow["email_configs"]
    assert len(emails) == 1
    assert emails[0]["to"] == "dev@dtcdev.click"
    assert emails[0]["from"] == "alerts@dtcdev.click"
    assert emails[0]["send_resolved"] is True
    assert emails[0]["smarthost"] == "__SMTP_ALERTS_SMARTHOST__"
    assert emails[0]["auth_username"] == "__SMTP_ALERTS_USER__"
    assert emails[0]["auth_password"] == "__SMTP_ALERTS_PASSWORD__"
    # prod-real must never receive slowness: class A10 route -> slowness-dev only
    prod_tos = [e["to"] for e in recv["prod-real"]["email_configs"]]
    assert "dev@dtcdev.click" in prod_tos and "alexey@datatalks.club" in prod_tos
    assert cfg["global"]["smtp_from"] == "noreply@datatalks.club"
    # remaining warnings stay dev-only (t1885u), below the A10 route so the dev
    # p95 warning keeps its alerts@ sender
    warn_routes = [r for r in routes if 'severity="warning"' in str(r.get("matchers", []))]
    assert len(warn_routes) == 1 and warn_routes[0]["receiver"] == "dev-only"
    assert routes.index(a10_routes[0]) < routes.index(warn_routes[0])
    # alexey prod-real leg carries no RECOVERED mail (t1885u, deployed)
    alexey_leg = next(e for e in recv["prod-real"]["email_configs"] if e["to"] == "alexey@datatalks.club")
    assert alexey_leg["send_resolved"] is False

    raw = (ROOT / "configs" / "vmalert" / "rules-vm.yml").read_text()
    rules = yaml.safe_load(raw)
    group = next(g for g in rules["groups"] if g["name"] == "obs-a10-slowness")
    by_name = {r["alert"]: r for r in group["rules"]}
    for name in ("A10_service_p95_slow", "A10_dev_service_p95_slow"):
        expr = by_name[name]["expr"]
        assert f'ALERTS{{alertname="{name}", alertstate="firing"}}' in expr
        assert "> 2.0" in expr  # recovery threshold below the 2.5 fire threshold
        assert "max by (service)" in expr  # keeps the alert label set stable

    installer = (ROOT / "scripts" / "install-obs-alerting.sh").read_text()
    for ph in ("__SMTP_ALERTS_SMARTHOST__", "__SMTP_ALERTS_USER__", "__SMTP_ALERTS_PASSWORD__"):
        assert ph in installer
    assert "resolve(\"alerts\")" in installer
