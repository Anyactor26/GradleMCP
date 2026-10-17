# Queue and resource management

Admission returns 202 and persists the entire execution request/source reference.
Global and per-client queued quotas are checked in the same serialized transaction
as insertion and idempotency. FIFO `(created,id)` ordering applies to eligible jobs;
a client at its active quota is skipped so other clients can progress. An older
blocked job becomes eligible when its client's slot is released. There are no
priority classes. Slots, not momentary free RAM, control admission to workers.

Transitions:
- queued → preparing (atomic claim), or cancelled (before dispatch).
- preparing → running; preparing/running → cancelling on a cancellation request.
- preparing/running → succeeded/failed/timed_out/resource_limit_exceeded after cleanup.
- cancelling → cancelled only after termination confirmation.
- active on restart → failed/server_interrupted after removal, never automatic retry.
- termination cannot be confirmed → cancelling with termination_unconfirmed; slot retained.

Global queue position is informative: per-client fairness can move eligible jobs
past blocked jobs. No estimated completion/wait time is invented (`null`). Queue
counts, free slots and free disk are authenticated; Prometheus gauges require admin.

Defaults: 1 worker, 2 GiB memory, 1 CPU, 256 PIDs, 30-minute Gradle execution timeout,
512 MiB tmpfs workspace plus 64 MiB `/tmp`, 16 MiB ZIP, 64 MiB exported artifacts,
8 MiB stored log, 32 queued jobs, 8 queued/1 active per client, 7-day retention.
Expanded source is restricted to half the workspace. Logs are drained after their
storage cap to prevent deadlocks. tmpfs is charged against container memory;
Gradle heap + JDK/native memory + workspace must all fit. No swap is permitted.

A 12-GB/2-vCPU operator could configure 2 workers with 3 GiB each, 1 CPU each and
`total_memory_mb=6144`. Set `per_client_active=2` only if desired; otherwise two clients
can use both slots. Leave RAM for OS, Docker, API, filesystem caches and database.
Detected hardware/free disk is advisory, never the concurrency gate. Total reservation
must cover max_workers × memory_mb. CPU budget is max_workers × cpus; choose it manually.

The Docker cgroup enforces worker memory/CPU/PIDs. tmpfs provides an actual worker disk
bound, not polling estimates; large projects may need bigger limits or an independently
quota-enforced custom design. Root filesystem is read-only. Logical artifact stream
size/file count checks additionally block sparse-file export exhaustion. Parent log
and artifact budgets are bounded per job. Free-space reserve prevents dispatch/upload
under disk pressure. Retention sweeps at most once a minute delete terminal job data
and expired unused source; small job metadata/idempotency records remain in SQL.
Plan database retention/archival for high-volume services. Back the data directory
with an operator-enforced volume quota for a hard **total host disk** limit; the
free-space reserve alone is not a host security boundary. Docker image disk usage is
operator-controlled. Do not prune images in use by running workers.

Timeout covers Gradle execution. Image pulls and fixed setup/export operations have
separate bounded deadlines (pull: configured build timeout; copy/export up to 120s).
Thus end-to-end job duration may exceed timeout_seconds during preparation/cleanup.
