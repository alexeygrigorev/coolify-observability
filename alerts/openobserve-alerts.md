# OpenObserve alert pack (apply via UI/API after deploy)

Destination: email `dev@dtcdev.click`.

| Name | Type | Condition (sketch) | For |
|------|------|--------------------|-----|
| disk_pressure | metrics | `node_filesystem_avail_bytes / node_filesystem_size_bytes < 0.25` (or host_metrics gauge) | A2 |
| mem_pressure | metrics | available mem ratio < 0.10 | A3 |
| host_silence | metrics | no data 5m for host | A6 |
| postgres_down | metrics | `pg_up == 0` | A4 |
| container_restarts | metrics / logs | restart count spike | A5 |
| error_spike | logs | rate of level=error | A7/A1 |

Exact PromQL/SQL tuned during implement + Pass 2 cross-review.
