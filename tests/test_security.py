import io
import stat
import zipfile

import pytest
from conftest import archive
from pydantic import ValidationError

from gradlemcp.config import Settings
from gradlemcp.diagnostics import redact
from gradlemcp.errors import ServiceError
from gradlemcp.service import BuildRequest
from gradlemcp.source import extract_zip


def test_config_limits():
    with pytest.raises(ValidationError):
        Settings(max_workers=2)
    with pytest.raises(ValidationError):
        Settings(public_url="http://unsafe.test")
    with pytest.raises(ValidationError):
        Settings(publish_tasks=["publish"])


@pytest.mark.parametrize("path", ["../escape", "/absolute", "a/../../escape", "C:/escape", "a\\b"])
def test_archive_traversal(config, tmp_path, path):
    with pytest.raises(ServiceError, match="Unsafe"):
        extract_zip(archive({path: "x"}), tmp_path / "out", config)
    assert not (tmp_path / "escape").exists()


def test_symlink(config, tmp_path):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as z:
        info = zipfile.ZipInfo("link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        z.writestr(info, "/etc/passwd")
    with pytest.raises(ServiceError):
        extract_zip(stream.getvalue(), tmp_path / "out", config)


def test_malformed_and_oversized(config, tmp_path):
    for data in [b"invalid", b"x" * (config.upload_mb * 1024**2 + 1)]:
        with pytest.raises(ServiceError):
            extract_zip(data, tmp_path / "out", config)


def test_decompression_limit(config, tmp_path):
    config.workspace_mb = 16
    with pytest.raises(ServiceError):
        extract_zip(archive({"bomb": "x" * (9 * 1024**2)}), tmp_path / "out", config)


@pytest.mark.parametrize(
    "task", ["--init-script=evil", "build;id", "$(id)", "build\nexec", "-Dsecret=x"]
)
def test_task_injection(task):
    with pytest.raises(ValidationError):
        BuildRequest(project_id="id", tasks=[task])


def test_revocation(service, token):
    service.db.revoke("agent")
    with pytest.raises(ServiceError) as error:
        service.db.authenticate(token)
    assert error.value.status == 401


def test_invalid_credentials(http):
    assert http.get("/api/v1/queue", headers={"Authorization": "Bearer invalid"}).status_code == 401


def test_cross_client_access(service, client, project):
    other = service.db.authenticate(service.db.create_credential("other", ["read", "build"]))
    job = service.submit(client, BuildRequest(project_id=project))
    with pytest.raises(ServiceError) as error:
        service.status(other, job["id"])
    assert error.value.status == 404
    with pytest.raises(ServiceError):
        service.artifact(other, job["id"], "../secret")


def test_scopes(service):
    readonly = service.db.authenticate(service.db.create_credential("reader", ["read"]))
    with pytest.raises(ServiceError):
        service.upload(readonly, archive())


def test_redaction():
    result = redact("token xyz Bearer abc https://user:pass@host", ["xyz"])
    assert "xyz" not in result and "abc" not in result and "pass@" not in result


def test_publishing_disabled(service, client, project):
    with pytest.raises(ServiceError) as error:
        service.submit(
            client, BuildRequest(project_id=project, tasks=["publish"]), publication=True
        )
    assert error.value.status == 403


def test_origin(http):
    assert http.get("/api/v1/queue", headers={"Origin": "https://evil.invalid"}).status_code == 403


def test_base64_validation(service, client):
    with pytest.raises(ServiceError):
        service.upload_base64(client, "not base64!")


def test_request_errors_do_not_echo_secrets(http):
    result = http.post(
        "/api/v1/builds", json={"project_id": "id", "tasks": ["--password=super-secret"]}
    )
    assert result.status_code == 422
    assert "super-secret" not in result.text


def test_rotation_preserves_ownership_and_revokes_old_token(service, client, token, project):
    result = service.submit(client, BuildRequest(project_id=project))
    replacement = service.db.rotate_credential("agent", ["read", "build", "publish"])
    with pytest.raises(ServiceError):
        service.db.authenticate(token)
    rotated = service.db.authenticate(replacement)
    assert "publish" in rotated.scopes
    assert service.status(rotated, result["id"])["owner"] == "agent"
