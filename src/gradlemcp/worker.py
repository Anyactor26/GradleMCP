"""Docker CLI adapter. No fallback to host execution is permitted."""

import fnmatch
import hashlib
import json
import os
import selectors
import subprocess
import tarfile
import threading
import time
from pathlib import PurePosixPath

from .diagnostics import diagnose, redact
from .errors import ServiceError


class DockerWorker:
    def __init__(self, config):
        self.config = config

    def command(self, *args, timeout=60, check=True):
        try:
            result = subprocess.run(["docker", *args], capture_output=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ServiceError(
                "worker_unavailable",
                "Docker is unavailable or did not respond",
                503,
                retryable=True,
            ) from exc
        if check and result.returncode:
            raise ServiceError(
                "worker_error",
                "Docker operation failed; inspect administrator Docker logs",
                503,
                retryable=True,
            )
        return result

    def available(self):
        try:
            return self.command("info", "--format", "{{.ServerVersion}}", timeout=5).returncode == 0
        except ServiceError:
            return False

    def cleanup(self, job_id):
        name = "gradlemcp-" + job_id
        self.command("rm", "-f", name, check=False)
        result = self.command("ps", "-aq", "--filter", f"name=^/{name}$")
        if result.stdout.strip():
            raise ServiceError(
                "termination_unconfirmed", "Worker termination could not be confirmed", 503
            )

    def execute(self, job, state, running):
        c = self.config
        name = "gradlemcp-" + job.id
        work = c.data_dir / "jobs" / job.id
        work.mkdir(parents=True, exist_ok=True, mode=0o700)
        profile = c.toolchains[job.spec["toolchain"]]
        if c.auto_pull:
            self.command("pull", profile.image, timeout=c.timeout_seconds)
        metadata = json.loads(self.command("image", "inspect", profile.image).stdout)[0]
        if metadata.get("Config", {}).get("Volumes"):
            raise ServiceError(
                "unsafe_worker_image",
                "Worker images must not declare Docker VOLUME paths; use the supplied multi-stage worker image",
            )
        env = ["--env", "HOME=/tmp", "--env", "GRADLE_USER_HOME=/workspace/.gradle-cache"]
        publication = job.spec.get("publication", False)
        if publication:
            # docker --env-file avoids credentials in argv; Docker admins can inspect them.
            env += ["--env-file", str(c.publish_secrets_file.resolve())]
        self.command(
            "create",
            "--name",
            name,
            "--label",
            "gradlemcp.job=" + job.id,
            "--read-only",
            "--user",
            "1000:1000",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--memory",
            f"{c.memory_mb}m",
            "--memory-swap",
            f"{c.memory_mb}m",
            "--cpus",
            str(c.cpus),
            "--pids-limit",
            str(c.pids),
            "--network",
            c.network,
            "--log-driver",
            "none",
            "--ulimit",
            "nofile=4096:4096",
            "--tmpfs",
            f"/workspace:rw,exec,nosuid,nodev,size={c.workspace_mb}m,mode=1777",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=64m,mode=1777",
            "--workdir",
            "/workspace",
            *env,
            "--entrypoint",
            "/bin/sh",
            profile.image,
            "-c",
            "exec sleep infinity",
        )
        process = None
        try:
            self.command("start", name)
            source = (c.data_dir / "projects" / job.project).resolve()
            self.stage_source(name, source)
            if state() == "cancelling":
                return "cancelled", None, {}, []
            running()
            cwd = (
                "/workspace"
                if job.spec["subdirectory"] == "."
                else "/workspace/" + job.spec["subdirectory"]
            )
            executable = ["sh", "./gradlew"] if job.spec["use_wrapper"] else ["gradle"]
            args = [
                "docker",
                "exec",
                "--workdir",
                cwd,
                name,
                *executable,
                "--no-daemon",
                "--console=plain",
                "--stacktrace",
                f"--max-workers={max(1, int(c.cpus))}",
                *job.spec["tasks"],
            ]
            process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            assert process.stdout is not None
            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ)
            start = time.monotonic()
            captured = 0
            tail = ""
            outcome = None
            with (work / "build.log").open("wb") as log:
                if publication:
                    log.write(
                        b"Publication output suppressed to protect injected secrets; artifacts are not exported.\n"
                    )
                while True:
                    if state() == "cancelling":
                        outcome = "cancelled"
                        break
                    if time.monotonic() - start > c.timeout_seconds:
                        outcome = "timed_out"
                        break
                    for key, _ in selector.select(timeout=0.2):
                        chunk = os.read(key.fd, 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                        elif not publication:
                            text = redact(chunk.decode(errors="replace"))
                            tail = (tail + text)[-131072:]
                            data = text.encode()[: max(0, c.log_mb * 1024**2 - captured)]
                            log.write(data)
                            log.flush()
                            captured += len(data)
                    if process.poll() is not None and not selector.get_map():
                        break
            selector.close()
            if outcome:
                return (
                    outcome,
                    None,
                    {"code": outcome, "message": "Worker stopped: " + outcome, "retryable": False},
                    [],
                )
            code = process.wait(timeout=5)
            info = self.command("inspect", name)
            oom = json.loads(info.stdout)[0]["State"].get("OOMKilled", False)
            if oom or code == 137:
                return (
                    "resource_limit_exceeded",
                    code,
                    {
                        "code": "worker_memory_limit",
                        "message": "Worker killed, likely memory limit; inspect Docker events",
                        "retryable": False,
                    },
                    [],
                )
            artifacts = [] if publication else self.collect(name, job, work)
            if code:
                return (
                    "failed",
                    code,
                    (
                        {
                            "code": "publication_failed",
                            "message": "Publication failed; check destination before retrying",
                        }
                        if publication
                        else diagnose(tail, code)
                    ),
                    artifacts,
                )
            return "succeeded", code, {}, artifacts
        finally:
            # Kill the whole container, not only the docker exec client.
            self.cleanup(job.id)
            if process:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                if process.stdout:
                    process.stdout.close()

    def stage_source(self, name, source):
        # Extract as the worker UID, not privileged chown/CAP_CHOWN. No host bind mount.
        process = subprocess.Popen(
            [
                "docker",
                "exec",
                "-i",
                name,
                "tar",
                "--no-same-owner",
                "-C",
                "/workspace",
                "-xf",
                "-",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        timer = threading.Timer(120, process.kill)
        timer.start()
        try:
            with tarfile.open(fileobj=process.stdin, mode="w|") as archive:
                # Do not include the tmpfs root header: it belongs to root, and an
                # unprivileged tar must not try to restore its mode/ownership.
                for child in sorted(source.iterdir()):
                    archive.add(child, arcname=child.name, recursive=True)
            if process.stdin:
                process.stdin.close()
            if process.wait(timeout=5):
                raise ServiceError(
                    "source_copy_failed", "Could not stage source into isolated workspace"
                )
        finally:
            timer.cancel()
            if process.poll() is None:
                process.kill()
            process.wait()
            if process.stdin:
                process.stdin.close()

    def collect(self, name, job, work):
        # Stream tar without extracting paths. Reject sparse/oversized members before reading.
        # A tmpfs bounds physical space, not sparse files' logical length.
        process = subprocess.Popen(
            ["docker", "exec", name, "tar", "-C", "/workspace", "-cf", "-", "."],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        timer = threading.Timer(120, process.kill)
        timer.start()
        target = work / "artifacts"
        target.mkdir(exist_ok=True)
        result: list[dict] = []
        total = exported = entries = 0
        prefix = PurePosixPath(job.spec["subdirectory"])
        try:
            with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
                for member in archive:
                    entries += 1
                    path = PurePosixPath(member.name)
                    if path.is_absolute() or ".." in path.parts:
                        raise ServiceError(
                            "unsafe_artifact", "Worker returned an unsafe output path"
                        )
                    total += member.size
                    if (
                        total > self.config.workspace_mb * 1024**2
                        or entries > self.config.max_files
                    ):
                        raise ServiceError(
                            "output_limit", "Worker output exceeds logical size or file count limit"
                        )
                    if not member.isfile() or member.issparse():
                        continue
                    try:
                        relative = path.relative_to(prefix)
                    except ValueError:
                        continue
                    if ".gradle-cache" in relative.parts or not any(
                        fnmatch.fnmatchcase(relative.as_posix(), p)
                        or fnmatch.fnmatchcase(relative.as_posix(), p.removeprefix("**/"))
                        for p in job.spec["artifact_patterns"]
                    ):
                        continue
                    exported += member.size
                    if exported > self.config.artifact_mb * 1024**2:
                        raise ServiceError(
                            "artifact_limit",
                            "Selected artifacts exceed export limit",
                            remediation="Select narrower artifact patterns",
                        )
                    identifier = hashlib.sha256(relative.as_posix().encode()).hexdigest()[:32]
                    stream = archive.extractfile(member)
                    if stream is None:
                        continue
                    digest = hashlib.sha256()
                    with (target / identifier).open("xb") as output:
                        while chunk := stream.read(65536):
                            output.write(chunk)
                            digest.update(chunk)
                    result.append(
                        {
                            "id": identifier,
                            "path": relative.as_posix(),
                            "size": member.size,
                            "sha256": digest.hexdigest(),
                        }
                    )
            if process.wait(timeout=5):
                raise ServiceError(
                    "artifact_export_failed", "Worker artifact export failed or timed out"
                )
            return result
        finally:
            timer.cancel()
            if process.poll() is None:
                process.kill()
            process.wait()
            if process.stdout:
                process.stdout.close()
