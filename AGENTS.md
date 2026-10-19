# Agent entry point

GradleMCP is an asynchronous remote Gradle executor. Read `docs/AI_GUIDE.md`.
Discover policy with MCP `get_capabilities` or REST `GET /api/v1/capabilities`.
Remote MCP uses Streamable HTTP at `/mcp/` (trailing slash), not legacy SSE; REST
uses `/api/v1`. Send `Authorization: Bearer <token>` on every request.
Upload ZIP → inspect → check compatibility → submit once with an idempotency key →
poll queued/preparing/running → inspect diagnostic/logs → retrieve artifacts.
Use bearer credentials, never place secrets in source. A queued job is not failed.
Cancellation is confirmed only at `cancelled`. Never blindly retry publication.
The `gradlemcp mcp` stdio adapter needs a running `gradlemcp serve` sharing storage.
The Docker install needs no host Python and is managed with `./gmc start|stop|status`;
its optional dashboard is enabled with `./gmc ui on`. Repository development:
`uv sync --locked`; `make lint typecheck test`.
Do not replace isolation with host subprocess execution to make a test pass.
