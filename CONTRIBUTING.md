# Contributing

Read the architecture and threat model before changing build execution. Open an issue
for major interface/security changes; report vulnerabilities privately per SECURITY.md.
Use Python 3.11+, uv 0.13.1 and Linux. No proprietary AI service is required.

```sh
uv sync --locked
make format lint typecheck test
# Docker daemon and provisioned worker images required:
docker build -f deploy/worker.Dockerfile -t gradlemcp-worker:17 .
make integration
make openapi
make release
```

Add tests for behavior, input validation, ownership and cleanup failure paths. Never
replace an integration build with a fake subprocess to get a green test. Unit tests
may use explicitly labeled controlled subprocesses for worker adapter logic. Update
API docs, AI guide, capability metadata, changelog and OpenAPI when interfaces change.
Pin new dependencies using uv.lock; keep them minimal and audit them. Do not commit
secrets, local config, archives, logs, artifacts, virtualenvs or generated datasets.

Use `ruff format`, `ruff check`, mypy and pytest. The CI templates in deploy/ci (pending activation by an authorized maintainer) use
read-only GitHub permissions
and does not inject publication credentials into PR builds. Expect a review for
queue race conditions, restart behavior and untrusted-code boundaries. Include actual
test results and explicitly list skipped environments. Contributions are accepted
under Apache-2.0; you retain copyright. Be respectful per CODE_OF_CONDUCT.md.
