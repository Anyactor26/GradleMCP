import time

import pytest
from conftest import archive

from gradlemcp.config import Toolchain
from gradlemcp.db import Job
from gradlemcp.errors import ServiceError
from gradlemcp.scheduler import Scheduler
from gradlemcp.service import BuildRequest


class FakeWorker:
    def __init__(self):
        self.cleaned = []

    def cleanup(self, identifier):
        self.cleaned.append(identifier)


def test_http_lifecycle(http):
    result = http.post(
        "/api/v1/projects", content=archive(), headers={"Content-Type": "application/zip"}
    )
    assert result.status_code == 201
    project = result.json()["project_id"]
    result = http.post("/api/v1/builds", json={"project_id": project, "idempotency_key": "one"})
    assert result.status_code == 202
    identifier = result.json()["id"]
    duplicate = http.post("/api/v1/builds", json={"project_id": project, "idempotency_key": "one"})
    assert duplicate.json()["id"] == identifier
    assert http.get(f"/api/v1/builds/{identifier}").json()["state"] == "queued"
    assert http.get("/api/v1/queue").json()["queued"] == 1
    assert http.get(f"/api/v1/builds/{identifier}/logs").json()["text"] == ""
    assert http.post(f"/api/v1/builds/{identifier}/cancel").json()["state"] == "cancelled"
    assert http.get(f"/api/v1/builds/{identifier}/artifacts/fake").status_code == 404
    assert http.get("/health", headers={"Authorization": ""}).status_code == 200
    assert http.get("/api/v1/metrics").status_code == 403


def test_queue_fifo_and_capacity(service, client, project):
    jobs = [service.submit(client, BuildRequest(project_id=project)) for _ in range(3)]
    scheduler = Scheduler(service, FakeWorker())
    first = scheduler.claim()
    assert first.id == jobs[0]["id"]
    assert scheduler.claim() is None
    service.cancel(client, first.id)
    assert service.status(client, first.id)["state"] == "cancelling"
    with service.db.transaction() as s:
        job = s.get(Job, first.id)
        job.state = "cancelled"
    assert scheduler.claim().id == jobs[1]["id"]
    scheduler.pool.shutdown()


def test_fairness(service, client, project):
    service.config.max_workers = 2
    service.config.total_memory_mb = 4096
    one = service.submit(client, BuildRequest(project_id=project))
    blocked = service.submit(client, BuildRequest(project_id=project))
    other = service.db.authenticate(service.db.create_credential("other", ["read", "build"]))
    other_project = service.upload(other, archive())["project_id"]
    eligible = service.submit(other, BuildRequest(project_id=other_project))
    scheduler = Scheduler(service, FakeWorker())
    assert scheduler.claim().id == one["id"]
    assert scheduler.claim().id == eligible["id"]
    assert service.status(client, blocked["id"])["state"] == "queued"
    scheduler.pool.shutdown()


def test_quota_and_idempotency_conflict(service, client, project):
    service.config.per_client_queued = 1
    service.submit(client, BuildRequest(project_id=project, idempotency_key="x"))
    with pytest.raises(ServiceError) as exc:
        service.submit(
            client, BuildRequest(project_id=project, tasks=["test"], idempotency_key="x")
        )
    assert exc.value.status == 409
    with pytest.raises(ServiceError) as exc:
        service.submit(client, BuildRequest(project_id=project))
    assert exc.value.status == 429


def test_restart_recovery(service, client, project):
    running = service.submit(client, BuildRequest(project_id=project))
    queued = service.submit(client, BuildRequest(project_id=project))
    worker = FakeWorker()
    scheduler = Scheduler(service, worker)
    scheduler.claim()
    # Keep dispatch from consuming the persisted queued job during this recovery assertion.
    scheduler.stop_event.set()
    scheduler.start()
    scheduler.thread.join()
    assert service.status(client, running["id"])["diagnostic"]["code"] == "server_interrupted"
    assert service.status(client, queued["id"])["state"] == "queued"
    assert running["id"] in worker.cleaned
    scheduler.stop()


