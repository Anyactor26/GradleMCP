# GitHub Actions templates — activation required

These are complete workflow configurations, intentionally inactive until a repository
owner activates them. The Arena GitHub App used for this delivery can push source
but GitHub rejected `.github/workflows/*` with a missing `workflows` permission.
No CI execution is claimed. Templates are preserved here rather than omitted.

Reconnect GitHub with workflow-write permission, or use an authorized maintainer
account, then copy these files into the protected workflow directory and commit:

```sh
mkdir -p .github/workflows
cp deploy/ci/ci.yml deploy/ci/release.yml .github/workflows/
git add .github/workflows
git commit -m "Activate GradleMCP CI workflows"
# Push using your authorized account and the appropriate working branch.
```

`ci.yml` runs lint/type checks, tests, package/audit/OpenAPI checks, real Docker/Gradle
integration, one-command installer + repeat installation, and PostgreSQL integration.
`release.yml` builds release-candidate artifacts on manual dispatch, without publishing
or requiring registry credentials. Workflow permissions are read-only. Ephemeral CI
PostgreSQL credentials are fixtures, never production secrets.
