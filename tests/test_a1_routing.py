"""A1 real-outage versus drill routing checks; no Docker services required."""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys

import pytest
import yaml

pytestmark = pytest.mark.no_drill_stack

ROOT = Path(__file__).resolve().parents[1]
RULES_VM = ROOT / "configs" / "vmalert" / "rules-vm.yml"
PROMETHEUS = ROOT / "configs" / "vm" / "prometheus.yml"
ALERTMANAGER = ROOT / "configs" / "alertmanager" / "alertmanager.yml.template"
DOCKER_COMPOSE = ROOT / "docker-compose.yml"


def _alert_rules():
    data = yaml.safe_load(RULES_VM.read_text())
    return {
        rule["alert"]: rule
        for group in data["groups"]
        for rule in group.get("rules", [])
        if "alert" in rule
    }


def test_a1_canary_routes_dev_only_and_real_outage_pages_prod():
    alerts = _alert_rules()
    real = alerts["A1_https_down"]
    canary = alerts["A1_https_canary"]

    assert real["expr"] == 'probe_success{job="blackbox-https"} == 0'
    assert real["labels"] == {"severity": "critical", "class": "A1"}
    real_annotations = " ".join(real["annotations"].values()).lower()
    for drill_phrase in ("prod-safe canary fault", "real site stays up", "drill:"):
        assert drill_phrase not in real_annotations

    assert canary["expr"] == 'probe_success{job="blackbox-https-canary"} == 0'
    assert canary["labels"]["drill"] == "true"
    assert canary["labels"]["class"] == "A1"

    scrape_jobs = yaml.safe_load(PROMETHEUS.read_text())["scrape_configs"]
    jobs = {job["job_name"]: job for job in scrape_jobs}
    real_targets = jobs["blackbox-https"]["static_configs"][0]["targets"]
    canary_targets = jobs["blackbox-https-canary"]["static_configs"][0]["targets"]
    assert all(target.startswith("https://") for target in real_targets)
    assert canary_targets == ["http://127.0.0.1:9116/health"]
    assert jobs["blackbox-https-canary"]["static_configs"][0]["labels"]["drill"] == "true"

    canary_service = yaml.safe_load(DOCKER_COMPOSE.read_text())["services"]["obs-a1-https-canary"]
    canary_command = "".join(canary_service["command"])
    assert canary_service["network_mode"] == "host"
    assert '("127.0.0.1", 9116)' in canary_command

    config = yaml.safe_load(ALERTMANAGER.read_text())
    route = config["route"]
    assert route["receiver"] == "prod-real"
    routes = route["routes"]
    drill_route = next(child for child in routes if 'drill="true"' in child["matchers"])
    canary_route = next(child for child in routes if 'alertname=~".*canary.*"' in child["matchers"])
    assert drill_route["receiver"] == canary_route["receiver"] == "dev-only"

    receivers = {receiver["name"]: receiver for receiver in config["receivers"]}
    prod_to = {email["to"] for email in receivers["prod-real"]["email_configs"]}
    dev_to = [email["to"] for email in receivers["dev-only"]["email_configs"]]
    assert prod_to == {"alexey@datatalks.club", "dev@dtcdev.click"}
    assert dev_to == ["dev@dtcdev.click"]

    def receiver_for(labels):
        for child in routes:
            matcher = child["matchers"][0]
            if matcher == 'drill="true"':
                matches = labels.get("drill") == "true"
            elif matcher == 'alertname=~".*canary.*"':
                matches = re.fullmatch(r".*canary.*", labels.get("alertname", "")) is not None
            elif matcher == 'alertname="A1_https_down"':
                matches = labels.get("alertname") == "A1_https_down"
            elif matcher == 'class="A10"':
                matches = labels.get("class") == "A10"
            elif matcher == 'severity="warning"':
                matches = labels.get("severity") == "warning"
            else:
                raise AssertionError(f"uncovered Alertmanager matcher in A1 routing test: {matcher}")
            if matches:
                return child["receiver"]
        return route["receiver"]

    # t2813u/t2814u: A1 is grouped into the service incident mailed by the
    # healthcheck/dead-man; it must not mail a second time.
    assert receiver_for({**real["labels"], "alertname": "A1_https_down"}) == "obs-log"
    assert not receivers["obs-log"].get("email_configs")
    assert real["keep_firing_for"] == "5m"
    assert receiver_for({**canary["labels"], "alertname": "A1_https_canary"}) == "dev-only"


def test_drill_alerter_rejects_alexey_as_recipient():
    env = os.environ.copy()
    env["ALERT_TO"] = "alexey@datatalks.club,dev@dtcdev.click"
    result = subprocess.run(
        [sys.executable, "-c", "import runpy; runpy.run_path('scripts/drill_alerter.py')"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "may only send to dev@dtcdev.click" in result.stderr


def test_drill_alerter_defaults_to_dev_only():
    env = os.environ.copy()
    env.pop("ALERT_TO", None)
    result = subprocess.run(
        [sys.executable, "-c", "import runpy; runpy.run_path('scripts/drill_alerter.py')"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
