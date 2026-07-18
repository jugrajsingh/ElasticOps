"""In-process async job runner.

Runs submitted jobs as background ``asyncio`` tasks, moving each job through the
``queued -> executing -> completed | failed | cancelled`` lifecycle and persisting status,
progress, and errors to the DB. It mirrors the background-task idiom of
:class:`backend.services.poller` (``asyncio.create_task`` + a per-job task registry + graceful
cancellation), but is keyed by job rather than by cluster.

Concurrency model — the queue is *visible*:

* A route flips a job to ``queued`` and calls :meth:`submit`. Each :meth:`submit` launches one
  ``asyncio.Task`` per job, tracked in ``self._tasks`` and evicted by a done-callback.
  Re-submitting a job already in flight is a no-op.
* A :class:`asyncio.Semaphore` (``max_concurrent``) bounds how many jobs run concurrently. A
  submitted task is created immediately but **blocks on the semaphore** while still labelled
  ``queued``; only once it acquires a slot does it flip the job to ``executing`` and invoke the
  executor. So at any moment at most ``max_concurrent`` jobs are ``executing`` and the rest sit
  ``queued`` — the UI can show a real queue. The cap defaults to
  ``get_settings().jobs.max_concurrent`` (env ``JOBS__MAX_CONCURRENT``) but stays injectable for
  tests, and is exposed read-only as :attr:`max_concurrent`.

Session model: the runner opens its **own** short-lived DB session per job (and a separate one per
progress update) via the injected ``session_factory`` — it never shares a session across tasks. This
keeps each job's writes isolated and avoids cross-task session reuse (which SQLAlchemy async sessions
forbid).

Recovery: :meth:`recover` re-submits any job left in ``queued`` or ``executing`` after a restart, on
the assumption that the registered executors are idempotent / resumable.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select

from backend.database import async_session_factory
from backend.models.cluster import Cluster
from backend.models.job import Job
from backend.services import executor as default_executor
from backend.services.es_client import ESClient
from backend.services.secrets import decrypt
from config.settings import get_settings

logger = logging.getLogger("elasticops")

# Once a job reaches one of these it is done; no later writer may move it. Guards against a late
# "completed"/"failed" finalize clobbering a "cancelled" that won the cancellation race.
_TERMINAL = frozenset({"completed", "failed", "cancelled", "rejected"})


def _default_es_factory(cluster: Cluster) -> ESClient:
    return ESClient(
        base_url=cluster.url,
        username=cluster.username,
        password=decrypt(cluster.password_encrypted),
        verify_ssl=cluster.verify_ssl,
    )


def _default_executors() -> dict[str, Callable]:
    # Only the executors that exist today. Later tasks add new entries here when those executor
    # functions land. Do NOT reference functions that don't exist yet — it would break this
    # module's import.
    return {
        "force_merge": default_executor.execute_force_merge,
        "reduce_shards": default_executor.execute_reduce_shards,
        "relocate_shard": default_executor.execute_relocate_shard,
        "drain_node": default_executor.execute_drain_node,
        "split_shards": default_executor.execute_split_shards,
        "expunge_deletes": default_executor.execute_expunge_deletes,
        "promote_index": default_executor.execute_promote_index,
        "reindex": default_executor.execute_reindex,
    }


class JobRunner:
    """Runs approved jobs as background asyncio tasks, updating status + progress in the DB."""

    def __init__(
        self,
        *,
        session_factory=async_session_factory,
        es_factory=_default_es_factory,
        executors: dict[str, Callable] | None = None,
        max_concurrent: int | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._es_factory = es_factory
        self._executors = executors or _default_executors()
        self._max_concurrent = max_concurrent if max_concurrent is not None else get_settings().jobs.max_concurrent
        self._sem = asyncio.Semaphore(self._max_concurrent)
        self._tasks: dict[int, asyncio.Task] = {}

    @property
    def max_concurrent(self) -> int:
        """Global cap on concurrently-executing jobs (read-only; reportable to the UI)."""
        return self._max_concurrent

    def submit(self, job_id: int) -> None:
        """Launch a background task for ``job_id`` (no-op if one is already in flight)."""
        if job_id in self._tasks:
            return
        task = asyncio.create_task(self._run(job_id))
        self._tasks[job_id] = task
        task.add_done_callback(lambda _t, jid=job_id: self._tasks.pop(jid, None))

    async def wait(self, job_id: int) -> None:
        """Await a submitted job's task (test/shutdown helper); tolerates cancellation."""
        task = self._tasks.get(job_id)
        if task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def cancel(self, job_id: int) -> bool:
        """Request cancellation of an in-flight job. Returns False if it isn't running."""
        task = self._tasks.get(job_id)
        if task is None:
            return False
        task.cancel()
        return True

    async def stop_all(self) -> None:
        """Cancel all in-flight job tasks and await their cancellation (lifespan shutdown)."""
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    async def recover(self) -> None:
        """Resume jobs left in 'queued' or 'executing' after a restart by re-submitting them.

        A job interrupted while still ``queued`` (waiting for a slot) resumes the same way as one
        interrupted mid-``executing``: it is re-submitted and re-acquires a slot before running.

        NOTE: resumption is best-effort — executors are expected to be idempotent where possible;
        ``reduce_shards`` is not fully idempotent and may fail cleanly on re-run.
        """
        async with self._session_factory() as s:
            rows = (await s.execute(select(Job).where(Job.status.in_(("queued", "executing"))))).scalars().all()
            ids = [j.id for j in rows]
            # Re-queue anything caught mid-flight: a recovered job re-enters the queue and only
            # flips back to 'executing' once it re-acquires a slot (keeps the _run gate queued-only).
            for job in rows:
                if job.status != "queued":
                    job.status = "queued"
            await s.commit()
        for jid in ids:
            self.submit(jid)
        if ids:
            logger.info("JobRunner resuming %d interrupted job(s): %s", len(ids), ids)

    async def _set_progress(self, job_id: int, text: str) -> None:
        async with self._session_factory() as s:
            job = await s.get(Job, job_id)
            if job is not None:
                job.progress = text
                await s.commit()

    async def _run(self, job_id: int) -> None:
        try:
            await self._sem.acquire()
        except asyncio.CancelledError:
            # Cancelled while still 'queued' (blocked on the slot) — never acquired a slot, so the
            # executor never ran. Mark it cancelled and re-raise.
            await self._mark_cancelled_if_queued(job_id)
            raise
        try:
            await self._run_with_slot(job_id)
        finally:
            self._sem.release()

    async def _mark_cancelled_if_queued(self, job_id: int) -> None:
        """Flip a still-'queued' job to 'cancelled' (cancel arrived before it acquired a slot)."""
        async with self._session_factory() as s:
            job = await s.get(Job, job_id)
            if job is not None and job.status == "queued":
                job.status = "cancelled"
                job.completed_at = datetime.now(UTC)
                try:
                    await s.commit()
                except Exception:
                    logger.exception("Failed to persist cancelled status for queued job %s", job_id)

    async def _run_with_slot(self, job_id: int) -> None:
        """Run the executor for a job that has acquired a concurrency slot.

        The DB session is NOT held while the executor runs — that can take minutes/hours (drain,
        reindex), and pinning a connection for the whole job both starves the pool in production
        and deadlocks the shared in-memory test DB. Instead: flip ``queued`` -> ``executing`` in a
        short session, detach the job + cluster, run the executor against the detached object
        (progress updates use their own short sessions), then persist the terminal status and the
        executor's in-place mutations in a second short session.
        """
        async with self._session_factory() as s:
            # The job sat in 'queued' while this task blocked on the semaphore. Now that a slot is
            # held we flip it to 'executing' — so at most ``max_concurrent`` jobs are ever
            # 'executing' and the rest stay visibly 'queued'.
            job = await s.get(Job, job_id)
            if job is None or job.status != "queued":
                # Cancelled or otherwise changed while waiting for a slot — never run the executor.
                return
            job.status = "executing"
            job.progress = "starting"
            await s.commit()
            cluster = await s.get(Cluster, job.cluster_id)
            s.expunge(job)
            if cluster is not None:
                s.expunge(cluster)
        # Session released — no DB connection is held for the duration of the executor.
        es = self._es_factory(cluster)
        fn = self._executors.get(job.job_type)

        async def on_progress(text: str) -> None:
            await self._set_progress(job_id, text)

        try:
            if fn is None:
                raise ValueError(f"Unknown job type: {job.job_type}")  # noqa: TRY003, TRY301
            await fn(es, job, on_progress=on_progress)
        except asyncio.CancelledError:
            await self._finalize(job_id, "cancelled", None, job)
            raise
        except Exception as exc:
            logger.exception("Job %s (%s) failed", job_id, job.job_type)
            await self._finalize(job_id, "failed", str(exc), job)
        else:
            await self._finalize(job_id, "completed", None, job)

    async def _finalize(self, job_id: int, status: str, error: str | None, src: Job) -> None:
        """Persist the terminal status + the executor's in-place mutations in a short session."""
        async with self._session_factory() as s:
            job = await s.get(Job, job_id)
            if job is None:
                return
            if job.status in _TERMINAL:
                # Already finalized (e.g. a cancel won the race). First terminal writer wins.
                return
            job.status = status
            job.completed_at = datetime.now(UTC)
            if error is not None:
                job.error_message = error
            # Carry over the fields executors mutate on the (now-detached) job object. Progress is
            # intentionally NOT copied — it's owned by on_progress() via its own short sessions, and
            # src (detached) never sees those updates, so copying it would clobber the live value.
            job.detail = src.detail
            job.target_shards = src.target_shards
            job.task_id = src.task_id
            try:
                await s.commit()
            except Exception:
                logger.exception("Failed to persist terminal status for job %s", job_id)
