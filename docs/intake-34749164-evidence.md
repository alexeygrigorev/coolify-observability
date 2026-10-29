# Archive env alert investigation, 2026-10-29

Intake: `34749164-22d9-4c57-96b4-c531a404e40d`. Status: open; acceptance is incomplete.

Read-only SSH inspection of contabo-a at **2026-10-29 14:07 UTC** found:

- `/etc/coolify-obs-archive.env`: root-owned, mode `600`, mtime
  `2026-10-22 07:21:36 +0200`. No secret values were read or printed.
- `cron` service active; `/etc/cron.d/coolify-obs-archive` contains
  `TZ=Europe/Berlin` and the daily `15 0` root archive command.
- Installed archive script passes `bash -n`.
- Alertmanager `/api/v2/alerts` contains no `ObsArchiveFailed` alert.

Local validation: both archive and installer pass `bash -n`; `git diff --check`
passes. Running the archive script with a clean environment, a nonexistent
`COOLIFY_OBS_ARCHIVE_ENV_FILE`, and alert delivery disabled exits **1** and emits
`S3_BUCKET is not set` before any export/upload or temporary work is created.
Thus the existing archive monitor fails loudly for the reported missing-env
case. The installer itself still creates placeholders and continues.

The existing host archive log records:

| Berlin timestamp | Evidence |
| --- | --- |
| Oct 29 00:15:46 +0100 | Oct 27 metrics object verified |
| Oct 29 12:33:34 +0100 | `ALL_DONE day=2026-10-27`, logs uploaded |
| Oct 29 12:34:45 +0100 | Oct 28 metrics object verified, 191655813 bytes |
| Oct 29 12:41:00 +0100 | `ALL_DONE day=2026-10-28`, metrics and logs uploaded |
| Oct 29 12:53:10 +0100 | `[DRILL] ALL_DONE day=2026-10-28`, logs uploaded |
| Oct 29 12:53:35 and 12:54:19 +0100 | `[DRILL]` missing `S3_BUCKET` failures |

Objects recorded in those successful runs use bucket
`dtc-coolify-backups-387546586013`, prefix `coolify/obs/`, with the dated
`metrics/2026/10/{27,28}/` and `logs/2026/10/{27,28}/` paths.
This is historical host-log evidence, not a fresh independent S3 existence check.
The intake's missing-env diagnosis conflicts with the existing env metadata and
the drill markers; confirm drill provenance before treating it as a production
configuration failure.

## Remaining proof

- AC1: file ownership/mode is observed, but the writer identity and complete
  configuration were not independently verified.
- AC2: successful runs and object verification are recorded in the host log;
  fresh S3 checks were not run. Current operator rules prohibit using static AWS
  keys without explicit approval for this exact job. No AWS credentials were used.
- AC3: observe the next scheduled run at **2026-10-30 00:15 Europe/Berlin**
  (**2026-10-29 23:15 UTC**), including completion status and alert state.
  The fail-loud half of AC3 is covered by the missing-env validation above and
  the historical same-run failure alerts; scheduled success remains pending.
- Independent review completed by session
  `hub-f0c25c30-3c75-47b3-8552-2f7b6cf37fb3` on October 29, recorded in
  coordination message `01a187ff-0c6e-77d1-a904-7eaa14eea837`. Its independent
  host read agrees with the timestamps and manual/drill distinction; it found
  no unsupported S3 proof claim and confirmed that scheduled success and
  credential identity remain pending.

No production files or credentials were changed during this inspection.
