# Hub tasks — coolify-observability (t1015u / t1016u)

Parent: [a478bb62-ead3-4cce-a8cc-4a8897e7ca71](https://hub.dtcdev.click/#/intake/a478bb62-ead3-4cce-a8cc-4a8897e7ca71)  
Plan: [849afb15-98ec-437c-a824-d96e4e8e800b](https://hub.dtcdev.click/#/intake/849afb15-98ec-437c-a824-d96e4e8e800b) · `obs-lightweight-plan-t1012u-2026-10-22.md`

**Live Contabo stack (t1016u peer pivot):** VictoriaMetrics + VictoriaLogs on `.163` (vmui) + Vector×2. OpenObserve partial install **stopped**.  
**Plan vote was 2/3 OpenObserve**; Argon VM+VL + later steering won the Contabo cutover.  
**Alert email (t1205u):** `alexey@datatalks.club` + `dev@dtcdev.click` (CI drill A8 asserts both; no grokbot).

| # | Title | Hub id | Link | Notes |
|---|-------|--------|------|-------|
| 1 | Scaffold compose (OO→superseded by VM+VL) | `4a090ff4-3dba-4e7c-8240-c296a53c0415` | [hub](https://hub.dtcdev.click/#/intake/4a090ff4-3dba-4e7c-8240-c296a53c0415) | see `docker-compose.prod.yml` |
| 2 | Vector configs .163/.141 | `d35efc85-b91f-4e7a-be10-42a068062821` | [hub](https://hub.dtcdev.click/#/intake/d35efc85-b91f-4e7a-be10-42a068062821) | `configs/vector/` |
| 3 | Alert rules → mail | `f050b9ed-9970-420f-9ca0-76f9bf8453c9` | [hub](https://hub.dtcdev.click/#/intake/f050b9ed-9970-420f-9ca0-76f9bf8453c9) | destinations deferred |
| 4 | Docker alert matrix A1–A8 | `ebf663e1-e5a2-4bcb-b344-864b9cb45756` | [hub](https://hub.dtcdev.click/#/intake/ebf663e1-e5a2-4bcb-b344-864b9cb45756) | A1/A4/A8 passed on Hetzner 2026-10-22 |
| 5 | CI workflow / workflow-scope unblock | `5f5d3002-fc2d-4f27-a6db-3593cb26ef99` | [hub](https://hub.dtcdev.click/#/intake/5f5d3002-fc2d-4f27-a6db-3593cb26ef99) | docs pending |
| 6 | Soak-test RAM gate | `3b76e8eb-39f7-48bf-877f-08f7a3495036` | [hub](https://hub.dtcdev.click/#/intake/3b76e8eb-39f7-48bf-877f-08f7a3495036) | VM 256 / VL 256 / Vector 128 |
| 7 | Teardown leftover .141 LGTM exporters | `533d8583-77a5-4e56-913a-aee64920aacd` | [hub](https://hub.dtcdev.click/#/intake/533d8583-77a5-4e56-913a-aee64920aacd) | promtail gone; keep node+pg×2 (+cadvisor) |
| 8 | Contabo Coolify deploy | `6e4fc316-1551-4c25-a097-1bbf78949c84` | [hub](https://hub.dtcdev.click/#/intake/6e4fc316-1551-4c25-a097-1bbf78949c84) | VM+VL live on `.163` |
| 9 | Pass 2 Astra/Argon/Opus cross-review | `251fdf16-fec5-4d13-b074-3333bfbf7cad` | [hub](https://hub.dtcdev.click/#/intake/251fdf16-fec5-4d13-b074-3333bfbf7cad) | open |

| 10 | Obs retention + S3 archive (2d hot / 14d S3) | `t1031u` | — | `docs/retention-s3.md`; cron on `.163` |

Never write sprint reports into dataops-knowledge.
