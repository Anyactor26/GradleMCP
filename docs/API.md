# HTTP API v1

Generated specification: [openapi.json](openapi.json). The live `/openapi.json` and
`/docs` also require a bearer credential. All `/api/v1` endpoints are authenticated.
`read` scope reads owned data; `build` uploads/submits/cancels/deletes; `publish` is
additional; `admin` grants all scopes and cross-client access. CLI credential
management is local-only, deliberately not an HTTP remote admin shell.

| Method | Path | Result / permission |
|---|---|---|
| GET | `/health` | Public minimal liveness |
| GET | `/ready` | Public minimal Docker/storage readiness, 503 when unavailable |
| GET | `/api/v1/capabilities` | Limits, profiles, states and policy / read |
| GET | `/api/v1/system/endpoint` | Configured URL, exposure/probe state, REST path and exact Streamable HTTP MCP path / read |
| GET | `/api/v1/system/toolchains`, `/api/v1/toolchains` | Approved profiles / read |
| POST | `/api/v1/projects` | Raw ZIP bytes → 201 `{project_id,inspection}` / build |
| POST | `/api/v1/projects/inspect` | `{project_id,subdirectory?}` → static inspection / read |
| POST | `/api/v1/projects/compatibility` | BuildRequest → profile selection or structured error / read |
| DELETE | `/api/v1/projects/{project_id}` | Delete unused source → `{deleted:true}` / build |
| POST | `/api/v1/builds` | BuildRequest → 202 Job / build |
| GET | `/api/v1/builds?offset=0&limit=50` | Owned Job array, max 100 / read |
| GET | `/api/v1/builds/{id}` | Job + queue position when queued / read |
| POST | `/api/v1/builds/{id}/cancel` | Updated Job; request != confirmed termination / build |
| GET | `/api/v1/builds/{id}/logs?offset=0&limit=65536` | `{text,next_offset,eof}`, bytes, max 64 KiB / read |
| GET | `/api/v1/builds/{id}/artifacts` | Array `{id,path,size,sha256}` bounded by file/export limit / read |
| GET | `/api/v1/builds/{id}/artifacts/{artifact_id}` | Streamed octet-stream attachment / read |
| POST | `/api/v1/builds/{id}/publish` | `{tasks:[...],idempotency_key:"..."}` → 202 publication Job / publish |
| GET | `/api/v1/queue` | Counts, client queued, available slots, free disk / read |
| GET | `/api/v1/metrics` | Prometheus text gauges / admin |

`GET /api/v1/capabilities` and `/api/v1/system/endpoint` also advertise protocol
paths: REST `/api/v1`, remote MCP Streamable HTTP `/mcp/` (trailing slash), with
`Authorization: Bearer <token>`. A configured URL is not proof of external reachability.
The operator UI at `/ui/` is enabled by default; disable it on a Docker install with
`./gmc ui off` (or `ui_enabled=false`). Its `/ui/` page does not bypass API
authentication.

BuildRequest:
```json
{"project_id":"opaque-project-id","tasks":["build"],"toolchain":"java17",
 "java":17,"subdirectory":".","use_wrapper":false,
 "artifact_patterns":["**/build/libs/*"],"idempotency_key":"unique-operation-id"}
```
Only `project_id` is required. Omitted/null `use_wrapper` prefers a valid wrapper
only when server policy enables it; false explicitly selects managed Gradle. Unknown fields and task switches are rejected.
Artifacts use case-sensitive shell-style patterns against relative POSIX paths;
`**/` prefixes also match the build root. `*` can match `/`; choose patterns narrowly.
Idempotency is per-client, persistent, and conflicts return 409. Repeated accepted
submissions with the same key and identical inputs return the existing Job, even if
it already failed. To retry intentionally use a new key.

Job shape:
```json
{"id":"...","owner":"agent","project":"...","state":"queued",
 "created":1790000000.0,"started":null,"finished":null,"exit_code":null,
 "diagnostic":{},"artifacts":[],"duration_seconds":null,"execution":{"project_id":"...","tasks":["build"],
 "toolchain":"java17","java":null,"subdirectory":".","use_wrapper":false,
 "artifact_patterns":["**/build/libs/*"],"idempotency_key":null,"publication":false}}
```
Times are Unix UTC seconds. `started` is dispatch/preparation time.
`duration_seconds` measures elapsed active job time including preparation/cleanup;
it is null before dispatch and fixed once completed. No fabricated ETA.
Queue counts are global but non-admin list/status/logs/artifacts never expose another
client's source or job details. Cross-client identifiers return 404.

Errors:
```json
{"error":{"code":"toolchain_unavailable","message":"No approved worker matches detected or requested requirements",
 "remediation":"Ask the operator to configure an approved JDK/SDK worker image, or explicitly select the correct Java version",
 "retryable":false,"permanent":true,"details":{"java":21,"available":["java17"]}}}
```
400 policy/source errors; 401 credentials; 403 scope; 404 missing/inaccessible;
409 busy/idempotency; 413 size; 422 schema; 429 quota/rate; 503 worker/storage.
Runtime failures appear in terminal Job diagnostics, not as HTTP submission failures.
Diagnostic `permanent` means retrying identical inputs is not advised, not that no
operator intervention can ever fix the environment.

Request bodies are bounded before routing; ZIP's tighter upload limit applies too.
API clients should poll rather than maintaining unbounded log streams. Use HTTPS for
all non-local traffic. No cookies, CORS wildcard, credentials in URLs, or shell APIs.
