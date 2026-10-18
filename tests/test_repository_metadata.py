"""Keep published identity/license and manually activated CI paths consistent."""

import tomllib
from pathlib import Path

import pytest
import yaml


def test_arr_license_and_developer_metadata():
    project = tomllib.loads(Path("pyproject.toml").read_text())["project"]
    assert project["license"] == "LicenseRef-ARR"
    assert project["authors"] == [{"name": "Anyactor"}]
    assert "Copyright (c) 2026 Anyactor" in Path("LICENSE").read_text()
    assert "Developed by Anyactor" in Path("NOTICE").read_text()
    assert "Apache-2.0" not in Path("README.md").read_text()


def workflow_directory(base):
    # Prefer actual active workflows. A documentation README is not an Actions input.
    for candidate in (base / ".github/workflows", base / ".test/workflows"):
        if all((candidate / name).is_file() for name in ("ci.yml", "release.yml")):
            return candidate
    raise AssertionError("Expected CI and release workflows in .github/workflows")


def test_ci_workflows_validate_without_requiring_a_readme():
    root = workflow_directory(Path("."))
    for name in ("ci.yml", "release.yml"):
        workflow = yaml.safe_load((root / name).read_text())
        assert workflow["jobs"]
        assert workflow["permissions"] == {"contents": "read"}


@pytest.mark.parametrize("folder", [".github", ".test"])
def test_workflow_layout_does_not_need_documentation(tmp_path, folder):
    root = tmp_path / folder / "workflows"
    root.mkdir(parents=True)
    for name in ("ci.yml", "release.yml"):
        (root / name).write_text("name: fixture\n")
    assert not (root.parent / "README.md").exists()
    assert workflow_directory(tmp_path) == root


def test_active_workflows_take_precedence_over_leftover_test_directory(tmp_path):
    (tmp_path / ".test").mkdir()
    active = tmp_path / ".github/workflows"
    active.mkdir(parents=True)
    for name in ("ci.yml", "release.yml"):
        (active / name).write_text("name: active\n")
    assert workflow_directory(tmp_path) == active


def test_controller_uses_modern_standalone_docker_client():
    dockerfile = Path("Dockerfile").read_text()
    assert "DOCKER_CLI_IMAGE=docker:28-cli" in dockerfile
    assert "COPY --from=docker_cli /usr/local/bin/docker /usr/local/bin/docker" in dockerfile
    assert "apt-get install -y --no-install-recommends docker.io" not in dockerfile
