# MCP integration

Uses maintained Python `mcp` SDK 2.x (`MCPServer`), locked in `uv.lock`.
The tools are registered from `mcp_adapter.py`; the SDK owns framing, discovery,
input validation, error serialization and Streamable HTTP transport. No custom MCP
wire protocol is implemented. HTTP transport is stateless, request-authenticated.

## Local stdio

Run `gradlemcp serve` separately with the same configuration/database/storage.
The stdio adapter is an authenticated client of the same application services, not
another scheduler. Example client configuration (adapt environment substitution to
your client's actual behavior):

```json
{"mcpServers":{"gradlemcp":{"command":"/absolute/path/to/.venv/bin/gradlemcp",
 "args":["mcp"],"env":{"GRADLEMCP_CONFIG":"/etc/gradlemcp/config.json",
 "GRADLEMCP_TOKEN":"INJECT_FROM_CLIENT_SECRET_STORE"}}}}
```

Do not commit the filled configuration. Relative data and SQLite paths resolve
against process working directory: use absolute deployment paths for stdio clients.
Do not let unrelated tenants run local adapters; local filesystem/DB access is trusted.

## Remote Streamable HTTP

URL: `https://builds.example.org/mcp/` (trailing slash). Configure matching `public_url`
so the SDK Host/Origin defenses allow the public host. Send a manual bearer API token
on **every** request. Origins other than the configured public URL are rejected.
TLS termination belongs at the reverse proxy/tunnel. Tools apply the same scopes,
ownership checks, quota and scheduler as REST, including credential revocation.

Example conceptual client configuration:
```json
{"mcpServers":{"gradlemcp":{"type":"http","url":"https://builds.example.org/mcp/",
 "headers":{"Authorization":"Bearer INJECT_FROM_SECRET_STORE"}}}}
```
Client configuration formats and secret interpolation differ. This is not a claim
that every editor accepts this JSON. Clients that require interactive OAuth discovery
without manual headers are **not supported** by this release: no OAuth authorization
server, dynamic registration, token exchange or OAuth discovery is advertised.
Use a client that supports configured bearer headers or local stdio. Do not pretend
an API key implements the full MCP OAuth authorization specification.

Tested here: SDK-backed Streamable HTTP tool discovery, initialization (protocol
2025-11-25), upload, queue submission, status, schema errors, authorization, revocation
through Starlette TestClient. The official SDK ClientSession also tested the real
stdio subprocess: initialization, discovery, upload, submission and status. No named
third-party editor or external desktop configuration was tested.

Tools and workflow: [AI guide](AI_GUIDE.md). Downloads return authorized HTTP paths,
not base64 multi-gigabyte blobs. Errors are MCP tool errors containing structured
service error JSON. `list_gradle_tasks` queues real isolated configuration execution.
