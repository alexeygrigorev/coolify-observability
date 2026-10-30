"""vmalert disk rules: all-hosts warn/crit/predict/inodes + node-absent + prod routing (t1493u)."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RULES_VM = ROOT / "configs" / "vmalert" / "rules-vm.yml"
AM_TMPL = ROOT / "configs" / "alertmanager" / "alertmanager.yml.template"

# intake AC1: warn <15% 10m, crit <8% 5m, fill-predict 24h horizon AND <40% free 30m,
# inodes warn <10% / crit <5%; fstype guard tmpfs|overlay|squashfs|vfat|fuse.*;
# NodeExporterAbsent for contabo-a, contabo-b, hetzner.
REQUIRED_DISK_ALERTS = {
    "A2_disk_warn": ("warning", {"0.15", "fstype"}),
    "A2_disk_crit": ("critical", {"0.08", "0.10", "alertstate"}),
    "A2_disk_fill_predict": ("warning", {"predict_linear", "86400", "0.4"}),
    "A2_disk_inodes_warn": ("warning", {"node_filesystem_files_free", "0.1"}),
    "A2_disk_inodes_crit": ("critical", {"node_filesystem_files_free", "0.05"}),
    "A2_disk_pressure": ("warning", set()),
    "A2_disk_fill_6h": ("critical", {"predict_linear", "21600", "0.15"}),
}
FSTYPE_GUARD = 'fstype!~"tmpfs|overlay|squashfs|vfat|fuse.*"'
EXPECTED_ABSENT_HOSTS = {"contabo-a", "contabo-b", "hetzner"}
# t1885u/3bf25bda (deployed 2026-10-29, reconciled into source 2026-10-30):
# A2_disk_crit 8%/10% hysteresis for 10m, A2_disk_pressure 2m, A2_disk_fill_6h
# 30m added alongside the still-present A2_disk_fill_predict 24h horizon.
FOR_SECONDS = {"A2_disk_warn": "10m", "A2_disk_crit": "10m",
               "A2_disk_fill_predict": "30m", "A2_disk_inodes_warn": "10m",
               "A2_disk_inodes_crit": "10m", "A2_disk_pressure": "2m",
               "A2_disk_fill_6h": "30m"}


def _load_vm():
    data = yaml.safe_load(RULES_VM.read_text())
    assert isinstance(data, dict) and "groups" in data
    return data


def _alerts():
    by_alert = {}
    for g in _load_vm()["groups"]:
        for r in g.get("rules", []):
            if "alert" in r:
                by_alert.setdefault(r["alert"], []).append((g["name"], r))
    return by_alert


def test_disk_rules_present_all_hosts():
    by_alert = _alerts()
    for alert, (severity, needles) in REQUIRED_DISK_ALERTS.items():
        assert alert in by_alert, f"missing {alert}"
        gname, rule = by_alert[alert][0]
        assert gname == "obs-a2-disk", f"{alert} must live in obs-a2-disk, got {gname}"
        assert rule["labels"]["severity"] == severity
        assert rule["labels"]["class"] == "A2"
        for needle in needles:
            assert needle in rule["expr"], f"{alert} expr must contain {needle!r}"
        # all-hosts: no hardcoded host filter on disk exprs; fstype guard excludes
        # ephemeral mounts (A2_disk_pressure is a root-mountpoint probe by design,
        # t1885u: mountpoint="/" instead of the fstype guard)
        assert 'host="' not in rule["expr"] and "host:" not in rule["expr"]
        if alert != "A2_disk_pressure":
            assert "fstype" in rule["expr"]
        assert rule["for"] == FOR_SECONDS[alert]


def test_disk_fstype_guard_matches_intake():
    for alert in REQUIRED_DISK_ALERTS:
        if alert == "A2_disk_pressure":
            _, rule = _alerts()[alert][0]
            assert 'mountpoint="/"' in rule["expr"], "pressure probe is root-only"
            continue
        _, rule = _alerts()[alert][0]
        assert FSTYPE_GUARD in rule["expr"], f"{alert} must exclude tmpfs|overlay|squashfs|vfat|fuse.*"


def test_disk_predict_requires_low_free_now():
    _, rule = _alerts()["A2_disk_fill_predict"][0]
    expr = rule["expr"]
    assert "predict_linear" in expr and "< 0 and" in expr and "< 0.4" in expr


def test_node_exporter_absent_per_host():
    rules = _alerts()["A2_node_exporter_absent"]
    hosts = {r["labels"]["host"] for _, r in rules}
    assert hosts == EXPECTED_ABSENT_HOSTS
    for _, rule in rules:
        assert rule["labels"]["severity"] == "warning"
        assert rule["labels"]["class"] == "A2"
        assert "absent(" in rule["expr"] and 'up{job="node"' in rule["expr"]
        assert '== 0' in rule["expr"]


def test_disk_legacy_guards_kept():
    alerts = set(_alerts())
    assert "A2_disk_pressure" in alerts
    assert "A2_disk_canary" in alerts


def test_prometheus_has_hetzner_tunnel_target():
    text = (ROOT / "configs" / "vm" / "prometheus.yml").read_text()
    assert '127.0.0.1:9102' in text
    assert "host: hetzner" in text


def test_dev_env_alerts_route_dev_only():
    # A10_dev_service_p95_slow commits to 'visible via dev-only mail'
    # (t181f4832). Since f5d8e22b AC3 the class="A10" route covers it: both
    # slowness rules (prod + dev) land on slowness-dev -> dev@dtcdev.click
    # only, from alerts@dtcdev.click, never prod-real.
    data = yaml.safe_load(AM_TMPL.read_text())
    a10_routes = [c for c in data["route"]["routes"]
                  if 'class="A10"' in c["matchers"]]
    assert len(a10_routes) == 1 and a10_routes[0]["receiver"] == "slowness-dev"
    # no legacy per-alertname dev route left behind
    assert not [c for c in data["route"]["routes"]
                if 'alertname="A10_dev_service_p95_slow"' in c["matchers"]]


def test_canary_rules_carry_drill_label():
    for canary in ("A2_disk_canary", "A3_canary_oom", "A5_canary_missing"):
        _, rule = _alerts()[canary][0]
        assert rule["labels"].get("drill") == "true", f"{canary} must be drill=true"


def test_routing_real_to_prod_drills_to_dev():
    data = yaml.safe_load(AM_TMPL.read_text())
    route = data["route"]
    # Real (non-drill) alerts: default route -> prod-real -> alexey@ + dev@.
    assert route["receiver"] == "prod-real"
    receivers = {r["name"]: r for r in data["receivers"]}
    prod = receivers["prod-real"]
    tos = {e["to"] for e in prod["email_configs"]}
    assert tos == {"alexey@datatalks.club", "dev@dtcdev.click"}
    # Drill alerts (drill=true or *_canary) -> dev-only -> dev@ only; the
    # f5d8e22b AC3 slowness route adds a third child receiver (dev-only mail
    # from alerts@dtcdev.click) without widening prod-real.
    child = {c["receiver"] for c in route["routes"]}
    assert child == {"dev-only", "slowness-dev"}
    matchers = [m for c in route["routes"] for m in c["matchers"]]
    assert any('drill="true"' in m for m in matchers)
    assert any('canary' in m for m in matchers)
    dev = receivers["dev-only"]
    assert [e["to"] for e in dev["email_configs"]] == ["dev@dtcdev.click"]
    # AC5: RESOLVED mails enabled on every dev@-bound email_config; the
    # alexey@ prod-real leg is deliberately false (t1885u/3bf25bda, deployed
    # 2026-10-29) to keep RECOVERED noise off Alexey's mailbox.
    for r in data["receivers"]:
        for e in r["email_configs"]:
            if e["to"] == "dev@dtcdev.click":
                assert e["send_resolved"] is True, f"{r['name']} dev leg must send_resolved"
            else:
                assert e["send_resolved"] is False, f"{r['name']} alexey leg must not send_resolved"
    blob = AM_TMPL.read_text()
    assert "__SMTP_SMARTHOST__" in blob  # placeholders only, secrets injected on-host
