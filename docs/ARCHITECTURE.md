# Architecture

```
REST /api/v1 ──┐
MCP adapter ──┴─ Service → SQLAlchemy SQLite/PostgreSQL
                         ↓ transactional admission/claim/cancel
                    single Scheduler → bounded thread pool
                         ↓
                    DockerWorker → per-job disposable container
                         ↓ bounded logs / streaming tar export
                    controlled artifact storage → authorized FileResponse
```

Modules: `config` validated policy; `db` models/transaction serialization and hashed
credentials; `source` ZIP handling/static inspection; `service` shared authorization,
project/build lifecycle; `scheduler` fairness/recovery/retention; `worker` isolation,
limits/termination/export; `diagnostics` failure classification; `endpoint` exposure
reporting; `mcp_adapter` SDK tools; `api` HTTP and transport middleware; `cli` operations.

SQLite uses WAL, BEGIN IMMEDIATE, a 10-second busy timeout and short transactions.
PostgreSQL uses transaction-scoped advisory locks for queue admission/claim/cancel.
No Redis is needed. Large outputs never enter SQL. A local scheduler `flock` prevents
two controllers on the same data directory; use **one controller/one Uvicorn worker**.
PostgreSQL support does not make this a distributed worker fleet: multi-host active
controllers and independently mounted data directories are not supported. PostgreSQL
TLS/backups are operator-managed. Automatic table creation supports fresh installs;
future incompatible schema releases require an explicit migration, not blind upgrade.

Queued source is immutable, referenced by project UUID; per-job task/toolchain/policy
choices are persisted. A crash leaves active jobs occupied until Docker cleanup is
confirmed on startup, then marks them failed with interruption diagnostics. They are
not replayed. Queued jobs resume normally. Graceful shutdown requests cancellation
and waits for whole-worker cleanup. A termination failure occupies its slot until
operator recovery; it is never falsely reported cancelled.

No host execution fallback exists. Docker creates a non-root, read-only-root worker,
then source is streamed into tmpfs and extracted as the non-root worker UID.
Image-declared Docker volumes are rejected to prevent unbounded anonymous storage. The Gradle process runs as UID 1000. Network is `none` unless an administrator
provides an externally restricted named network. Gradle tasks are argv values, never
shell commands. The container remains alive briefly after Gradle exits so outputs
can be streamed using trusted `tar`. Export never extracts worker-controlled paths;
links/special/sparse entries are skipped, counts/expanded sizes/exports are bounded.
The whole container is removed before the terminal state is committed.

Images contain approved JDK/Gradle installations; Docker caches those layers. Optional
auto-pull requires digest-pinned images and is the automatic approved provisioning
mechanism. No project-controlled JDK executables are downloaded by the controller.
Shared mutable cross-tenant Gradle caches are intentionally absent. Pre-warm images
or provide reviewed offline dependencies rather than sharing writable caches.

Endpoint reporting is an adapter boundary for operator-managed tunnels. ngrok can be
queried at an operator-configured status API; Cloudflare/custom report unknown state,
not a made-up connection. Add a provider in `endpoint.py`, never accept remote shell
commands to start arbitrary tunnels.
