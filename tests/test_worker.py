"""Worker adapter tests with controlled local subprocesses, NOT real Gradle builds."""

import base64
import io
import json
import subprocess
import sys
import tarfile
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from gradlemcp.errors import ServiceError
from gradlemcp.scheduler import Scheduler
from gradlemcp.service import BuildRequest
from gradlemcp.worker import DockerWorker


def job(service, client, project):
    result = service.submit(client, BuildRequest(project_id=project))
    return SimpleNamespace(id=result["id"], project=project, spec=result["execution"])


def setup_worker(monkeypatch, config, output="print('example output')"):
    worker = DockerWorker(config)
    commands = []

    def command(*args, **kwargs):
        commands.append(args)
        data = b""
        if args[:2] == ("image", "inspect"):
            data = json.dumps([{"Config": {"Volumes": None}}]).encode()
        elif args[0] == "inspect":
            data = json.dumps([{"State": {"OOMKilled": False}}]).encode()
        return SimpleNamespace(stdout=data, returncode=0)

    real_popen = subprocess.Popen

    def popen(args, **kwargs):
        commands.append(tuple(args))
        return real_popen([sys.executable, "-c", output], **kwargs)

    monkeypatch.setattr(worker, "command", command)
    monkeypatch.setattr(worker, "stage_source", lambda *args: None)
    monkeypatch.setattr(worker, "collect", lambda *args: [])
    monkeypatch.setattr("gradlemcp.worker.subprocess.Popen", popen)
    return worker, commands


def test_worker_limits_and_no_host_execution(monkeypatch, config, service, client, project):
    worker, commands = setup_worker(monkeypatch, config)
    current = job(service, client, project)
    result = worker.execute(current, lambda: "running", lambda: None)
    assert result[0] == "succeeded"
    create = next(c for c in commands if c[0] == "create")
    for flag in (
        "--read-only",
        "--cap-drop",
        "--security-opt",
        "--pids-limit",
        "--memory",
        "--memory-swap",
        "--cpus",
        "--tmpfs",
    ):
        assert flag in create
    assert create[create.index("--network") + 1] == "none"
    assert create[create.index("--user") + 1] == "1000:1000"
    assert "--volume" not in create and "-v" not in create
    assert any(c[0] == "ps" for c in commands)
    assert "example output" in (config.data_dir / "jobs" / current.id / "build.log").read_text()


def test_timeout(monkeypatch, config, service, client, project):
    config.timeout_seconds = 1
    worker, _ = setup_worker(monkeypatch, config, "import time; time.sleep(1.3)")
    assert (
        worker.execute(job(service, client, project), lambda: "running", lambda: None)[0]
        == "timed_out"
    )


def test_cancellation(monkeypatch, config, service, client, project):
    worker, _ = setup_worker(monkeypatch, config, "import time; time.sleep(0.1)")
    states = iter(["preparing", "cancelling"])
    assert (
        worker.execute(job(service, client, project), lambda: next(states), lambda: None)[0]
        == "cancelled"
    )


def test_publication_output_suppressed(monkeypatch, config, service, client, project):
    config.publish_secrets_file = config.data_dir / "secrets.env"
    worker, commands = setup_worker(monkeypatch, config, "print('very-secret-publication-key')")
    current = job(service, client, project)
    current.spec["publication"] = True
    assert worker.execute(current, lambda: "running", lambda: None)[0] == "succeeded"
    log = (config.data_dir / "jobs" / current.id / "build.log").read_text()
    assert "very-secret" not in log
    create = next(c for c in commands if c[0] == "create")
    assert "--env-file" in create
    assert "very-secret" not in repr(commands)


def test_volume_image_rejected(monkeypatch, config, service, client, project):
    worker = DockerWorker(config)
    monkeypatch.setattr(
        worker,
        "command",
        lambda *args, **kwargs: SimpleNamespace(stdout=b'[{"Config":{"Volumes":{"/cache":{}}}}]'),
    )
    with pytest.raises(ServiceError) as error:
        worker.execute(job(service, client, project), lambda: "running", lambda: None)
    assert error.value.body["code"] == "unsafe_worker_image"


def test_cleanup_does_not_confuse_daemon_loss_with_absence(monkeypatch, config):
    worker = DockerWorker(config)

    def command(*args, **kwargs):
        if args[0] == "ps":
            raise ServiceError("worker_unavailable", "Docker lost")
        return SimpleNamespace(stdout=b"", returncode=1)

    monkeypatch.setattr(worker, "command", command)
    with pytest.raises(ServiceError):
        worker.cleanup("id")


def tar_bytes(name, content=b"output", symlink=False):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        info = tarfile.TarInfo(name)
        info.size = len(content)
        if symlink:
            info.type, info.linkname, info.size = tarfile.SYMTYPE, "/etc/passwd", 0
        archive.addfile(info, io.BytesIO(content) if not symlink else None)
    return output.getvalue()


