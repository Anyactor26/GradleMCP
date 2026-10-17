# Deployment and public endpoints

Keep the service private by default. Public reachability is an operator responsibility:
opening a port or reporting a URL does not prove a firewall/NAT/tunnel route works.
Authentication applies to REST, MCP, metrics and docs regardless of exposure mode.
Use one scheduler/one Uvicorn worker; do not horizontally scale this release.

## A. Private network or VPS IP

`host` and `port` are configurable. Default localhost is appropriate behind a proxy.
To serve an internal network, bind the intended interface and restrict ingress to
agent hosts/VPN. Set `GRADLEMCP_URL` in clients. For a direct VPS public IP, terminate
TLS at an HTTPS proxy capable of issuing a certificate for your configured identity
(or use a DNS name). Open only required inbound ports, usually 443 and 80 for ACME;
keep 8000 and the Docker socket private. Do not transmit real bearer tokens over
public plaintext HTTP. IPv6 firewall rules must match IPv4 policy.

Set `public_url=https://builds.example.org` and `exposure=direct`/`proxy` as appropriate.
Do not add trailing paths/slashes to the public base URL. GradleMCP never attempts to
infer your public IP or punch through NAT automatically.

## B. Reverse proxy

`deploy/Caddyfile` is a working template: replace the DNS name, point DNS at the server,
install/start Caddy, and permit ACME validation. Caddy handles certificate issuance
and renewal; monitor its renewal failures. Keep Uvicorn on 127.0.0.1:8000, or a
private Compose network. `public_url` must match the client-facing HTTPS origin.
Preserve Authorization and Host. MCP is `/mcp/`, not the deprecated SSE transport.

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
