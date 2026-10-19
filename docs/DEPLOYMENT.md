# Deployment and public endpoints

Keep the service private by default. Public reachability is an operator responsibility:
opening a port or reporting a URL does not prove a firewall/NAT/tunnel route works.
Authentication applies to REST, MCP, metrics and docs regardless of exposure mode.
Use one scheduler/one Uvicorn worker; do not horizontally scale this release.

## A. Private network or VPS IP

Compose publishes the controller as `0.0.0.0:8000:8000` by default, and a native
`gradlemcp serve` also binds `0.0.0.0:8000`, so `http://<VPS-IP>:8000` answers once TCP
8000 is allowed in both the OS firewall and the VPS/cloud security group. Set `host` to
`127.0.0.1` (or `GRADLEMCP_BIND_ADDRESS=127.0.0.1` for Compose) for a loopback-only
listener.
This is plain HTTP and the API is bearer-authenticated, so treat direct exposure as trusted
network/VPN only; do not transmit real bearer tokens, source ZIPs or build output over
public plaintext HTTP. To make the controller loopback-only, run `./gmc expose off`
(or set `GRADLEMCP_BIND_ADDRESS=127.0.0.1`). `./gmc expose direct <VPS-IP>` records the
public host for MCP Host validation while keeping the all-interface binding.

For a public endpoint, terminate TLS at a reverse proxy. The one-command Caddy setup is
`./gmc expose https builds.example.org` (see section B). Point DNS at the server and
allow inbound ports 80/443 in both the OS firewall and VPS/cloud security group. Set
`GRADLEMCP_URL` in REST clients to the HTTPS origin; MCP clients use the exact `/mcp/`
path. IPv6 firewall rules must match IPv4 policy. GradleMCP cannot edit provider-level
firewalls/NAT rules, and a configured endpoint is not proof of external reachability.

Set `public_url=https://builds.example.org` and `exposure=direct`/`proxy` as appropriate.
Do not add trailing paths/slashes to the public base URL. GradleMCP never attempts to
infer your public IP or punch through NAT automatically.

The root path `/` is a public, token-free landing page (HTML for browsers, JSON for
`curl` and agents) that confirms the controller is serving and lists the health, API,
MCP, OpenAPI and dashboard paths. Use it as the first reachability check after opening
the firewall. `./gmc doctor` prints the actual host-side Docker binding (for example
`0.0.0.0:8000` versus `127.0.0.1:8000`) and warns when a loopback-only publish makes the
VPS address unreachable; `./gmc endpoint` prints the REST, MCP, landing and dashboard
URLs derived from the current bind address, detected host IP or configured domain.

## B. Reverse proxy

### Automatic Caddy profile

`./gmc expose https builds.example.org` writes the protected endpoint configuration and
starts the optional Caddy Compose profile. Point the domain's A/AAAA record to the VPS
and allow inbound TCP 80/443 (optionally UDP 443) through the OS and provider firewalls.
Caddy obtains and renews TLS certificates automatically. GradleMCP's public controller
port remains bound to localhost; do not publish 8000 or the Docker socket to the Internet.

The command configures `public_url=https://builds.example.org` and the MCP Host allowlist.
Use `https://builds.example.org/api/v1` for REST and
`https://builds.example.org/mcp/` for remote Streamable HTTP MCP. `./gmc expose off`
returns the controller to localhost-only mode. Preserve Authorization and Host headers.
MCP is `/mcp/`, not the deprecated SSE transport. Review `deploy/Caddyfile` before use.
Monitor Caddy's logs and certificate renewal status.

### Manual proxy alternative

`deploy/Caddyfile` can also be used with external Caddy; provide `GRADLEMCP_DOMAIN`,
configure `public_url` to the exact HTTPS origin, and change its `reverse_proxy`
upstream from the Compose service name `gradlemcp:8000` to the controller's private
address (for example, `127.0.0.1:8000`). Ensure the proxy can reach the controller over
a private network. Never forward credentials via untrusted plain HTTP.

Configure production proxy connection/request limits, request-body limits (at least
~22 MiB for default base64 MCP uploads; binary ZIP is 16 MiB), body read deadlines,
unauthenticated rate limits and connection concurrency. The Python middleware is not
a protection against arbitrary numbers of slow incomplete connections. Do not log
Authorization, request bodies or URL secrets. Uvicorn does not trust forwarded
headers automatically; generated application download URLs are relative/configured,
not derived from untrusted X-Forwarded headers. There is no secure-cookie session.

## C. Cloudflare Tunnel (optional, operator-managed)

Create a named tunnel in Cloudflare, configure DNS/public hostname and upstream
`http://gradlemcp:8000` in its supported management UI/configuration. Store the tunnel
run token in `deploy/cloudflare-token.local` (gitignored, chmod 600), then:

```sh
docker compose --profile cloudflare up -d gradlemcp cloudflared
# Shut down explicitly with the same profile selection:
docker compose --profile cloudflare down
```

Set public_url and exposure=cloudflare in GradleMCP, then restart it. If adding
Cloudflare Access, configure your machine client to send both Access credentials
and GradleMCP bearer authorization; interactive browser-only gates can break MCP.
No token appears in endpoint reports. Cloudflared lifecycle/reconnect behavior is
managed by Compose/provider; GradleMCP reports **not_probed**, not fabricated connected.
Inspect provider logs/dashboard for actual connection health. This profile was not
run in the authoring environment; provider configuration/account must be verified.

## D. ngrok (optional, operator-managed)

Copy `deploy/ngrok.example.yml` to `deploy/ngrok.local.yml` (0600), configure the agent
authtoken and assigned domain according to your account capabilities. It is a provider
configuration template, not a claim all accounts include permanent domains.

```sh
docker compose --profile ngrok up -d gradlemcp ngrok
docker compose --profile ngrok down
```

Configure `exposure=ngrok`, your HTTPS public_url, and optionally
`tunnel_status_url=http://ngrok:4040/api/tunnels`. Keep that local management API
unpublished and inaccessible to workers. GradleMCP follows no redirects when querying
it and reports connected only if an HTTPS tunnel is returned. Failures/empty listings
report disconnected; assigned URL changes are reflected on the next report. `temporary`
is conservatively true; domain permanence is not inferred from the account.

You can instead run `ngrok http 8000` under your own service supervisor for temporary
URLs and point tunnel_status_url at the local agent API. When a domain changes, update
configured public_url and restart GradleMCP so MCP Host/Origin protection knows the
new allowed origin. Endpoint probing alone deliberately does not broaden Host trust.
No live ngrok account/tunnel was tested here. Compose manages startup/shutdown, not
a remote client-controlled subprocess endpoint.

## E. Custom provider

Run a tunnel under an operator-controlled system service/Compose profile, set
exposure=custom and public_url. Reports indicate not_probed. Extend endpoint.py with
a non-secret read-only status adapter if necessary; no remote arbitrary tunnel
commands/configuration are accepted.

## Operations

- Health/ready are public minimal booleans; detailed queue/storage metrics require auth.
- Scrape `/api/v1/metrics` with an admin token stored in your monitoring secret store.
- Reserve OS/database/daemon memory. Use volume quotas, log rotation, data backup and
  retention. `docker system prune` must not remove active workers/images.
- Monitor cancelling/termination_unconfirmed and restore Docker before restarting;
  never delete SQL state while its build container may still execute.
- Test a real build, intentional failure, queue wait, cancellation and artifact
  download after deployment. Verify egress policies against IPv4/IPv6 metadata,
  internal services, DNS rebinding and redirects before allowing untrusted clients.
