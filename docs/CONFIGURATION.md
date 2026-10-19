# Configuration reference

Precedence (highest wins): CLI `serve --host/--port` → `GRADLEMCP_<FIELD>` environment
→ JSON at `$GRADLEMCP_CONFIG` (default `./gradlemcp.json`) → typed defaults.
`config/gradlemcp.example.json` is a non-secret complete example; `gradlemcp init` exports every default; `gradlemcp config validate` validates without
printing secrets. Settings are declared in `src/gradlemcp/config.py`. Unknown JSON
fields are rejected. JSON arrays/objects/booleans/numbers in environment variables
use JSON syntax; ordinary string values can be plain text.

Example JSON (merge into generated config):
```json
{"data_dir":"/var/lib/gradlemcp/data",
 "database_url":"sqlite:////var/lib/gradlemcp/data/gradlemcp.db",
 "host":"0.0.0.0","port":8000,"max_workers":2,"memory_mb":3072,
 "total_memory_mb":6144,"cpus":1,"per_client_active":1,
 "toolchains":{"java17":{"image":"gradlemcp-worker:17","java":17,"gradle":"8.14.3"},
               "java21":{"image":"gradlemcp-worker:21","java":21,"gradle":"8.14.3"}}}
```

| Field(s) | Meaning / default |
|---|---|
| `data_dir`, `database_url` | Durable private storage, SQLite `./data/gradlemcp.db`; alternatively `postgresql+psycopg://...` |
| `host`, `port` | Default `0.0.0.0:8000`, so the VPS address is reachable (set `host` to `127.0.0.1` for a loopback-only listener); the Docker controller also binds `0.0.0.0` inside its container, and Compose publishes `0.0.0.0:8000` on the host by default |
| `max_workers`, `max_queue` | 1 active slot, 32 globally queued |
| `per_client_active`, `per_client_queued` | 1, 8; retained upload quota is 4 × queued quota |
| `memory_mb`, `total_memory_mb` | 2048 each; reservation validation enforces product of worker count and memory |
| `cpus`, `pids` | 1 CPU quota, 256 process/thread limit |
| `timeout_seconds` | 1800, Gradle execution; setup/export have separate deadlines |
| `upload_mb`, `workspace_mb` | 16 compressed, 512 worker tmpfs; source expands to at most workspace/2 |
| `artifact_mb`, `log_mb`, `max_files` | 64 exported, 8 log, 10000 source/output entries |
| `retention_hours`, `storage_reserve_mb` | 168, 1024 free disk reserve |
| `requests_per_minute` | 120 per authenticated client, process-local sliding window |
| `network` | `none` or operator-created egress-filtered network; host/default/bridge/container namespace reuse rejected |
| `toolchains` | Operator-approved profile map: image, java, gradle, android=false, native=false |
| `auto_pull` | false; true requires every image be pinned as `registry/image@sha256:<64 hex>` |
| `wrapper_enabled`, `wrapper_hosts` | false; HTTPS hosts services.gradle.org/downloads.gradle.org |
| `public_url`, `exposure` | null, private; `public_url` must be the exact HTTPS origin; modes private/direct/proxy/cloudflare/ngrok/custom |
| `mcp_allowed_hosts` | Empty; exact hostname/IP entries with optional port (`example.org:*`), used by MCP Host validation for a direct/custom endpoint |
| `mcp_allowed_origins` | Empty; exact HTTP(S) origins (optionally wildcard port, such as `http://192.0.2.4:*`) for direct/private MCP browser clients; public HTTPS uses `public_url` |
| `ui_enabled` | true; serves the operator dashboard at `/ui/` (static token-gated shell, no data without a credential); set false or use `./gmc ui off` to remove the route |
| `tunnel_status_url` | null; operator-owned local ngrok tunnel API, e.g. `http://ngrok:4040/api/tunnels` |
| `publish_tasks`, `publish_toolchain`, `publish_secrets_file` | Empty/null; allowlisted tasks, dedicated profile, protected Docker env-file |
| `log_level` | INFO; DEBUG/INFO/WARNING/ERROR |

Compose installs write optional container overrides to `.gradlemcp.env` (0600),
which is gitignored; Compose's `.env` selects only the host port binding. Installs set
`GRADLEMCP_BIND_ADDRESS=0.0.0.0` so `<VPS-IP>:8000` answers; restrict access with the
OS/provider firewall, or set `GRADLEMCP_BIND_ADDRESS=127.0.0.1` (`./gmc expose off`) for
a loopback-only controller. `./gmc expose https DOMAIN` configures Caddy, `public_url`
and MCP Host validation; `./gmc expose direct HOST` keeps the all-interface binding while
recording the public host for MCP Host validation. Host and provider firewall rules
remain operator-owned, and plain-HTTP exposure should stay on trusted networks/VPNs.

Credentials reside as SHA-256 digests of random tokens in SQL. They are managed by
CLI, not plaintext config fields. `credentials rotate NAME` preserves identity while
invalidating the previous token; optional `--scopes read,build,publish` changes grants
at the same time. A new client name has separate ownership and quotas. Secret filenames are references; keep their content
out of JSON and version control. Database URL may contain credentials: use a protected
config/environment and never print it in diagnostics. Scope admin is a trusted controller
operator. Worker profiles/SDK installations are administrator inputs, not client URLs.

The queue backend is the configured database; there is no unused Redis option. MCP
transport is chosen by command (`serve` includes HTTP, `mcp` is stdio). Artifact/log
storage is the data directory, deliberately not a collection of unimplemented cloud
storage toggles. Provisioning uses approved images, not arbitrary JDK download URLs.
Metrics are always available behind admin auth. Repository publication credentials
use the publication env-file, not a general-purpose secret upload endpoint.

Example environment override:
```sh
export GRADLEMCP_TOOLCHAINS='{"java17":{"image":"gradlemcp-worker:17","java":17,"gradle":"8.14.3"}}'
export GRADLEMCP_CONFIG=/etc/gradlemcp/config.json
```
