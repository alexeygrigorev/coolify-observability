# Docker alert test matrix

Run the entire `tests/` suite: the completeness check examines collected cases
and rejects missing or duplicate IDs. Docker and Compose are required for live
drills. Mailpit captures messages addressed only to `dev@dtcdev.click`; these
tests do not prove delivery to the real mailbox. Services communicate inside
Docker; only Mailpit's UI is published on loopback port 8025. Test recipient
overrides do not change production notification configuration.

| ID | Repository drill | Status and acceptance criteria |
| --- | --- | --- |
| A1 | HTTP endpoint down | Implemented: stop the nginx target, assert FIRE https, restart and assert CLEAR https. HTTPS/TLS coverage remains follow-up work; the fixture currently uses HTTP. |
| A2 | Disk pressure | Expected failure: add a bounded disposable filesystem injector, assert alert before exhaustion, verify recovery and cleanup. |
| A3 | RAM pressure | Expected failure: apply pressure only to a capped canary, assert memory/OOM alert, verify recovery and cleanup. |
| A4 | Postgres unreachable | Implemented: stop the disposable Postgres target, assert FIRE postgres, restart and assert CLEAR postgres. |
| A5 | Container unhealthy | Expected failure: force canary healthcheck failure, assert alert and recovery; distinguish unhealthy from process exit. |
| A6 | Store unavailable | Implemented: stop VictoriaMetrics, assert FIRE store, restart and assert CLEAR store. External dead-man coverage remains follow-up work. |
| A7 | Log pipeline failure | Expected failure: break disposable Vector/log ingestion, assert pipeline alert and recovery; test ERROR bursts/multiline events separately. |
| A8 | Email recipient routing | Implemented: inject target failure and assert the matching captured message has exactly the dev recipient. SMTP outage/retry and real delivery evidence remain follow-up work. |

The earlier merged t1012u planning report used different ID assignments (for
example A2 recovery, A3 Postgres, A4 disk, A6 restart loop and A8 SMTP retry).
The table above preserves the existing repository IDs. Child tasks must name
both the fault and ID, cover those additional planning scenarios explicitly,
and record fire, near-miss, recovery and cleanup evidence. Do not silently
reinterpret an existing test ID.

The four expected failures are documented implementation debt, permitted by
the parent scaffold acceptance criteria. Removing a placeholder without adding
its drill fails the completeness check. Completing this scaffold does not close
the full drill implementation or Contabo installation tasks.
