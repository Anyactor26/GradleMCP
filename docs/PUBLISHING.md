# Controlled publishing

Publishing is disabled unless all are configured: `publish_tasks`, a dedicated
`publish_toolchain`, a protected `publish_secrets_file`, and a caller with publish
scope. The operator approves exact task names (including subproject paths). A previous
source build must have succeeded before the HTTP/MCP publish operation is available.

Example operator policy:
```json
{"publish_tasks":[":library:publish"],"publish_toolchain":"release17",
 "publish_secrets_file":"/etc/gradlemcp/publication.env"}
```
Add `release17` to toolchains. Normal jobs cannot select this dedicated profile;
secret injection is only enabled by the publication operation. Profiles can use the
same reviewed image digest, but separate keys preserve policy. Create a protected
Docker env-file (not JSON) with project-understood narrow environment variables:
```
MAVEN_USERNAME=configure-locally
MAVEN_PASSWORD=configure-locally
```
Do not commit populated files. For a container controller, mount the env-file read-only
into the trusted controller at its configured path; never bind-mount it into ordinary
workers. Use 0600 permissions, protect Docker control access,
and limit tokens to the intended repository. Configure the Gradle project's actual
maven-publish/plugin-publish/custom plugin settings; there is no hardcoded universal
publish task. Configure an egress-filtered network allowing the intended repository.
The current release has one global worker network and one publication secret profile;
use separate deployments for unrelated publication trust domains/destinations.

`POST /api/v1/builds/{successful_id}/publish`:
```json
{"tasks":[":library:publish"],"idempotency_key":"release-project-version-destination"}
```
It queues a new job from the immutable source with dedicated credentials. It does
not reuse previous artifacts, guarantee reproducibility, automatically sign, require
a human approval UI, or implement a repository-specific staging/promote protocol.
For production publication, explicitly grant publish scope only after review.
A separate administrator can approve cross-client builds; a non-admin approval agent
can only publish its own client identity's builds (there is no project-sharing ACL).
Use local `credentials rotate NAME --scopes read,build,publish` to change the existing
client's grant while preserving ownership and revoking its prior token. Review source and task/destination configuration before
approval: arbitrary code can read/exfiltrate injected secrets despite task allowlists.

Publication metadata records caller, source, task/profile, timestamps, exit code,
publication flag and idempotency key. All publication output is suppressed and artifacts
are not exported to avoid leaking credentials. Consult the destination's audit trail
for remote transaction IDs and uncertain outcomes. Never auto-retry failed/interrupted
publishing: the destination may already have accepted part/all of the operation.

Maven Central/Gradle Plugin Portal/private repositories still require their accounts,
verified namespaces, signing, acceptance of terms and appropriately scoped credentials.
These integrations need operator infrastructure and were not verified with real
production credentials in this repository's authoring environment.
