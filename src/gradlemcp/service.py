import base64
import hashlib
import json
import shutil
import time
import uuid
from pathlib import PurePosixPath
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import func, select

from .db import ACTIVE, TERMINAL, Job, Project, owned, require
from .errors import ServiceError
from .source import extract_zip, inspect_project

Task = Annotated[str, StringConstraints(pattern=r"^:?[A-Za-z0-9_][A-Za-z0-9_:.-]{0,199}$")]


class BuildRequest(BaseModel):
    model_config = {"extra": "forbid"}
    project_id: str
    tasks: list[Task] = Field(default=["build"], min_length=1, max_length=32)
    toolchain: str | None = None
    java: int | None = Field(default=None, ge=8, le=99)
    subdirectory: str = Field(default=".", min_length=1, max_length=1024)
    use_wrapper: bool | None = None
    artifact_patterns: list[str] = Field(
        default=["**/build/libs/*", "**/build/reports/**", "**/build/test-results/**"],
        max_length=32,
    )
    idempotency_key: str | None = Field(default=None, max_length=128)


class Service:
    def __init__(self, config, db):
        self.config, self.db = config, db
        for name in ("projects", "jobs"):
            (config.data_dir / name).mkdir(parents=True, exist_ok=True, mode=0o700)

    def capabilities(self, client):
        require(client, "read")
        return {
            "name": "GradleMCP",
            "version": "0.1.0",
            "source_modes": ["zip"],
            "toolchains": {k: v.model_dump() for k, v in self.config.toolchains.items()},
            "limits": {
                k: getattr(self.config, k)
                for k in (
                    "max_workers",
                    "max_queue",
                    "per_client_active",
                    "per_client_queued",
                    "memory_mb",
                    "cpus",
                    "pids",
                    "workspace_mb",
                    "artifact_mb",
                    "upload_mb",
                    "log_mb",
                    "timeout_seconds",
                )
            },
            "network": self.config.network,
            "publishing_enabled": bool(self.config.publish_tasks),
            "wrapper_enabled": self.config.wrapper_enabled,
            "states": sorted(TERMINAL | ACTIVE | {"queued"}),
            "documentation": "docs/AI_GUIDE.md",
            "git_sources": False,
            "isolation": "Docker; stronger VM isolation recommended for hostile tenants",
            "automatic_provisioning": "Approved worker images only; auto_pull is operator opt-in",
        }

    def upload(self, client, data):
        require(client, "build")
        self.check_disk()
        project_id = uuid.uuid4().hex
        root = self.config.data_dir / "projects" / project_id
        # Reserve upload quota before decompression, including concurrent in-flight uploads.
        with self.db.transaction() as session:
            count = session.scalar(
                select(func.count()).select_from(Project).where(Project.owner == client.id)
            )
            if count >= self.config.per_client_queued * 4:
                raise ServiceError(
                    "project_quota", "Retained project quota reached; delete unused projects", 429
                )
            session.add(Project(id=project_id, owner=client.id, inspection={}))
        try:
            extract_zip(data, root, self.config)
            inspection = inspect_project(root, self.config)
            with self.db.transaction() as session:
                session.get(Project, project_id).inspection = inspection
            return {"project_id": project_id, "inspection": inspection}
        except BaseException:
            shutil.rmtree(root, ignore_errors=True)
            with self.db.transaction() as session:
                project = session.get(Project, project_id)
                if project:
                    session.delete(project)
            raise

    def upload_base64(self, client, archive):
        if len(archive) > self.config.upload_mb * 1024**2 * 4 // 3 + 4:
            raise ServiceError("upload_limit", "Archive exceeds upload limit", 413)
        try:
            data = base64.b64decode(archive, validate=True)
        except ValueError as exc:
            raise ServiceError("invalid_archive", "Expected base64 ZIP data") from exc
        return self.upload(client, data)

    def project(self, client, project_id, subdirectory="."):
        require(client, "read")
        path = PurePosixPath(subdirectory)
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in subdirectory
            or "\x00" in subdirectory
            or len(subdirectory) > 1024
        ):
            raise ServiceError("invalid_path", "Subdirectory must remain inside the project")
        with self.db.sessions() as s:
            owned(s, Project, project_id, client)
        root = self.config.data_dir / "projects" / project_id / str(path)
        if not root.is_dir():
            raise ServiceError("not_found", "Project subdirectory not found", 404)
        return root, inspect_project(root, self.config)

    def compatibility(self, client, request):
        _, inspection = self.project(client, request.project_id, request.subdirectory)
        if not inspection["build_files"] and not inspection["settings_files"]:
            raise ServiceError("not_gradle", "No Gradle build or settings files detected")
        use_wrapper = request.use_wrapper
        if use_wrapper is None:
            use_wrapper = self.config.wrapper_enabled and inspection["wrapper"]["valid"]
        if use_wrapper:
            if not self.config.wrapper_enabled or not inspection["wrapper"]["valid"]:
                raise ServiceError(
                    "unsafe_wrapper",
                    "Wrapper is disabled or lacks approved HTTPS distribution and SHA-256",
                    remediation="Use managed Gradle or configure a complete approved wrapper",
                )
        java = request.java or (max(inspection["java_hints"]) if inspection["java_hints"] else None)
        candidates = {
            k: t
            for k, t in self.config.toolchains.items()
            if (java is None or t.java == java)
            and (not inspection["android"] or t.android)
            and (not inspection["native"] or t.native)
        }
        if request.toolchain:
            candidates = {k: v for k, v in candidates.items() if k == request.toolchain}
        if not candidates:
            raise ServiceError(
                "toolchain_unavailable",
                "No approved worker matches detected or requested requirements",
                remediation="Ask the operator to configure an approved JDK/SDK worker image, or explicitly select the correct Java version",
                details={
                    "java": java,
                    "android": inspection["android"],
                    "native": inspection["native"],
                    "available": list(self.config.toolchains),
                },
            )
        key = next(iter(candidates))
        return {
            "toolchain": key,
            "use_wrapper": bool(use_wrapper),
            "inspection": inspection,
            "limitations": [
                "Static hints are not authoritative; runtime/plugin compatibility is verified by the build."
            ],
        }

    def submit(self, client, request: BuildRequest, publication=False):
        require(client, "publish" if publication else "build")
        self.check_disk()
        for pattern in request.artifact_patterns:
            if (
                PurePosixPath(pattern).is_absolute()
                or ".." in PurePosixPath(pattern).parts
                or "\\" in pattern
            ):
                raise ServiceError(
                    "invalid_pattern", "Artifact patterns must remain in the workspace"
                )
        if publication:
            if not self.config.publish_tasks or any(
                t not in self.config.publish_tasks for t in request.tasks
            ):
                raise ServiceError(
                    "publishing_disabled", "Publication requires an operator-approved task", 403
                )
            request = request.model_copy(update={"toolchain": self.config.publish_toolchain})
        elif self.config.publish_toolchain and request.toolchain == self.config.publish_toolchain:
            raise ServiceError(
                "forbidden", "Dedicated publication toolchain requires publish permission", 403
            )
        result = self.compatibility(client, request)
        # Prevent implicit selection of the secret-bearing publication profile for normal jobs.
        if not publication and result["toolchain"] == self.config.publish_toolchain:
            raise ServiceError("forbidden", "Select a non-publication toolchain", 403)
        spec = request.model_dump() | {
            "toolchain": result["toolchain"],
            "use_wrapper": result["use_wrapper"],
            "publication": publication,
        }
        fingerprint = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
        spec["fingerprint"] = fingerprint
        with self.db.transaction() as s:
            if request.idempotency_key:
                previous = s.scalar(
                    select(Job).where(
                        Job.owner == client.id, Job.idempotency == request.idempotency_key
                    )
                )
                if previous:
                    if previous.spec.get("fingerprint") != fingerprint:
                        raise ServiceError(
                            "idempotency_conflict", "Key already used for a different request", 409
                        )
                    return self.serialize(previous)
            queued = s.scalars(select(Job).where(Job.state == "queued")).all()
            if (
                len(queued) >= self.config.max_queue
                or sum(j.owner == client.id for j in queued) >= self.config.per_client_queued
            ):
                raise ServiceError(
                    "queue_full", "Queue admission quota reached", 429, retryable=True
                )
            job = Job(
                id=uuid.uuid4().hex,
                owner=client.id,
                project=request.project_id,
                state="queued",
                spec=spec,
                idempotency=request.idempotency_key,
            )
            s.add(job)
            s.flush()
            return self.serialize(job)

    def serialize(self, job):
        diagnostic = dict(job.diagnostic)
        if diagnostic:
            diagnostic.setdefault("message", "Build operation did not complete successfully")
            diagnostic.setdefault("retryable", False)
            diagnostic.setdefault("permanent", not diagnostic["retryable"])
            diagnostic.setdefault(
                "remediation", "Inspect job logs and operator diagnostics before retrying"
            )
            diagnostic.setdefault("details", {})
        return {
            key: getattr(job, key)
            for key in (
                "id",
                "owner",
                "project",
                "state",
                "created",
                "started",
                "finished",
                "exit_code",
                "artifacts",
            )
        } | {
            "diagnostic": diagnostic,
            "duration_seconds": max(0, (job.finished or time.time()) - job.started)
            if job.started is not None
            else None,
            "execution": {k: v for k, v in job.spec.items() if k != "fingerprint"},
        }

    def status(self, client, job_id):
        require(client, "read")
        with self.db.sessions() as s:
            job = owned(s, Job, job_id, client)
            result = self.serialize(job)
            if job.state == "queued":
                result["queue_position"] = s.scalar(
                    select(func.count())
                    .select_from(Job)
                    .where(Job.state == "queued", Job.created <= job.created)
                )
                result["queue_note"] = (
                    "Global FIFO position; per-client active quotas can cause eligible jobs to pass blocked jobs."
                )
            return result

    def list_jobs(self, client, offset=0, limit=50):
        require(client, "read")
        with self.db.sessions() as s:
            query = select(Job)
            if "admin" not in client.scopes:
                query = query.where(Job.owner == client.id)
            return [
                self.serialize(j)
                for j in s.scalars(
                    query.order_by(Job.created.desc()).offset(offset).limit(min(limit, 100))
                )
            ]

    def cancel(self, client, job_id):
        require(client, "build")
        with self.db.transaction() as s:
            job = owned(s, Job, job_id, client)
            if job.state == "queued":
                job.state, job.finished = "cancelled", time.time()
            elif job.state in ACTIVE:
                job.state = "cancelling"
            return self.serialize(job)

    def logs(self, client, job_id, offset=0, limit=65536):
        self.status(client, job_id)
        path = self.config.data_dir / "jobs" / job_id / "build.log"
        if not path.exists():
            return {"text": "", "next_offset": offset, "eof": True}
        with path.open("rb") as stream:
            stream.seek(offset)
            data = stream.read(min(limit, 65536))
        return {
            "text": data.decode(errors="replace"),
            "next_offset": offset + len(data),
            "eof": offset + len(data) >= path.stat().st_size,
        }

    def artifacts(self, client, job_id):
        return self.status(client, job_id)["artifacts"]

    def artifact(self, client, job_id, artifact_id):
        items = self.artifacts(client, job_id)
        item = next((a for a in items if a["id"] == artifact_id), None)
        if not item:
            raise ServiceError("not_found", "Artifact not found", 404)
        path = self.config.data_dir / "jobs" / job_id / "artifacts" / artifact_id
        if not path.is_file() or path.is_symlink():
            raise ServiceError("not_found", "Artifact expired or unavailable", 404)
        return path, item

    def queue(self, client):
        require(client, "read")
        with self.db.sessions() as s:
            all_jobs = s.scalars(select(Job).where(Job.state.in_(ACTIVE | {"queued"}))).all()
            return {
                "queued": sum(j.state == "queued" for j in all_jobs),
                "active": sum(j.state in ACTIVE for j in all_jobs),
                "available_workers": max(
                    0, self.config.max_workers - sum(j.state in ACTIVE for j in all_jobs)
                ),
                "client_queued": sum(
                    j.state == "queued" and j.owner == client.id for j in all_jobs
                ),
                "max_workers": self.config.max_workers,
                "estimated_wait_seconds": None,
                "disk_free_bytes": shutil.disk_usage(self.config.data_dir).free,
            }

    def check_disk(self):
        if shutil.disk_usage(self.config.data_dir).free < self.config.storage_reserve_mb * 1024**2:
            raise ServiceError(
                "disk_pressure", "Server storage reserve reached", 503, retryable=True
            )

    def delete_project(self, client, project_id):
        require(client, "build")
        with self.db.transaction() as s:
            project = owned(s, Project, project_id, client)
            active = s.scalar(
                select(Job).where(Job.project == project_id, Job.state.not_in(TERMINAL))
            )
            if active:
                raise ServiceError("project_busy", "Project has pending jobs", 409)
            s.delete(project)
        shutil.rmtree(self.config.data_dir / "projects" / project_id, ignore_errors=True)
        return {"deleted": True}
