import json
import os
import shutil
from pathlib import Path

import httpx
import typer
import uvicorn
from pydantic import ValidationError

from .config import Settings, load_settings
from .db import Database
from .errors import ServiceError
from .observability import configure_logging

app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)
credentials = typer.Typer(no_args_is_help=True)
config_app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)
app.add_typer(credentials, name="credentials")
app.add_typer(config_app, name="config")


@app.command()
def init(path: Path = Path("gradlemcp.json")):
    """Write a non-secret configuration without overwriting existing files."""
    settings = Settings()
    with path.open("x") as stream:
        stream.write(settings.model_dump_json(indent=2) + "\n")
    os.chmod(path, 0o600)
    Database(settings)
    typer.echo("Initialized. Build worker image, create credentials, then run doctor and serve.")


@config_app.command("validate")
def validate():
    load_settings()
    typer.echo("Configuration valid (secrets omitted)")


@credentials.command("create")
def create(name: str, scopes: str = "read,build"):
    """Generate a token once; rotate keeps the client identity and existing job access."""
    values = scopes.split(",")
    if not set(values) <= {"read", "build", "publish", "admin"}:
        raise typer.BadParameter("Scopes: read,build,publish,admin")
    typer.echo(Database(load_settings()).create_credential(name, values))


@credentials.command("rotate")
def rotate(name: str, scopes: str | None = None):
    """Atomically replace a token, optionally changing scopes. Old token stops working immediately."""
    values = scopes.split(",") if scopes is not None else None
    if values is not None and not set(values) <= {"read", "build", "publish", "admin"}:
        raise typer.BadParameter("Scopes: read,build,publish,admin")
    typer.echo(Database(load_settings()).rotate_credential(name, values))


@credentials.command("revoke")
def revoke(name: str):
    Database(load_settings()).revoke(name)
    typer.echo("Revoked")


@app.command()
def serve(host: str | None = None, port: int | None = None):
    from .api import create_app

    overrides = {k: v for k, v in {"host": host, "port": port}.items() if v is not None}
    settings = load_settings(**overrides)
    configure_logging(settings.log_level)
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        workers=1,
        proxy_headers=False,
        access_log=False,
        log_config=None,
    )


@app.command()
def mcp():
    """Run stdio MCP adapter; a separately running serve process dispatches queued work."""
    from .mcp_adapter import create_mcp
    from .service import Service

    settings = load_settings()
    server, _ = create_mcp(Service(settings, Database(settings)))
    server.run(transport="stdio")


def request(path):
    settings = load_settings()
    base = os.environ.get("GRADLEMCP_URL", f"http://127.0.0.1:{settings.port}")
    with httpx.Client(timeout=10) as client:
        response = client.get(
            base + path,
            headers={"Authorization": "Bearer " + os.environ.get("GRADLEMCP_TOKEN", "")},
        )
        response.raise_for_status()
        typer.echo(json.dumps(response.json(), indent=2))


@app.command()
def status():
    request("/api/v1/capabilities")


@app.command()
def endpoint():
    request("/api/v1/system/endpoint")


@app.command()
def queue():
    request("/api/v1/queue")


@app.command()
def doctor():
    from .worker import DockerWorker

    settings = load_settings()
    Database(settings)
    checks = {
        "configuration": True,
        "docker_cli": bool(shutil.which("docker")),
        "docker_daemon": DockerWorker(settings).available(),
        "storage_free_mb": shutil.disk_usage(settings.data_dir).free // 1024**2,
    }
    typer.echo(json.dumps(checks, indent=2))
    if not checks["docker_daemon"]:
        raise typer.Exit(1)


@app.command("export-openapi")
def export_openapi(path: Path = Path("docs/openapi.json")):
    from .api import create_app

    path.write_text(json.dumps(create_app(start_scheduler=False).openapi(), indent=2) + "\n")


def main():
    """Do not let CLI tracebacks serialize secret-bearing configuration inputs."""
    try:
        app()
    except ValidationError as exc:
        fields = [".".join(map(str, error["loc"])) or "policy" for error in exc.errors()]
        typer.echo(
            "Validation failed for: " + ", ".join(fields) + ". Check docs/CONFIGURATION.md.",
            err=True,
        )
        raise SystemExit(2) from None
    except ServiceError as exc:
        typer.echo(json.dumps({"error": exc.body}), err=True)
        raise SystemExit(1) from None
    except (OSError, ValueError):
        typer.echo(
            "Operation failed. Check config syntax, storage permissions and prerequisites; values omitted for safety.",
            err=True,
        )
        raise SystemExit(1) from None
    except Exception as exc:
        typer.echo(
            "Operation failed ("
            + type(exc).__name__
            + "). Check prerequisites and protected operator logs; values omitted for safety.",
            err=True,
        )
        raise SystemExit(1) from None
