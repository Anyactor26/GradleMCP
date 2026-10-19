# Installation

## One-command installation (including Docker prerequisites)

From a downloaded/cloned checkout, run:

```sh
./install.sh
```

Or clone the repository's default branch and install in a single command:

```sh
git clone https://github.com/Anyactor26/GradleMCP.git && cd GradleMCP && ./install.sh
```

For a VPS without Git, the README provides a single command that first installs Git
and CA certificates from the configured OS repositories. Git is only needed to fetch
source; a downloaded checkout can run the installer directly. **Docker, Python, Java,
Gradle and uv do not need manual installation for this path.**

### Automatic platform support and privileges

| Platform | Automatic missing Docker/Compose setup |
|---|---|
| Debian 12 (bookworm), 13 (trixie), amd64/arm64 | Supported, running systemd required |
| Ubuntu 22.04 (jammy), 24.04 (noble), amd64/arm64 | Supported, running systemd required |
| Existing compatible running Docker/Compose | Reused without package changes |
| Other distributions/architectures, non-systemd containers/chroots | No automatic package setup; actionable manual guidance |

Run as an administrator, or as a user who can authorize `sudo`; an OS password prompt
is normal. The script escalates individual trusted operations, not a downloaded shell
script. If the daemon needs privileged access, installation continues with `sudo docker`
and reports that management prefix; **no group change or re-login is required**.
`--check` never requests sudo and changes nothing. `--no-system-changes` prohibits
package/repository/daemon changes, though accessing an existing daemon may use sudo.

### Exactly what changes on a clean supported host

1. Check systemd, distribution/architecture and conflicting runtime packages before
   installing anything. Existing docker.io, containerd, runc, Snap/Podman integrations
   are not silently removed or migrated. A compatible existing Docker skips bootstrap.
2. Install CA certificates, curl and GnuPG using configured signed OS repositories.
3. Fetch Docker's public APT key via HTTPS, verify primary fingerprint
   `9DC858229FC7DD38854AE2D88D81803C0EBFCD88`, and enable its stable signed repository.
   A mismatch fails closed; review legitimate upstream key rotation before updating.
4. Write `/etc/apt/keyrings/gradlemcp-docker.asc` and
   `/etc/apt/sources.list.d/gradlemcp-docker.sources`. Existing administrator-managed
   `docker.sources`/`docker.list` are reused, not rewritten. Customized managed files
   and symlinked destinations are refused. No `apt-key` or unauthenticated packages.
5. Install docker-ce, docker-ce-cli, containerd.io, Buildx and Compose plugins; enable
   and start Docker with systemd. For a compatible but stopped existing engine, only
   startup is requested. No Docker-group grant/socket chmod is performed.
6. Build the Python controller/Java 17 worker containers, initialize private
   config/storage and `.gradlemcp.env` only if absent, create an installer-agent
   read/build credential, start Compose and verify readiness plus authenticated API access.

The controller copies a modern standalone Docker CLI from docker:28-cli rather than
Debian's older docker.io package; the controller never runs its own daemon. Pin base
image digests according to your production provenance policy.

All scripts are local and auditable. No `curl | sudo sh`, automatic production
publication, public firewall opening or TLS/tunnel account configuration occurs.
APT/registry/PyPI access is necessary during installation. Package-manager locks have
a bounded wait. Bootstrap may leave installed prerequisite packages or valid repository
files if a later operation fails; it does not promise transactional rollback of OS changes.

### State, recovery and management

The token is saved to `data/bootstrap-token.local` with mode 0600, never logged or
passed in argv. Reruns preserve config/data/token and use image caches; source updates
remain an explicit `git pull`. A local lock prevents concurrent installers. Config,
data and token symlinks are refused. No silent credential rotation is performed.

A failed install exits nonzero, releases its lock and cleans temporary app credential/
config files. Inspect `docker compose logs gradlemcp` (or `sudo docker compose ...`)
and `journalctl -u docker`. A started service may remain available for inspection.
A lock left by SIGKILL must only be removed after confirming no installer is running.
If the token is lost/revoked or the DB replaced, restore a consistent backup or use
the container CLI to explicitly rotate installer-agent; protect the new token output.
Operator-customized config/storage paths may need corresponding Compose mounts.

The controller's Python, Java worker runtime and Gradle toolchain live in containers;
no host Python/Java/Gradle/uv install is needed for this path. Port 8000 is published on
all interfaces by default, so endpoints are `http://<VPS-IP>:8000`, `/api/v1` (REST), and
`/mcp/` (authenticated Streamable HTTP); allow TCP 8000 in the OS and provider firewalls
(or use `./gmc expose off` to keep it loopback-only). Use
`./gmc start|stop|restart|status|logs|doctor|token` rather than remembering Compose
flags. Stop requests a graceful controller shutdown; durable data and credentials remain.

For a public deployment with a DNS name, `./gmc expose https builds.example.org`
configures the optional Caddy TLS proxy. Point DNS to the VPS and allow inbound TCP
80/443 in both the OS and provider firewall. Use plain HTTP on 8000 only for trusted
private/VPN access or testing: it must not carry real tokens across the public Internet. The application cannot open a cloud-provider
security group or prove external reachability. Run `./gmc doctor` for local status and
check remote firewall/NAT/DNS from a separate network.

Optional web dashboard: `./gmc ui on` serves `/ui/`; `./gmc ui off` disables it. The
page requires an API token, stores it only in page memory, and supports queue/build
monitoring, manual ZIP compilation, logs, cancellation, diagnostics and artifacts.
Container-created database files may be root owned; use the container CLI rather than
mixing native and container maintenance.

**Verification boundary:** automatic package setup is exercised against controlled
OS-tool/filesystem fixtures, including invalid keys, unsupported hosts, conflicts,
failed downloads, sudo denial and daemon startup. A fresh-VM Docker installation was
not possible in this sandbox. Existing Docker integration runs in the active workflow;
do not equate mocked package tests with a verified installation on every VPS image.

## Native/manual controller alternative

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

See the README and `compose.yaml`. Initialize `gradlemcp.json` and copy
`config/gradlemcp.env.example` to `.gradlemcp.env` (mode 0600) before starting Compose;
a missing bind-mounted config or environment file causes startup errors. The data
directory is durable. Do not mount the entire host into workers. Only the trusted
controller receives the Docker socket. Use `./gmc` for stop/start and optional UI/HTTPS
configuration; workers are created dynamically and named `gradlemcp-<job UUID>`.

## Upgrade and backup

Stop submissions and service, confirm no workers remain, back up source config,
secret files and data directory consistently. For SQLite use the SQLite backup API
or copy the database only while stopped (WAL sidecars matter). Use `pg_dump` for
PostgreSQL. Install the locked new release, read its schema/migration notes, then
start and run a small real build. Roll back code **and the database** together if
schema changed. This initial release creates its schema; it does not ship a generic
automatic schema migration engine. Never delete durable data to hide an upgrade error.
