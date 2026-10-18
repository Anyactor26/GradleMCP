import hashlib
import hmac
import re
import secrets
import time
from contextlib import contextmanager

from sqlalchemy import JSON, Boolean, Float, Integer, String, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .errors import ServiceError


class Base(DeclarativeBase):
    pass


class Credential(Base):
    __tablename__ = "credentials"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    digest: Mapped[str] = mapped_column(String)
    scopes: Mapped[list] = mapped_column(JSON)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner: Mapped[str] = mapped_column(String, index=True)
    project: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String, index=True, default="queued")
    spec: Mapped[dict] = mapped_column(JSON)
    created: Mapped[float] = mapped_column(Float, default=time.time, index=True)
    started: Mapped[float | None] = mapped_column(Float, nullable=True)
    finished: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    diagnostic: Mapped[dict] = mapped_column(JSON, default=dict)
    artifacts: Mapped[list] = mapped_column(JSON, default=list)
    idempotency: Mapped[str | None] = mapped_column(String, nullable=True)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner: Mapped[str] = mapped_column(String, index=True)
    created: Mapped[float] = mapped_column(Float, default=time.time)
    inspection: Mapped[dict] = mapped_column(JSON)


class Database:
    def __init__(self, config):
        config.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.engine = create_engine(config.database_url)
        if self.engine.dialect.name == "sqlite":

            @event.listens_for(self.engine, "connect")
            def pragmas(connection, _):
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA busy_timeout=10000")

        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        Base.metadata.create_all(self.engine)

    @contextmanager
    def transaction(self):
        # Serializes queue admission/claim/cancel across threads and processes.
        with self.sessions() as session:
            if self.engine.dialect.name == "sqlite":
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            else:
                session.connection().exec_driver_sql("SELECT pg_advisory_xact_lock(73461982)")
            try:
                yield session
                session.commit()
            except BaseException:
                session.rollback()
                raise

    def create_credential(self, name, scopes):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
            raise ServiceError(
                "invalid_client", "Client ID must be 1-64 letters, digits, dashes or underscores"
            )
        token = name + "." + secrets.token_urlsafe(32)
        with self.transaction() as s:
            if s.get(Credential, name):
                raise ServiceError(
                    "client_exists", "Use credentials rotate to replace this client token", 409
                )
            s.add(
                Credential(
                    id=name, digest=hashlib.sha256(token.encode()).hexdigest(), scopes=scopes
                )
            )
        return token

    def rotate_credential(self, name, scopes=None):
        """Replace a token atomically without changing ownership or per-client quotas."""
        with self.transaction() as session:
            credential = session.get(Credential, name)
            if not credential:
                raise ServiceError("not_found", "Client not found", 404)
            token = name + "." + secrets.token_urlsafe(32)
            credential.digest = hashlib.sha256(token.encode()).hexdigest()
            credential.revoked = False
            if scopes is not None:
                credential.scopes = scopes
        return token

    def authenticate(self, token):
        with self.sessions() as s:
            credential = s.get(Credential, token.split(".")[0])
            digest = credential.digest if credential else "0" * 64
            valid = hmac.compare_digest(digest, hashlib.sha256(token.encode()).hexdigest())
            if not valid or not credential or credential.revoked:
                raise ServiceError("unauthorized", "Valid bearer credential required", 401)
            return credential

    def revoke(self, name):
        with self.transaction() as s:
            credential = s.get(Credential, name)
            if not credential:
                raise ServiceError("not_found", "Client not found", 404)
            credential.revoked = True


def require(client, scope):
    if scope not in client.scopes and "admin" not in client.scopes:
        raise ServiceError("forbidden", f"Required scope: {scope}", 403)


def owned(session, model, identifier, client):
    obj = session.get(model, identifier)
    if obj is None or (obj.owner != client.id and "admin" not in client.scopes):
        raise ServiceError("not_found", "Resource not found", 404)
    return obj


TERMINAL = {"succeeded", "failed", "cancelled", "timed_out", "resource_limit_exceeded"}
ACTIVE = {"preparing", "running", "cancelling"}
