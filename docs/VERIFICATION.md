# Delivery verification — 2026-10-18

This is a source implementation/release candidate, **not a declaration that all
production deployment requirements have been verified**. The implementation is delivered on `arena/6626d3dc-gradlemcp`. The owner activated
`.github/workflows/ci.yml` and `release.yml`; this update preserves those files
unchanged and does not restore `.test`. The owner's CI log showed a missing
`.github/README.md` assertion (85 passed, 1 failed, 1 skipped, 7 deselected); that
unnecessary assertion is removed and covered by regression tests. The current app
cannot query Actions runs (403: Actions-read permission), so no new remote green
result is claimed. Local results follow. No registry/publication/tunnel claim is made.

## Executed in the authoring environment

Linux, Python 3.11.2, uv 0.13.1, Node 22.22.3. No Docker CLI/daemon, Java, Gradle,
PostgreSQL service, external tunnel account or publication credentials were available.

| Check | Actual result |
|---|---|
| `uv sync --locked` | Passed; locked dependencies installed |
| `ruff check src tests examples/client.py` | Passed |
| `ruff format --check src tests examples/client.py` | Passed |
| `mypy src/gradlemcp` | Passed, 14 source files; non-strict check_untyped_defs mode |
| `pytest -q` | **112 passed, 8 skipped** |
| Non-Docker suite (`make test`) | Same 112 passing tests; PostgreSQL skipped, 7 Docker tests deselected |
| Dependency audit (`pip-audit --skip-editable`) | No known vulnerabilities reported for installed audited dependencies; project itself skipped as editable |
| `uv build` | Wheel and sdist produced |
| Fresh wheel install | Installed into separate environment with locked runtime dependencies; `gradlemcp --help` succeeded |
| Distribution inspection | Source/docs included; worker module/license in wheel; no data, tokens, virtualenv or local configuration packaged |
| Generated OpenAPI | Regenerated from application; equality checked against runtime schema; structured validation/service error schemas included |
| CLI initialization/validation | `init`, `config validate`, credential creation/revocation exercised |
| Live CLI startup | `serve --host 0.0.0.0 --port 8000` started and shut down cleanly |
| Live HTTP smoke | health 200; missing-Docker readiness **503**; unauthenticated capabilities 401; authenticated capabilities/queue/OpenAPI 200 |
| `doctor` | Correctly returned exit 1 with docker_cli=false and docker_daemon=false; not represented as a successful worker check |
| Local documentation links | Checked; all referenced repository documentation exists |

Shell syntax checks pass for both `install.sh` and `scripts/install-docker.sh`.
Controlled tests cover automatic prerequisite setup, sudo/no-relogin operation,
read-only and no-system-changes modes, daemon-only startup, refused sudo, supported
Debian/Ubuntu variants, rejected signing keys, failed downloads, runtime conflicts,
unsupported/non-systemd hosts, source-file preservation and private app credentials.
The bootstrap tests use a staged filesystem and fake OS/package/network tools:
**they do not execute real APT, sudo, Docker installation or a fresh VM**.

ARR (LicenseRef-ARR) and Anyactor identity metadata are checked. Workflow validation
checks YAML/jobs/permissions, not a README. Regression fixtures verify both historical
inactive and current active layouts without documentation files, preferring active
workflows even if an empty old directory exists. No old folder is recreated in the repo.

### What the passing tests establish

- Configuration constraints/precedence, network/image policy, scope checks, invalid
  tokens, revocation, rotation preserving ownership, unauthorized project/job/artifact
  access, admin access, rate and request size limits, sanitized input errors.
- ZIP traversal/absolute/drive/backslash paths, symlinks, malformed/encrypted policy,
  expanded/upload limits; safe static inspection, wrapper HTTPS/host/checksum rules,
  wrapper preference versus explicit managed Gradle, Java profile selection.
- Transactional FIFO/concurrency gates, per-client fairness, queue quotas, concurrent
  idempotency/claim safety, cancellation transitions, persistent interrupted-job
  recovery and retained queued work, retention and busy source deletion rejection.
