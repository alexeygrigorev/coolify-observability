"""Fable infra audit: retention, scrape targets, cardinality and alert coverage."""
from __future__ import annotations

from pathlib import Path

import yaml
import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.no_drill_stack


def _alerts():
    rules = yaml.safe_load((ROOT / "configs/vmalert/rules-vm.yml").read_text())
    return {
        rule["alert"]: rule
        for group in rules["groups"]
        for rule in group.get("rules", [])
        if "alert" in rule
    }


def test_metrics_stores_have_audited_retention_and_memory_caps():
    for filename in ("docker-compose.yml", "docker-compose.prod.yml"):
        services = yaml.safe_load((ROOT / filename).read_text())["services"]
        vm = services["victoria-metrics"]
        vl = services["victoria-logs"]
        assert "-retentionPeriod=30d" in vm["command"]
        assert "-memory.allowedBytes=1073741824" in vm["command"]
        assert vm["mem_limit"] == vm["memswap_limit"] == "2g"
        assert "-retentionPeriod=14d" in vl["command"]
        assert "-memory.allowedBytes=536870912" in vl["command"]
        assert vl["mem_limit"] == vl["memswap_limit"] == "1g"


def test_cadvisor_scrapes_both_hosts_and_bounds_deploy_cardinality():
    config = yaml.safe_load((ROOT / "configs/vm/prometheus.yml").read_text())
    cadvisor = next(job for job in config["scrape_configs"] if job["job_name"] == "cadvisor")
    hosts = {
        static["labels"]["host"]
        for static in cadvisor["static_configs"]
        if any(target.endswith(":9101") for target in static["targets"])
    }
    assert hosts == {"contabo-a", "contabo-b"}
    relabels = cadvisor["metric_relabel_configs"]
    normalize_name = next(rule for rule in relabels if rule.get("target_label") == "name")
    assert normalize_name["regex"] == "(.+)-[0-9]{8}T[0-9]{6}"
    assert normalize_name["replacement"] == "$1"
    assert any(rule.get("action") == "labeldrop" and rule.get("regex") == "id" for rule in relabels)


def test_blackbox_covers_aishl_and_website_production_every_15_seconds():
    config = yaml.safe_load((ROOT / "configs/vm/prometheus.yml").read_text())
    job = next(job for job in config["scrape_configs"] if job["job_name"] == "blackbox-https")
    targets = {
        target
        for static in job["static_configs"]
        for target in static["targets"]
    }
    assert job["scrape_interval"] == "15s"
    assert "https://aishippinglabs.com/ping" in targets
    assert "https://prod.datatalks.club/" in targets


def test_f4_h2_and_h5_alerts_cover_the_verified_gaps():
    alerts = _alerts()
    expected = {
        "F4_all_backends_down",
        "F4_5xx_rate_high",
        "F4_cpu_pressure_high",
        "F4_host_load_high",
        "H2_container_memory_high",
        "H2_container_oom_kill",
        "H5_traefik_metrics_down",
        "H5_certificate_expiring_14d",
        "H5_certificate_expiring_7d",
        "H5_container_restart_burst",
        "H5_container_unhealthy",
        "H5_postgres_connections_high",
        "H5_postgres_replication_lag",
    }
    assert expected <= alerts.keys()
    assert alerts["F4_all_backends_down"]["expr"] == "max by (host, service) (traefik_service_server_up) == 0"
    assert alerts["F4_all_backends_down"]["for"] == "20s"
    assert "traefik_router_requests_total" in alerts["F4_5xx_rate_high"]["expr"]
    assert "node_pressure_cpu_waiting_seconds_total" in alerts["F4_cpu_pressure_high"]["expr"]
    assert "node_load1 > 16" in alerts["F4_host_load_high"]["expr"]
    assert "0.85" in alerts["H2_container_memory_high"]["expr"]
    assert "container_oom_events_total" in alerts["H2_container_oom_kill"]["expr"]
    assert "container_health_state" in alerts["H5_container_unhealthy"]["expr"]
    assert "container_start_time_seconds" in alerts["H5_container_restart_burst"]["expr"]
    assert "pg_stat_database_numbackends" in alerts["H5_postgres_connections_high"]["expr"]
    assert "pg_settings_max_connections" in alerts["H5_postgres_connections_high"]["expr"]
    assert "pg_replication_lag_seconds" in alerts["H5_postgres_replication_lag"]["expr"]

    alertmanager = yaml.safe_load((ROOT / "configs/alertmanager/alertmanager.yml.template").read_text())
    assert alertmanager["route"]["receiver"] == "prod-real"
    prod_real = next(receiver for receiver in alertmanager["receivers"] if receiver["name"] == "prod-real")
    assert "dev@dtcdev.click" in {email["to"] for email in prod_real["email_configs"]}
    assert alerts["F4_all_backends_down"]["labels"]["severity"] == "critical"
    assert alerts["H2_container_oom_kill"]["labels"]["severity"] == "critical"


def test_retention_docs_match_compose_policy():
    readme = (ROOT / "README.md").read_text()
    policy = (ROOT / "docs/retention-s3.md").read_text()
    assert "VM **`-retentionPeriod=30d`**" in readme
    assert "**`-retentionPeriod=30d`**" in policy
