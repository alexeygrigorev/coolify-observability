# Production drill evidence — 2026-10-26 (bc9b3f30, DECISION t1468u)

Status: all A1-A8 classes fired a real alert to dev@ only via vmalert/Alertmanager and cleared.
Mail metrics (Alertmanager, sanitized): every drill shows `requests_failed_total{integration="email"} 0`.
Receivers: all alerts `receivers:[{name:dev-only}]`, config `to: dev@dtcdev.click` only (no other recipient).
No real prod alerts muted (healthcheck separate, still active). No PG/app/data touched (exporters/Vectors only).

## Live stack (post-install, all healthy)

- contabo-a: VM, VL, Vector (3d), blackbox, vmalert-vm, vmalert-vl, AM, obs-a5-canary — all Up, no crash-loops.
- contabo-b: node/cadvisor/postgres exporters Up, Vector Up.
- VM targets: 12 active, 0 down (`up` query). Blackbox probes: 3/3 `probe_success 1`.
- vmalert: 6 VM groups + 1 VL group loaded, 0 firing at rest. AM: 0 active alerts at rest.

## Drills (UTC; JST = UTC+9)

- A4 (postgres exporter, real): 03:19:36Z stop relay exporter (.b) → `up==0`, vmalert pending 03:20:00Z, firing 03:20:00Z+, AM active 03:21:00Z (receiver dev-only). 03:22:27Z restart → `up==1`, AM [] by 03:23:58Z. Mail: requests_total increased, failed 0.
- A2 (synthetic canary, tmpfs not exposed by node_exporter — live probe 2026-10-26): 03:24:26Z push `obs_drill_disk_free_ratio 0.1` → firing 03:24:30Z+, AM active 03:25:30Z. 03:27:49Z push 0.9 → AM [] . Mail failed 0.
- A3 (synthetic, cadvisor has no container names — live probe 2026-10-26): 03:29:28Z push `obs_drill_mem_free_ratio 0.1` → pending, firing 03:32:15Z-, AM active. 03:32:15Z push 0.9 → AM [] by ~03:33:51Z. Mail failed 0.
- A5 (synthetic, `container_last_seen` has no `name` label — live probe): 03:33:51Z push `obs_drill_container_healthy 0` → firing 03:35:35Z-, AM active. Push 1 → AM [] . Mail failed 0.
- A1 (blackbox prober, real): firewall-to-courses did NOT break probe (DNS/multi-IP, probe stayed 1 — no fire, block removed 03:38:46Z). Fallback: 03:38:56Z stop obs-blackbox → `up{job="blackbox-https"}==0`, AM active (3x, one per target, grouped). 03:41:22Z restart → AM [] . Mail failed 0. `probe_success==0` path validated in local Docker (TLS/bad-cert); prod prober-down path proves A1 notifier.
- A6 (node exporter, real): first stop 03:42:48Z exceeded tool timeout, restarted ~03:46Z (pending only, no fire). Redo 03:46:00Z stop → pending, firing 03:49:44Z (activeAt 03:46:30Z, for 2m + eval), AM active 03:48:30Z. 03:49:45Z restart (downtime 3m45s, over 2m plan — rule `for:2m` requires >2m to fire; monitoring-only, PG safe) → `up==1`, AM [] by 03:51:35Z. Mail failed 0.
- A7 (logs, real): 03:51:43Z stop vector-b → `_time:2m` VL query shows only contabo-a (no .b) — pipeline gap proven. VL `stats by (host)` omits absent hosts, so gap rule cannot fire on absent (documented). ERROR-burst path: 03:57:00Z canary 60 ERROR (0 ingested — Vector just restarted, timing), 03:58:50Z burst 70 (71 ingested), 04:01:31Z burst2 70 → vmalert-vl pending (value 78), firing 04:00:00Z+, AM active. Natural clear by 04:06:40Z (AM []). Vector-b restarted 03:56:22Z (gap 4m39s, over 2m plan — VL `interval:2m for:2m` needs sustained signal; logs-only gap, no app impact). Mail failed 0.
- A8 (retry + routing): 04:06:51Z push A2-fire (0.1) + stop AM 1.5m → restart 04:08:25Z → AM active (vmalert retry delivered), mail requests_total 0→1, failed 0. 04:09:57Z push 0.9 → AM [] . All drill alerts `receivers:dev-only`; AM config has single receiver `to: dev@dtcdev.click`; metrics `failed 0` throughout. No SMTP-secret, inbox, or credential values recorded.

## Notes / follow-ups (not waived)

- A1 `probe_success==0` via egress-block did not fire (target multi-IP/DNS); prober-down path used instead. Egress-block method needs per-target IP verification if retried.
- A6/A7 exceeded 2m plan (3m45s / 4m39s) because rules require `for:2m` + `interval:2m`. Still production-safe (monitoring/logs only). Consider shortening `for` or documenting extended bounds in drill plan.
- Synthetic canaries (A2/A3/A5) prove evaluator→AM→dev@ path; real host signals (tmpfs mount, container names) unavailable from node_exporter/cadvisor (live-probed 2026-10-26). Real guards (`node_filesystem /`, `node_memory`, `up`) remain active.
- Inbox (dev@) receipt verified via AM SMTP acceptance (`failed 0`), not via mailbox read (no secrets accessed). Operator may confirm inbox delivery.
- External dead-man, archive overlap/restore, soak: still open per ADR pointer (not claimed).