- Worker adapter security flags, logical output bounds, unsafe artifact paths/links,
  source tar metadata safety, log cap, controlled-subprocess timeout/cancellation,
  no false termination confirmation on daemon loss, occupied slot on cleanup failure,
  singleton scheduler lock, publication policy and output suppression.
- MCP initialization/discovery/upload/submission/status/errors/authentication through
  the real SDK-backed HTTP transport. Official SDK ClientSession against an actual
  stdio subprocess also tests initialization/discovery/upload/submission/status.
- Python and TypeScript client programs against the actual HTTP app using explicitly
  labeled completion/output fixtures. This verifies client protocol/download behavior,
  **not real Gradle execution**. No named external editor was tested.
- ngrok status adapter against mocked provider responses, including URL changes and
  disconnection; no live tunnel connectivity claim.

## Not executed here / release gates

The eight skipped tests are seven real Docker tests (Groovy/Kotlin-DSL/multi-project
builds, intentional failure, queue/cancellation/timeout, concurrency, alternative JDK)
and one real PostgreSQL transaction test. Active `.github/workflows` jobs include
Docker, the real installer with already-present Docker, and PostgreSQL. Status of
those remote jobs is not accessible through the connected app. Fresh-OS package
bootstrap still requires independent VM verification, not just mocked tests.

Before claiming a production-ready release:

- [ ] Verify Docker prerequisite installation on clean supported Debian/Ubuntu VMs,
      including root/sudo paths, reboot persistence and least-privilege operator access.
- [ ] Build controller/worker images and run the Docker integration suite on a real
      Linux Docker host. Confirm a real Gradle build, smoke test, intentional failure,
      queue wait, cancellation, timeout, concurrent jobs and authorized JAR download.
- [ ] Verify cgroup memory/CPU/PID and tmpfs limits under load on the target host.
- [ ] Run Java 21 (or other advertised JDK) and actual Android/native SDK projects
      where those profiles are advertised. Base images do not contain those SDKs.
- [ ] Run PostgreSQL service integration, TLS configuration and backup/restore checks.
- [ ] Validate a production reverse proxy/firewall, HTTPS renewal and real remote MCP
      client. Verify external volume quotas and egress restrictions if networking is enabled.
- [ ] Test Cloudflare/ngrok profile startup/shutdown and current provider configuration
      against real accounts before calling those templates tested integrations.
- [ ] Test approved publication in a staging repository with narrowly scoped credentials,
      including partial success/interruption and destination-side verification.
- [ ] Review base-image digests/provenance, load behavior and security posture; there
      has been no independent penetration test or container escape audit.

## Explicit scope limitations

Implemented: single-controller Docker execution, SQLite/PostgreSQL database adapters,
ZIP source ingestion, approved image-based automatic JDK/Gradle provisioning,
managed/wrapper Gradle, HTTP/MCP lifecycle, optional controlled publication,
operator-managed exposure with truthful status reporting.

Not implemented: Git repository fetching/private Git credentials, native host build
execution, transparent egress proxy, automatic arbitrary JDK/SDK executable downloads,
MCP OAuth authorization server/discovery, distributed multi-controller scheduling,
web dashboard, automatic VM provisioning, per-repository publication staging/approval
UI, cross-client project-sharing ACLs, named editor compatibility certification.
These are not advertised as available capabilities. Git input and advanced exposure
providers are optional extension opportunities, not placeholder endpoints.

Host-wide storage quotas, TLS, egress filtering, stronger VM isolation, SDK licenses,
registry access, private repository credentials and publication accounts are operator
infrastructure. Default `network=none` is enforceable; an arbitrary named network is
**not** magically restricted by GradleMCP. Source/JDK compatibility is heuristic;
real plugins, repositories, OS and architecture requirements still govern success.

The supplied source is usable for deployment validation; mandatory real-worker
verification remains open because its required environment was unavailable. Do not
interpret unit-test success or CI YAML as proof of a successful Gradle build.
