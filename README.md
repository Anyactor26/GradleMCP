# GradleMCP

**A self-hosted remote Gradle build engine for AI agents.**
Developed by **Anyactor**. **All Rights Reserved (ARR)**; see [LICENSE](LICENSE).
This is not open-source software under the current license. Provider-independent. Submit immutable ZIP projects through REST or MCP; builds wait
in a persistent queue and run in disposable, resource-limited Docker containers.

## What is implemented

- MCP SDK 2.x: stdio and authenticated Streamable HTTP (`/mcp/`).
- FastAPI REST under `/api/v1`, generated [OpenAPI](docs/openapi.json).
- SQLite WAL / PostgreSQL transactional FIFO queue, per-client quotas, cancellation,
  timeouts, recovery without replaying interrupted publication.
- ZIP safety checks; non-executing project inspection; approved JDK/Gradle worker
  profiles; opt-in digest-pinned image provisioning; managed Gradle or validated wrapper.
- Bounded logs, diagnostic classification, streamed authorized artifacts, retention,
  bearer scopes, credential rotation/revocation, authenticated metrics.
- Docker CPU/memory/PID limits, read-only root, non-root builds, bounded tmpfs workspace,
  no worker socket mount, **no build network by default**.
- Optional same-origin dashboard for monitoring/manual builds, plus `./gmc` lifecycle,
  endpoint and HTTPS setup commands.

This is not universal Gradle compatibility or a hardened public hostile-code hosting
platform. Read the [security boundary](docs/SECURITY_MODEL.md) before enabling access.
Docker/JDK/Gradle execution and public tunnels could not be verified in the authoring
sandbox. Real Docker integration tests and GitHub Actions workflows are supplied; see [verification](docs/VERIFICATION.md).

## One-command installation — Docker is installed automatically

On **Debian 12/13 or Ubuntu 22.04/24.04**, amd64/arm64, with systemd and root/sudo
access, you do **not** need to install Docker, Python, Java, Gradle or uv yourself.
From an existing checkout, run **`./install.sh`**. Or clone the repository's default branch and install in one command:

```sh
git clone https://github.com/Anyactor26/GradleMCP.git && cd GradleMCP && ./install.sh
```

If Git is also missing on a fresh VPS, this single command installs Git from your
configured OS repositories first (no downloaded shell script is piped into root):

```sh
sh -c 'if ! command -v git >/dev/null 2>&1; then if [ "$(id -u)" = 0 ]; then apt-get update && apt-get install -y git ca-certificates; else sudo apt-get update && sudo apt-get install -y git ca-certificates; fi; fi && git clone https://github.com/Anyactor26/GradleMCP.git && cd GradleMCP && ./install.sh'
```

The installer automatically provisions Docker Engine/Compose on supported Debian/Ubuntu
hosts, builds the Python controller and Java 17 worker containers, initializes private
config/storage, creates a scoped API token, starts GradleMCP, and verifies readiness
**and authenticated API access**. Python, Java, Gradle and uv run in containers; the
recommended install does not require a host Python installation. Sudo may ask for your
OS password. No Docker-group change, re-login, or manual daemon start is needed.
Review `install.sh`, `scripts/install-docker.sh`, `gmc` and the Dockerfiles before
running with administrative access.

- REST API: `http://127.0.0.1:8000/api/v1`; MCP: `http://127.0.0.1:8000/mcp/` (Streamable HTTP).
- API token is generated automatically and saved to `data/bootstrap-token.local` (0600).
  Reveal it deliberately with `./gmc token`; it is never printed by installation.
- `./gmc start`, `stop`, `restart`, `status`, `logs`, `doctor` and `endpoint` manage the service.
- `./gmc agent create NAME read,build` creates a separate one-time token for an AI agent.
- `./gmc ui on` enables the optional dashboard at `/ui/`; `./gmc ui off` disables it.
- `./install.sh --check` is read-only; `--no-system-changes` requires existing Docker.
- Config, data and credentials survive stop/restart/reinstall; no silent token rotation.
- No world-writable sockets, automatic Docker-group grants, or downloaded root shell scripts.

**Why a VPS IP:8000 can appear unreachable:** the safe default publishes port 8000 on
localhost only. For a public domain with automatic HTTPS, run:

```sh
./gmc expose https builds.example.org
```

Point the domain at the VPS and allow inbound TCP 80/443 in both the VPS firewall and
cloud-provider security group. The MCP endpoint is then
`https://builds.example.org/mcp/`; REST is `https://builds.example.org/api/v1`.
For a trusted private/VPN test only, `./gmc expose direct <VPS-IP>` binds port 8000 on
all interfaces using plain HTTP. **Do not send real bearer tokens over public HTTP.**
GradleMCP cannot change provider-level firewalls or prove reachability from outside;
`./gmc doctor` reports local readiness and explains the remaining network checks.

