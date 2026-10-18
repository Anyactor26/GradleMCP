import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from gradlemcp.api import create_app
from gradlemcp.config import Settings


@pytest.fixture
def config(tmp_path):
    return Settings(
        data_dir=tmp_path, database_url=f"sqlite:///{tmp_path}/test.db", storage_reserve_mb=0
    )


@pytest.fixture
def app(config):
    return create_app(config, start_scheduler=False)


@pytest.fixture
def service(app):
    return app.state.service


@pytest.fixture
def token(service):
    return service.db.create_credential("agent", ["read", "build"])


@pytest.fixture
def client(service, token):
    return service.db.authenticate(token)


@pytest.fixture
def http(app, token):
    with TestClient(
        app, base_url="http://localhost:8000", headers={"Authorization": "Bearer " + token}
    ) as http:
        yield http


def archive(files=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as z:
        for name, content in (files or {"build.gradle": "plugins { id 'java' }"}).items():
            z.writestr(name, content)
    return output.getvalue()


@pytest.fixture
def project(service, client):
    return service.upload(client, archive())["project_id"]
