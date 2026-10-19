import asyncio
import collections
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse, urlsplit

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.staticfiles import StaticFiles

from .config import load_settings
from .db import Database, require
from .endpoint import endpoint_status
from .errors import ErrorResponse, ServiceError
from .mcp_adapter import create_mcp, request_token
from .scheduler import Scheduler
from .service import BuildRequest, Service
from .worker import DockerWorker


class InspectRequest(BaseModel):
    project_id: str
    subdirectory: str = "."


class PublishRequest(BaseModel):
    tasks: list[str] = Field(min_length=1, max_length=32)
    idempotency_key: str = Field(min_length=1, max_length=128)


def _origin_parts(value, scheme_hint=None):
    try:
        parsed = urlsplit(value if scheme_hint is None else f"{scheme_hint}://{value}")
        scheme = (parsed.scheme or scheme_hint or "").lower()
        if (
            scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            return None
        port = parsed.port or (443 if scheme == "https" else 80)
        return scheme, parsed.hostname.rstrip(".").lower(), port
    except ValueError:
        return None


def _origin_allowed(origin, host_header, public_url):
    expected = _origin_parts(public_url) if public_url else None
    if expected:
        return _origin_parts(origin) == expected
    origin_parts = _origin_parts(origin)
    if not origin_parts or not host_header:
        return False
    host_parts = _origin_parts(host_header.decode(errors="replace"), origin_parts[0])
    return host_parts == origin_parts


class SecurityMiddleware:
    def __init__(self, app, service):
        self.app, self.service = app, service
        self.windows = collections.defaultdict(collections.deque)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        path = scope["path"]
        if path in ("/health", "/ready", "/ui") or path.startswith("/ui/"):
            return await self.app(scope, receive, send)
        try:
            auth = headers.get(b"authorization", b"").decode(errors="replace")
            if not auth.startswith("Bearer "):
                raise ServiceError("unauthorized", "Bearer credential required", 401)
            token = auth[7:]
            client = await run_in_threadpool(self.service.db.authenticate, token)
            origin = headers.get(b"origin")
            if origin and not _origin_allowed(
                origin.decode(errors="replace"),
                headers.get(b"host"),
                self.service.config.public_url,
            ):
                raise ServiceError(
                    "origin_rejected",
                    "Origin must match the configured public URL or this same origin",
                    403,
                )
            now = time.monotonic()
            window = self.windows[client.id]
            while window and window[0] < now - 60:
                window.popleft()
            if len(window) >= self.service.config.requests_per_minute:
                raise ServiceError("rate_limit", "Client rate limit reached", 429, retryable=True)
            window.append(now)
            maximum = self.service.config.upload_mb * 1024**2 * 4 // 3 + 65536
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body.extend(message.get("body", b""))
                if len(body) > maximum:
                    raise ServiceError(
                        "request_limit", "Request body exceeds configured limit", 413
                    )
                if not message.get("more_body", False):
                    break
            sent = False

            async def replay():
                nonlocal sent
                if not sent:
                    sent = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            scope.setdefault("state", {})["client"] = client
            context_token = request_token.set(token)
            try:
                await self.app(scope, replay, send)
            finally:
                request_token.reset(context_token)
        except ServiceError as exc:
            response = JSONResponse(
                {"error": exc.body},
                status_code=exc.status,
                headers={"WWW-Authenticate": "Bearer"} if exc.status == 401 else None,
            )
            await response(scope, receive, send)


def create_app(config=None, *, start_scheduler=True, worker=None):
    config = config or load_settings()
    db = Database(config)
    service = Service(config, db)
    worker = worker or DockerWorker(config)
    scheduler = Scheduler(service, worker)
    mcp, publish = create_mcp(service)
    allowed_hosts = ["localhost:*", "127.0.0.1:*", "[::1]:*", *config.mcp_allowed_hosts]
    if config.host not in {"0.0.0.0", "::", ""}:
        configured_host = f"[{config.host}]:*" if ":" in config.host else f"{config.host}:*"
        allowed_hosts.append(configured_host)
    if config.public_url:
        public_host = urlparse(config.public_url).hostname
        if public_host:
            allowed_hosts.append(f"[{public_host}]:*" if ":" in public_host else f"{public_host}:*")
    allowed_hosts = list(dict.fromkeys(allowed_hosts))
    remote = mcp.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        max_request_body_size=config.upload_mb * 1024**2 * 4 // 3 + 65536,
        transport_security=TransportSecuritySettings(
            allowed_hosts=allowed_hosts,
            allowed_origins=[config.public_url]
            if config.public_url
            else config.mcp_allowed_origins,
        ),
    )

    @asynccontextmanager
    async def lifespan(app):
        started = False
        try:
            if start_scheduler:
                await asyncio.to_thread(scheduler.start)
                started = True
            async with remote.router.lifespan_context(remote):
                yield
        finally:
            if started:
                await asyncio.to_thread(scheduler.stop)
            db.engine.dispose()

    app = FastAPI(
        title="GradleMCP",
        version="0.1.0",
        lifespan=lifespan,
        description="Bearer-authenticated asynchronous isolated Gradle execution. ZIP upload uses application/zip. All /api/v1 routes require a credential.",
    )
    app.state.service, app.state.scheduler = service, scheduler
    app.add_middleware(SecurityMiddleware, service=service)

    @app.exception_handler(ServiceError)
    async def error(request, exc):
        return JSONResponse({"error": exc.body}, status_code=exc.status)

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        return JSONResponse(
            {
                "error": {
                    "code": "internal_error",
                    "message": "Internal service error; contact the operator",
                    "retryable": False,
                    "permanent": False,
                    "details": {},
                }
            },
            status_code=500,
        )

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        # Pydantic input values can contain secrets; never serialize them back.
        return JSONResponse(
            {
                "error": {
                    "code": "invalid_request",
                    "message": "Request does not match the documented schema",
                    "retryable": False,
                    "permanent": True,
                    "details": {"fields": [list(e["loc"]) for e in exc.errors()]},
                }
            },
            status_code=422,
        )

    def client(request: Request):
        return request.state.client

    @app.get("/health", tags=["Health"])
    def health():
        return {"status": "ok"}

    @app.get("/ready", tags=["Health"])
    def ready():
        ok = worker.available()
        try:
            service.check_disk()
        except ServiceError:
            ok = False
        return JSONResponse({"ready": ok}, status_code=200 if ok else 503)

    @app.get("/api/v1/capabilities")
    def capabilities(c=Depends(client)):
        return service.capabilities(c)

    @app.get("/api/v1/system/endpoint")
    def endpoint(c=Depends(client)):
        require(c, "read")
        return endpoint_status(config)

    @app.get("/api/v1/system/toolchains")
    @app.get("/api/v1/toolchains")
    def toolchains(c=Depends(client)):
        return service.capabilities(c)["toolchains"]

    @app.post(
        "/api/v1/projects",
        status_code=201,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
            }
        },
    )
    async def upload(request: Request, c=Depends(client)):
        data = await request.body()
        return await run_in_threadpool(service.upload, c, data)

    @app.post("/api/v1/projects/inspect")
    def inspect(request: InspectRequest, c=Depends(client)):
        return service.project(c, request.project_id, request.subdirectory)[1]

    @app.post("/api/v1/projects/compatibility")
    def compatibility(request: BuildRequest, c=Depends(client)):
        return service.compatibility(c, request)

    @app.delete("/api/v1/projects/{project_id}")
    def delete_project(project_id: str, c=Depends(client)):
        return service.delete_project(c, project_id)

    @app.post("/api/v1/builds", status_code=202)
    def submit(request: BuildRequest, c=Depends(client)):
        return service.submit(c, request)

    @app.get("/api/v1/builds")
    def builds(
        offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), c=Depends(client)
    ):
        return service.list_jobs(c, offset, limit)

    @app.get("/api/v1/builds/{build_id}")
    def status(build_id: str, c=Depends(client)):
        return service.status(c, build_id)

    @app.post("/api/v1/builds/{build_id}/cancel")
    def cancel(build_id: str, c=Depends(client)):
        return service.cancel(c, build_id)

    @app.get("/api/v1/builds/{build_id}/logs")
    def logs(
        build_id: str,
        offset: int = Query(0, ge=0),
        limit: int = Query(65536, ge=1, le=65536),
        c=Depends(client),
    ):
        return service.logs(c, build_id, offset, limit)

    @app.get("/api/v1/builds/{build_id}/artifacts")
    def artifacts(build_id: str, c=Depends(client)):
        return service.artifacts(c, build_id)

    @app.get("/api/v1/builds/{build_id}/artifacts/{artifact_id}")
    def artifact(build_id: str, artifact_id: str, c=Depends(client)):
        path, item = service.artifact(c, build_id, artifact_id)
        return FileResponse(
            path, filename=item["path"].split("/")[-1], media_type="application/octet-stream"
        )

    @app.post("/api/v1/builds/{build_id}/publish", status_code=202)
    def publication(build_id: str, request: PublishRequest, c=Depends(client)):
        return publish(c, build_id, request.tasks, request.idempotency_key)

    @app.get("/api/v1/queue")
    def queue(c=Depends(client)):
        return service.queue(c)

    @app.get("/api/v1/metrics", response_class=PlainTextResponse)
    def metrics(c=Depends(client)):
        require(c, "admin")
        q = service.queue(c)
        return (
            "\n".join(
                f"gradlemcp_{key} {q[key]}"
                for key in ("queued", "active", "available_workers", "disk_free_bytes")
            )
            + "\n"
        )

    if config.ui_enabled:
        web_root = Path(__file__).with_name("web")
        if not (web_root / "index.html").is_file():
            raise RuntimeError("Optional web UI assets are missing from this installation")

        @app.get("/ui", include_in_schema=False)
        def ui_redirect():
            return RedirectResponse("/ui/", status_code=307)

        @app.get("/ui/", include_in_schema=False)
        def ui_index():
            return FileResponse(
                web_root / "index.html",
                media_type="text/html",
                headers={
                    "Cache-Control": "no-store",
                    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
                    "Referrer-Policy": "no-referrer",
                    "X-Content-Type-Options": "nosniff",
                    "X-Frame-Options": "DENY",
                },
            )

        app.mount(
            "/ui/assets",
            StaticFiles(directory=web_root / "assets", check_dir=True),
            name="ui-assets",
        )

    # Actual routes supply schemas; declare shared bearer security for clients/code generators.
    original_openapi = app.openapi

    def openapi():
        schema = original_openapi()
        schema.setdefault("components", {}).setdefault("securitySchemes", {})["BearerAuth"] = {
            "type": "http",
            "scheme": "bearer",
        }
        errors = ErrorResponse.model_json_schema(ref_template="#/components/schemas/{model}")
        definitions = errors.pop("$defs", {})
        schemas = schema["components"].setdefault("schemas", {})
        schemas.update(definitions)
        schemas["ErrorResponse"] = errors
        for path, operations in schema["paths"].items():
            if path.startswith("/api/"):
                for operation in operations.values():
                    operation["security"] = [{"BearerAuth": []}]
                    for status_code in (400, 401, 403, 404, 409, 413, 422, 429, 500, 503):
                        operation.setdefault("responses", {})[str(status_code)] = {
                            "description": "Structured service or validation error",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                                }
                            },
                        }
        return schema

    app.openapi = openapi  # type: ignore[method-assign]
    app.mount("/mcp", remote)
    return app
