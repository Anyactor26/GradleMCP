import json
import os
import re
from ipaddress import IPv6Address
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Toolchain(BaseModel):
    image: str
    java: int = Field(ge=8, le=99)
    gradle: str
    android: bool = False
    native: bool = False


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GRADLEMCP_", extra="forbid")
    data_dir: Path = Path("./data")
    database_url: str = "sqlite:///./data/gradlemcp.db"
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    max_workers: int = Field(default=1, ge=1, le=32)
    max_queue: int = Field(default=32, ge=1)
    per_client_active: int = Field(default=1, ge=1)
    per_client_queued: int = Field(default=8, ge=1)
    memory_mb: int = Field(default=2048, ge=256)
    total_memory_mb: int = Field(default=2048, ge=256)
    cpus: float = Field(default=1, gt=0)
    pids: int = Field(default=256, ge=32)
    timeout_seconds: int = Field(default=1800, ge=1)
    upload_mb: int = Field(default=16, ge=1)
    workspace_mb: int = Field(default=512, ge=16)
    artifact_mb: int = Field(default=64, ge=1)
    log_mb: int = Field(default=8, ge=1)
    max_files: int = Field(default=10000, ge=1)
    retention_hours: int = Field(default=168, ge=1)
    storage_reserve_mb: int = Field(default=1024, ge=0)
    requests_per_minute: int = Field(default=120, ge=1)
    network: str = "none"
    wrapper_enabled: bool = False
    wrapper_hosts: list[str] = ["services.gradle.org", "downloads.gradle.org"]
    auto_pull: bool = False
    toolchains: dict[str, Toolchain] = {
        "java17": Toolchain(image="gradlemcp-worker:17", java=17, gradle="8.14.3")
    }
    public_url: str | None = None
    mcp_allowed_hosts: list[str] = []
    mcp_allowed_origins: list[str] = []
    ui_enabled: bool = False
    exposure: Literal["private", "direct", "proxy", "cloudflare", "ngrok", "custom"] = "private"
    tunnel_status_url: str | None = None
    publish_tasks: list[str] = []
    publish_toolchain: str | None = None
    publish_secrets_file: Path | None = None
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @model_validator(mode="after")
    def validate_policy(self):
        if self.max_workers * self.memory_mb > self.total_memory_mb:
            raise ValueError("total_memory_mb must cover max_workers * memory_mb")
        if not self.toolchains:
            raise ValueError("configure at least one approved toolchain")
        if self.network in {"host", "bridge", "default"} or self.network.startswith("container:"):
            raise ValueError("network must be none or an operator-created egress-filtered network")
        if self.auto_pull and any(
            not re.fullmatch(r"[^\s]+@sha256:[a-f0-9]{64}", t.image)
            for t in self.toolchains.values()
        ):
            raise ValueError("auto_pull requires digest-pinned approved toolchain images")
        if self.public_url:
            try:
                url = urlparse(self.public_url)
                port = url.port
            except ValueError as exc:
                raise ValueError("public_url must be an HTTPS origin with a valid port") from exc
            if (
                url.scheme != "https"
                or not url.hostname
                or url.username
                or url.password
                or url.path
                or url.query
                or url.fragment
                or (port is not None and not 1 <= port <= 65535)
            ):
                raise ValueError(
                    "public_url must be an HTTPS origin without credentials, path or query"
                )
        for allowed_host in self.mcp_allowed_hosts:
            if (
                not isinstance(allowed_host, str)
                or not allowed_host
                or allowed_host != allowed_host.strip()
            ):
                raise ValueError(
                    "mcp_allowed_hosts entries must be exact host names with an optional port"
                )
            host_part = allowed_host
            port_part = None
            if allowed_host.startswith("["):
                closing = allowed_host.find("]")
                if closing < 0:
                    raise ValueError("mcp_allowed_hosts contains an invalid IPv6 host")
                host_part = allowed_host[1:closing]
                suffix = allowed_host[closing + 1 :]
                if suffix:
                    if not suffix.startswith(":"):
                        raise ValueError("mcp_allowed_hosts contains an invalid host/port")
                    port_part = suffix[1:]
                try:
                    IPv6Address(host_part)
                except ValueError as exc:
                    raise ValueError("mcp_allowed_hosts contains an invalid IPv6 host") from exc
            elif ":" in allowed_host:
                host_part, port_part = allowed_host.rsplit(":", 1)
            if not allowed_host.startswith("[") and not re.fullmatch(r"[A-Za-z0-9.-]+", host_part):
                raise ValueError("mcp_allowed_hosts contains an invalid host")
            if (
                not host_part
                or host_part == "*"
                or host_part.startswith((".", "-"))
                or host_part.endswith((".", "-"))
                or ".." in host_part
                or ".-" in host_part
                or "-." in host_part
            ):
                raise ValueError("mcp_allowed_hosts entries must name a specific host")
            if port_part is not None and port_part != "*":
                if not port_part.isdigit() or not 1 <= int(port_part) <= 65535:
                    raise ValueError("mcp_allowed_hosts ports must be 1..65535 or *")
        for allowed_origin in self.mcp_allowed_origins:
            if not isinstance(allowed_origin, str) or allowed_origin != allowed_origin.strip():
                raise ValueError("mcp_allowed_origins entries must be exact origins")
            wildcard_port = allowed_origin.endswith(":*")
            candidate = allowed_origin[:-2] if wildcard_port else allowed_origin
            try:
                origin = urlparse(candidate)
                port = origin.port
            except ValueError as exc:
                raise ValueError("mcp_allowed_origins contains an invalid origin") from exc
            if wildcard_port and port is not None:
                raise ValueError("mcp_allowed_origins wildcard ports must be the only port marker")
            if (
                origin.scheme not in {"http", "https"}
                or not origin.hostname
                or "*" in origin.hostname
                or origin.username
                or origin.password
                or origin.path
                or origin.query
                or origin.fragment
                or allowed_origin == "*"
            ):
                raise ValueError("mcp_allowed_origins entries must be specific HTTP(S) origins")
            if port is not None and not 1 <= port <= 65535:
                raise ValueError("mcp_allowed_origins ports must be 1..65535 or *")
        if self.publish_secrets_file and (
            not self.publish_secrets_file.is_file()
            or self.publish_secrets_file.stat().st_mode & 0o077
        ):
            raise ValueError(
                "publish_secrets_file must exist and have private 0600/0400 permissions"
            )
        if self.publish_tasks and (
            self.publish_toolchain not in self.toolchains or not self.publish_secrets_file
        ):
            raise ValueError("publishing requires a dedicated approved toolchain and secret file")
        return self


def load_settings(**overrides) -> Settings:
    path = Path(os.environ.get("GRADLEMCP_CONFIG", "gradlemcp.json"))
    values = json.loads(path.read_text()) if path.exists() else {}
    # BaseSettings environment normally loses to init values; merge explicitly for documented order.
    for key in Settings.model_fields:
        env = os.environ.get(f"GRADLEMCP_{key.upper()}")
        if env is not None:
            try:
                values[key] = json.loads(env)
            except ValueError:
                values[key] = env
    return Settings(**(values | overrides))
