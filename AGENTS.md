# Agent entry point

GradleMCP is an asynchronous remote Gradle executor. Read `docs/AI_GUIDE.md`.
Discover policy with `get_capabilities` or `GET /api/v1/capabilities`.
Upload ZIP → inspect → check compatibility → submit once with idempotency key →
poll queued/preparing/running → inspect diagnostic/logs → retrieve artifacts.
Use bearer credentials, never place secrets in source. A queued job is not failed.
Cancellation is confirmed only at `cancelled`. Never blindly retry publication.
The `gradlemcp mcp` stdio adapter needs a running `gradlemcp serve` sharing storage.
Repository development: `uv sync --locked`; `make lint typecheck test`.
Do not replace isolation with host subprocess execution to make a test pass.
