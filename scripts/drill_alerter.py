#!/usr/bin/env python3
"""Test-only evaluator/notifier for bounded Docker drills; no production install.

Sensors read real canary cgroup/filesystem data, Docker health/restarts and
VictoriaLogs queries. SMTP failures retain ordered transitions for retry.
"""
from __future__ import annotations

from collections import deque
from email.message import EmailMessage
import http.client
import http.server
import json
import os
import smtplib
import socket
import threading
import time
import urllib.parse
import urllib.request

ALERT_TO = os.environ.get('ALERT_TO', 'alexey@datatalks.club,dev@dtcdev.click')
INTERVAL = float(os.environ.get('POLL_INTERVAL', '1'))
HOLD = float(os.environ.get('ALERT_HOLD', '3'))
# f5d8e22b latency drill (ops-only, like A1-A8): when LATENCY_URL is set,
# measure GET duration; ok = < LATENCY_WARN_SEC (default 3s). HOLD gates
# sustained firing (prod 600s via healthcheck; drills use short HOLD).
LATENCY_URL = os.environ.get('LATENCY_URL', '')
LATENCY_WARN_SEC = float(os.environ.get('LATENCY_WARN_SEC', '3'))
STATE = {}
PENDING = deque()
RETRIES = 0
SENT = 0
LAST_POLL = 0
EVENT_UNTIL = {}
COUNTERS = {}


def get(url):
    with urllib.request.urlopen(url, timeout=2) as response:
        if response.status != 200:
            raise ValueError(f'HTTP {response.status}')
        return response.read()


def healthy(url):
    try:
        get(url)
        return True
    except (OSError, ValueError):
        return False


def docker(path):
    connection = http.client.HTTPConnection('localhost', timeout=2)
    connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.sock.settimeout(2)
    connection.sock.connect('/var/run/docker.sock')
    try:
        connection.request('GET', '/v1.44' + path)
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError(f'Docker HTTP {response.status}')
        return json.load(response)
    finally:
        connection.close()


def event(name, value):
    previous = COUNTERS.get(name, value)
    COUNTERS[name] = value
    if value > previous:
        EVENT_UNTIL[name] = time.monotonic() + 8
    return time.monotonic() >= EVENT_UNTIL.get(name, 0)


def logs(query):
    url = 'http://victoria-logs:9428/select/logsql/query?' + urllib.parse.urlencode({'query': query})
    return [json.loads(line) for line in get(url).splitlines() if line]


def checks():
    if os.environ.get('MODE') == 'deadman':
        ok = healthy('http://victoria-metrics:8428/health')
        try:
            state = json.loads(get('http://drill-alerter:8000/state'))
            ok = ok and time.time() - state['last_poll'] < 5
        except (OSError, ValueError, KeyError):
            ok = False
        return {'deadman': ok}
    result = {'https': healthy(os.environ['HTTP_URL']),
              'store': healthy('http://victoria-metrics:8428/health')}
    if LATENCY_URL:
        start = time.monotonic()
        try:
            with urllib.request.urlopen(LATENCY_URL, timeout=5) as response:
                response.read(1)
            dur = time.monotonic() - start
            result['latency'] = dur < LATENCY_WARN_SEC
        except (OSError, ValueError):
            result['latency'] = False
    try:
        with socket.create_connection(('target-pg', 5432), timeout=2):
            result['postgres'] = True
    except OSError:
        result['postgres'] = False
    try:
        sensor = json.loads(get('http://canary:8000/status'))
        result.update(disk=sensor['disk'] < .8, memory=sensor['memory'] < .8,
                      oom=event('oom', sensor['oom']))
    except (OSError, ValueError, KeyError):
        result.update(disk=False, memory=False, oom=False)
    try:
        filters = urllib.parse.quote(json.dumps({'label': [
            'com.docker.compose.project=' + os.environ['COMPOSE_PROJECT_NAME']]}))
        containers = docker('/containers/json?all=true&filters=' + filters)
        by_service = {c['Labels']['com.docker.compose.service']: c for c in containers}
        canary = docker('/containers/' + by_service['canary']['Id'] + '/json')
        restart = docker('/containers/' + by_service['restart-target']['Id'] + '/json')
        result['unhealthy'] = canary['State'].get('Health', {}).get('Status') == 'healthy'
        result['restart'] = event('restart', restart['RestartCount'])
    except (OSError, ValueError, KeyError):
        result.update(unhealthy=False, restart=False)
    try:
        result['pipeline'] = bool(logs('_time:8s AND "INFO heartbeat"'))
        errors = logs('_time:8s AND "ERROR" | stats count() as total')
        result['errors'] = int(errors[0]['total']) < 3
        result['multiline'] = not bool(logs('_time:8s AND "PANIC"'))
    except (OSError, ValueError, KeyError, IndexError):
        # A failed query is pipeline failure, not evidence of application errors.
        # Leave previous application-log states untouched until queries recover.
        result['pipeline'] = False
    return result


def edge(name, ok, now):
    state = STATE.setdefault(name, {'ok': True, 'candidate': True, 'since': now})
    if state['candidate'] != ok:
        state.update(candidate=ok, since=now)
    if state['ok'] != ok and now - state['since'] >= HOLD:
        state['ok'] = ok
        PENDING.append((name, 'CLEAR' if ok else 'FIRE'))


def flush():
    global RETRIES, SENT
    while PENDING:
        name, transition = PENDING[0]
        message = EmailMessage()
        message['From'] = 'drill-alerter@coolify-obs.local'
        message['To'] = ALERT_TO
        message['Subject'] = f'[drill] {transition} {name}'
        message.set_content(f'{name}: {transition}')
        try:
            with smtplib.SMTP(os.environ.get('SMTP_HOST', 'mailpit'),
                              int(os.environ.get('SMTP_PORT', '1025')), timeout=2) as smtp:
                refused = smtp.send_message(message)
                if refused:
                    raise smtplib.SMTPRecipientsRefused(refused)
        except (OSError, smtplib.SMTPException) as error:
            RETRIES += 1
            print(f'SMTP retry pending={len(PENDING)} {type(error).__name__}', flush=True)
            return
        PENDING.popleft()
        SENT += 1


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({'checks': STATE, 'pending': list(PENDING),
                           'retries': RETRIES, 'sent': SENT, 'last_poll': LAST_POLL}).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main():
    global LAST_POLL
    threading.Thread(target=http.server.HTTPServer(('0.0.0.0', 8000), Handler).serve_forever,
                     daemon=True).start()
    while True:
        for name, ok in checks().items():
            edge(name, ok, time.monotonic())
        LAST_POLL = time.time()
        flush()
        time.sleep(INTERVAL)


if __name__ == '__main__':
    main()
