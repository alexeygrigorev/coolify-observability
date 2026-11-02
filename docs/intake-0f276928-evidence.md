# Unattended archive verification: intake 0f276928

Status: DONE. The first unattended run after the windowed-export fix completed
successfully, the three October 28 objects were independently listed and
headed in S3, and Alertmanager has no firing non-drill `ObsArchiveFailed`
alert. No rerun was needed.

## Code and deployment

The archive fix is on `main`: commit `586aa1f5a73759b0e99e9c639598a53ec9886f38`
is an ancestor of `origin/main` at verification time. On `contabo-a`,
`sha256sum /usr/local/sbin/coolify-obs-archive.sh` and the repository's
`scripts/obs-day-archive.sh` both returned
`3bcb96408dc1b246cad9f0f0aca38cd77d4b2a346a76feeafc14cac345e23273`.

## Unattended run

Read-only SSH inspection of `/var/log/coolify-obs-archive.log` returned these
lines for the October 30 run:

```text
2026-10-30T00:15:02+0100 start target_day=2026-10-28 berlin day_path=2026/10/28 start_utc=2026-10-27T23:00:00Z end_utc=2026-10-28T23:00:00Z kinds=metrics logs run_dir=/var/tmp/coolify-obs-archive/run-2026-10-28-20261030T0015+0100-1852330
2026-10-30T00:15:56+0100 verified s3://dtc-coolify-backups-387546586013/coolify/obs/metrics/2026/10/28/metrics-2026-10-28-20261030T0015+0100.ndjson.gz bytes=191634745
2026-10-30T00:22:00+0100 logs export complete windows=24 rows=1628005 zero_row_windows=0
2026-10-30T00:22:45+0100 verified s3://dtc-coolify-backups-387546586013/coolify/obs/logs/2026/10/28/logs-2026-10-28-20261030T0015+0100.ndjson.gz bytes=168471885
2026-10-30T00:22:47+0100 verified s3://dtc-coolify-backups-387546586013/coolify/obs/logs/2026/10/28/logs-2026-10-28-20261030T0015+0100.manifest.ndjson bytes=2216
2026-10-30T00:22:47+0100 alertmanager resolved: obs archive OK day=2026-10-28
2026-10-30T00:22:47+0100 ALL_DONE day=2026-10-28 metrics=coolify/obs/metrics/2026/10/28/metrics-2026-10-28-20261030T0015+0100.ndjson.gz logs=coolify/obs/logs/2026/10/28/logs-2026-10-28-20261030T0015+0100.ndjson.gz
```

No `ERROR` appears between this run's start and `ALL_DONE`. The cron journal
records invocation at `2026-10-30T00:15:01+01:00` and session closure at
`00:22:47+01:00`. The journal does not expose a numeric exit code; the job's
`ALL_DONE` and same-second cron closure are the available completion evidence.

## Independent S3 and Alertmanager checks

Using the archive host's job environment without displaying its contents, a
fresh `aws s3api list-objects-v2` and `head-object` check returned the three
objects below. The list results and head sizes agree:

| Object | Bytes | S3 LastModified (UTC) |
| --- | ---: | --- |
| `coolify/obs/metrics/2026/10/28/metrics-2026-10-28-20261030T0015+0100.ndjson.gz` | 191634745 | 2026-10-29T23:15:54Z |
| `coolify/obs/logs/2026/10/28/logs-2026-10-28-20261030T0015+0100.ndjson.gz` | 168471885 | 2026-10-29T23:22:42Z |
| `coolify/obs/logs/2026/10/28/logs-2026-10-28-20261030T0015+0100.manifest.ndjson` | 2216 | 2026-10-29T23:22:47Z |

The live filtered query
`curl --fail --silent --show-error 'http://127.0.0.1:9093/api/v2/alerts?filter=alertname%3DObsArchiveFailed'`
followed by a filter excluding `drill=true` returned `[]`.

The conditional failed-run acceptance criteria do not apply: this unattended
run succeeded. No archive rerun, production configuration change, object
deletion, or credential output was performed. This commit only records the
verification evidence; tests were not run because no executable code changed.
