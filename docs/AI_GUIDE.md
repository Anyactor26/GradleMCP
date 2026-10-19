# AI-agent guide

## Discover, don't guess

GradleMCP executes Gradle tasks on a remote server, not on your agent's machine.
Retrieve capabilities first. JDK versions, SDKs, network permissions, limits and
publication policy are operator-dependent. Static inspection is advisory, not a
promise that plugins, target toolchains or dependency repositories will work.

REST uses `Authorization: Bearer $GRADLEMCP_TOKEN` on every `/api/v1/...` request.
Remote MCP is **Streamable HTTP** at `https://HOST/mcp/` (include the trailing slash)
and uses the same bearer header; it is not legacy SSE and does not implement OAuth
login/discovery. Native stdio reads `GRADLEMCP_TOKEN`. Never put a token in a URL or
project archive. Keep source secrets out of logs and outputs. Every build script is
executable code.

For a custom client, use the HTTPS origin as its base URL, REST path `/api/v1`, MCP
path `/mcp/`, and first call `GET /api/v1/capabilities` (or MCP `get_capabilities`).
The capabilities response documents these paths and transport. HTTP `202` means a job
was accepted, not that it compiled successfully. For the Docker install, the one-time
token is stored in `data/bootstrap-token.local`; `./gmc token` reveals it deliberately,
and `./gmc agent create NAME read,build` makes a separate client credential. Do not
send real credentials over public HTTP.

## Recommended workflow

1. `get_capabilities` / `GET /api/v1/capabilities` and `get_queue_status` / `GET /api/v1/queue`.
2. ZIP the project root (no symlinks, credentials, `.git`, caches or prior outputs).
   REST: `POST /api/v1/projects` with raw `application/zip`; MCP: `upload_project`
   with `archive_base64`. Save `project_id`. No arbitrary host paths or Git URL fetch.
3. `inspect_project(project_id)` / `POST /api/v1/projects/inspect` with
   `{"project_id":"...","subdirectory":"."}`. For nested archives choose the build's
   relative subdirectory. DSL, settings, included builds, catalogs and Java hints are detected.
4. `get_project_compatibility(request)` / `POST /api/v1/projects/compatibility`.
   Request matches submission below. If unavailable, ask the operator for an approved
   toolchain image; do not repeatedly resubmit an unavailable JDK/Android/native SDK.
5. `submit_build(request)` / `POST /api/v1/builds`:
   ```json
   {"project_id":"...","tasks":["build"],"idempotency_key":"source-sha-build-1",
    "subdirectory":".","use_wrapper":false,
    "artifact_patterns":["**/build/libs/*","**/build/reports/**"]}
   ```
   Optional `java` or `toolchain` selects an approved environment. Tasks are task
   names/paths, not shell commands or arbitrary Gradle CLI switches. Custom outputs
   are supported by explicit artifact patterns. HTTP 202 means **accepted, queued**.
6. `get_build_status(build_id)` / `GET /api/v1/builds/{id}` every 2–5 seconds with
   backoff; respect client rate limits. No push-subscription API is implemented.
   `queued` waits for capacity; `preparing` provisions/copies source; `running`
   executes Gradle; `cancelling` waits for termination confirmation.
7. Terminal states: `succeeded`, `failed`, `cancelled`, `timed_out`,
   `resource_limit_exceeded`. Only `succeeded` means exit code zero. Interrupted
   jobs become `failed` with `server_interrupted`; queued jobs survive restart.
8. On failure, read `diagnostic` and `get_build_logs(build_id, offset, limit)` /
   `GET /api/v1/builds/{id}/logs?offset=0&limit=65536`. Continue from `next_offset`.
   `eof` is the current end, not proof the build is finished. Logs are capped;
   see capability `log_mb`. Unsupported JDK/SDK, authentication, offline repositories,
   compile failures, test failures, OOM and disk pressure need different fixes.
9. Change source or request only when justified, upload a new immutable project and
   use a new idempotency key. Retry transient 429/503 with bounded exponential backoff.
   Never infinitely retry permanent errors or side effects.
10. `list_artifacts` / `GET .../artifacts`; `download_artifact` returns a relative
    HTTP URL, not inline binary. Download with bearer authorization and verify SHA-256.
    Any output type is supported, not only JARs. Artifacts expire with retention.
11. `cancel_build` / `POST .../cancel` works for your jobs. Keep polling until a
    terminal state. `termination_unconfirmed` requires operator action, not more work.
12. Delete unused source with `DELETE /api/v1/projects/{id}` when jobs are terminal.

## Task discovery

`list_gradle_tasks(project_id, toolchain)` queues `tasks` in the same sandbox. Read
its log once completed. It is asynchronous because Gradle configuration executes code.
For nested builds, submit a normal request with `tasks:["tasks"]` and `subdirectory`.

## Publication

Disabled by default. `publish_build(build_id, tasks, idempotency_key)` /
`POST /api/v1/builds/{id}/publish` requires a successful source build, `publish` scope,
an operator-approved task and a dedicated publication environment. It runs against
that immutable source, **not a previously generated artifact**; builds must be
reproducible or operators must implement a project-specific staging workflow.
Logs and artifact export are suppressed for secret-bearing jobs. Confirm destination
state before retrying an interrupted/failed publish. External accounts, scoped keys,
signing and repository verification remain necessary.

## MCP tool list

`get_capabilities`, `upload_project`, `inspect_project`, `get_project_compatibility`,
`submit_build`, `get_build_status`, `get_build_logs`, `cancel_build`, `list_artifacts`,
`download_artifact`, `list_gradle_tasks`, `publish_build`, `get_queue_status`.
See [MCP setup](MCP.md) and [API reference](API.md) for client-specific details.
