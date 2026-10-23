"""Disposable, capped sensor and self-expiring fault injector. Never run on hosts."""
import http.server
import json
import os
import signal
from pathlib import Path
import sys
import threading
import time

CONTROL = Path('/control')
LOG = Path('/logs/events.log')


def cgroup(name):
    return Path('/sys/fs/cgroup', name).read_text()


def status():
    disk = os.statvfs('/pressure')
    return {
        'disk': 1 - disk.f_bavail / disk.f_blocks,
        'memory': int(cgroup('memory.current')) / int(cgroup('memory.max')),
        'oom': int(dict(line.split() for line in cgroup('memory.events').splitlines())['oom_kill']),
    }


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps(status()).encode())

    def log_message(self, *args):
        pass


def emit(message):
    with LOG.open('a') as stream:
        stream.write(message + '\n')
        stream.flush()


def inject(kind, value, duration):
    # A hard upper bound remains even if pytest dies before its finally block.
    duration = min(float(duration), 45)
    if kind == 'disk':
        path = Path('/pressure/fill')
        try:
            with path.open('wb') as stream:
                for _ in range(min(int(value), 58)):
                    stream.write(b'x' * 1024 * 1024)
            time.sleep(duration)
        finally:
            path.unlink(missing_ok=True)
    elif kind == 'ram':
        data = bytearray(min(int(value), 100) * 1024 * 1024)
        time.sleep(duration)
        del data
    elif kind == 'oom':
        # Only this exec process is killed; PID 1 has oom_score_adj=-1000.
        data = bytearray(256 * 1024 * 1024)
        time.sleep(duration)
    elif kind in ('unhealthy', 'restart'):
        marker = CONTROL / kind
        marker.write_text(str(time.time() + duration))
        time.sleep(duration)
        marker.unlink(missing_ok=True)
    elif kind == 'logs':
        emit(value.replace('\\n', '\n'))
    else:
        raise ValueError(kind)


def fault_active(name):
    try:
        return float((CONTROL / name).read_text()) > time.time()
    except (FileNotFoundError, ValueError):
        return False


if __name__ == '__main__':
    mode = sys.argv[1]
    if mode == 'inject':
        pidfile = CONTROL / ('inject-' + sys.argv[2] + '.pid')
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        pidfile.write_text(str(os.getpid()))
        try:
            inject(*sys.argv[2:])
        finally:
            pidfile.unlink(missing_ok=True)
    elif mode == 'cleanup':
        for pidfile in CONTROL.glob('inject-*.pid'):
            try:
                pid = int(pidfile.read_text())
                if b'canary.py\x00inject' in Path(f'/proc/{pid}/cmdline').read_bytes():
                    os.kill(pid, signal.SIGTERM)
            except (FileNotFoundError, ProcessLookupError):
                pass
        for marker in ('unhealthy', 'restart'):
            (CONTROL / marker).unlink(missing_ok=True)
        Path('/pressure/fill').unlink(missing_ok=True)
    elif mode == 'health':
        sys.exit(1 if fault_active('unhealthy') else 0)
    elif mode == 'restart':
        while True:
            time.sleep(1)
            if fault_active('restart'):
                sys.exit(1)
    elif mode == 'serve':
        # Protect the sensor while the separate, capped exec process OOMs.
        Path('/proc/self/oom_score_adj').write_text('-1000')
        threading.Thread(target=http.server.HTTPServer(('0.0.0.0', 8000), Handler).serve_forever, daemon=True).start()
        while True:
            emit('INFO heartbeat')
            time.sleep(1)
