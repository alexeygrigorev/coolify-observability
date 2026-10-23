# GitHub Actions CI is enabled

The active workflow is [`.github/workflows/ci.yml`](../.github/workflows/ci.yml).
It runs pytest business-metrics checks and the full Docker A1–A8 matrix on main.
The old workflow-scope blocker is resolved; no activation step is needed.

`ci.yml.workflow-pending` is a historical scaffold. Do not copy it over the active
workflow: it predates the isolated Compose lifecycle and generated TLS fixtures.
