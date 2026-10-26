# Production alert drill plan — PREP ONLY (no approval, no execution)

Date: 2026-10-26. Status: **PLAN ONLY. Do not execute until `docs/install-approval-request.md` is APPROVED by Alexey.**
Rule binding: destructive/fault-injection steps on prod are PREP-ONLY; this file is the exact plan to be approved.

## Preconditions (all must hold before any drill)

- Install approval granted for exact commit `14a5167` and deployed per that request.
- vmalert/Alertmanager (or current `coolify-healthcheck` dead-man path) evaluating `alerts/rules.yaml` against real Contabo targets.
- Recipient mailbox `dev@dtcdev.click` monitored; sender `noreply@datatalks.club` via SES confirmed working by a benign test mail.
- Independent observer outside Contabo failure domain assigned (open item from prior gates).
- Maintenance-window etiquette: drills one at a time, business-hours Europe/Berlin, abort on any customer-visible impact.

## Drill matrix (each: FIRE real alert to dev@ only, then CLEAR; record UTC/JST timestamps + message-ids)

| Class | Production-safe injection | Expected alert | Clear |
|-------|---------------------------|----------------|-------|
| A1 https_down | Stop a single synthetic probe target (not real site); or blackhole one scrape target IP via host iptables for ≤2 min | `A1_https_down` critical to dev@ | Remove block; CLEAR |
| A2 disk_pressure | Bounded tmpfs fill on a scratch mount only (never PG/store mounts); cap <85% host | disk warning to dev@ | Release tmpfs; CLEAR |
| A3 ram_pressure | Capped cgroup allocation on a canary container (memory limit enforced, no host OOM) | memory/OOM to dev@ | Kill canary; CLEAR |
| A4 postgres_down | Stop **exporter** (not PG) for ≤2 min to simulate `up==0`; never stop real PG | `A4_postgres_down` critical to dev@ | Restart exporter; CLEAR |
| A5 unhealthy_container | Force-unhealthy a canary container (failing healthcheck, PID 1 stays up) ≤5 min | unhealthy/restart to dev@ | Restore healthcheck; CLEAR |
| A6 scrape_gap / store_gap | Pause VM scrape target (single node exporter) ≤2 min; separate step: stop VM container ≤2 min to prove store-gap path | `A6_scrape_gap` warning / store critical to dev@ | Restart; CLEAR |
| A7 log_pipeline | Stop Vector on `.141` only ≤2 min; replay check for absence then recovery | pipeline/errors to dev@ | Restart Vector; CLEAR |
| A8 mail_routing | Same as A1 FIRE while SMTP briefly held (proxy stop ≤1 min) to prove queued retry; assert **only** dev@ in To, empty Cc/Bcc, no grokbot address | ordered FIRE then CLEAR to dev@ | Restore SMTP; CLEAR |

Out of scope without a second explicit OK: stopping real Postgres, filling real disks, killing VM/VL both at once (except the A6 observer-survival check which uses the external dead-man, still bounded ≤2 min), touching SES credentials, or sending to any recipient other than dev@.

## Evidence to record per drill (after approval)

- Start/end timestamps (UTC + JST), injector command, alert subject + message-id, CLEAR subject + message-id, vmui/VL query showing the gap, and operator sign-off.
- Any drill that pages, pages twice, pages the wrong address, or fails to clear aborts the whole series and is reported before continuing.

Current state: **zero production drills executed**. Local Docker equivalents are green (14/14, see install-approval request); production mappings remain untested until this plan is approved and run.
