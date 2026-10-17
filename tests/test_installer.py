"""Installer orchestration/safety tests. Docker itself is verified separately in CI."""

import json
import os
import shutil
import subprocess
import sys

import pytest


@pytest.fixture
def installer(tmp_path):
    root = tmp_path / "checkout with spaces"
    root.mkdir()
    shutil.copyfile("install.sh", root / "install.sh")
    (root / "config").mkdir()
    (root / "config" / "gradlemcp.example.json").write_text('{"max_workers":1}\n')
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        f"#!{sys.executable}\n"
        "import json,os,sys\n"
        "args=sys.argv[1:]\n"
        "with open(os.environ['DOCKER_COMMAND_LOG'],'a') as log: log.write(json.dumps(args)+'\\n')\n"
        "if args[:2]==['compose','up'] and '--help' in args: print('--wait-timeout');sys.exit(0)\n"
        "if os.environ.get('DOCKER_FAIL') and ' '.join(args).startswith(os.environ['DOCKER_FAIL']): sys.exit(1)\n"
        "if 'credentials' in args: print('installer-agent.controlled-fixture-token')\n"
    )
    docker.chmod(0o755)
    log = tmp_path / "docker.jsonl"
    env = os.environ | {
        "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
        "DOCKER_COMMAND_LOG": str(log),
    }
    return root, env, log


def run(installer, *args, extra_env=None):
    root, env, _ = installer
    return subprocess.run(
        ["sh", str(root / "install.sh"), *args],
        cwd=root.parent,
        env=env | (extra_env or {}),
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_installer_complete_flow_and_private_token(installer):
    root, _, log = installer
    result = run(installer)
    assert result.returncode == 0, result.stderr
    token = root / "data" / "bootstrap-token.local"
    assert token.read_text().strip() == "installer-agent.controlled-fixture-token"
    assert token.stat().st_mode & 0o777 == 0o600
    assert (root / "gradlemcp.json").stat().st_mode & 0o777 == 0o600
    assert "controlled-fixture-token" not in result.stdout + result.stderr
    commands = [json.loads(line) for line in log.read_text().splitlines()]
    assert any(c[:2] == ["build", "-f"] for c in commands)
    assert ["compose", "up", "-d", "--wait", "--wait-timeout", "120", "gradlemcp"] in commands
    assert any(c[:3] == ["compose", "exec", "-T"] for c in commands)
    assert not (root / ".gradlemcp-install.lock").exists()


def test_installer_rerun_preserves_state(installer):
    root, _, log = installer
    assert run(installer).returncode == 0
    token = root / "data" / "bootstrap-token.local"
    original_token = token.read_bytes()
    config = root / "gradlemcp.json"
    config.write_text('{"operator_customization":true}')
    assert run(installer).returncode == 0
    assert token.read_bytes() == original_token
    assert config.read_text() == '{"operator_customization":true}'
    commands = [json.loads(line) for line in log.read_text().splitlines()]
    assert sum("credentials" in c for c in commands) == 1


def test_check_does_not_create_files(installer):
    root, _, _ = installer
    assert run(installer, "--check").returncode == 0
    assert not (root / "data").exists()
    assert not (root / "gradlemcp.json").exists()


@pytest.mark.parametrize(
    "step", ["info", "compose version", "build", "compose build", "compose up -d", "compose exec"]
)
def test_failure_is_not_reported_success(installer, step):
    root, _, _ = installer
    result = run(installer, extra_env={"DOCKER_FAIL": step})
    assert result.returncode != 0
    assert "GradleMCP is ready at" not in result.stdout
    assert not (root / ".gradlemcp-install.lock").exists()


def test_failed_credential_creation_cleans_temporary_token(installer):
    root, _, _ = installer
    result = run(
        installer, extra_env={"DOCKER_FAIL": "compose run --rm --no-deps gradlemcp credentials"}
    )
    assert result.returncode != 0
    assert not (root / "data" / "bootstrap-token.local").exists()
    assert not list((root / "data").glob(".bootstrap-token.*"))


def test_symlink_is_rejected(installer, tmp_path):
    root, _, _ = installer
    outside = tmp_path / "outside.json"
    outside.write_text("untouched")
    (root / "gradlemcp.json").symlink_to(outside)
    assert run(installer).returncode != 0
    assert outside.read_text() == "untouched"


def test_installer_lock(installer):
    root, _, _ = installer
    (root / ".gradlemcp-install.lock").mkdir()
    result = run(installer)
    assert result.returncode != 0
    assert "Another installer" in result.stderr
