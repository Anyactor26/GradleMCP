# Security boundary and threat model

Gradle scripts/plugins/wrappers execute arbitrary code. An API task name allowlist or
static inspection **cannot** sandbox Gradle or prevent a task from invoking another
task/network program. Treat every uploaded project as untrusted code.

## Assets and trust

Protect host/controller integrity, other tenants' source/logs/artifacts, production
publication keys, API tokens, database, Docker control socket and internal networks.
Trusted: local administrators, controller code/dependencies, reviewed worker images,
reverse proxy, Docker daemon/kernel, local storage. Untrusted: all project bytes,
Gradle output, wrapper URLs, artifacts and remote agent requests. The API controller
has Docker administration capability; compromising it is host compromise.

## Implemented protections

- High-entropy random API tokens shown once; SQL stores SHA-256 digests, constant-time
  comparison. Multiple named clients, revoke and rotate; read/build/publish/admin scopes.
- Ownership checks on projects/jobs/logs/artifacts, opaque IDs, unauthorized resources
  return 404. Admin is intentionally cross-tenant. No shell, host path or remote
  credential-management endpoint. Rate limit after auth; use proxy limits before auth.
- Request and expanded ZIP bounds, file count, traversal/absolute/drive/backslash checks,
  duplicate paths, symlink/special/encrypted/malformed ZIP rejection; private storage.
- Non-root UID/GID 1000 builds, read-only container root, no capabilities, no-new-privileges,
  CPU/memory/no-swap/PID limits, bounded tmpfs, minimal explicitly configured environment,
  separate workspace, wall-clock termination, no host mounts/socket in build workers.
- `network=none` by default: no dependency/metadata/internal-address access. Container
  loopback is its own namespace, not the host. Named worker networks require external
  controls. Host/default bridge and shared container namespaces are refused.
- Streaming tar export does not extract worker paths. Links/special/sparse files skipped;
  logical size/count limits before reads; opaque artifact IDs and bounded exports.
  HTTP download streams from controller-owned filenames, never client path arguments.
- Secrets injected only into explicitly authorized publication workers; no publication
  logs/artifacts exported, no automatic publication replay. All Gradle jobs can execute
  code; never inject credentials into a project you do not trust.
- Minimal public health/readiness; capabilities, metrics, docs and all build data require
  authentication. Origin checks everywhere, plus MCP SDK DNS-rebinding/Host checks for
  host-specific binds (an all-interface bind is already reachable by any address, so it
  relies on bearer auth and REST Origin checks). No wildcard CORS.
- Optional dashboard is disabled by default and serves only static login/UI assets without
  a token. API calls remain bearer-authenticated; the UI holds a user-entered token in
  page memory only (not localStorage/cookies) and clears it on logout/page reload.

## Network and SSRF

There is no Git-fetch endpoint, arbitrary controller download endpoint or automatic
project URL downloader. The controller accesses Docker/approved registries and an
operator-configured ngrok status endpoint only. Default isolated builds have no
network. This is the enforceable SSRF defense, not hostname string checks.

If dependency access is needed, create a dedicated Docker network and implement a
host-level egress firewall or explicit repository proxy. Block **all** RFC1918,
loopback, link-local, metadata (169.254.169.254), host gateways, IPv6 local/link-local,
other Docker networks and administrative endpoints; permit only reviewed destinations.
Apply controls after DNS resolution and every redirect, for both IPv4 and IPv6;
DNS rebinding and malicious repository redirects must not bypass them. Force proxy
usage at the network layer, not merely HTTP_PROXY that hostile builds can unset.
GradleMCP does not implement a transparent egress proxy or claim arbitrary named
networks are filtered. Verify external policy independently before setting network.
With unrestricted egress you lose the SSRF boundary and may exfiltrate source/secrets.

## Important limits

Containers share a kernel and Docker is not a perfect hostile-code sandbox. For
untrusted public multi-tenant deployment use disposable VMs, a dedicated worker host,
rootless Docker with verified cgroups, or an independently validated stronger runtime.
This release does not automate VM provisioning or attest seccomp/hypervisor safety.
Default Docker seccomp is inherited; keep daemon, kernel and images patched.

Tmpfs counts against memory: large archives/cache files can OOM a worker. Total host
storage needs an operator-managed filesystem/project quota, not just the free-space
reserve. Log export is capped but a malicious job may consume its assigned resources
until cancellation/timeout. Many sequential jobs can retain bounded-per-job outputs
until cleanup; use client quotas, retention and host volume quotas. Metadata/idempotency
records need an operator archival policy at high volume.

API rate limiting is single-process, in-memory and resets on restart. Put connection,
unauthenticated request-rate, body/read timeout, and request concurrency limits at the
reverse proxy/firewall. Only one application worker/scheduler is supported. Do not
expose Uvicorn directly to a high-risk public internet workload. HTTPS can be terminated
by the optional Caddy Compose profile or another operator-managed proxy; DNS, firewall
rules, certificate monitoring and proxy hardening remain operator responsibilities.

Pattern-based log redaction is best effort and cannot guarantee removal of arbitrary
or encoded secrets, including patterns split across pipe chunks. Never place secrets
in normal build source or dependencies. Secret-bearing publication output is entirely
suppressed instead. A malicious publication build can exfiltrate injected secrets
through its allowed network or external publication destination; authorize only
reviewed source and use least-privilege, short-lived signing/repository credentials.
Artifacts from ordinary jobs may contain sensitive project data: access control is
not content classification. Do not grant tenants local database/data-directory access.

## Recovery

Cancellation kills/removes the entire container and confirms absence via a successful
Docker query; losing daemon contact is not success. Failure to confirm occupies the
slot and requests operator recovery. Restart first removes known interrupted containers
then records failed/server_interrupted; queued work remains. Never blindly replay
side-effecting jobs. Back up databases, protected config and artifacts; audit local
operator credential actions through your OS/access control system.

## Verification boundary

Security tests cover API ownership/scopes/revocation, ZIP attacks, task input injection,
limits, wrapper policy and output safety. Docker integration tests are opt-in and were
not executable in the authoring sandbox. There has been no third-party penetration
test, container escape audit, egress firewall verification, or production load test.


## Installer privileges

On supported Debian/Ubuntu systemd hosts, install.sh can install Docker automatically.
It requests root/sudo, uses signed OS/APT packages, verifies the Docker public-key
fingerprint, and keeps repository trust scoped via Signed-By. No downloaded shell
installer, socket chmod or automatic Docker-group grant is used. Existing runtimes
are not removed silently. Docker administration remains root-equivalent even without
group changes: review local scripts/Dockerfiles before authorizing. --check is read-only;
--no-system-changes disables package/repository/service changes. OS bootstrap is tested
with controlled tools, not claimed verified on a fresh VM in this authoring environment.
