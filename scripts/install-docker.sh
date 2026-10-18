#!/bin/sh
# Privileged, auditable prerequisite setup. Only signed APT packages are executed;
# no downloaded shell installer is used. Called by ../install.sh through sudo.
set -eu
umask 022

# Fixed production root; tests remap this assignment in an isolated script copy.
SYSTEM_ROOT=
TMP=''
fail() { printf 'Docker prerequisite setup failed: %s\n' "$*" >&2; exit 1; }
cleanup() { [ -z "$TMP" ] || rm -rf -- "$TMP"; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
[ "$(id -u)" = 0 ] || fail 'Administrative privileges are required. Run the main install.sh; it requests sudo when needed.'
[ "$(uname -s)" = Linux ] || fail 'Automatic Docker installation supports Linux only.'
case "${1:-}" in --start-only|'') ;; *) fail 'Unsupported prerequisite setup option.' ;; esac
[ "$#" -le 1 ] || fail 'Too many arguments.'

# Refuse partial package installation in containers/non-systemd environments.
command -v systemctl >/dev/null 2>&1 || fail 'A running systemd host is required for automatic setup; install/start Docker using your platform tooling instead.'
systemctl show-environment >/dev/null 2>&1 || fail 'systemd is not running. Nested container/chroot setup is not supported; use a Linux VM/VPS with systemd.'
if [ "${1:-}" = --start-only ]; then
    systemctl start docker
    systemctl is-active --quiet docker || fail 'Docker did not start; inspect journalctl -u docker.'
    exit 0
fi

OS_RELEASE="$SYSTEM_ROOT/etc/os-release"
[ -f "$OS_RELEASE" ] || fail 'Cannot identify this Linux distribution.'
# Parse data, never source/eval os-release as root.
os_value() { sed -n "s/^$1=//p" "$OS_RELEASE" | head -n 1 | tr -d "\"'"; }
OS_ID=$(os_value ID)
CODENAME=$(os_value VERSION_CODENAME)
case "$OS_ID:$CODENAME" in
    debian:bookworm|debian:trixie|ubuntu:jammy|ubuntu:noble) ;;
    *) fail 'Automatic installation supports Debian 12/13 and Ubuntu 22.04/24.04. On other systems install Docker Engine + Compose v2 using vendor instructions, then rerun.' ;;
esac
command -v apt-get >/dev/null 2>&1 || fail 'APT is required on the supported distributions.'
ARCH=$(dpkg --print-architecture)
case "$ARCH" in amd64|arm64) ;; *) fail 'Automatic setup supports amd64 and arm64; install Docker for your architecture manually.' ;; esac

# Never silently remove/migrate an operator's existing engine/runtime.
case "$(command -v docker || true)" in /snap/*) fail 'Existing Snap Docker installation detected; manage its Compose plugin manually rather than replacing the engine.' ;; esac
for package in docker.io docker-compose docker-compose-v2 podman-docker containerd runc; do
    status=$(dpkg-query -W -f='${db:Status-Status}' "$package" 2>/dev/null || true)
    [ "$status" != installed ] || fail "Conflicting package $package is installed. No packages were removed; review Docker migration instructions or supply a working Compose v2 plugin."
done

printf 'Installing Docker prerequisites from your configured signed OS repositories...\n'
export DEBIAN_FRONTEND=noninteractive
apt-get -o DPkg::Lock::Timeout=120 update
apt-get -o DPkg::Lock::Timeout=120 install -y --no-install-recommends ca-certificates curl gnupg

SOURCES="$SYSTEM_ROOT/etc/apt/sources.list.d"
KEYS="$SYSTEM_ROOT/etc/apt/keyrings"
SOURCE_FILE="$SOURCES/gradlemcp-docker.sources"
KEY_FILE="$KEYS/gradlemcp-docker.asc"
# Existing administrator-managed Docker repositories take precedence; don't rewrite them.
if [ -e "$SOURCES/docker.sources" ] || [ -e "$SOURCES/docker.list" ]; then
    printf 'Reusing existing administrator-managed Docker APT repository.\n'
else
    [ ! -L "$SOURCE_FILE" ] && [ ! -L "$KEY_FILE" ] || fail 'Refusing symlinked Docker APT configuration/key files.'
    install -d -m 0755 "$SOURCES" "$KEYS"
    TMP=$(mktemp -d)
    mkdir -m 0700 "$TMP/gnupg"
    curl --fail --silent --show-error --proto '=https' --tlsv1.2 \
        --connect-timeout 15 --max-time 120 \
        "https://download.docker.com/linux/$OS_ID/gpg" --output "$TMP/docker.asc"
    gpg --batch --homedir "$TMP/gnupg" --show-keys --with-colons "$TMP/docker.asc" > "$TMP/key-details"
    fingerprint=$(awk -F: '$1=="pub" {primary=1; next} primary && $1=="fpr" {print $10; primary=0}' "$TMP/key-details")
    primary_count=$(awk -F: '$1=="pub" {count++} END {print count+0}' "$TMP/key-details")
    [ "$primary_count" = 1 ] && [ "$fingerprint" = 9DC858229FC7DD38854AE2D88D81803C0EBFCD88 ] || fail 'Docker signing-key fingerprint mismatch. No new repository was enabled; review upstream key rotation before updating this installer.'
    cat > "$TMP/docker.sources" <<REPO
Types: deb
URIs: https://download.docker.com/linux/$OS_ID
Suites: $CODENAME
Components: stable
Architectures: $ARCH
Signed-By: $KEY_FILE
REPO
    if [ -e "$SOURCE_FILE" ]; then
        cmp -s "$SOURCE_FILE" "$TMP/docker.sources" || fail 'Existing gradlemcp-docker.sources differs from the expected repository. Refusing to overwrite operator changes.'
    fi
    install -m 0644 "$TMP/docker.asc" "$KEY_FILE"
    install -m 0644 "$TMP/docker.sources" "$SOURCE_FILE"
fi

apt-get -o DPkg::Lock::Timeout=120 update
apt-get -o DPkg::Lock::Timeout=120 install -y --no-install-recommends \
    docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
systemctl is-active --quiet docker || fail 'Docker installation completed but the daemon failed to start; inspect journalctl -u docker.'
printf 'Docker Engine and Compose v2 installed and started. No Docker group/socket permissions were broadened.\n'
