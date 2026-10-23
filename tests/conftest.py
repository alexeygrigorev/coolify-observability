from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = str(ROOT / 'docker-compose.test.yml')
MAILPIT = ''
os.environ.setdefault('GOMAXPROCS', '2')
os.environ.setdefault('COMPOSE_PROJECT_NAME', 'obs-drills-' + uuid.uuid4().hex[:10])


def compose(*args, timeout=90):
    result = subprocess.run(['docker', 'compose', '-f', COMPOSE_FILE,
                             '--profile', 'full', *args], cwd=ROOT,
                            capture_output=True, text=True, timeout=timeout)
    assert result.returncode == 0, result.stderr + result.stdout
    return result.stdout


def execute(service, code):
    return compose('exec', '-T', service, 'python', '-c', code)


def state(service='drill-alerter'):
    return json.loads(execute(service, "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/state',timeout=3).read().decode())"))


def eventually(predicate, timeout=45):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = predicate()
            if last:
                return last
        except (OSError, ValueError, AssertionError) as error:
            last = repr(error)
        time.sleep(.5)
    raise AssertionError(f'condition did not converge in {timeout}s; last={last}')


def messages():
    with urllib.request.urlopen(MAILPIT + '/api/v1/messages', timeout=3) as response:
        return json.load(response).get('messages', [])


def assert_recipient(message):
    assert [r['Address'] for r in message['To']] == ['dev@dtcdev.click'], message
    assert not message.get('Cc') and not message.get('Bcc'), message
    return message


def wait_mail(needle, timeout=45):
    def matching():
        for message in messages():
            assert_recipient(message)
            if message['Subject'] == '[drill] ' + needle:
                return message
    return eventually(matching, timeout)


def no_mail(seconds=6):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        assert messages() == [], messages()
        time.sleep(.5)


def clear_mail():
    with urllib.request.urlopen(urllib.request.Request(MAILPIT + '/api/v1/messages', method='DELETE'), timeout=3):
        pass


def settled():
    for service, count in [('drill-alerter', 11), ('external-deadman', 1)]:
        data = state(service)
        if len(data['checks']) != count or data['pending'] or any(
            not c['ok'] or not c['candidate'] for c in data['checks'].values()
        ):
            return False
    return True


@pytest.fixture(scope='session')
def drill_stack(tmp_path_factory):
    global MAILPIT
    # Missing Docker is an error: CI must never pass by skipping the matrix.
    subprocess.run(['docker', 'info'], capture_output=True, check=True, timeout=30)
    certs = Path(os.environ.get('DRILL_CERT_DIR', str(tmp_path_factory.mktemp('drill-certs'))))
    certs.mkdir(parents=True, exist_ok=True)
    os.environ['DRILL_CERT_DIR'] = str(certs)
    def openssl(*args):
        subprocess.run(['openssl', *args], cwd=certs, capture_output=True, check=True, timeout=15)
    try:
        openssl('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '2',
                '-subj', '/CN=drill-ca', '-keyout', 'ca.key', '-out', 'ca.crt')
        openssl('req', '-newkey', 'rsa:2048', '-nodes', '-subj', '/CN=target-http',
                '-keyout', 'server.key', '-out', 'server.csr')
        (certs / 'extensions').write_text('subjectAltName=DNS:target-http\n')
        openssl('x509', '-req', '-in', 'server.csr', '-CA', 'ca.crt', '-CAkey', 'ca.key',
                '-CAcreateserial', '-days', '2', '-extfile', 'extensions', '-out', 'server.crt')
        openssl('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '2',
                '-subj', '/CN=untrusted', '-keyout', 'invalid.key', '-out', 'invalid.crt')
        compose('up', '-d', '--wait', '--wait-timeout', '90', timeout=180)
        binding = compose('port', 'mailpit', '8025').strip()
        MAILPIT = 'http://' + binding
        eventually(settled, timeout=60)
        clear_mail()
        yield
    finally:
        # Includes setup/assertion failures and removes named volumes and networks.
        try:
            compose('down', '-v', '--remove-orphans')
            project_filter = 'label=com.docker.compose.project=' + os.environ['COMPOSE_PROJECT_NAME']
            for command in (['ps', '-aq'], ['volume', 'ls', '-q'], ['network', 'ls', '-q']):
                result = subprocess.run(['docker', *command, '--filter', project_filter],
                                        check=True, capture_output=True, text=True, timeout=15)
                assert not result.stdout.strip(), result.stdout
        finally:
            for path in certs.iterdir():
                path.unlink()


def restore():
    ids = compose('ps', '-a', '-q').split()
    details = json.loads(subprocess.run(['docker', 'inspect', *ids], capture_output=True,
                                       text=True, check=True, timeout=15).stdout)
    for container in details:
        if container['State']['Paused']:
            compose('unpause', container['Config']['Labels']['com.docker.compose.service'])
    compose('start', 'smtp-proxy', 'target-http', 'target-pg', 'victoria-metrics',
            'victoria-logs', 'vector', 'drill-alerter', 'external-deadman')
    compose('exec', '-T', 'canary', 'python', '/fixture/canary.py', 'cleanup')
    compose('exec', '-T', 'target-http', 'rm', '-f', '/tmp/bad-tls')
    compose('start', 'restart-target')


@pytest.fixture(autouse=True)
def clean_scenario(request):
    if request.node.name == 'test_matrix_ids_complete':
        yield
        return
    request.getfixturevalue('drill_stack')
    eventually(settled, timeout=60)
    clear_mail()
    try:
        yield
    finally:
        restore()
        eventually(settled, timeout=60)
        for message in messages():
            assert_recipient(message)
