"""Exercise client programs against the real HTTP app with explicit terminal fixtures.

No Gradle execution is simulated or claimed: fixture output is labelled as such.
"""

import os
import shutil
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest
import uvicorn
from conftest import archive

from gradlemcp.db import Job


@pytest.fixture
def example_server(app, service, token, monkeypatch):
    original_submit = service.submit

    def complete_fixture(client, request, publication=False):
        result = original_submit(client, request, publication)
        directory = service.config.data_dir / "jobs" / result["id"]
        (directory / "artifacts").mkdir(parents=True)
        (directory / "artifacts" / "fixture").write_bytes(b"controlled artifact fixture")
        import hashlib
        import time

        artifact = {
            "id": "fixture",
            "path": "build/fixture.txt",
            "size": 27,
            "sha256": hashlib.sha256(b"controlled artifact fixture").hexdigest(),
        }
        failed = request.tasks == ["intentionalFailure"]
        (directory / "build.log").write_text("Controlled terminal fixture; not Gradle execution.\n")
        with service.db.transaction() as session:
            current = session.get(Job, result["id"])
            current.state = "failed" if failed else "succeeded"
            current.finished = time.time()
            current.artifacts = [] if failed else [artifact]
            current.diagnostic = {"code": "fixture_failure"} if failed else {}
        return result

    monkeypatch.setattr(service, "submit", complete_fixture)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    yield os.environ | {"GRADLEMCP_URL": f"http://127.0.0.1:{port}", "GRADLEMCP_TOKEN": token}
    server.should_exit = True
    thread.join(timeout=10)
    listener.close()
    assert not thread.is_alive()


def test_python_client(example_server, tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "examples/client.py",
            "examples/groovy",
            "--output",
            str(tmp_path / "outputs"),
        ],
        env=example_server,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        tmp_path / "outputs" / "fixture-fixture.txt"
    ).read_bytes() == b"controlled artifact fixture"


def test_python_diagnosis(example_server, tmp_path):
    result = subprocess.run(
        [sys.executable, "examples/client.py", "examples/groovy", "--task", "intentionalFailure"],
        env=example_server,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "fixture_failure" in result.stdout


@pytest.mark.skipif(not shutil.which("node"), reason="optional Node client runtime missing")
def test_typescript_client(example_server, tmp_path):
    source = tmp_path / "project.zip"
    source.write_bytes(archive())
    result = subprocess.run(
        ["node", str(Path("examples/client.ts").resolve()), str(source)],
        cwd=tmp_path,
        env=example_server,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        tmp_path / "downloaded-artifacts" / "fixture-fixture.txt"
    ).read_bytes() == b"controlled artifact fixture"
