# Vector configs

| Host | Path | Sink |
|------|------|------|
| contabo-a `.163` | `contabo-a/vector.yaml` | OpenObserve on localhost / compose net |
| contabo-b `.141` | `contabo-b/vector.yaml` | OpenObserve at `http://10.100.0.1:5080` (WireGuard) |

Validate: `vector validate --config-dir .` (or container entrypoint).
