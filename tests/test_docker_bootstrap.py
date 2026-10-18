"""Run the prerequisite script with a staged filesystem and fake OS tools.

Never touch host APT, services or network. These tests are not a fresh-VM install.
"""

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

FINGERPRINT = "9DC858229FC7DD38854AE2D88D81803C0EBFCD88"


@pytest.fixture
def bootstrap(tmp_path):
    system = tmp_path / "system root"
    (system / "etc").mkdir(parents=True)
    (system / "etc/os-release").write_text('ID="debian"\nVERSION_CODENAME="bookworm"\n')
    script = tmp_path / "install-docker.sh"
    source = Path("scripts/install-docker.sh").read_text()
    assert source.count("SYSTEM_ROOT=\n") == 1
    script.write_text(
        source.replace("SYSTEM_ROOT=\n", f"SYSTEM_ROOT={shlex.quote(str(system))}\n", 1)
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    dispatcher = bin_dir / "dispatcher"
    dispatcher.write_text(
        f"#!{sys.executable}\n"
        "import json,os,sys\nfrom pathlib import Path\n"
        "tool=Path(sys.argv[0]).name; args=sys.argv[1:]\n"
        "with open(os.environ['BOOTSTRAP_LOG'],'a') as out: out.write(json.dumps([tool,*args])+'\\n')\n"
        "if os.environ.get('FAIL_TOOL')==tool: sys.exit(1)\n"
        "if tool=='id': print(os.environ.get('FIXTURE_UID','0'))\n"
        "elif tool=='uname': print('Linux')\n"
        "elif tool=='dpkg': print(os.environ.get('FIXTURE_ARCH','amd64'))\n"
        "elif tool=='dpkg-query':\n"
        " if args[-1]==os.environ.get('CONFLICT_PACKAGE'): print('installed')\n"
        " else: sys.exit(1)\n"
        "elif tool=='curl': Path(args[args.index('--output')+1]).write_text('controlled public key fixture')\n"
        "elif tool=='gpg':\n"
        " print('pub::::::::::');print('fpr:::::::::'+os.environ['KEY_FINGERPRINT']+':')\n"
        " if os.environ.get('EXTRA_PRIMARY_KEY'): print('pub::::::::::');print('fpr:::::::::'+'B'*40+':')\n"
    )
    dispatcher.chmod(0o755)
    for tool in ("id", "uname", "systemctl", "dpkg", "dpkg-query", "apt-get", "curl", "gpg"):
        (bin_dir / tool).symlink_to(dispatcher)
    log = tmp_path / "commands.jsonl"
    env = os.environ | {
        "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
        "BOOTSTRAP_LOG": str(log),
        "KEY_FINGERPRINT": FINGERPRINT,
    }
    return script, system, env, log


def run(bootstrap, *args, **extra):
    script, _, env, _ = bootstrap
    return subprocess.run(
        ["sh", str(script), *args], env=env | extra, capture_output=True, text=True, timeout=10
    )


def commands(bootstrap):
    return [json.loads(line) for line in bootstrap[3].read_text().splitlines()]


@pytest.mark.parametrize(
    "distro,codename",
    [("debian", "bookworm"), ("debian", "trixie"), ("ubuntu", "jammy"), ("ubuntu", "noble")],
)
def test_signed_package_installation_for_supported_hosts(bootstrap, distro, codename):
    _, system, _, _ = bootstrap
    (system / "etc/os-release").write_text(f'ID="{distro}"\nVERSION_CODENAME="{codename}"\n')
    result = run(bootstrap)
    assert result.returncode == 0, result.stderr
    repo = system / "etc/apt/sources.list.d/gradlemcp-docker.sources"
    key = system / "etc/apt/keyrings/gradlemcp-docker.asc"
    assert f"URIs: https://download.docker.com/linux/{distro}" in repo.read_text()
    assert f"Suites: {codename}" in repo.read_text()
    assert f"Signed-By: {key}" in repo.read_text()
    assert key.stat().st_mode & 0o777 == 0o644
    calls = commands(bootstrap)
    packages = next(c for c in calls if c[0] == "apt-get" and "docker-ce" in c)
    assert "docker-compose-plugin" in packages and "containerd.io" in packages
    assert ["systemctl", "enable", "--now", "docker"] in calls
    assert not any("remove" in c or "purge" in c for c in calls)


@pytest.mark.parametrize("failure", ["curl", "gpg"])
def test_key_download_or_validation_failure_never_enables_repository(bootstrap, failure):
    result = run(bootstrap, FAIL_TOOL=failure)
    assert result.returncode != 0
    assert not (bootstrap[1] / "etc/apt/sources.list.d/gradlemcp-docker.sources").exists()
    assert not any("docker-ce" in call for call in commands(bootstrap))


def test_mismatched_key_fingerprint_is_rejected(bootstrap):
    result = run(bootstrap, KEY_FINGERPRINT="A" * 40)
    assert result.returncode != 0 and "fingerprint mismatch" in result.stderr
    assert not (bootstrap[1] / "etc/apt/sources.list.d/gradlemcp-docker.sources").exists()


def test_existing_container_runtime_is_not_removed(bootstrap):
    result = run(bootstrap, CONFLICT_PACKAGE="docker.io")
    assert result.returncode != 0
    assert "No packages were removed" in result.stderr
    assert not any(c[0] == "apt-get" for c in commands(bootstrap))


def test_unsupported_distro_is_not_evaluated_or_modified(bootstrap, tmp_path):
    marker = tmp_path / "must-not-exist"
    (bootstrap[1] / "etc/os-release").write_text(
        f"ID=$(touch {marker})\nVERSION_CODENAME=unknown\n"
    )
    assert run(bootstrap).returncode != 0
    assert not marker.exists()
    assert not any(c[0] == "apt-get" for c in commands(bootstrap))


def test_existing_admin_repository_is_reused(bootstrap):
    sources = bootstrap[1] / "etc/apt/sources.list.d"
    sources.mkdir(parents=True)
    admin = sources / "docker.sources"
    admin.write_text("administrator-managed mirror")
    assert run(bootstrap).returncode == 0
    assert admin.read_text() == "administrator-managed mirror"
    assert not (sources / "gradlemcp-docker.sources").exists()
    assert not any(c[0] in ("curl", "gpg") for c in commands(bootstrap))


def test_modified_managed_repository_is_not_overwritten(bootstrap):
    sources = bootstrap[1] / "etc/apt/sources.list.d"
    sources.mkdir(parents=True)
    configured = sources / "gradlemcp-docker.sources"
    configured.write_text("operator customization")
    assert run(bootstrap).returncode != 0
    assert configured.read_text() == "operator customization"


def test_daemon_start_only_does_not_install_packages(bootstrap):
    assert run(bootstrap, "--start-only").returncode == 0
    calls = commands(bootstrap)
    assert ["systemctl", "start", "docker"] in calls
    assert not any(c[0] in ("apt-get", "curl", "gpg", "dpkg") for c in calls)


@pytest.mark.parametrize(
    "extra", [{"FIXTURE_UID": "1000"}, {"FAIL_TOOL": "systemctl"}, {"FIXTURE_ARCH": "unsupported"}]
)
def test_unsupported_execution_environment_fails_before_apt(bootstrap, extra):
    assert run(bootstrap, **extra).returncode != 0
    assert not any(c[0] == "apt-get" for c in commands(bootstrap))


def test_additional_untrusted_key_in_bundle_is_rejected(bootstrap):
    result = run(bootstrap, EXTRA_PRIMARY_KEY="1")
    assert result.returncode != 0 and "fingerprint mismatch" in result.stderr
    assert not (bootstrap[1] / "etc/apt/sources.list.d/gradlemcp-docker.sources").exists()
