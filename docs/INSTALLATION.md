# Installation

## One-command Docker installation

Install Git, Docker Engine and Docker Compose v2 using your OS/provider's supported
packages first. Your account must be able to use Docker; do not make its socket
world-writable. Then run:

```sh
git clone --branch arena/6626d3dc-gradlemcp https://github.com/Anyactor26/GradleMCP.git && cd GradleMCP && ./install.sh
```

Or `./install.sh` from an existing checkout. The explicit branch selects the current
implementation before it is merged to main. This is one installation command, not
an assertion that every OS already includes Docker. There is deliberately no opaque
remote root script or automatic modification of system package repositories.
The local script is auditable and can be reviewed before execution.

The installer checks daemon/Compose compatibility, builds both images, copies the
complete example config only if none exists, reserves private storage, creates an
`installer-agent` credential with read/build scope if the token file is missing,
starts Compose with a health deadline, and checks readiness/authenticated access.
Token output goes directly to `data/bootstrap-token.local` with mode 0600, never to
logs or process argv. No host Python/Java/Gradle/uv is required.

Re-running is supported: existing config/data/token are preserved, image builds use
Docker's cache, and Compose reconciles the service. It is an install/reconcile command,
not a source auto-updater (`git pull` is an explicit operator decision). Dependencies
and base images need registry/PyPI access during build; default builds remain offline.
`./install.sh --check` only checks prerequisites. Configuration/storage and secret
paths must not be symlinks. Concurrent installers are blocked by a local directory lock.

If setup fails, it exits nonzero, cleans temporary credential/config files and releases
its lock; it never announces success or silently rotates a pre-existing credential.
A started service may remain running for inspection: `docker compose logs gradlemcp`.
If a previous process was killed without cleanup, first confirm it stopped, then remove
`.gradlemcp-install.lock`. If the token is lost/revoked or the DB was replaced, restore
a consistent backup or explicitly manage credentials with the container CLI. An existing
client name without its matching token is not automatically taken over by the installer.
Use `docker compose run --rm gradlemcp credentials rotate installer-agent` deliberately,
redirecting the new token to a private temporary file and replacing the token file safely.
An operator-customized config may also require corresponding Compose mounts; the
installer does not rewrite custom deployment paths or configure public HTTPS.

Default endpoints are localhost:8000 (REST) and localhost:8000/mcp/ (MCP). Use the token
from its private file; configure public HTTPS separately. Stop with
`docker compose stop gradlemcp`; start again with `docker compose up -d gradlemcp`.
Docker controller-created database files may be root-owned on the host; use the
container CLI for maintenance rather than mixing native and container installations.


## Supported controller

Linux, Python 3.11+, Docker Engine with working cgroups/tmpfs, `uv` 0.13.1. An operator
with Docker access is root-equivalent. Never expose the Docker API publicly. Docker
Desktop can provide a Linux worker VM, but native non-Linux controller startup uses
unsupported file-lock semantics and has not been tested. Rootless Docker is desirable
where its memory/CPU/PID enforcement is verified; do not assume every rootless setup
enforces cgroups. Supply x86_64/aarch64 images matching your host architecture.

1. Install Python, Docker and uv from their documented package/release sources. No
   root curl-pipe-shell installer is provided by GradleMCP.
2. Clone the repository, `uv sync --locked`; `uv run gradlemcp init` creates a local
   config and database. Pin the source tag/commit in production.
3. `docker build -f deploy/worker.Dockerfile -t gradlemcp-worker:17 .`. Review/pin the
   base image digest for reproducible production images; tag defaults are convenient,
   not immutable registry inputs. Build alternative SDK/JDK images as required.
4. `uv run gradlemcp credentials create agent --scopes read,build`. Save the one-time
   token in a secret manager. Scope `admin` is separate, not the default. Use `credentials rotate agent` for atomic token replacement without changing
   job ownership. The old token stops working immediately; coordinate the client update.
   A new client name is a separate identity, not a rotation of existing job ownership.
5. `uv run gradlemcp config validate`; `uv run gradlemcp doctor` checks storage and
   Docker reachability (not whether cgroups or actual builds work). Validate cgroup
   behavior with the supplied Docker integration/security tests and host monitoring.
6. `uv run gradlemcp serve`; check `GET /health` and `GET /ready`. Missing Docker
   means readiness is 503; there is deliberately no unrestricted host fallback.
7. Send authenticated capabilities/ZIP/build requests using examples or MCP.
8. Configure an HTTPS endpoint, firewall and egress policy before public exposure.

## Linux system service

Install the project in `/opt/gradlemcp` with a `.venv` (`uv sync --locked --no-dev`).
Create a dedicated `gradlemcp` OS account, `/var/lib/gradlemcp` owned by it, and an
operator-owned `/etc/gradlemcp/config.json` readable only by that account. Use absolute
`data_dir` and `database_url` paths. Add the account to the Docker group only after
understanding it grants host administration. Review/copy `deploy/gradlemcp.service`
to `/etc/systemd/system/`, then:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now gradlemcp
sudo journalctl -u gradlemcp -f
```

Run the credential CLI as the same account with the same `GRADLEMCP_CONFIG`.
Do not run `uv` dependency resolution on every service start. Keep controller,
worker image and configuration revisions in your operations inventory.

## Container controller

See the README and `compose.yaml`. Initialize the JSON config first; otherwise a
missing bind-mounted file can become a directory. The data directory is durable.
Do not mount the entire host into workers. Only the trusted controller receives
the Docker socket. Compose starts/stops only the services you request; workers are
created dynamically and named `gradlemcp-<job UUID>`.

## Upgrade and backup

Stop submissions and service, confirm no workers remain, back up source config,
secret files and data directory consistently. For SQLite use the SQLite backup API
or copy the database only while stopped (WAL sidecars matter). Use `pg_dump` for
PostgreSQL. Install the locked new release, read its schema/migration notes, then
start and run a small real build. Roll back code **and the database** together if
schema changed. This initial release creates its schema; it does not ship a generic
automatic schema migration engine. Never delete durable data to hide an upgrade error.
