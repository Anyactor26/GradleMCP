from pathlib import Path

from fastapi.testclient import TestClient

from gradlemcp.api import create_app
from gradlemcp.config import Settings


def test_dashboard_is_served_by_default(config):
    # A fresh deployment must answer /ui/ directly; operators should not need a
    # separate enablement step to reach the interface.
    app = create_app(config, start_scheduler=False)
    with TestClient(app) as http:
        page = http.get("/ui/")
        assert page.status_code == 200
        assert "Compile a project" in page.text
        assert http.get("/ui/assets/app.js").status_code == 200

    # Explicit operator opt-out still removes the route entirely.
    config.ui_enabled = False
    disabled = create_app(config, start_scheduler=False)
    with TestClient(disabled) as http:
        assert http.get("/ui/").status_code == 404
        assert http.get("/ui").status_code == 404


def test_root_landing_is_public_without_a_token(config):
    # The bare VPS address must prove the controller is actually serving instead of
    # returning a 401/404 that makes the port look bound to nothing.
    app = create_app(config, start_scheduler=False)
    with TestClient(app) as http:
        page = http.get("/", headers={"Accept": "text/html"})
        assert page.status_code == 200
        assert "text/html" in page.headers["content-type"]
        assert "GradleMCP controller" in page.text
        assert "/health" in page.text and "/mcp/" in page.text
        assert "Content-Security-Policy" in page.headers
        assert page.headers["X-Frame-Options"] == "DENY"
        # Dashboard is on by default, so the landing page links straight to it.
        assert 'href="/ui/"' in page.text

        api = http.get("/", headers={"Accept": "application/json"})
        assert api.status_code == 200
        body = api.json()
        assert body["status"] == "ok"
        assert body["ui_enabled"] is True
        assert body["paths"]["ui"] == "/ui/"
        assert body["paths"]["mcp"] == "/mcp/"

        # Generic clients (curl, agents) send */* and receive structured JSON.
        default = http.get("/")
        assert default.status_code == 200
        assert "application/json" in default.headers["content-type"]


def test_root_landing_explains_explicitly_disabled_dashboard(tmp_path):
    config = Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path}/disabled.db",
        storage_reserve_mb=0,
        ui_enabled=False,
    )
    app = create_app(config, start_scheduler=False)
    with TestClient(app) as http:
        page = http.get("/", headers={"Accept": "text/html"})
        assert page.status_code == 200
        assert 'href="/ui/"' not in page.text
        assert "./gmc ui on" in page.text
        body = http.get("/", headers={"Accept": "application/json"}).json()
        assert body["ui_enabled"] is False
        assert body["paths"]["ui"] is None


def test_root_landing_links_dashboard_when_enabled(tmp_path):
    config = Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path}/landing.db",
        storage_reserve_mb=0,
        ui_enabled=True,
    )
    app = create_app(config, start_scheduler=False)
    with TestClient(app) as http:
        page = http.get("/", headers={"Accept": "text/html"})
        assert page.status_code == 200
        assert 'href="/ui/"' in page.text
        body = http.get("/", headers={"Accept": "application/json"}).json()
        assert body["ui_enabled"] is True
        assert body["paths"]["ui"] == "/ui/"
        # The landing page stays public; protected routes still demand a token.
        assert http.get("/api/v1/capabilities").status_code == 401


def test_dashboard_is_optional_and_authenticated_ui_api_stays_protected(tmp_path):
    config = Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path}/ui.db",
        storage_reserve_mb=0,
        ui_enabled=True,
    )
    app = create_app(config, start_scheduler=False)
    token = app.state.service.db.create_credential("dashboard", ["read", "build"])
    with TestClient(app, base_url="http://localhost:8000") as http:
        page = http.get("/ui/")
        assert page.status_code == 200
        assert "Compile a project" in page.text
        assert "Content-Security-Policy" in page.headers
        assert http.get("/ui/assets/app.js").status_code == 200
        assert http.get("/api/v1/capabilities").status_code == 401
        headers = {
            "Authorization": f"Bearer {token}",
            "Origin": "http://localhost:8000",
        }
        assert http.get("/api/v1/capabilities", headers=headers).status_code == 200
        assert (
            http.get(
                "/api/v1/capabilities",
                headers={**headers, "Origin": "https://attacker.invalid"},
            ).status_code
            == 403
        )


def test_dashboard_ships_theme_toggle_and_self_contained_assets():
    web_root = Path(__file__).resolve().parents[1] / "src" / "gradlemcp" / "web"
    index = (web_root / "index.html").read_text()
    script = (web_root / "assets" / "app.js").read_text()
    styles = (web_root / "assets" / "styles.css").read_text()

    # Manual light/dark override plus OS-level dark mode support.
    assert 'id="themeToggle"' in index
    assert "icon-moon" in index and "icon-sun" in index
    assert "initTheme" in script and "gradlemcp-theme" in script
    assert "prefers-color-scheme: dark" in styles
    assert '[data-theme="dark"]' in styles

    # Self-hosted/CSP-safe: no external font/stylesheet references (the SVG
    # namespace URL inside the data-URI favicon is an identifier, not a fetch).
    assert 'rel="icon" href="data:image/svg+xml' in index
    assert 'href="http' not in index and 'src="http' not in index
    assert "fonts.googleapis" not in styles and "@import" not in styles
    assert "url(http" not in styles
    # Every interactive status class the JavaScript generates still has styling.
    for class_name in (
        "badge-success",
        "badge-danger",
        "badge-running",
        "badge-queued",
        "badge-neutral",
        "indicator-error",
        "indicator-busy",
        "sidebar-open",
        "has-file",
        "dragging",
    ):
        assert f".{class_name}" in styles


def test_agent_discovery_documents_exact_protocol_paths(http):
    capabilities = http.get("/api/v1/capabilities").json()
    assert capabilities["protocols"]["rest"]["base_path"] == "/api/v1"
    assert capabilities["protocols"]["mcp"] == {
        "transport": "streamable-http",
        "path": "/mcp/",
        "authentication": "Authorization: Bearer <token>",
    }
    endpoint = http.get("/api/v1/system/endpoint").json()
    assert endpoint["rest_base_path"] == "/api/v1"
    assert endpoint["mcp_path"] == "/mcp/"
    assert endpoint["mcp_transport"] == "streamable-http"


def test_explicit_mcp_host_allowlist_accepts_direct_ip_host(config, token):
    config.mcp_allowed_hosts = ["198.51.100.27:*"]
    config.mcp_allowed_origins = ["http://198.51.100.27:*"]
    app = create_app(config, start_scheduler=False)
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "host-check", "version": "1"},
        },
    }
    with TestClient(app, base_url="http://198.51.100.27:8000") as http:
        response = http.post(
            "/mcp/",
            headers={
                "Authorization": f"Bearer {token}",
                "Host": "198.51.100.27:8000",
                "Origin": "http://198.51.100.27:8000",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-11-25",
            },
            json=request,
        )
    assert response.status_code == 200, response.text


def test_all_interface_bind_accepts_requests_at_the_vps_address(config, token):
    config.host = "0.0.0.0"
    app = create_app(config, start_scheduler=False)
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "vps-address", "version": "1"},
        },
    }
    with TestClient(app, base_url="http://203.0.113.9:8000") as http:
        response = http.post(
            "/mcp/",
            headers={
                "Authorization": f"Bearer {token}",
                "Host": "203.0.113.9:8000",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-11-25",
            },
            json=request,
        )
    assert response.status_code == 200, response.text
