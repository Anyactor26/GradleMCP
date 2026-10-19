from fastapi.testclient import TestClient

from gradlemcp.api import create_app
from gradlemcp.config import Settings


def test_dashboard_is_off_by_default(config):
    app = create_app(config, start_scheduler=False)
    with TestClient(app) as http:
        assert http.get("/ui/").status_code == 404


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
