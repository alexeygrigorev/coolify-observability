"""vmalert disk rules: all-hosts warn/crit/predict/inodes + dev-only routing."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RULES_VM = ROOT / "configs" / "vmalert" / "rules-vm.yml"
AM_TMPL = ROOT / "configs" / "alertmanager" / "alertmanager.yml.template"

REQUIRED_DISK_ALERTS = {
    "A2_disk_warn": ("warning", "0.2"),
    "A2_disk_crit": ("critical", "0.1"),
    "A2_disk_fill_predict": ("warning", "predict_linear"),
    "A2_disk_inodes_warn": ("warning", "node_filesystem_files_free"),
    "A2_disk_inodes_crit": ("critical", "node_filesystem_files_free"),
}


def _load_vm():
    data = yaml.safe_load(RULES_VM.read_text())
    assert isinstance(data, dict) and "groups" in data
    return data


def test_disk_rules_present_all_hosts():
    data = _load_vm()
    by_alert = {}
    for g in data["groups"]:
        for r in g.get("rules", []):
            if "alert" in r:
                by_alert[r["alert"]] = (g["name"], r)
    for alert, (severity, needle) in REQUIRED_DISK_ALERTS.items():
        assert alert in by_alert, f"missing {alert}"
        gname, rule = by_alert[alert]
        assert gname == "obs-a2-disk", f"{alert} must live in obs-a2-disk, got {gname}"
        assert rule["labels"]["severity"] == severity
        assert rule["labels"]["class"] == "A2"
        assert needle in rule["expr"], f"{alert} expr must contain {needle!r}"
        # all-hosts: no hardcoded host filter; fstype guard excludes ephemeral mounts
        assert 'host="' not in rule["expr"] and "host:" not in rule["expr"]
        assert "fstype" in rule["expr"]
        assert "for" in rule


def test_disk_legacy_guards_kept():
    data = _load_vm()
    alerts = {r["alert"] for g in data["groups"] for r in g.get("rules", []) if "alert" in r}
    assert "A2_disk_pressure" in alerts
    assert "A2_disk_canary" in alerts


def test_prod_routing_dev_only():
    data = yaml.safe_load(AM_TMPL.read_text())
    assert data["route"]["receiver"] == "dev-only"
    assert len(data["receivers"]) == 1
    assert data["receivers"][0]["name"] == "dev-only"
    to = data["receivers"][0]["email_configs"][0]["to"]
    assert to == "dev@dtcdev.click"
    blob = AM_TMPL.read_text()
    assert "__SMTP_SMARTHOST__" in blob  # placeholders only, secrets injected on-host
    # No recipient other than dev@: scan actual receiver addresses, not comments.
    assert "alexey@" not in str(data["receivers"])
