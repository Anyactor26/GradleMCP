import json
import os
import shutil
import subprocess
import sys


def control_fixture(tmp_path):
    root = tmp_path / "control-checkout"
    root.mkdir()
    shutil.copyfile("gmc", root / "gmc")
    (root / "gradlemcp.json").write_text("{}\n")
    (root / ".gradlemcp.env").write_text("# local overrides\n")
    (root / "data").mkdir()
    (root / "data" / "bootstrap-token.local").write_text("agent.private-test-token\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "docker.jsonl"
    docker = bin_dir / "docker"
    docker.write_text(
        f"#!{sys.executable}\n"
        "import json,os,sys\n"
        "args=sys.argv[1:]\n"
        "if args==['info']: sys.exit(0)\n"
        "with open(os.environ['DOCKER_LOG'],'a') as out: out.write(json.dumps(args)+'\\n')\n"
        "if args[:2]==['compose','port']: print(os.environ.get('GMCP_TEST_PORT', '0.0.0.0:8000'))\n"
    )
    docker.chmod(0o755)
    # Deterministic stand-in for `hostname -I`; defaults to no routable address so
    # loopback fallback behaviour stays testable.
    hostname = bin_dir / "hostname"
    hostname.write_text(
        f"#!{sys.executable}\n"
        "import os, sys\n"
        "sys.exit(print(os.environ.get('GMCP_TEST_HOSTNAME', '')) or 0)\n"
    )
    hostname.chmod(0o755)
    env = os.environ | {
        "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
        "DOCKER_LOG": str(log),
    }
    return root, env, log


def run_control(control, *args, extra_env=None):
    root, env, _ = control
    return subprocess.run(
        ["sh", str(root / "gmc"), *args],
        cwd=root,
        env=env | (extra_env or {}),
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_control_commands_have_easy_start_stop_and_token_access(tmp_path):
    control = control_fixture(tmp_path)
    root, _, log = control
    help_text = run_control(control, "help").stdout
    assert "./gmc stop" in help_text
    assert "./gmc ui on" in help_text
    token = run_control(control, "token")
    assert token.stdout.strip() == "agent.private-test-token"
    assert run_control(control, "stop").returncode == 0
    commands = [json.loads(line) for line in log.read_text().splitlines()]
    assert ["compose", "stop", "-t", "180", "gradlemcp"] in commands
    assert root.joinpath("gradlemcp.json").exists()


def test_direct_exposure_sets_bind_and_exact_mcp_host(tmp_path):
    control = control_fixture(tmp_path)
    result = run_control(control, "expose", "direct", "198.51.100.27")
    assert result.returncode == 0, result.stderr
    root, _, log = control
    compose_env = (root / ".env").read_text()
    app_env = (root / ".gradlemcp.env").read_text()
    assert "GRADLEMCP_BIND_ADDRESS=0.0.0.0" in compose_env
    assert "GRADLEMCP_PUBLIC_HOST=198.51.100.27" in compose_env
    assert "GRADLEMCP_PUBLIC_URL=null" in app_env
    assert "GRADLEMCP_EXPOSURE=direct" in app_env
    assert "GRADLEMCP_MCP_ALLOWED_HOSTS='[\"198.51.100.27:*\"]'" in app_env
    assert "GRADLEMCP_MCP_ALLOWED_ORIGINS='[\"http://198.51.100.27:*\"]'" in app_env
    assert "WARNING" in result.stdout
    commands = [json.loads(line) for line in log.read_text().splitlines()]
    assert any(
        item[:3] == ["compose", "up", "-d"] and "--wait-timeout" in item and "gradlemcp" in item
        for item in commands
    )


def test_https_exposure_configures_caddy_and_public_mcp_url(tmp_path):
    control = control_fixture(tmp_path)
    result = run_control(control, "expose", "https", "builds.example.org")
    assert result.returncode == 0, result.stderr
    root, _, log = control
    assert "GRADLEMCP_DOMAIN=builds.example.org" in (root / ".env").read_text()
    app_env = (root / ".gradlemcp.env").read_text()
    assert "GRADLEMCP_PUBLIC_URL=https://builds.example.org" in app_env
    assert "GRADLEMCP_EXPOSURE=proxy" in app_env
    assert "GRADLEMCP_MCP_ALLOWED_HOSTS='[\"builds.example.org:*\"]'" in app_env
    commands = [json.loads(line) for line in log.read_text().splitlines()]
    assert any(item[:4] == ["compose", "--profile", "tls", "up"] for item in commands)


def test_ui_toggle_persists_setting_and_restarts_service(tmp_path):
    control = control_fixture(tmp_path)
    result = run_control(control, "ui", "on")
    assert result.returncode == 0, result.stderr
    root, _, log = control
    assert "GRADLEMCP_UI_ENABLED=true" in (root / ".gradlemcp.env").read_text()
    commands = [json.loads(line) for line in log.read_text().splitlines()]
    assert any(item[:3] == ["compose", "up", "-d"] for item in commands)
    assert "http://127.0.0.1:8000/ui/" in result.stdout


def test_ui_endpoint_uses_direct_public_host_when_exposed(tmp_path):
    control = control_fixture(tmp_path)
    assert run_control(control, "expose", "direct", "198.51.100.27").returncode == 0
    result = run_control(control, "ui", "on")
    assert result.returncode == 0, result.stderr
    assert "http://198.51.100.27:8000/ui/" in result.stdout


def test_ui_url_uses_detected_vps_address_on_default_publish(tmp_path):
    # Default install publishes 0.0.0.0:8000; the printed UI URL must use the
    # host's routable address instead of an unopenable 127.0.0.1 URL.
    control = control_fixture(tmp_path)
    result = run_control(control, "ui", "on", extra_env={"GMCP_TEST_HOSTNAME": "198.51.100.27"})
    assert result.returncode == 0, result.stderr
    assert "http://198.51.100.27:8000/ui/" in result.stdout
    assert "127.0.0.1:8000/ui/" not in result.stdout


def test_primary_host_skips_link_local_addresses(tmp_path):
    control = control_fixture(tmp_path)
    result = run_control(
        control,
        "ui",
        "on",
        extra_env={"GMCP_TEST_HOSTNAME": "169.254.10.10 198.51.100.27"},
    )
    assert result.returncode == 0, result.stderr
    assert "http://198.51.100.27:8000/ui/" in result.stdout


def test_primary_host_brackets_ipv6_when_no_ipv4_exists(tmp_path):
    control = control_fixture(tmp_path)
    result = run_control(control, "ui", "on", extra_env={"GMCP_TEST_HOSTNAME": "2001:db8::10"})
    assert result.returncode == 0, result.stderr
    assert "http://[2001:db8::10]:8000/ui/" in result.stdout


def test_primary_host_falls_back_to_loopback_without_routable_address(tmp_path):
    control = control_fixture(tmp_path)
    result = run_control(control, "ui", "on", extra_env={"GMCP_TEST_HOSTNAME": "169.254.10.10"})
    assert result.returncode == 0, result.stderr
    assert "http://127.0.0.1:8000/ui/" in result.stdout


def test_expose_off_reports_loopback_url_despite_detected_address(tmp_path):
    control = control_fixture(tmp_path)
    assert (
        run_control(
            control, "expose", "off", extra_env={"GMCP_TEST_HOSTNAME": "198.51.100.27"}
        ).returncode
        == 0
    )
    result = run_control(control, "ui", "on", extra_env={"GMCP_TEST_HOSTNAME": "198.51.100.27"})
    assert result.returncode == 0, result.stderr
    assert "http://127.0.0.1:8000/ui/" in result.stdout
    assert "198.51.100.27" not in result.stdout


def test_endpoint_output_lists_public_landing_page(tmp_path):
    control = control_fixture(tmp_path)
    result = run_control(control, "endpoint", extra_env={"GMCP_TEST_HOSTNAME": "198.51.100.27"})
    assert result.returncode == 0, result.stderr
    assert "Landing:    http://198.51.100.27:8000/" in result.stdout
    assert "Dashboard:  http://198.51.100.27:8000/ui/" in result.stdout


def test_doctor_flags_loopback_only_published_port(tmp_path):
    control = control_fixture(tmp_path)
    result = run_control(control, "doctor", extra_env={"GMCP_TEST_PORT": "127.0.0.1:8000"})
    assert result.returncode == 0, result.stderr
    assert "127.0.0.1:8000" in result.stdout
    assert "WARNING: loopback-only binding" in result.stdout


def test_doctor_confirms_all_interface_publish_and_firewall_hint(tmp_path):
    control = control_fixture(tmp_path)
    result = run_control(control, "doctor")
    assert result.returncode == 0, result.stderr
    assert "0.0.0.0:8000" in result.stdout
    assert "loopback-only" not in result.stdout
    assert "provider firewalls" in result.stdout


def test_ui_status_reports_enabled_without_explicit_opt_in(tmp_path):
    control = control_fixture(tmp_path)
    result = run_control(control, "ui", "status")
    assert result.returncode == 0, result.stderr
    assert "Dashboard: enabled at" in result.stdout
    assert "http://127.0.0.1:8000/ui/" in result.stdout


def test_ui_status_reports_disabled_after_opt_out(tmp_path):
    control = control_fixture(tmp_path)
    root, _, _ = control
    with (root / ".gradlemcp.env").open("a") as env:
        env.write("GRADLEMCP_UI_ENABLED=false\n")
    result = run_control(control, "ui", "status")
    assert result.returncode == 0, result.stderr
    assert "Dashboard: disabled" in result.stdout


def test_doctor_reports_dashboard_state_host_addresses_and_nat_guidance(tmp_path):
    control = control_fixture(tmp_path)
    result = run_control(control, "doctor", extra_env={"GMCP_TEST_HOSTNAME": "10.0.0.112"})
    assert result.returncode == 0, result.stderr
    assert "Dashboard (/ui/):" in result.stdout
    assert "Configuration: enabled (default" in result.stdout
    assert "10.0.0.112" in result.stdout
    # NAT guidance must name the public-IP/private-IP split and an external probe.
    assert "1:1 NAT" in result.stdout
    assert "http://<public-ip>:8000/ui/" in result.stdout


def test_doctor_reports_disabled_dashboard_configuration(tmp_path):
    control = control_fixture(tmp_path)
    root, _, _ = control
    with (root / ".gradlemcp.env").open("a") as env:
        env.write("GRADLEMCP_UI_ENABLED=false\n")
    result = run_control(control, "doctor")
    assert result.returncode == 0, result.stderr
    assert "Configuration: disabled" in result.stdout
    assert "./gmc ui on" in result.stdout
