# Relay Postgres exporter on contabo-b

The exporter must connect to the `pg-relay` Coolify resource through Docker's
external `coolify` network. Its database hostname is the running container's
Docker name, discovered using `coolify.resourceName=pg-relay`; do not use a
container IP or the WireGuard bridge as the database target.

The Compose source is [`docker-compose.postgres.yml`](../docker-compose.postgres.yml).
Production uses project `lgtm-pgexp`, Compose file
`/data/lgtm/exporters/docker-compose.postgres.yml`, and private environment file
`/data/lgtm/exporters/.env`. Keep credentials on the host. Never print a resolved
Compose config or a full container environment into reports.

## t1218u correction, 2026-10-23

| Setting | Before | After |
| --- | --- | --- |
| Relay database destination (credentials omitted) | `10.100.0.2:5432/relay` | `mqimefrti7ratmaliirnikov:5432/relay` |
| Relay exporter network | `lgtm-pgexp_default` | external `coolify` |
| `pg_up` | `0` | `1` |
| `pg_exporter_last_scrape_error` | `1` | `0` |

The `DATA_SOURCE_NAME_RELAY` hostname in the private `.env` was replaced while
preserving the credentials and all other connection options. Only
`postgres-exporter-relay` was recreated, using:

```sh
sudo docker compose --project-name lgtm-pgexp \
  --env-file /data/lgtm/exporters/.env \
  -f /data/lgtm/exporters/docker-compose.postgres.yml config --quiet
sudo docker compose --project-name lgtm-pgexp \
  --env-file /data/lgtm/exporters/.env \
  -f /data/lgtm/exporters/docker-compose.postgres.yml \
  up -d --no-deps postgres-exporter-relay
```

VictoriaMetrics still scrapes `10.100.0.2:9187`. This is the exporter's published
HTTP endpoint, not its database destination. The shared exporter retains its
existing network, credentials, and published port `9188`.

No Postgres container was recreated. No static IP, Docker alias, DNS setting,
WireGuard bridge, or watchdog change was made. Docker resolves the database
hostname to its current address. If Coolify replaces the database resource with
a different name, discover the new resource name and update the private DSN;
this change does not add automatic hostname migration.

## Verification

On contabo-a, query VictoriaMetrics at `http://127.0.0.1:8428` with selector:

```promql
{job="postgres",instance_name="pg-relay",__name__=~"pg_up|pg_exporter_last_scrape_error|up"}
```

Use `/api/v1/export` with `match[]`, `start`, and `end` to inspect raw samples.
Require at least 600 seconds between first and last samples for each series,
all `pg_up=1`, all `pg_exporter_last_scrape_error=0`, and all `up=1`. Check sample
gaps against the configured 30-second scrape interval. Instant queries alone
do not prove the complete interval. Check `/api/v1/targets` for `health=up` and
an empty `lastError` too.

The 2026-10-23 soak passed from **01:40:17.868 to 01:51:17.868 UTC**
(03:40–03:51 Europe/Berlin): 23 raw samples per series across 660 seconds.
Every `pg_up` and `up` sample was 1; every `pg_exporter_last_scrape_error`
sample was 0. Every consecutive sample gap was 30 seconds. The final target
reported `health=up` with an empty `lastError`.

The full evidence is recorded in
`~/tmp/agent-reports/postgres-exporter-relay-fix-t1218u-2026-10-23.md` on the
operator machine, with a sanitized raw-sample JSON companion.

## Rollback

The original `.env` and Compose file are backed up on contabo-b in root-only
`/root/pgexp-relay-t1218u-backup/`. Restore both to `/data/lgtm/exporters/` and
run the same service-scoped Compose command above. This restores the former
configuration, including its broken database route. Do not restart Postgres
or bring down the entire exporter project.
