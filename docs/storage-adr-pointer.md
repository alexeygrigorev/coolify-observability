# Storage ADR pointer — coolify-observability

Date: 2026-10-26. Intake: bc9b3f30 (re-file of a478bb62 family).

## Decision (merged in aws-infra, reused here — not re-decided)

- ADR: `docs/architecture/ADR-0001-observability-storage-thin-layer.md`
  at aws-infra commit `589fb1c` (`docs: record observability storage and thin-layer ADR [skip ci]`).
- Content: retain single-node VictoriaMetrics + VictoriaLogs on contabo-a,
  Vector on both hosts, 2-day hot + 14-day S3 archive; select **two vmalert
  evaluators + one Alertmanager**; `drill_alerter.py` stays a fixture;
  no bespoke storage layer; OpenObserve contingent only.
- This repo implements that ADR (vmalert/Alertmanager + rules in
  `configs/vmalert/`, `configs/alertmanager/`, `docker-compose.yml`).
  No ADR text is duplicated here to avoid drift; the aws-infra commit above is canonical.

## Review (different model from implementer)

- Implementer of the ADR: Codex Agent (aws-infra commit 589fb1c, 2026-10-23).
- Reviewer for this pointer + implementation: Muse Spark (this session, 2026-10-26).
- Method: read ADR at pinned commit (`git show 589fb1c:...`), checked
  placement/retention/budget/fallback/rollback sections against live Contabo
  state (read-only SSH 2026-10-26: VM/VL/Vector running, 216G free on a,
  2-day retention flags, existing exporter mounts retained).
- Findings:
  1. ADR requires exact compatible releases/digests before implementation — **addressed**:
     this change pins `victoriametrics/vmalert:v1.115.0` (matches live VM/VL 1.115.0/1.15.0)
     and `prom/alertmanager:v0.28.0`, with mem caps 96M/96M/64M.
  2. ADR requires two evaluators (VM + VL with `type: vlogs`) + one Alertmanager
     with persisted state — **addressed**: `vmalert-vm` (datasource :8428),
     `vmalert-vl` (datasource :9428, `type: vlogs`), Alertmanager data volume
     `/data/alertmanager-data` (silence/notification log).
  3. ADR open items remain open (external observer, archive overlap/restore proof,
     measured admission/soak) — **not claimed** by this change; recorded in
     `docs/production-drill-evidence-*.md` as follow-ups.
  4. No Grok review was used.
- Verdict: pointer accurate; implementation conforms to ADR selection;
  open items explicitly carried forward, not waived.

## Verification (live proof, sanitized)

- `git log --oneline origin/main -- docs/architecture/ADR-0001-observability-storage-thin-layer.md`
  in aws-infra shows `589fb1c` present on `origin/main` (checked 2026-10-26).
- `git diff --check` clean for this repo's pointer + config changes.
- No secrets in repo (`grep -ri password|secret` shows only placeholders + docs references).
