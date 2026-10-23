"""A1–A8: live bounded injection, near-miss, SMTP capture, recovery and cleanup."""
from contextlib import contextmanager
import json
import re
import subprocess
import time

from conftest import (assert_recipient, clear_mail, compose, eventually, execute,
                      messages, no_mail, settled, state, wait_mail)


def test_matrix_ids_complete(request):
    ids = []
    for item in request.session.items:
        if item.path == request.node.path:
            match = re.match(r'test_(A[1-8])_', item.originalname or item.name)
            if match:
                assert item.get_closest_marker('xfail') is None
                assert item.get_closest_marker('skip') is None
                ids.append(match.group(1))
    assert sorted(ids) == [f'A{i}' for i in range(1, 9)], ids


@contextmanager
def stopped(service):
    compose('stop', '-t', '1', service)
    try:
        yield
    finally:
        compose('start', service)


@contextmanager
def injected(kind, value='0', duration='30'):
    compose('exec', '-T', '-d', 'canary', 'python', '/fixture/canary.py',
            'inject', kind, str(value), str(duration))
    try:
        yield
    finally:
        compose('exec', '-T', 'canary', 'python', '/fixture/canary.py', 'cleanup')


def sensor():
    return json.loads(execute('canary', "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/status').read().decode())"))


def container(service):
    container_id = compose('ps', '-a', '-q', service).strip()
    return json.loads(subprocess.run(['docker', 'inspect', container_id], check=True,
                                    capture_output=True, text=True, timeout=15).stdout)[0]


def log(message):
    compose('exec', '-T', 'canary', 'python', '/fixture/canary.py',
            'inject', 'logs', message, '0')


def query_logs(query):
    return json.loads(execute('drill-alerter',
        'import sys,json; sys.path.insert(0,"/app"); from drill_alerter import logs; '
        f'print(json.dumps(logs({query!r})))'))


def test_A1_https_endpoint_and_tls():
    # A transient pause that ends within the HTTP timeout is a near-miss.
    compose('pause', 'target-http')
    try:
        time.sleep(.5)
    finally:
        compose('unpause', 'target-http')
    no_mail()
    with stopped('target-http'):
        wait_mail('FIRE https')
    wait_mail('CLEAR https')  # old plan A2 recovery
    clear_mail()
    # The process still serves HTTPS, but the configured CA rejects this cert.
    compose('exec', '-T', 'target-http', 'touch', '/tmp/bad-tls')
    try:
        compose('restart', '-t', '1', 'target-http')
        wait_mail('FIRE https')
        assert container('target-http')['State']['Running']
    finally:
        compose('exec', '-T', 'target-http', 'rm', '-f', '/tmp/bad-tls')
        compose('restart', '-t', '1', 'target-http')
    wait_mail('CLEAR https')


def test_A2_bounded_disk_pressure():
    with injected('disk', 40):
        eventually(lambda: .60 < sensor()['disk'] < .70)
        no_mail()
    eventually(lambda: sensor()['disk'] < .1)
    with injected('disk', 56):
        measured = eventually(lambda: s if .8 < (s := sensor())['disk'] < .95 else None)
        assert measured['disk'] < 1  # alert before exhaustion, old plan A4
        wait_mail('FIRE disk')
    wait_mail('CLEAR disk')
    assert sensor()['disk'] < .1


def test_A3_capped_ram_and_oom():
    with injected('ram', 30):
        no_mail()
    with injected('ram', 80):
        eventually(lambda: sensor()['memory'] > .8)
        wait_mail('FIRE memory')
    wait_mail('CLEAR memory')
    clear_mail()
    previous = sensor()['oom']
    # Real cgroup OOM in the exec canary, never host-wide pressure.
    with injected('oom'):
        eventually(lambda: sensor()['oom'] > previous)
        wait_mail('FIRE oom')
    wait_mail('CLEAR oom')
    assert sensor()['memory'] < .8
    assert container('canary')['HostConfig']['MemorySwap'] == 128 * 1024 * 1024
    assert container('canary')['State']['Running']


def test_A4_postgres_unreachable():
    # Old plan A3: a brief interruption must not produce mail.
    with stopped('target-pg'):
        pass
    no_mail()
    with stopped('target-pg'):
        wait_mail('FIRE postgres')
    wait_mail('CLEAR postgres')


