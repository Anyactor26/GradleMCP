# Changelog

## 0.1.0 — unreleased

- Bind the controller to `0.0.0.0:8000` by default for native, systemd and Compose
  deployments, so `<VPS-IP>:8000` is reachable; set `host` to `127.0.0.1` for a
  loopback-only listener.
- Automatically provision Docker Engine/Compose from signed packages on Debian 12/13
  and Ubuntu 22.04/24.04 (amd64/arm64, systemd), start the daemon and use sudo without
  a re-login when necessary; no host Python setup required.
- Ship a modern standalone Docker CLI in the controller instead of Debian's old
  docker.io client, for compatibility with newly installed Engines.
- Added read-only/no-system-changes options and bootstrap security/regression tests.
- Preserve the owner's activated .github/workflows; fixed metadata test incorrectly
  requiring a workflow README and updated stale activation instructions.

- Changed the current project license to All Rights Reserved (ARR) and credited
  Anyactor as developer/copyright holder. Third-party licenses remain unchanged.
- Moved inactive workflows to `.test/workflows/`; the owner can rename `.test` to
  `.github` to activate them with an authorized account.

- Added auditable one-command Docker installation with prerequisite checks, private
  bootstrap credentials, idempotent reruns and authenticated readiness verification.

- Shared authenticated REST and MCP SDK adapters with stdio/Streamable HTTP.
- Persistent SQLite/PostgreSQL queue, quotas, idempotency, recovery, cancellation.
- ZIP safety and static Gradle/Java/SDK inspection; approved image toolchains.
- Docker workers with CPU/memory/PID/tmpfs/time limits and no default network.
- Bounded logs, failure diagnosis, safe artifact streaming and retention.
- Explicitly authorized publication with suppressed secret-bearing output.
- CLI, deployment/tunnel templates, AI guide, examples and CI suite templates.
- GitHub App workflow-write permission is missing; workflows remain inactive under
  .test until an authorized maintainer activates them.

Verification exclusions and release blockers are documented in docs/VERIFICATION.md.
No production release, registry publication, or successful public tunnel is claimed.
