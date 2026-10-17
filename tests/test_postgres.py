"""PostgreSQL transaction/claim path. CI supplies a disposable PostgreSQL service."""

import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import archive

from gradlemcp.config import Settings
from gradlemcp.db import Database
from gradlemcp.scheduler import Scheduler
from gradlemcp.service import BuildRequest, Service


@pytest.mark.skipif(
    not os.getenv("GRADLEMCP_TEST_POSTGRES"), reason="PostgreSQL test service not configured"
)
def test_postgres_admission_and_claim(tmp_path):
    settings = Settings(
        data_dir=tmp_path, database_url=os.environ["GRADLEMCP_TEST_POSTGRES"], storage_reserve_mb=0
    )
    database = Database(settings)
    service = Service(settings, database)
    token = database.create_credential("test-" + uuid.uuid4().hex, ["read", "build"])
    client = database.authenticate(token)
    project = service.upload(client, archive())["project_id"]
    request = BuildRequest(project_id=project, idempotency_key="same-operation")
    with ThreadPoolExecutor(max_workers=8) as pool:
        submitted = list(pool.map(lambda _: service.submit(client, request), range(8)))
    assert len({job["id"] for job in submitted}) == 1
    scheduler = Scheduler(service, object())
    with ThreadPoolExecutor(max_workers=8) as pool:
        claimed = list(pool.map(lambda _: scheduler.claim(), range(8)))
    assert sum(job is not None for job in claimed) == 1
    scheduler.pool.shutdown()
    database.engine.dispose()
