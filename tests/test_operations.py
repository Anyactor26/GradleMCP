import json
import logging

import httpx
import pytest
from pydantic import ValidationError

from gradlemcp.config import Settings, load_settings
from gradlemcp.endpoint import endpoint_status
from gradlemcp.errors import ServiceError
from gradlemcp.observability import JsonFormatter
from gradlemcp.service import BuildRequest


def test_precedence(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"port": 9000}))
    monkeypatch.setenv("GRADLEMCP_CONFIG", str(path))
    monkeypatch.setenv("GRADLEMCP_PORT", "9001")
    assert load_settings().port == 9001
    assert load_settings(port=9002).port == 9002


def test_network_and_image_policy():
    for network in ["host", "bridge", "default", "container:other"]:
        with pytest.raises(ValidationError):
            Settings(network=network)
    with pytest.raises(ValidationError):
        Settings(auto_pull=True)
    settings = Settings(
        auto_pull=True,
        toolchains={
            "java17": {
                "image": "approved/image@sha256:" + "a" * 64,
                "java": 17,
                "gradle": "8.14.3",
            }
        },
    )
    assert settings.auto_pull


def test_endpoint_allowlists_must_be_specific_and_valid():
    with pytest.raises(ValidationError):
        Settings(public_url="https://example.org:70000")
    for host in (
        "*",
        "*.example.org:*",
        "-bad.example.org",
        "https://example.org",
        "example.org:70000",
        "[::::]:*",
        "bad host",
    ):
        with pytest.raises(ValidationError):
            Settings(mcp_allowed_hosts=[host])
    assert Settings(
        mcp_allowed_hosts=["builds.example.org:*", "198.51.100.9:8000", "[2001:db8::1]:*"]
    ).mcp_allowed_hosts
    for origin in (
        "*",
        "http://*",
        "https://example.org/path",
        "http://example.org:80:*",
        "ftp://example.org",
    ):
        with pytest.raises(ValidationError):
            Settings(mcp_allowed_origins=[origin])
    assert Settings(mcp_allowed_origins=["http://198.51.100.9:*"]).mcp_allowed_origins


def test_rate_limit(http, service):
    service.config.requests_per_minute = 1
    assert http.get("/api/v1/queue").status_code == 200
    result = http.get("/api/v1/queue")
    assert result.status_code == 429 and result.json()["error"]["retryable"]


def test_body_limit(http, service):
    service.config.upload_mb = 1
    response = http.post("/api/v1/projects", content=b"x" * (2 * 1024**2))
    assert response.status_code == 413


def test_ngrok_status_reports_changes(monkeypatch, config):
    config.exposure = "ngrok"
    config.tunnel_status_url = "http://local-agent/api/tunnels"
    answers = iter(
        [
            {"tunnels": [{"public_url": "https://one.example"}]},
            {"tunnels": [{"public_url": "https://two.example"}]},
            {"tunnels": []},
        ]
    )
    real_client = httpx.Client
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=next(answers)))
    monkeypatch.setattr(
        "gradlemcp.endpoint.httpx.Client",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )
    assert endpoint_status(config)["public_url"] == "https://one.example"
    assert endpoint_status(config)["public_url"] == "https://two.example"
    assert endpoint_status(config)["connection_status"] == "disconnected"


def test_json_logs():
    record = logging.LogRecord("gradlemcp", logging.INFO, "", 0, '{"event":"a"}', (), None)
    assert json.loads(JsonFormatter().format(record))["event"] == "a"
    record.msg = 'plain "quoted" message'
    assert json.loads(JsonFormatter().format(record))["message"] == record.msg


def test_no_source_delete_while_queued(service, client, project):
    service.submit(client, BuildRequest(project_id=project))
    with pytest.raises(ServiceError) as error:
        service.delete_project(client, project)
    assert error.value.status == 409


def test_source_export_reservation(service, client, project):
    service.config.per_client_queued = 1
    # A retained source quota remains distinct from active/queued job quotas.
    from conftest import archive

    for _ in range(3):
        service.upload(client, archive())
    with pytest.raises(ServiceError) as error:
        service.upload(client, archive())
    assert error.value.body["code"] == "project_quota"


def test_cli_never_echoes_invalid_secret_config(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    path = tmp_path / "bad-config.json"
    path.write_text(
        json.dumps({"database_url": "postgresql://user:do-not-leak@host/db", "port": "do-not-leak"})
    )
    result = subprocess.run(
        [str(Path(sys.executable).parent / "gradlemcp"), "config", "validate"],
        env=os.environ | {"GRADLEMCP_CONFIG": str(path)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "do-not-leak" not in result.stdout + result.stderr


def test_publish_secret_file_permissions(tmp_path):
    path = tmp_path / "publication.env"
    path.write_text("TOKEN=not-a-real-token")
    path.chmod(0o644)
    with pytest.raises(ValidationError):
        Settings(publish_secrets_file=path)
    path.chmod(0o600)
    assert Settings(publish_secrets_file=path).publish_secrets_file == path


def test_publication_policy_and_metadata(service, client, project):
    from gradlemcp.config import Toolchain
    from gradlemcp.db import Job
    from gradlemcp.mcp_adapter import create_mcp

    first = service.submit(client, BuildRequest(project_id=project))
    with service.db.transaction() as session:
        session.get(Job, first["id"]).state = "succeeded"
    service.config.toolchains["release"] = Toolchain(
        image="approved-release:17", java=17, gradle="8.14.3"
    )
    service.config.publish_tasks = [":library:publish"]
    service.config.publish_toolchain = "release"
    _, publish = create_mcp(service)
    with pytest.raises(ServiceError) as error:
        publish(client, first["id"], [":library:publish"], "release-1")
    assert error.value.status == 403
    client.scopes = [*client.scopes, "publish"]
    result = publish(client, first["id"], [":library:publish"], "release-1")
    assert result["execution"]["publication"]
    assert result["execution"]["toolchain"] == "release"
    with pytest.raises(ServiceError):
        publish(client, first["id"], ["notApproved"], "release-2")
    with pytest.raises(ServiceError):
        service.submit(client, BuildRequest(project_id=project, toolchain="release"))


def test_admin_cross_client_status(service, client, project):
    result = service.submit(client, BuildRequest(project_id=project))
    admin = service.db.authenticate(service.db.create_credential("operator", ["admin"]))
    assert service.status(admin, result["id"])["owner"] == client.id
