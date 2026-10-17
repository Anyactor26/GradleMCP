"""Keep published identity/license and manually activated CI paths consistent."""

import tomllib
from pathlib import Path

import yaml


def test_arr_license_and_developer_metadata():
    project = tomllib.loads(Path("pyproject.toml").read_text())["project"]
    assert project["license"] == "LicenseRef-ARR"
    assert project["authors"] == [{"name": "Anyactor"}]
    assert "Copyright (c) 2026 Anyactor" in Path("LICENSE").read_text()
    assert "Developed by Anyactor" in Path("NOTICE").read_text()
    assert "Apache-2.0" not in Path("README.md").read_text()


def test_ci_templates_survive_owner_folder_rename():
    root = Path(".test") if Path(".test").is_dir() else Path(".github")
    for name in ("ci.yml", "release.yml"):
        path = root / "workflows" / name
        workflow = yaml.safe_load(path.read_text())
        assert workflow["jobs"]
        assert workflow["permissions"] == {"contents": "read"}
    assert "mv .test .github" in (root / "README.md").read_text()