@pytest.mark.parametrize(
    "name,symlink,expected",
    [
        ("build/libs/a.jar", False, 1),
        ("build/libs/link.jar", True, 0),
        ("../outside.jar", False, -1),
    ],
)
def test_artifact_export_safety(monkeypatch, config, tmp_path, name, symlink, expected):
    worker = DockerWorker(config)
    current = SimpleNamespace(spec={"subdirectory": ".", "artifact_patterns": ["**/build/libs/*"]})
    payload = base64.b64encode(tar_bytes(name, symlink=symlink)).decode()
    real_popen = subprocess.Popen
    monkeypatch.setattr(
        "gradlemcp.worker.subprocess.Popen",
        lambda args, **kwargs: real_popen(
            [
                sys.executable,
                "-c",
                f"import base64,sys;sys.stdout.buffer.write(base64.b64decode('{payload}'))",
            ],
            **kwargs,
        ),
    )
    if expected == -1:
        with pytest.raises(ServiceError):
            worker.collect("container", current, tmp_path)
    else:
        artifacts = worker.collect("container", current, tmp_path)
        assert len(artifacts) == expected
        if artifacts:
            assert (tmp_path / "artifacts" / artifacts[0]["id"]).read_bytes() == b"output"
    assert not (tmp_path.parent / "outside.jar").exists()


def test_atomic_idempotency_and_dispatch(service, client, project):
    request = BuildRequest(project_id=project, idempotency_key="parallel")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: service.submit(client, request), range(8)))
    assert len({r["id"] for r in results}) == 1
    scheduler = Scheduler(service, object())
    with ThreadPoolExecutor(max_workers=8) as pool:
        claimed = list(pool.map(lambda _: scheduler.claim(), range(8)))
    assert sum(c is not None for c in claimed) == 1
    scheduler.pool.shutdown()


def test_failed_confirmation_retains_capacity(service, client, project):
    current = service.submit(client, BuildRequest(project_id=project))

    class FailingWorker:
        def execute(self, *args):
            raise RuntimeError("worker failure")

        def cleanup(self, *args):
            raise ServiceError("worker_unavailable", "Docker lost")

    scheduler = Scheduler(service, FailingWorker())
    scheduler.run_job(scheduler.claim())
    status = service.status(client, current["id"])
    assert status["state"] == "cancelling"
    assert status["diagnostic"]["code"] == "termination_unconfirmed"
    assert scheduler.claim() is None
    scheduler.pool.shutdown()


def test_source_staging_has_no_root_metadata(monkeypatch, config, tmp_path):
    source = tmp_path / "source"
    (source / "nested").mkdir(parents=True)
    (source / "nested" / "build.gradle").write_text("plugins { id 'java' }")
    received = tmp_path / "received.json"
    real_popen = subprocess.Popen
    script = "import json,sys,tarfile;from pathlib import Path; a=tarfile.open(fileobj=sys.stdin.buffer, mode='r|'); Path(sys.argv[1]).write_text(json.dumps([m.name for m in a]))"
    monkeypatch.setattr(
        "gradlemcp.worker.subprocess.Popen",
        lambda args, **kwargs: real_popen([sys.executable, "-c", script, str(received)], **kwargs),
    )
    DockerWorker(config).stage_source("fixture-container", source)
    names = json.loads(received.read_text())
    assert "." not in names and "/" not in names
    assert "nested/build.gradle" in names


def test_artifact_logical_size_limit(monkeypatch, config, tmp_path):
    config.workspace_mb = 16
    member = tarfile.TarInfo("build/libs/sparse-like.jar")
    member.size = 32 * 1024**2
    payload = base64.b64encode(member.tobuf() + b"\0" * 1024).decode()
    real_popen = subprocess.Popen
    monkeypatch.setattr(
        "gradlemcp.worker.subprocess.Popen",
        lambda args, **kwargs: real_popen(
            [
                sys.executable,
                "-c",
                f"import base64,sys;sys.stdout.buffer.write(base64.b64decode('{payload}'))",
            ],
            **kwargs,
        ),
    )
    current = SimpleNamespace(spec={"subdirectory": ".", "artifact_patterns": ["**/*"]})
    with pytest.raises(ServiceError) as error:
        DockerWorker(config).collect("fixture", current, tmp_path)
    assert error.value.body["code"] == "output_limit"


def test_log_storage_cap(monkeypatch, config, service, client, project):
    config.log_mb = 1
    worker, _ = setup_worker(
        monkeypatch, config, "import sys;sys.stdout.write('x' * (2 * 1024**2))"
    )
    current = job(service, client, project)
    assert worker.execute(current, lambda: "running", lambda: None)[0] == "succeeded"
    assert (config.data_dir / "jobs" / current.id / "build.log").stat().st_size == 1024**2


def test_scheduler_singleton_lock(service):
    first = Scheduler(service, object())
    first.stop_event.set()
    first.start()
    first.thread.join()
    second = Scheduler(service, object())
    try:
        with pytest.raises(RuntimeError, match="Only one"):
            second.start()
        assert not first.lockfile.closed
    finally:
        first.stop()
