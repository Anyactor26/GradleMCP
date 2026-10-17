# Inactive GitHub Actions files — rename .test to .github

These are the two workflow files that could not be pushed to their active paths
because the connected GitHub App lacks workflow-write permission:

- `.test/workflows/ci.yml` → `.github/workflows/ci.yml`
- `.test/workflows/release.yml` → `.github/workflows/release.yml`

They are preserved here on GitHub, but **not active**. No CI execution is claimed.
Using your authorized maintainer account, rename the root `.test` folder to `.github`
and commit/push the change. For a checkout without an existing `.github` directory:

```sh
mv .test .github
git add -A -- .test .github
git commit -m "Activate GradleMCP CI workflows"
# Push using your authorized account and the appropriate working branch.
```

If `.github` already exists, copy the two YAML files into `.github/workflows/`
instead, preserving any existing files. GitHub still requires workflow-write
permission for activation; this alternate folder does not bypass that requirement.

`ci.yml` runs lint/type checks, tests, package/audit/OpenAPI checks, real Docker/Gradle
integration, one-command installer + repeat installation, and PostgreSQL integration.
`release.yml` builds release-candidate artifacts on manual dispatch without publishing
or requiring registry credentials. Workflow permissions are read-only. Ephemeral CI
PostgreSQL credentials are fixtures, never production secrets.
