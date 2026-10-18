import json
import os
import re
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
    host: str = "127.0.0.1"
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
            url = urlparse(self.public_url)
            if (
                url.scheme != "https"
                or not url.hostname
                or url.username
                or url.password
                or url.path
                or url.query
                or url.fragment
            ):
                raise ValueError(
                    "public_url must be an HTTPS origin without credentials, path or query"
                )
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