```sh
export GRADLEMCP_TOKEN="$(./gmc token)"
./gmc logs -f
./gmc stop       # graceful shutdown; queued work and data are preserved
./gmc start
```

See [installation](docs/INSTALLATION.md) for supported platforms and recovery, and
[deployment](docs/DEPLOYMENT.md) for HTTPS, firewall, tunnel and endpoint details.
The installer is covered by controlled tests; fresh-VM package bootstrap still needs
verification on a real supported host.

## Optional operator web UI

The dashboard is disabled by default. On an installed Docker deployment, enable it with
`./gmc ui on` and open `http://127.0.0.1:8000/ui/` locally (or the configured HTTPS
URL plus `/ui/`). Use `./gmc ui off` to remove the route. It provides live queue and
worker monitoring, recent build history, manual ZIP upload/compile, job cancellation,
logs, diagnostics, artifact downloads, and copy-ready REST/MCP client details.

The UI is served by the controller—no Node.js or extra web server is required. It asks
for a scoped API token, keeps it in page memory only, and sends it in authenticated API
requests; it does not save tokens in localStorage or cookies. Use HTTPS for remote
browsers. The dashboard is separate from the API/MCP protocols and is not required by
AI agents.

## Manual / development installation


Requires Python 3.11+, `uv` (tested 0.13.1), Docker Engine with cgroups and tmpfs,
and access to PyPI and a registry during installation. macOS/Windows require a Linux
Docker VM; native Windows controller/scheduler is not supported.

```sh
git clone https://github.com/Anyactor26/GradleMCP.git
cd GradleMCP
uv sync --locked
uv run gradlemcp init
docker build -f deploy/worker.Dockerfile -t gradlemcp-worker:17 .
uv run gradlemcp credentials create agent --scopes read,build
# Store the printed token in a secret store; it is shown only once.
export GRADLEMCP_TOKEN='YOUR_GENERATED_TOKEN'
uv run gradlemcp doctor
uv run gradlemcp serve
```

In another shell, export the token and use the [Python client](examples/client.py):

```sh
export GRADLEMCP_URL=http://127.0.0.1:8000
python examples/client.py examples/groovy
```

The default worker uses Java 17 / Gradle 8.14.3. The dependency-free Groovy sample
compiles Java, runs an offline smoke-test harness, and produces a JAR. Ordinary
projects often need dependency access: configure an **externally filtered** worker
network or bake dependencies into an approved image. Do not simply enable unrestricted
egress on a machine containing sensitive services.

## Docker deployment

For manual Compose use, create the private environment file, then build the images and start the controller:

```sh
cp config/gradlemcp.env.example .gradlemcp.env && chmod 600 .gradlemcp.env
uv run gradlemcp init
docker build -f deploy/worker.Dockerfile -t gradlemcp-worker:17 .
docker compose build gradlemcp
docker compose run --rm gradlemcp credentials create docker-agent --scopes read,build
docker compose up -d --wait gradlemcp
```

The controller (not workers) mounts the Docker socket and is root-equivalent on its
Docker host. Bindings default to localhost. Use `./gmc` for lifecycle commands; configure
HTTPS before remote access. [Deployment and tunnel instructions](docs/DEPLOYMENT.md).

## Continuous integration

GitHub Actions quality, Docker integration and PostgreSQL jobs are defined under
[`.github/workflows`](.github/workflows). See [verification](docs/VERIFICATION.md)
for the checks performed locally and environment-dependent release gates.

## Documentation

| Need | Start here |
|---|---|
| Agent workflow | [AI guide](docs/AI_GUIDE.md), [AGENTS.md](AGENTS.md) |
| REST requests and responses | [API reference](docs/API.md), [OpenAPI](docs/openapi.json) |
| MCP client setup | [MCP guide](docs/MCP.md) |
| Install / operate | [Installation](docs/INSTALLATION.md), [Deployment](docs/DEPLOYMENT.md) |
| Configuration / queue | [Configuration](docs/CONFIGURATION.md), [Queue](docs/QUEUE.md) |
| Compatibility / specialized SDKs | [Toolchains](docs/TOOLCHAINS.md) |
| Boundaries / secrets / publication | [Threat model](docs/SECURITY_MODEL.md), [Publishing](docs/PUBLISHING.md) |
| Internals / contributing | [Architecture](docs/ARCHITECTURE.md), [Contributing](CONTRIBUTING.md) |
| Failures / verification / release | [Troubleshooting](docs/TROUBLESHOOTING.md), [Verification](docs/VERIFICATION.md), [Release](docs/RELEASING.md) |

## Development

```sh
make install   # uv sync --locked
make lint typecheck test
make integration  # requires Docker and the worker image
make openapi
make release
```

No external AI account or paid service is required. Nothing in this repository
provisions VPS infrastructure, bypasses repository publication prerequisites, or
claims that a configured public URL is actually reachable.