def test_inspection_and_toolchain(service, client):
    data = archive(
        {
            "settings.gradle.kts": 'include(":app"); includeBuild("logic")',
            "app/build.gradle.kts": "java { toolchain { languageVersion = JavaLanguageVersion.of(21) } }",
            "gradle/libs.versions.toml": "[versions]",
        }
    )
    project = service.upload(client, data)
    inspection = project["inspection"]
    assert inspection["java_hints"] == [21] and inspection["composite"]
    request = BuildRequest(project_id=project["project_id"])
    with pytest.raises(ServiceError, match="No approved"):
        service.compatibility(client, request)
    service.config.toolchains["java21"] = Toolchain(image="approved:21", java=21, gradle="8.14.3")
    assert service.compatibility(client, request)["toolchain"] == "java21"


@pytest.mark.parametrize(
    "url",
    [
        "http://services.gradle.org/distributions/gradle-8.14.3-bin.zip",
        "https://127.0.0.1/distributions/gradle-8.14.3-bin.zip",
        "https://services.gradle.org.evil.test/distributions/gradle-8.14.3-bin.zip",
        "https://services.gradle.org/distributions/gradle-8.14.3-bin.zip?evil=1",
    ],
)
def test_wrapper_rejects(service, client, url):
    project = service.upload(
        client,
        archive(
            {
                "build.gradle": "",
                "gradlew": "",
                "gradle/wrapper/gradle-wrapper.jar": "",
                "gradle/wrapper/gradle-wrapper.properties": f"distributionUrl={url}\ndistributionSha256Sum={'a' * 64}",
            }
        ),
    )
    assert not project["inspection"]["wrapper"]["valid"]


def test_valid_wrapper(service, client):
    project = service.upload(
        client,
        archive(
            {
                "build.gradle": "",
                "gradlew": "",
                "gradle/wrapper/gradle-wrapper.jar": "",
                "gradle/wrapper/gradle-wrapper.properties": f"distributionUrl=https\\://services.gradle.org/distributions/gradle-8.14.3-bin.zip\ndistributionSha256Sum={'a' * 64}",
            }
        ),
    )
    assert project["inspection"]["wrapper"]["valid"]
    service.config.wrapper_enabled = True
    selected = service.submit(client, BuildRequest(project_id=project["project_id"]))
    assert selected["execution"]["use_wrapper"] is True
    managed = service.submit(
        client, BuildRequest(project_id=project["project_id"], use_wrapper=False)
    )
    assert managed["execution"]["use_wrapper"] is False


def test_artifact_authorization_and_paging(service, client, project, http):
    job = service.submit(client, BuildRequest(project_id=project))
    directory = service.config.data_dir / "jobs" / job["id"]
    (directory / "artifacts").mkdir(parents=True)
    (directory / "artifacts" / "opaque").write_bytes(b"jar-data")
    (directory / "build.log").write_text("abcdefgh")
    with service.db.transaction() as s:
        saved = s.get(Job, job["id"])
        saved.artifacts = [{"id": "opaque", "path": "build/a.jar", "size": 8}]
        saved.state, saved.finished = "succeeded", time.time()
    assert http.get(f"/api/v1/builds/{job['id']}/artifacts/opaque").content == b"jar-data"
    assert service.logs(client, job["id"], 2, 3)["text"] == "cde"
    assert http.get(f"/api/v1/builds/{job['id']}/logs?offset=-1").status_code == 422


def test_retention(service, client, project):
    job = service.submit(client, BuildRequest(project_id=project))
    directory = service.config.data_dir / "jobs" / job["id"]
    directory.mkdir()
    with service.db.transaction() as s:
        saved = s.get(Job, job["id"])
        saved.state, saved.finished = "succeeded", 0
    scheduler = Scheduler(service, FakeWorker())
    scheduler.cleanup_expired()
    assert not directory.exists()
    scheduler.pool.shutdown()


def test_task_result_diagnostics():
    from gradlemcp.diagnostics import diagnose

    assert diagnose("Could not resolve dependency", 1)["code"] == "dependency_resolution"
    assert diagnose("SDK location not found", 1)["code"] == "android_sdk_missing"
    assert diagnose("There were failing tests", 1)["code"] == "tests_failed"


def test_endpoint_states(config):
    from gradlemcp.endpoint import endpoint_status

    assert endpoint_status(config)["connection_status"] == "private"
    config.exposure = "cloudflare"
    assert endpoint_status(config)["connection_status"] == "not_probed"