def test_A5_forced_healthcheck_and_restart_loop():
    with injected('unhealthy', duration='1'):
        no_mail()
    with injected('unhealthy'):
        eventually(lambda: container('canary')['State']['Health']['Status'] == 'unhealthy')
        assert container('canary')['State']['Running']
        wait_mail('FIRE unhealthy')
    wait_mail('CLEAR unhealthy')
    clear_mail()
    # Old plan A6 is a separate container restart loop, capped at five retries.
    with injected('restart'):
        eventually(lambda: container('restart-target')['RestartCount'] >= 2)
        wait_mail('FIRE restart')
    compose('start', 'restart-target')
    wait_mail('CLEAR restart')
    assert container('restart-target')['State']['Running']


def test_A6_vm_unavailable_and_external_deadman():
    compose('pause', 'victoria-metrics')
    try:
        time.sleep(.5)
    finally:
        compose('unpause', 'victoria-metrics')
    no_mail()
    with stopped('victoria-metrics'):
        wait_mail('FIRE store')
        wait_mail('FIRE deadman')
    wait_mail('CLEAR store')
    wait_mail('CLEAR deadman')
    clear_mail()
    # Observer must still send with the entire in-band monitoring group down.
    with (stopped('drill-alerter'), stopped('victoria-metrics'),
          stopped('victoria-logs'), stopped('vector')):
        wait_mail('FIRE deadman')
        for service in ('drill-alerter', 'victoria-metrics', 'victoria-logs', 'vector'):
            assert not container(service)['State']['Running']
        assert container('external-deadman')['State']['Running']
    wait_mail('CLEAR deadman')
    eventually(settled)


def test_A7_vector_ingestion_error_and_multiline():
    compose('pause', 'vector')
    try:
        time.sleep(.5)
    finally:
        compose('unpause', 'vector')
    no_mail()
    with stopped('vector'):
        wait_mail('FIRE pipeline')
        log('INFO replay-after-vector-outage')
    wait_mail('CLEAR pipeline')
    eventually(lambda: query_logs('"replay-after-vector-outage"'))
    clear_mail()
    # One ERROR is below the three-event threshold; INFO text is harmless.
    log('ERROR near-miss')
    log('INFO harmless multiline\\n  ordinary continuation')
    no_mail(10)
    for number in range(3):
        log(f'ERROR burst-{number}')
    wait_mail('FIRE errors')
    wait_mail('CLEAR errors')
    clear_mail()
    log('PANIC multiline-drill\\n  frame_one\\n  frame_two')
    records = eventually(lambda: query_logs('"multiline-drill"'))
    assert len(records) == 1, records
    assert records[0]['_msg'] == 'PANIC multiline-drill\n  frame_one\n  frame_two'
    wait_mail('FIRE multiline')
    wait_mail('CLEAR multiline')
    clear_mail()
    # Also exercise a live collector whose ingestion destination is down.
    with stopped('victoria-logs'):
        wait_mail('FIRE pipeline')
        log('INFO replay-after-ingestion-outage')
    wait_mail('CLEAR pipeline')
    eventually(lambda: query_logs('"replay-after-ingestion-outage"'))


def test_A8_exact_dev_routing_smtp_outage_retry():
    # Short SMTP outage without a pending transition is a near-miss.
    with stopped('smtp-proxy'):
        time.sleep(.5)
    no_mail()
    before = state()['retries']
    with stopped('smtp-proxy'):
        with stopped('target-http'):
            eventually(lambda: state()['retries'] > before)
            assert state()['pending'][0] == ['https', 'FIRE']
            assert messages() == []  # no delivery while SMTP is unavailable
        # Recovery is queued behind FIRE while SMTP remains down.
        eventually(lambda: ['https', 'CLEAR'] in state()['pending'])
        assert container('drill-alerter')['State']['Running']
    fire = wait_mail('FIRE https')
    clear = wait_mail('CLEAR https')
    assert fire['ID'] != clear['ID']
    eventually(lambda: not state()['pending'])
    assert sorted(m['Subject'] for m in messages()) == ['[drill] CLEAR https', '[drill] FIRE https']
    for message in messages():
        assert_recipient(message)
