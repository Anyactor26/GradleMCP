import contextvars
import json
import os

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .db import Job, owned
from .endpoint import endpoint_status
from .errors import ServiceError
from .service import BuildRequest

request_token = contextvars.ContextVar("request_token", default=None)


def create_mcp(service):
    mcp = MCPServer(
        "GradleMCP",
        version="0.1.0",
        instructions="Upload a ZIP, inspect compatibility, submit once, poll queued/running jobs, then retrieve bounded logs and artifacts. Never blindly retry publication. See docs/AI_GUIDE.md.",
    )

    def call(method, *args, **kwargs):
        try:
            token = request_token.get() or os.environ.get("GRADLEMCP_TOKEN", "")
            client = service.db.authenticate(token)
            return method(client, *args, **kwargs)
        except ServiceError as exc:
            raise ToolError(json.dumps(exc.body)) from None

    @mcp.tool()
    def get_capabilities() -> dict:
        """Discover supported toolchains, limits, security policy and operations."""
        return call(service.capabilities)

    @mcp.tool()
    def upload_project(archive_base64: str) -> dict:
        """Upload a base64 ZIP (root is build root); bounded by configured upload size."""
        return call(service.upload_base64, archive_base64)

    @mcp.tool()
    def inspect_project(project_id: str, subdirectory: str = ".") -> dict:
        """Statically inspect source without executing Gradle scripts; requirements are heuristic."""
        return call(lambda c: service.project(c, project_id, subdirectory)[1])

    @mcp.tool()
    def get_project_compatibility(request: BuildRequest) -> dict:
        """Check detected requirements against approved worker JDK/SDK profiles."""
        return call(service.compatibility, request)

    @mcp.tool()
    def submit_build(request: BuildRequest) -> dict:
        """Queue a build asynchronously. Acceptance is not success. Use an idempotency key."""
        return call(service.submit, request)

    @mcp.tool()
    def get_build_status(build_id: str) -> dict:
        """Get state, timestamps, diagnostics and approximate FIFO queue position."""
        return call(service.status, build_id)

    @mcp.tool()
    def get_build_logs(build_id: str, offset: int = 0, limit: int = 65536) -> dict:
        """Read at most 64 KiB of log bytes; resume from next_offset."""
        if offset < 0 or not 1 <= limit <= 65536:
            raise ToolError("offset must be nonnegative and limit must be 1..65536")
        return call(service.logs, build_id, offset, limit)

    @mcp.tool()
    def cancel_build(build_id: str) -> dict:
        """Request cancellation; cancelling means worker termination is not yet confirmed."""
        return call(service.cancel, build_id)

    @mcp.tool()
    def list_artifacts(build_id: str) -> list[dict]:
        """List exported outputs with opaque IDs, sizes and SHA-256 digests."""
        return call(service.artifacts, build_id)

    @mcp.tool()
    def download_artifact(build_id: str, artifact_id: str) -> dict:
        """Return an authorized relative HTTP download URL. Send your bearer token separately."""

        def result(client):
            _, item = service.artifact(client, build_id, artifact_id)
            return {
                "url": f"/api/v1/builds/{build_id}/artifacts/{artifact_id}",
                "artifact": item,
                "base_url": endpoint_status(service.config)["public_url"],
                "authentication": "Authorization: Bearer <token>",
            }

        return call(result)

    @mcp.tool()
    def list_gradle_tasks(project_id: str, toolchain: str | None = None) -> dict:
        """Queue isolated Gradle 'tasks'; configuration executes untrusted code. Read task listing in job logs."""
        return call(
            service.submit,
            BuildRequest(project_id=project_id, tasks=["tasks"], toolchain=toolchain),
        )

    @mcp.tool()
    def publish_build(build_id: str, tasks: list[str], idempotency_key: str) -> dict:
        """Queue explicitly authorized publication from a successful build's immutable source. Never auto-retry side effects."""
        return call(publish, build_id, tasks, idempotency_key)

    def publish(client, build_id, tasks, key):
        status = service.status(client, build_id)
        if status["state"] != "succeeded":
            raise ServiceError(
                "build_not_successful", "Publishing requires a successful source build", 409
            )
        with service.db.sessions() as session:
            original = owned(session, Job, build_id, client)
            request = BuildRequest.model_validate(
                {k: v for k, v in original.spec.items() if k in BuildRequest.model_fields}
            )
        request = request.model_copy(update={"tasks": tasks, "idempotency_key": key})
        # Revalidate model_copy updates so tasks cannot smuggle CLI arguments.
        request = BuildRequest.model_validate(request.model_dump())
        return service.submit(client, request, publication=True)

    @mcp.tool()
    def get_queue_status() -> dict:
        """Get capacity, global counts and caller quota usage; no fabricated wait estimate."""
        return call(service.queue)

    return mcp, publish
