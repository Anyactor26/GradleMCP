import concurrent.futures
import logging
import shutil
import threading
import time

from sqlalchemy import select

from .db import ACTIVE, TERMINAL, Job, Project
from .errors import ServiceError

log = logging.getLogger("gradlemcp.scheduler")


class Scheduler:
    """One scheduler per data directory; DB transactions additionally serialize dispatch."""

    def __init__(self, service, worker):
        self.service, self.worker = service, worker
        self.stop_event = threading.Event()
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=service.config.max_workers)
        self.futures = set()
        self.thread = None
        self.lockfile = None
        self.last_cleanup = 0.0

    def start(self):
        import fcntl

        self.lockfile = (self.service.config.data_dir / "scheduler.lock").open("w")
        try:
            try:
                fcntl.flock(self.lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("Only one GradleMCP scheduler may use a data directory") from exc
            # Crash recovery never releases slots until removal is confirmed.
            with self.service.db.transaction() as session:
                for job in session.scalars(select(Job).where(Job.state.in_(ACTIVE))):
                    self.worker.cleanup(job.id)
                    job.state, job.finished = "failed", time.time()
                    job.diagnostic = {
                        "code": "server_interrupted",
                        "message": "Server interrupted the job; worker removed. Publication is never automatically retried.",
                        "retryable": False,
                    }
            self.thread = threading.Thread(target=self.loop, daemon=True, name="scheduler")
            self.thread.start()
        except BaseException:
            self.lockfile.close()
            self.pool.shutdown(wait=False)
            raise

    def claim(self):
        self.service.check_disk()
        with self.service.db.transaction() as s:
            active = s.scalars(select(Job).where(Job.state.in_(ACTIVE))).all()
            if len(active) >= self.service.config.max_workers:
                return None
            for job in s.scalars(
                select(Job).where(Job.state == "queued").order_by(Job.created, Job.id)
            ):
                if (
                    sum(j.owner == job.owner for j in active)
                    >= self.service.config.per_client_active
                ):
                    continue
                job.state, job.started = "preparing", time.time()
                s.flush()
                return job
        return None

    def run_job(self, job):
        def state():
            with self.service.db.sessions() as s:
                current = s.get(Job, job.id)
                return current.state

        def running():
            with self.service.db.transaction() as s:
                current = s.get(Job, job.id)
                if current.state == "preparing":
                    current.state = "running"

        try:
            outcome, code, diagnostic, artifacts = self.worker.execute(job, state, running)
        except Exception as exc:
            log.error(
                '{"event":"worker_failure","job":"%s","type":"%s"}', job.id, type(exc).__name__
            )
            try:
                self.worker.cleanup(job.id)
            except Exception:
                # Keep slot occupied until a subsequent restart/operator confirms termination.
                with self.service.db.transaction() as s:
                    current = s.get(Job, job.id)
                    current.state = "cancelling"
                    current.diagnostic = {
                        "code": "termination_unconfirmed",
                        "message": "Operator must restore Docker and restart service to confirm worker termination",
                    }
                return
            outcome, code, artifacts = "failed", None, []
            diagnostic = (
                exc.body
                if isinstance(exc, ServiceError)
                else {
                    "code": "worker_internal",
                    "message": "Worker failed; contact administrator",
                    "retryable": False,
                }
            )
        with self.service.db.transaction() as s:
            current = s.get(Job, job.id)
            if current.state == "cancelling":
                outcome = "cancelled"
            current.state, current.exit_code = outcome, code
            current.diagnostic, current.artifacts, current.finished = (
                diagnostic,
                artifacts,
                time.time(),
            )

    def cleanup_expired(self):
        cutoff = time.time() - self.service.config.retention_hours * 3600
        with self.service.db.transaction() as s:
            for job in s.scalars(select(Job).where(Job.state.in_(TERMINAL), Job.finished < cutoff)):
                shutil.rmtree(self.service.config.data_dir / "jobs" / job.id, ignore_errors=True)
                job.artifacts = []
            for project in s.scalars(select(Project).where(Project.created < cutoff)):
                pending = s.scalar(
                    select(Job).where(Job.project == project.id, Job.state.not_in(TERMINAL))
                )
                if not pending:
                    shutil.rmtree(
                        self.service.config.data_dir / "projects" / project.id, ignore_errors=True
                    )
                    s.delete(project)

    def loop(self):
        while not self.stop_event.is_set():
            self.futures = {f for f in self.futures if not f.done()}
            try:
                if len(self.futures) < self.service.config.max_workers:
                    job = self.claim()
                    if job:
                        self.futures.add(self.pool.submit(self.run_job, job))
                if time.monotonic() - self.last_cleanup > 60:
                    self.cleanup_expired()
                    self.last_cleanup = time.monotonic()
            except Exception as exc:
                log.error('{"event":"scheduler_error","type":"%s"}', type(exc).__name__)
            self.stop_event.wait(0.25)

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join()
        with self.service.db.transaction() as s:
            for job in s.scalars(select(Job).where(Job.state.in_(ACTIVE))):
                job.state = "cancelling"
        self.pool.shutdown(wait=True)
        if self.lockfile:
            self.lockfile.close()
