# Hub tasks — coolify-observability (t1015u / t1016u)

Parent: [a478bb62-ead3-4cce-a8cc-4a8897e7ca71](https://hub.dtcdev.click/#/intake/a478bb62-ead3-4cce-a8cc-4a8897e7ca71)  
Plan: [849afb15-98ec-437c-a824-d96e4e8e800b](https://hub.dtcdev.click/#/intake/849afb15-98ec-437c-a824-d96e4e8e800b) · `obs-lightweight-plan-t1012u-2026-10-22.md`

**Recommended stack:** OpenObserve (`.163`) + Vector×2 → alerts `dev@dtcdev.click`  
**Fallback:** VictoriaMetrics + VictoriaLogs  
**Hard mem:** OpenObserve 512–1024 MiB  
**Docker alert fault-injection:** mandatory for any custom layer

| # | Title | Hub id | Link | Gate |
|---|-------|--------|------|------|
| 1 | Scaffold OpenObserve+Vector compose | `4a090ff4-3dba-4e7c-8240-c296a53c0415` | [hub](https://hub.dtcdev.click/#/intake/4a090ff4-3dba-4e7c-8240-c296a53c0415) | — |
| 2 | Vector configs .163/.141 → OpenObserve | `d35efc85-b91f-4e7a-be10-42a068062821` | [hub](https://hub.dtcdev.click/#/intake/d35efc85-b91f-4e7a-be10-42a068062821) | — |
| 3 | OpenObserve alert rules → mail | `f050b9ed-9970-420f-9ca0-76f9bf8453c9` | [hub](https://hub.dtcdev.click/#/intake/f050b9ed-9970-420f-9ca0-76f9bf8453c9) | — |
| 4 | Implement Docker alert matrix A1–A8 | `ebf663e1-e5a2-4bcb-b344-864b9cb45756` | [hub](https://hub.dtcdev.click/#/intake/ebf663e1-e5a2-4bcb-b344-864b9cb45756) | — |
| 5 | CI workflow promote / workflow-scope unblock | `5f5d3002-fc2d-4f27-a6db-3593cb26ef99` | [hub](https://hub.dtcdev.click/#/intake/5f5d3002-fc2d-4f27-a6db-3593cb26ef99) | token `workflow` |
| 6 | Soak-test RAM gate (512–1024 MiB; fallback VM+VL) | `3b76e8eb-39f7-48bf-877f-08f7a3495036` | [hub](https://hub.dtcdev.click/#/intake/3b76e8eb-39f7-48bf-877f-08f7a3495036) | after deploy |
| 7 | Teardown leftover .141 LGTM exporters | `533d8583-77a5-4e56-913a-aee64920aacd` | [hub](https://hub.dtcdev.click/#/intake/533d8583-77a5-4e56-913a-aee64920aacd) | after OO+Vector green (t1016u: proceed) |
| 8 | Contabo Coolify deploy OpenObserve+Vector | `6e4fc316-1551-4c25-a097-1bbf78949c84` | [hub](https://hub.dtcdev.click/#/intake/6e4fc316-1551-4c25-a097-1bbf78949c84) | t1016u: proceed without «го» |
| 9 | Pass 2 Astra/Argon/Opus cross-review of tests | `251fdf16-fec5-4d13-b074-3333bfbf7cad` | [hub](https://hub.dtcdev.click/#/intake/251fdf16-fec5-4d13-b074-3333bfbf7cad) | — |

Never write sprint reports into dataops-knowledge.
