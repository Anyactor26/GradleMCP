import base64
import json

from conftest import archive


def rpc(http, method, params=None):
    result = http.post(
        "/mcp/",
        headers={
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-11-25",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
    )
    assert result.status_code == 200, result.text
    return result.json()


def test_discovery_and_build(http):
    response = rpc(
        http,
        "initialize",
        {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    )
    assert response["result"]["serverInfo"]["name"] == "GradleMCP"
    names = {tool["name"] for tool in rpc(http, "tools/list")["result"]["tools"]}
    assert {
        "submit_build",
        "get_capabilities",
        "publish_build",
        "list_gradle_tasks",
        "download_artifact",
    } <= names
    upload = rpc(
        http,
        "tools/call",
        {
            "name": "upload_project",
            "arguments": {"archive_base64": base64.b64encode(archive()).decode()},
        },
    )
    assert not upload["result"].get("isError")
    data = json.loads(upload["result"]["content"][0]["text"])
    submit = rpc(
        http,
        "tools/call",
        {"name": "submit_build", "arguments": {"request": {"project_id": data["project_id"]}}},
    )
    data = json.loads(submit["result"]["content"][0]["text"])
    status = rpc(
        http, "tools/call", {"name": "get_build_status", "arguments": {"build_id": data["id"]}}
    )
    assert '"queued"' in status["result"]["content"][0]["text"]


def test_validation_and_authorization(http, service):
    invalid = rpc(
        http,
        "tools/call",
        {
            "name": "submit_build",
            "arguments": {"request": {"project_id": "id", "tasks": ["--evil"]}},
        },
    )
    assert invalid["result"]["isError"]
    denied = rpc(
        http, "tools/call", {"name": "get_build_status", "arguments": {"build_id": "missing"}}
    )
    assert denied["result"]["isError"]
    assert "not_found" in denied["result"]["content"][0]["text"]
    service.db.revoke("agent")
    assert http.post("/mcp/", json={}).status_code == 401


async def run_stdio(config, token, tmp_path):
    import os
    import sys
    from pathlib import Path

    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    path = tmp_path / "stdio-config.json"
    path.write_text(config.model_dump_json())
    parameters = StdioServerParameters(
        command=str(Path(sys.executable).parent / "gradlemcp"),
        args=["mcp"],
        env=os.environ | {"GRADLEMCP_CONFIG": str(path), "GRADLEMCP_TOKEN": token},
    )
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert "submit_build" in {tool.name for tool in tools.tools}
            result = await session.call_tool("get_capabilities", {})
            assert not result.is_error
            assert "GradleMCP" in result.content[0].text
            uploaded = await session.call_tool(
                "upload_project", {"archive_base64": base64.b64encode(archive()).decode()}
            )
            project_id = json.loads(uploaded.content[0].text)["project_id"]
            submitted = await session.call_tool(
                "submit_build", {"request": {"project_id": project_id}}
            )
            build_id = json.loads(submitted.content[0].text)["id"]
            status = await session.call_tool("get_build_status", {"build_id": build_id})
            assert json.loads(status.content[0].text)["state"] == "queued"


def test_stdio_sdk_client(config, token, tmp_path):
    import asyncio

    asyncio.run(run_stdio(config, token, tmp_path))
