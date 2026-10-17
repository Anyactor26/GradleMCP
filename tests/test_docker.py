"""Real builds: opt-in, never replaced by simulated build results."""

import io
import os
import time
import zipfile
from pathlib import Path

import pytest

from gradlemcp.config import Toolchain
from gradlemcp.scheduler import Scheduler
from gradlemcp.service import BuildRequest
from gradlemcp.worker import DockerWorker

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        os.getenv("GRADLEMCP_DOCKER_TESTS") != "1",
        reason="requires Docker and provisioned worker images",
    ),
]


def upload_example(service, client, name):
    stream = io.BytesIO()
    root = Path("examples") / name
    with zipfile.ZipFile(stream, "w") as archive:
        for path in root.rglob("*"):
            if (
                path.is_file()
                and "build" not in path.relative_to(root).parts
                and ".gradle" not in path.parts
            ):
                archive.write(path, path.relative_to(root))
    return service.upload(client, stream.getvalue())["project_id"]


def wait(service, client, job_id, states, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = service.status(client, job_id)
        if result["state"] in states:
            return result
        time.sleep(0.2)
    raise AssertionError(
        f"Timed out waiting: {service.status(client, job_id)} {service.logs(client, job_id)}"
    )


@pytest.fixture
def real_scheduler(service):
    service.config.workspace_mb = 1024
    service.config.memory_mb = service.config.total_memory_mb = 3072
    worker = DockerWorker(service.config)
    assert worker.available(), (
        "Docker unavailable: do not silently skip requested integration tests"
    )
    scheduler = Scheduler(service, worker)
    scheduler.start()
    yield scheduler
    scheduler.stop()


@pytest.mark.parametrize("name", ["groovy", "kotlin-dsl", "multi"])
def test_real_build_and_artifacts(service, client, real_scheduler, name):
    project = upload_example(service, client, name)
    result = service.submit(client, BuildRequest(project_id=project))
    done = wait(service, client, result["id"], {"succeeded", "failed", "resource_limit_exceeded"})
    assert done["state"] == "succeeded", service.logs(client, result["id"])
    assert any(a["path"].endswith(".jar") for a in done["artifacts"])
    for item in done["artifacts"]:
        path, _ = service.artifact(client, result["id"], item["id"])
        assert path.stat().st_size == item["size"]


def test_real_failure(service, client, real_scheduler):
    project = upload_example(service, client, "failing")
    result = service.submit(client, BuildRequest(project_id=project))
    done = wait(service, client, result["id"], {"failed"})
    assert done["diagnostic"]["code"] == "gradle_failed"
    assert "Intentional demonstration failure" in service.logs(client, result["id"])["text"]


def test_real_queue_cancellation_and_timeout(service, client, real_scheduler):
    project = upload_example(service, client, "groovy")
    one = service.submit(client, BuildRequest(project_id=project, tasks=["slow"]))
    wait(service, client, one["id"], {"running"})
    two = service.submit(client, BuildRequest(project_id=project))
    time.sleep(1)
    assert service.status(client, two["id"])["state"] == "queued"
    service.cancel(client, one["id"])
    wait(service, client, one["id"], {"cancelled"})
    wait(service, client, two["id"], {"succeeded"})
    service.config.timeout_seconds = 2
    three = service.submit(client, BuildRequest(project_id=project, tasks=["slow"]))
    wait(service, client, three["id"], {"timed_out"})


def test_real_concurrency(service, client, real_scheduler):
    service.config.max_workers = 2
    service.config.per_client_active = 2
    # Thread pool was constructed with one slot: replace before any jobs are submitted.
    import concurrent.futures

    real_scheduler.pool.shutdown()
    real_scheduler.pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    project = upload_example(service, client, "groovy")
    jobs = [
        service.submit(client, BuildRequest(project_id=project, tasks=["slow"])) for _ in range(2)
    ]
    for job in jobs:
        wait(service, client, job["id"], {"running"})
    assert service.queue(client)["active"] == 2
    for job in jobs:
        service.cancel(client, job["id"])
    for job in jobs:
        wait(service, client, job["id"], {"cancelled"})


@pytest.mark.skipif(
    not os.getenv("GRADLEMCP_JAVA21_IMAGE"), reason="optional Java 21 worker image not configured"
)
def test_alternative_jdk(service, client, real_scheduler):
    service.config.toolchains["java21"] = Toolchain(
        image=os.environ["GRADLEMCP_JAVA21_IMAGE"], java=21, gradle="8.14.3"
    )
    project = upload_example(service, client, "multi")
    result = service.submit(client, BuildRequest(project_id=project, java=21))
    assert wait(service, client, result["id"], {"succeeded", "failed"})["state"] == "succeeded"
