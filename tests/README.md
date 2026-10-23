# Docker alert test matrix

Run `python -m pytest tests/ -v --tb=short` after installing
`tests/requirements.txt`. Requires Linux Docker with cgroup v2, Compose v2,
and host OpenSSL. Pytest generates a short-lived fixture CA and TLS certificates,
starts an isolated Compose project from `docker-compose.test.yml`, discovers
Mailpit's ephemeral loopback port, and waits for healthy evaluations before
injecting faults. Missing Docker fails the run. No scenario is skipped or xfailed.

| ID | Repository drill | Injection, near-miss, FIRE and CLEAR |
| --- | --- | --- |
| A1 | HTTPS endpoint failure and TLS validation | Stop the TLS endpoint; also restart it with an untrusted certificate while the process stays running. Both produce FIRE https and CLEAR https after recovery. A sub-timeout pause produces no mail. The normal certificate chains to the generated CA and matches the service hostname; verification stays enabled. |
| A2 | Bounded disk pressure | Write 56 MiB into a disposable 64 MiB tmpfs; measured usage above 80% but below 95% produces FIRE disk before exhaustion. Removing the file produces CLEAR disk and usage below 10%. A 40 MiB fill remains below threshold with no mail. |
| A3 | Capped RAM and OOM | Allocate 80 MiB inside a 128 MiB canary (swap also capped at 128 MiB); measured cgroup usage above 80% produces FIRE memory, release produces CLEAR memory. A separate 256 MiB exec allocation is killed by the cgroup and increments real `memory.events:oom_kill`, producing FIRE/CLEAR oom while the sensor stays running. A 30 MiB allocation produces no mail. |
| A4 | Postgres unreachable | Stop disposable Postgres, assert FIRE postgres, restart and assert CLEAR postgres. A brief stop/start below the debounce window produces no mail. |
| A5 | Forced unhealthy healthcheck and restart loop | Force Docker healthcheck failure while PID 1 stays running, assert Docker unhealthy and FIRE unhealthy, remove marker and assert CLEAR unhealthy. A one-second marker produces no mail. Separately force a restart loop on a disposable container capped at five retries; verify RestartCount, FIRE restart, remove marker, restore running state and assert CLEAR restart. |
| A6 | VictoriaMetrics unavailable and external dead-man | A sub-timeout pause produces no mail. Stop VM, assert FIRE store plus FIRE deadman, restart and require both CLEAR messages. Then stop VM, VictoriaLogs, Vector and the in-band alerter; an observer with no monitored-service dependency, socket or sensor access still sends FIRE deadman and CLEAR on recovery over its independent SMTP/network path. |
| A7 | Vector/ingestion failure, ERROR and multiline | Stop Vector, assert FIRE pipeline from missing ingested heartbeat, restore and assert CLEAR plus replay of an outage log. Repeat with VictoriaLogs unavailable while Vector stays live. Brief collector pause produces no mail. One ERROR and an INFO continuation produce no mail; three ERROR events produce FIRE/CLEAR errors. A PANIC with two continuation lines is asserted as exactly one stored record with intact newlines and produces FIRE/CLEAR multiline. |
| A8 | Exact dev routing and SMTP outage/retry | Short idle transport outage produces no mail. Stop only the disposable SMTP proxy; inject and recover HTTPS while it stays down. Assert increasing retry count, ordered queued FIRE/CLEAR, no captured delivery during outage, and a live evaluator. Restore SMTP and require exactly the two distinct messages with no pending transitions. Every captured message in every drill has exactly the dev recipient and empty Cc/Bcc. |

Every fault has a bounded timeout. Resource injectors expire within 45 seconds
and have PID-scoped cleanup; disk/RAM pressure never runs on the host. The
canary's resource capability protects only its sensor PID from the deliberate
exec OOM; pressure and restart containers have memory, swap, process/CPU or
restart caps. Disk writes stop well before exhaustion. Function cleanup restores
services and removes markers/pressure even on failed assertions. Session cleanup
removes the entire owned project, volumes, networks and generated certificates,
including setup failures. CI has an additional unconditional cleanup step and
asserts that owned Docker resources are gone. Tests use no production targets,
mail credentials or notification configuration.

The alerter mounts the Docker socket to read health and restart metadata, scoped
by its Compose project label. Its code sends GET requests only; a read-only
socket mount does **not** restrict Docker API permissions. Run these fixtures on
a trusted disposable development/CI daemon, as required by the OOM drill too.
The external observer models a separate failure domain in Docker: this is an
executable dead-man scenario, not proof of a deployed off-host monitor. Actual
host loss and real mailbox delivery still need separately authorized validation.
The SMTP retry queue is in memory; process-crash persistence needs separate coverage.
Mailpit evidence proves SMTP capture only; it never proves real delivery.

The older t1012u merged plan assigned A2 to recovery, A3 to Postgres, A4 to
disk, A6 to restart loops and A8 to SMTP retry. Preserve repository IDs above:
those older scenarios are covered by repository A1, A4, A2, A5 and A8,
respectively. The completeness check inspects the collected matrix and rejects
missing, duplicate, skipped or xfailed IDs. These tests validate the existing
test-only thin evaluator; they do not certify the production declarative rule
pack or authorize an installation.

Historical reconciliation before implementation reused the VM/VL scaffold,
Vector config pattern, active CI and existing A1/A4/A6/A8 drills from main
`20e7a28` (including scaffold correction `d2e4513`). Historical drill child
`ebf663e1-e5a2-4bcb-b344-864b9cb45756` is recorded in `TASKS.md` along with the
other eight children. The parent report says direct reads returned `not_found`;
this worker's read-only parent/child lookups returned a generic Hub operation
failure. Artifact evidence was used without claiming task deletion or completion.
The existing `aws-infra/docs/observability-reconciliation.md`, merged t1012u plan
and all three t1014u recommendations informed this reconciliation. This child fills
the four documented placeholders and extends the four existing cases; it does
not repeat installation, teardown, CI enablement or scaffold work.
