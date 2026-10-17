# GradleMCP

**An open-source remote Gradle build engine for AI agents.** Apache-2.0, self-hosted,
provider-independent. Submit immutable ZIP projects through REST or MCP; builds wait
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
sandbox. Real Docker integration tests and CI templates are supplied; see [verification](docs/VERIFICATION.md).

## One-command installation

On a **Linux Docker host**, with Git, Docker Engine and Docker Compose v2 installed:

```sh
git clone --branch arena/6626d3dc-gradlemcp https://github.com/Anyactor26/GradleMCP.git && cd GradleMCP && ./install.sh
```

This is the current implementation branch; `main` is not updated until it is merged.
Already cloned this branch? Just run **`./install.sh`**.

The auditable installer builds the controller and Java 17 worker, initializes private
configuration/storage, creates a scoped API credential, starts the service, and checks
readiness **and authenticated API access**. It needs **no host Python, Java, Gradle or uv**.
It does not run sudo, install Docker automatically, or pipe downloaded scripts into a shell.
Review `install.sh` and the Dockerfiles first if you do not already trust this repository.

- API: `http://127.0.0.1:8000`; MCP: `http://127.0.0.1:8000/mcp/`.
- Token: `data/bootstrap-token.local` (0600), never printed by the installer.
- Re-running preserves your configuration, data and existing token; it never silently rotates credentials.
- `./install.sh --check` checks prerequisites without changing files/containers.
- Public access still requires your HTTPS proxy/tunnel. Docker access is host-administrative.

```sh
export GRADLEMCP_TOKEN="$(cat data/bootstrap-token.local)"
# Logs / stop / start later:
docker compose logs -f gradlemcp
docker compose stop gradlemcp
docker compose up -d gradlemcp
```

See [installation](docs/INSTALLATION.md) for prerequisites, recovery and manual alternatives.

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

## CI activation

The connected GitHub App cannot write `.github/workflows/` without additional
permission. Complete workflows are preserved in **[deploy/ci](deploy/ci/README.md)**,
but are **not active**. Reconnect GitHub with workflow-write permission or activate
them using an authorized maintainer account. No GitHub CI success is claimed.

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
