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

This is not universal Gradle compatibility or a hardened public hostile-code hosting
platform. Read the [security boundary](docs/SECURITY_MODEL.md) before enabling access.
Docker/JDK/Gradle execution and public tunnels could not be verified in the authoring
sandbox. Real Docker integration tests and GitHub Actions workflows are supplied; see [verification](docs/VERIFICATION.md).

## One-command installation — Docker is installed automatically

On **Debian 12/13 or Ubuntu 22.04/24.04**, amd64/arm64, with systemd and root/sudo
access, you do **not** need to install Docker, Python, Java, Gradle or uv yourself.
From an existing checkout, run **`./install.sh`**. Or clone and install in one command:

```sh
git clone --branch main https://github.com/Anyactor26/GradleMCP.git && cd GradleMCP && ./install.sh
```

If Git is also missing on a fresh VPS, this single command installs Git from your
configured OS repositories first (no downloaded shell script is piped into root):

```sh -c 'if ! command -v git >/dev/null 2>&1; then if [ "$(id -u)" = 0 ]; then apt-get update && apt-get install -y git ca-certificates; else sudo apt-get update && sudo apt-get install -y git ca-certificates; fi; fi && git clone --branch main https://github.com/Anyactor26/GradleMCP.git && cd GradleMCP && ./install.sh'
```

This is the current implementation branch; `main` is not updated until it is merged.
The installer automatically sets up missing Docker Engine/Compose from signed packages,
starts Docker, builds both images, initializes private config/storage, creates a scoped
credential, and verifies readiness **and authenticated API access**. Sudo may ask for
your OS password; no re-login, manual Docker-group change or host Python setup is needed.
Existing compatible Docker installs are reused. Review `install.sh`,
`scripts/install-docker.sh` and the Dockerfiles before granting administrative access.

- API: `http://127.0.0.1:8000`; MCP: `http://127.0.0.1:8000/mcp/`.
- Token: `data/bootstrap-token.local` (0600), never printed by the installer.
- Re-running preserves config/data/credentials; no silent rotation or runtime removal.
- `./install.sh --check` is read-only and never requests sudo.
- `./install.sh --no-system-changes` requires existing Docker; it does not install packages or start daemons.
- No world-writable sockets, automatic Docker-group grants, or downloaded root shell scripts.
- Unsupported hosts, conflicting runtimes, and nested/non-systemd environments fail with guidance.
- Public access still requires your HTTPS proxy/tunnel. Docker control is host-administrative.

```sh
export GRADLEMCP_TOKEN="$(cat data/bootstrap-token.local)"
# Prefix with sudo if the installer used privileged Docker access:
docker compose logs -f gradlemcp
docker compose stop gradlemcp
docker compose up -d gradlemcp
```

See [installation](docs/INSTALLATION.md) for the supported platform matrix, system
changes, recovery, and manual alternatives. Fresh-OS package bootstrap has controlled
tests but has not been verified on a fresh VM in the authoring sandbox.

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

After `uv run gradlemcp init` and building the worker image:

```sh
docker compose build
docker compose run --rm gradlemcp credentials create docker-agent --scopes read,build
docker compose up -d gradlemcp
```

The controller (not workers) mounts the Docker socket and is root-equivalent on its
Docker host. Bindings default to localhost. Configure HTTPS and `public_url` before
public use. [Deployment and tunnel instructions](docs/DEPLOYMENT.md).

## Continuous integration

The owner has activated the workflows under **[.github/workflows](.github/workflows)**.
They remain there; no rename back to `.test` is required. The quality tests validate
workflow configuration without requiring a `.github/README.md`. See
[verification](docs/VERIFICATION.md) for actual local results and remaining environment checks.

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
