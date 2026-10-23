#!/usr/bin/env python3
"""Run as root on contabo-b after install, using existing backup configuration.

Creates only biz_metrics and its dedicated roles; credentials are generated on
node and retained only in /etc/biz-metrics.env. Existing credentials/roles are
preserved. Requires the installed SQL files beside this script.
"""
import os
from pathlib import Path
import re
import secrets
import shlex
import subprocess
from urllib.parse import quote, unquote, urlsplit

BASE = Path('/data/biz-metrics')
ENV = Path('/etc/biz-metrics.env')


def command(args, data=None):
    result = subprocess.run(args, input=data, text=True, capture_output=True)
    if result.returncode:
        # Never print SQL/driver errors: they may include private configuration.
        raise RuntimeError('private provisioning operation failed; inspect on node')
    return result.stdout.strip()


def sql(container, db, statement):
    return command(['docker', 'exec', '-i', container, 'psql', '-X', '-U', 'pgadmin',
                    '-v', 'ON_ERROR_STOP=1', '-d', db, '-At'], statement)


def main():
    if os.geteuid() != 0:
        raise RuntimeError('run as root on the data node')
    containers = command(['bash', '-c', 'source /etc/coolify-pg-dump.env; '
                          'printf "%s\\n%s" "$PG_SHARED_CONTAINER" "$PG_RELAY_CONTAINER"']).splitlines()
    shared, relay = containers
    values = {}
    for line in ENV.read_text().splitlines():
        if line.strip() and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            parts = shlex.split(value)
            values[key] = parts[0] if parts else ''
    credentials = {}
    for role, key in [('biz_ro', 'BIZ_METRICS_CMP_DSN'), ('biz_rw', 'BIZ_METRICS_STORE_DSN')]:
        dsn = values.get(key, '')
        password = urlsplit(dsn).password if dsn else None
        if password and '__REDACTED__' not in password:
            credentials[role] = unquote(password)
        else:
            instances = [shared, relay] if role == 'biz_ro' else [shared]
            if any(sql(c, 'postgres', f"SELECT 1 FROM pg_roles WHERE rolname='{role}';") for c in instances):
                raise RuntimeError('existing role has no saved credentials; operator must reconcile privately')
            credentials[role] = secrets.token_urlsafe(36)
    # Save before mutating roles: a retry can always recover the credentials.
    for key, db in [('STORE', 'biz_metrics'), ('CMP', 'cmp'), ('WEBSITE', 'website'),
                    ('AISHL', 'aisl'), ('RELAY', 'relay')]:
        role = 'biz_rw' if key == 'STORE' else 'biz_ro'
        host = relay if key == 'RELAY' else shared
        values[f'BIZ_METRICS_{key}_DSN'] = f'postgresql://{role}:{quote(credentials[role], safe="")}@{host}:5432/{db}'
    values['BIZ_METRICS_SHARED_CONTAINER'] = shared
    values['BIZ_METRICS_RELAY_CONTAINER'] = relay
    values.setdefault('VM_PUSH_URL', 'http://10.100.0.1:8428/api/v1/import/prometheus')
    fd = os.open(ENV, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        for key, value in sorted(values.items()):
            stream.write(f'{key}={shlex.quote(value)}\n')
    os.chmod(ENV, 0o600)
    for container, role in [(shared, 'biz_ro'), (shared, 'biz_rw'), (relay, 'biz_ro')]:
        if not sql(container, 'postgres', f"SELECT 1 FROM pg_roles WHERE rolname='{role}';"):
            password = credentials[role].replace("'", "''")
            sql(container, 'postgres', f"CREATE ROLE {role} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD '{password}';")
        if role == 'biz_ro':
            sql(container, 'postgres', 'ALTER ROLE biz_ro SET default_transaction_read_only=on;')
    if not sql(shared, 'postgres', "SELECT 1 FROM pg_database WHERE datname='biz_metrics';"):
        sql(shared, 'postgres', 'CREATE DATABASE biz_metrics;')
    sql(shared, 'biz_metrics', (BASE / 'schema.sql').read_text())
    sql(shared, 'biz_metrics', (BASE / 'roles.sql').read_text())
    sql(shared, 'postgres', 'GRANT CONNECT ON DATABASE biz_metrics TO biz_rw;')
    grants = {
        'cmp': {'courses_submission': 'id,homework_id,submitted_at',
                'courses_homework': 'id,course_id,slug', 'courses_course': 'id,slug',
                'courses_courseregistration': 'id,campaign_id,course_id,status,created_at',
                'courses_registrationcampaign': 'id,slug'},
        'website': {'courses_submission': 'id,homework_id,submitted_at',
                    'courses_homework': 'id,course_id,slug', 'courses_course': 'id,slug',
                    'courses_courseregistration': 'id,campaign_id,course_id,created_at',
                    'courses_registrationcampaign': 'id,slug'},
        'aisl': {'analytics_useractivity': 'occurred_at,event_type,user_id,object_id,object_type',
                 'analytics_userattribution': 'user_id,first_touch_utm_source',
                 'cb_curriculum_unit': 'id,module_id', 'cb_curriculum_module': 'id,course_id',
                 'cb_curriculum_course': 'id,slug',
                 'payments_conversionattribution': 'created_at,tier_id,billing_period,first_touch_utm_source,mrr_eur',
                 'payments_tier': 'id,slug'},
        'relay': {'transactional_messages': 'created_at,client_id,status,template_key',
                  'clients': 'id,slug', 'campaign_recipients': 'campaign_id,status,sent_at,updated_at',
                  'campaigns': 'id,client_id',
                  'email_events': 'created_at,client_id,transactional_message_id,campaign_id,event_type'},
    }
    for db, tables in grants.items():
        container = relay if db == 'relay' else shared
        sql(container, db, f'GRANT CONNECT ON DATABASE {db} TO biz_ro; GRANT USAGE ON SCHEMA public TO biz_ro;')
        for table, columns in tables.items():
            sql(container, db, f'GRANT SELECT ({columns}) ON {table} TO biz_ro;')
    dump_env = Path('/etc/coolify-pg-dump.env')
    content = dump_env.read_text()
    match = re.search(r'^PG_SHARED_DBS=(.*)$', content, re.M)
    if not match:
        raise RuntimeError('dump database list missing; configure explicitly')
    dbs = shlex.split(match[1])[0].split()
    if 'biz_metrics' not in dbs:
        dbs.append('biz_metrics')
        content = content[:match.start()] + 'PG_SHARED_DBS=' + shlex.quote(' '.join(dbs)) + content[match.end():]
        dump_env.write_text(content)
    print('Provisioned biz_metrics, dedicated roles, column SELECT grants, private configuration and dump list')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Provisioning failed ({type(exc).__name__}); inspect configuration privately on node')
        raise SystemExit(1) from None
