#!/bin/sh
# Auditable local installation, including signed-package Docker setup on supported Linux.
set -eu
umask 077

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT"

usage() {
    cat <<'HELP'
Usage: ./install.sh [--check | --no-system-changes | --help]

Install and start GradleMCP, automatically installing Docker Engine and Compose v2
on Debian 12/13 or Ubuntu 22.04/24.04 (amd64/arm64, systemd) when needed.
Root or sudo permission is required for OS package/daemon setup and Docker access.
No host Python, Java, Gradle or uv installation is needed.

Builds the controller and Java 17 worker, preserves existing config/data/token,
creates a private bootstrap credential, starts the service and checks readiness.
Listens on 127.0.0.1:8000 only. Configure HTTPS separately for remote access.

--check              Read-only checks; never requests sudo or installs anything.
--no-system-changes  Require an existing running Docker + Compose; no OS changes.
--help               Show this help.

Docker control grants host-administrative privileges. Review this script and the
Dockerfiles and scripts/install-docker.sh before running. Sudo may prompt for your
OS password. Only signed APT packages are installed; no curl | sh is used.
No Docker group changes or world-writable sockets are used.
HELP
}

case "${1:-}" in
    --help|-h) usage; exit 0 ;;
    --check|--no-system-changes|'') ;;
    *) usage >&2; exit 2 ;;
esac
[ "$#" -le 1 ] || { usage >&2; exit 2; }

fail() { printf 'GradleMCP installation failed: %s\n' "$*" >&2; exit 1; }
docker_cli_ready() {
    command -v docker >/dev/null 2>&1 &&
        command docker compose version >/dev/null 2>&1 &&
        command docker compose up --help 2>/dev/null | grep -q -- '--wait-timeout'
}
if [ "${1:-}" = --check ]; then
    docker_cli_ready || fail 'Docker Engine + Compose v2 with up --wait-timeout are not available. Run ./install.sh to set them up automatically on supported Linux.'
    command docker info >/dev/null 2>&1 || fail 'Docker is unavailable to this account. Read-only check made no changes; run ./install.sh to start/use Docker with sudo.'
    printf 'Prerequisites available. Docker access is host-administrative. No files changed.\n'
    exit 0
fi

