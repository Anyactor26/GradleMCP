# Troubleshooting

| Symptom / code | Action |
|---|---|
| 401 unauthorized | Check Bearer header; create a new client if revoked; never paste tokens into issues. |
| 403 forbidden | Check scopes; publish permission and admin are intentionally separate. |
| 404 known job/artifact | Ownership may differ, or source/artifacts expired; use original client. |
| 421 MCP Invalid Host | Set public_url to the actual HTTPS origin and restart; keep SDK DNS-rebinding checks enabled. |
| 422 invalid_request | Inspect OpenAPI; tasks are names, not shell commands/options; no unknown fields. |
| 429 queue/rate limit | Back off and inspect queue; don't generate many replacement jobs. |
| queued | Not a failure. A worker slot or client-active quota is busy; no ETA is guaranteed. |
| preparing | Image pull/source staging; can be slower than ordinary execution. |
| toolchain_unavailable | Supply approved image for required Java/SDK/native toolchain; explicit java can correct heuristic hints. |
| unsafe_wrapper | Check all wrapper files, HTTPS host/path and distributionSha256Sum; or use managed Gradle. |
| unsafe_worker_image | Do not inherit image VOLUME declarations. Use deploy/worker.Dockerfile's multi-stage copy. |
| dependency_resolution | Default network is none; bake dependencies or provision a filtered repository proxy/network. |
| repository_auth | Configure narrowly scoped publication credentials; private general dependency auth is not automatic. |
| android_sdk_missing | Install matching SDK/license/build tools into approved image and declare android=true. |
| out_of_memory / resource_limit_exceeded | Check cgroup events; tmpfs counts against RAM. Reduce concurrency/parallelism or increase reserved worker memory. |
| disk_full / output_limit / artifact_limit | Workspace or export budget exceeded; narrow artifact patterns, clean outputs or increase capacity safely. |
| tests_failed / compilation_failed | Read compiler/test logs and exported reports, fix source, upload a new project. |
| server_interrupted | Worker removed during recovery; queued jobs remain. Do not replay publication blindly. |
| termination_unconfirmed | Docker contact/cleanup could not be confirmed. Restore daemon, inspect named worker, restart service; slot intentionally retained. |
| /ready returns 503 | Run doctor; check Docker permissions/daemon and free disk. No host execution fallback. |
| CLI cannot access database | Use same configuration and absolute paths/permissions as service account. |
| stdio MCP submits but never starts | Ensure a separate serve scheduler is running against the same storage/database. |
| tunnel not_probed | Truthful unknown status, not evidence of connectivity; inspect provider supervisor/dashboard. |

Logs stop growing at log_mb; eof is current end and not terminal state. Offset is a
byte offset. Publication output is deliberately suppressed. API input errors omit
submitted values to avoid reflecting credentials. Report sanitized diagnostic code,
job state and non-sensitive toolchain/version information; never attach production
ZIPs, full credentials, environment dumps, signing keys or auth headers to an issue.
