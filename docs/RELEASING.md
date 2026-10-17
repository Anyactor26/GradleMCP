# Release procedure

1. Review CHANGELOG, API/MCP compatibility and the explicit verification gaps. This
   initial source delivery is not an assertion all deployment scenarios were tested.
2. Run `uv sync --locked`, `make lint typecheck test`, the **real** Docker suite,
   optional Java 21 suite, `make openapi` and a clean schema/config start.
3. Run `make audit`; review base image CVEs, licenses/SBOM/provenance and freeze
   reviewed base images by digest. Dockerfile defaults are tags for convenience;
   a locked Python environment alone does not make registry tags immutable.
4. Verify PostgreSQL if advertising it for the release. Verify target tunnel profiles
   with actual accounts if claiming them tested. Test rotation, backup/restore and
   interrupted publication recovery in staging without production keys.
5. Update version in pyproject, API/MCP metadata/capabilities and changelog. Regenerate
   uv.lock/OpenAPI. Document schema changes/migrations explicitly.
6. `uv build` creates wheel and sdist; inspect contents, install wheel in a fresh
   environment and run `gradlemcp --help`. Run a source/dependency/secret scan.
7. A maintainer can tag the reviewed commit and publish a GitHub release with the
   wheel/sdist/checksums using their normal release process. No automated push/tag or
   public registry upload is performed by this project without operator action.
8. Optional PyPI/container registry publishing needs external registry credentials
   or configured trusted publishing. Do not expose those credentials to PR workflows.

After activation (see .test/README.md), CI builds distributions on pushes/PRs;
`.test/workflows/release.yml` is the template for building release
assets on explicit workflow dispatch with read-only permissions. Download artifacts,
verify checksums, then publish manually. No production publication secrets are
required in standard CI. Report actual CI results, not merely the existence of YAML.