LOCK=.gradlemcp-install.lock
mkdir "$LOCK" 2>/dev/null || fail 'Another installer is running. If interrupted, confirm it stopped before removing .gradlemcp-install.lock.'
TEMP_TOKEN=''
TEMP_CONFIG=''
cleanup() {
    [ -z "$TEMP_TOKEN" ] || rm -f -- "$TEMP_TOKEN"
    [ -z "$TEMP_CONFIG" ] || rm -f -- "$TEMP_CONFIG"
    rmdir "$LOCK" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Escalate individual trusted operations, not the whole checkout or remote scripts.
USE_SUDO=0
as_root() {
    if [ "$(id -u)" = 0 ]; then
        "$@"
    else
        command -v sudo >/dev/null 2>&1 || fail 'Root or sudo is needed for automatic setup. Ask your administrator to run this installer; no Python/Java setup is required.'
        sudo -- "$@"
    fi
}
if ! docker_cli_ready; then
    [ "${1:-}" != --no-system-changes ] || fail 'Docker/Compose prerequisites are missing or outdated; OS changes disabled.'
    printf 'Setting up Docker from signed packages (sudo may request your OS password)...\n'
    as_root sh "$ROOT/scripts/install-docker.sh"
    docker_cli_ready || fail 'Docker/Compose installation did not provide the required CLI features.'
fi
if ! command docker info >/dev/null 2>&1; then
    # Existing daemon may simply require privileged access; avoid unnecessary service changes.
    if [ "$(id -u)" != 0 ] && command -v sudo >/dev/null 2>&1 && sudo -- docker info >/dev/null 2>&1; then
        USE_SUDO=1
    else
        [ "${1:-}" != --no-system-changes ] || fail 'Docker daemon unavailable; OS changes disabled.'
        as_root sh "$ROOT/scripts/install-docker.sh" --start-only
        if command docker info >/dev/null 2>&1; then
            USE_SUDO=0
        elif [ "$(id -u)" != 0 ] && as_root docker info >/dev/null 2>&1; then
            USE_SUDO=1
        else
            fail 'Docker daemon is still unavailable after startup. Inspect journalctl -u docker; never chmod the socket world-writable.'
        fi
    fi
fi
docker() {
    if [ "$USE_SUDO" = 1 ]; then sudo -- docker "$@"; else command docker "$@"; fi
}

[ ! -L gradlemcp.json ] || fail 'Refusing a symlink at gradlemcp.json.'
[ ! -L data ] || fail 'Refusing a symlink at data; configure custom storage explicitly instead.'
mkdir -p data
if [ ! -e gradlemcp.json ]; then
    TEMP_CONFIG=$(mktemp .gradlemcp-config.XXXXXX)
    cat config/gradlemcp.example.json > "$TEMP_CONFIG"
    mv -- "$TEMP_CONFIG" gradlemcp.json
    TEMP_CONFIG=''
fi
[ -f gradlemcp.json ] || fail 'gradlemcp.json must be a regular JSON configuration file.'
TOKEN=data/bootstrap-token.local
[ ! -L "$TOKEN" ] || fail 'Refusing a symlink at the bootstrap token path.'

printf 'Building approved Java 17 / Gradle worker...\n'
docker build -f deploy/worker.Dockerfile -t gradlemcp-worker:17 .
printf 'Building GradleMCP controller...\n'
docker compose build gradlemcp
docker compose run --rm --no-deps gradlemcp config validate
if [ ! -e "$TOKEN" ]; then
    TEMP_TOKEN=$(mktemp data/.bootstrap-token.XXXXXX)
    # Credential values never enter command arguments or installer output.
    if ! docker compose run --rm --no-deps gradlemcp credentials create installer-agent --scopes read,build > "$TEMP_TOKEN"; then
        fail 'Could not create bootstrap credential. Existing credentials are never silently rotated; restore the token file or manage credentials with the CLI.'
    fi
    [ -s "$TEMP_TOKEN" ] || fail 'Credential creation returned an empty token.'
    chmod 600 "$TEMP_TOKEN"
    mv -- "$TEMP_TOKEN" "$TOKEN"
    TEMP_TOKEN=''
else
    [ -f "$TOKEN" ] && [ -s "$TOKEN" ] || fail 'Existing bootstrap token must be a nonempty regular file.'
    chmod 600 "$TOKEN"
    printf 'Preserving existing bootstrap credential; no rotation performed.\n'
fi

printf 'Starting GradleMCP and waiting for health...\n'
docker compose up -d --wait --wait-timeout 120 gradlemcp
docker compose exec -T gradlemcp python -c "import urllib.request; from pathlib import Path; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=10).close(); token=Path('data/bootstrap-token.local').read_text().strip(); request=urllib.request.Request('http://127.0.0.1:8000/api/v1/capabilities', headers={'Authorization':'Bearer '+token}); urllib.request.urlopen(request, timeout=10).close()"
printf '\nGradleMCP is ready at http://127.0.0.1:8000\n'
printf 'Private API token saved to %s/%s (0600); token not printed.\n' "$ROOT" "$TOKEN"
printf 'MCP: http://127.0.0.1:8000/mcp/ (send the bearer token).\n'
if [ "$USE_SUDO" = 1 ]; then
    printf 'Manage: sudo docker compose logs -f gradlemcp | sudo docker compose stop gradlemcp\n'
else
    printf 'Manage: docker compose logs -f gradlemcp | docker compose stop gradlemcp\n'
fi
printf 'Re-run ./install.sh safely; config, data and existing credentials are preserved.\n'
printf 'Remote access requires an explicitly configured HTTPS proxy/tunnel; see docs/DEPLOYMENT.md.\n'
