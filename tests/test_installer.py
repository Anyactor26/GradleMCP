"""Installer orchestration/safety tests. Docker itself is verified separately in CI."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

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
        "from pathlib import Path\n"
        "if os.environ.get('DOCKER_NEEDS_INSTALL') and not Path(os.environ['DOCKER_SETUP_MARKER']).exists(): sys.exit(1)\n"
        "if args==['info'] and os.environ.get('DOCKER_DAEMON_STOPPED') and not Path(os.environ['DOCKER_SETUP_MARKER']).exists(): sys.exit(1)\n"
        "if args==['info'] and os.environ.get('DOCKER_NEEDS_SUDO') and not os.environ.get('UNDER_SUDO'): sys.exit(1)\n"
        "with open(os.environ['DOCKER_COMMAND_LOG'],'a') as log: log.write(json.dumps(args)+'\\n')\n"
        "if args[:2]==['compose','up'] and '--help' in args: print('--wait-timeout');sys.exit(0)\n"
        "if os.environ.get('DOCKER_FAIL') and ' '.join(args).startswith(os.environ['DOCKER_FAIL']): sys.exit(1)\n"
        "if 'credentials' in args: print('installer-agent.controlled-fixture-token')\n"
    )
    docker.chmod(0o755)
    # All privilege/bootstrap paths are controlled fixtures; never run host sudo/APT.
    sudo = bin_dir / "sudo"
    sudo.write_text(
        f"#!{sys.executable}\n"
        "import os,sys\n"
        "if os.environ.get('SUDO_FAIL'): sys.exit(1)\n"
        "args=sys.argv[1:]; args=args[1:] if args[0]=='--' else args\n"
        "os.execvpe(args[0],args,os.environ | {'UNDER_SUDO':'1'})\n"
    )
    sudo.chmod(0o755)
    identity = bin_dir / "id"
    identity.write_text("#!/bin/sh\nprintf '1000\\n'\n")
    identity.chmod(0o755)
    (root / "scripts").mkdir()
    helper = root / "scripts/install-docker.sh"
    helper.write_text(
        f"#!{sys.executable}\n"
        "import json,os,sys\nfrom pathlib import Path\n"
        "with open(os.environ['SYSTEM_SETUP_LOG'],'a') as out: out.write(json.dumps(sys.argv[1:])+'\\n')\n"
        "if os.environ.get('BOOTSTRAP_FAIL'):sys.exit(1)\n"
        "Path(os.environ['DOCKER_SETUP_MARKER']).touch()\n"
    )
    # Parent invokes helper using sh, so use a shell trampoline to the test Python.
    python_helper = root / "scripts/helper.py"
    helper.rename(python_helper)
    helper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{python_helper}" "$@"\n')
    log = tmp_path / "docker.jsonl"
    env = os.environ | {
        "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
        "DOCKER_COMMAND_LOG": str(log),
        "SYSTEM_SETUP_LOG": str(tmp_path / "setup.jsonl"),
        "DOCKER_SETUP_MARKER": str(tmp_path / "docker-installed"),
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
    assert (root / ".gradlemcp.env").stat().st_mode & 0o777 == 0o600
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


def test_automatically_bootstraps_missing_docker(installer):
    _, env, _ = installer
    result = run(installer, extra_env={"DOCKER_NEEDS_INSTALL": "1"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert Path(env["DOCKER_SETUP_MARKER"]).exists()
    assert Path(env["SYSTEM_SETUP_LOG"]).read_text().splitlines() == ["[]"]


def test_uses_sudo_without_relogin_or_group_changes(installer):
    _, env, log = installer
    result = run(installer, extra_env={"DOCKER_NEEDS_SUDO": "1"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "sudo docker compose" in result.stdout
    assert not Path(env["SYSTEM_SETUP_LOG"]).exists()
    assert "credentials" in log.read_text()


def test_no_system_changes_and_readonly_check_never_bootstrap(installer):
    root, env, _ = installer
    for option in ("--check", "--no-system-changes"):
        result = run(installer, option, extra_env={"DOCKER_NEEDS_INSTALL": "1"})
        assert result.returncode != 0
        assert not Path(env["SYSTEM_SETUP_LOG"]).exists()
        assert not (root / "data").exists()
        assert not (root / ".gradlemcp-install.lock").exists()


def test_bootstrap_failure_does_not_create_config_or_token(installer):
    root, _, _ = installer
    result = run(installer, extra_env={"DOCKER_NEEDS_INSTALL": "1", "BOOTSTRAP_FAIL": "1"})
    assert result.returncode != 0
    assert not (root / "gradlemcp.json").exists()
    assert not (root / "data").exists()
    assert not (root / ".gradlemcp-install.lock").exists()


def test_stopped_daemon_is_started_without_reinstalling_packages(installer):
    _, env, _ = installer
    result = run(installer, extra_env={"DOCKER_DAEMON_STOPPED": "1"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert Path(env["SYSTEM_SETUP_LOG"]).read_text().splitlines() == ['["--start-only"]']


def test_sudo_denied_prevents_installation(installer):
    root, env, _ = installer
    result = run(installer, extra_env={"DOCKER_NEEDS_INSTALL": "1", "SUDO_FAIL": "1"})
    assert result.returncode != 0
    assert not Path(env["SYSTEM_SETUP_LOG"]).exists()
    assert not (root / "data").exists()


def test_app_environment_symlink_is_rejected(installer, tmp_path):
    root, _, _ = installer
    outside = tmp_path / "outside.env"
    outside.write_text("GRADLEMCP_UI_ENABLED=true\n")
    (root / ".gradlemcp.env").symlink_to(outside)
    result = run(installer)
    assert result.returncode != 0
    assert "symlink" in result.stderr.lower()
    assert outside.read_text() == "GRADLEMCP_UI_ENABLED=true\n"
