#!/bin/sh
# Auditable, local Docker installation. No sudo, package-manager changes or curl | sh.
set -eu
umask 077

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT"

usage() {
    cat <<'HELP'
Usage: ./install.sh [--check | --help]

Install and start GradleMCP with Docker Compose on Linux. Requires Docker Engine
and Compose v2 supporting up --wait-timeout, plus permission to use the daemon.
No host Python, Java, Gradle or uv installation is needed.

Builds the controller and Java 17 worker, preserves existing config/data/token,
creates a private bootstrap credential, starts the service and checks readiness.
Listens on 127.0.0.1:8000 only. Configure HTTPS separately for remote access.

--check  Check prerequisites only; no installation files or containers are created.
--help   Show this help.

Docker control grants host-administrative privileges. Review this script and the
Dockerfiles before running it. This installer never runs sudo or installs Docker.
HELP
}

case "${1:-}" in
    --help|-h) usage; exit 0 ;;
    --check|'') ;;
    *) usage >&2; exit 2 ;;
esac
[ "$#" -le 1 ] || { usage >&2; exit 2; }

fail() { printf 'GradleMCP installation failed: %s\n' "$*" >&2; exit 1; }
command -v docker >/dev/null 2>&1 || fail 'Install Docker Engine and Docker Compose v2 first: https://docs.docker.com/engine/install/'
docker info >/dev/null 2>&1 || fail 'Docker daemon is unavailable or your account lacks permission. Start Docker and review daemon access; do not chmod its socket world-writable.'
docker compose version >/dev/null 2>&1 || fail 'Docker Compose v2 is required (docker compose).'
docker compose up --help | grep -q -- '--wait-timeout' || fail 'Upgrade Docker Compose: up --wait-timeout is required (Compose 2.20+ recommended).'
if [ "${1:-}" = --check ]; then
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
printf 'Manage: docker compose logs -f gradlemcp | docker compose stop gradlemcp\n'
printf 'Re-run ./install.sh safely; config, data and existing credentials are preserved.\n'
printf 'Remote access requires an explicitly configured HTTPS proxy/tunnel; see docs/DEPLOYMENT.md.\n'
