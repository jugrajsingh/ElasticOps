"""Visible-queue + configurable-cap tests for :class:`backend.services.job_runner.JobRunner`.

A dedicated in-memory engine with a ``StaticPool`` (one shared connection) makes the runner's status
writes immediately visible to the test's reads. Tests coordinate via ``asyncio.Event`` (the executor
signals when it starts) and assert the cap with a counter — never by polling the DB for transient
states, which would race the runner on the shared connection. NEVER import ``engine`` /
``async_session_factory`` from ``backend.database``.
"""

import asyncio
import itertools
from collections.abc import AsyncIterator, Callable

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models.cluster import Cluster
from backend.models.job import Job
from backend.models.run import Run
from backend.services.job_runner import JobRunner

_cluster_seq = itertools.count()
Factory = Callable[[], AsyncSession]


@pytest.fixture
async def qdb() -> AsyncIterator[Factory]:
    """A dedicated in-memory engine (single shared connection) for concurrency tests."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _make_queued_job(factory: Factory, job_type: str = "force_merge") -> int:
    async with factory() as s:
        c = Cluster(name=f"c-{job_type}-{next(_cluster_seq)}", url="http://es.example.com")
        s.add(c)
        await s.flush()
        r = Run(cluster_id=c.id)
        s.add(r)
        await s.flush()  # Run has no `status` column
        j = Job(run_id=r.id, cluster_id=c.id, index_name="i", job_type=job_type, tier=1, status="queued")
        s.add(j)
        await s.commit()
        return j.id


async def _status(factory: Factory, job_id: int) -> str:
    async with factory() as s:
        job = await s.get(Job, job_id)
        assert job is not None
        return job.status


@pytest.mark.asyncio
async def test_should_cap_concurrent_executors_and_keep_the_rest_queued(qdb: Factory) -> None:
    """With max_concurrent=1, never more than one executor runs at once; the other stays 'queued'."""
    gate = asyncio.Event()
    started = asyncio.Event()
    running = 0
    max_running = 0
    job_a = await _make_queued_job(qdb)
    job_b = await _make_queued_job(qdb)

    async def blocking_exec(_es, _job, *, on_progress):  # noqa: ARG001
        nonlocal running, max_running
        running += 1
        max_running = max(max_running, running)
        started.set()
        try:
            await gate.wait()
        finally:
            running -= 1

    runner = JobRunner(
        session_factory=qdb,
        es_factory=lambda _c: object(),
        executors={"force_merge": blocking_exec},
        max_concurrent=1,
    )
    assert runner.max_concurrent == 1

    runner.submit(job_a)
    runner.submit(job_b)
    await asyncio.wait_for(started.wait(), timeout=10)  # one executor reached the slot
    await asyncio.sleep(0.05)  # give the other a chance to (wrongly) start — it must not

    assert max_running == 1  # the cap held: only one executor ever ran concurrently
    assert sorted((await _status(qdb, job_a), await _status(qdb, job_b))) == ["executing", "queued"]

    gate.set()
    await runner.wait(job_a)
    await runner.wait(job_b)
    assert max_running == 1  # the second only ran after the first released the slot
    assert await _status(qdb, job_a) == "completed"
    assert await _status(qdb, job_b) == "completed"


@pytest.mark.asyncio
async def test_should_transition_queued_to_executing_on_slot_acquisition(qdb: Factory) -> None:
    """A submitted job is 'queued' until it acquires a slot, then 'executing' while running."""
    gate = asyncio.Event()
    started = asyncio.Event()
    job_id = await _make_queued_job(qdb)

    async def blocking_exec(_es, _job, *, on_progress):  # noqa: ARG001
        started.set()
        await gate.wait()

    runner = JobRunner(
        session_factory=qdb,
        es_factory=lambda _c: object(),
        executors={"force_merge": blocking_exec},
        max_concurrent=1,
    )
    assert await _status(qdb, job_id) == "queued"  # before submit

    runner.submit(job_id)
    await asyncio.wait_for(started.wait(), timeout=10)  # executor running => status already flipped
    assert await _status(qdb, job_id) == "executing"

    gate.set()
    await runner.wait(job_id)
    assert await _status(qdb, job_id) == "completed"


@pytest.mark.asyncio
async def test_should_resubmit_queued_job_on_recover(qdb: Factory) -> None:
    """recover() re-submits a job left in 'queued' and runs it to completion."""
    job_id = await _make_queued_job(qdb)
    ran: list[int] = []

    async def quick_exec(_es, job, *, on_progress):  # noqa: ARG001
        ran.append(job.id)

    runner = JobRunner(
        session_factory=qdb,
        es_factory=lambda _c: object(),
        executors={"force_merge": quick_exec},
        max_concurrent=2,
    )
    await runner.recover()
    await runner.wait(job_id)

    assert ran == [job_id]
    assert await _status(qdb, job_id) == "completed"


@pytest.mark.asyncio
async def test_should_cancel_queued_job_without_running_executor(qdb: Factory) -> None:
    """Cancelling a job still blocked on the slot marks it 'cancelled' and never runs the executor."""
    gate = asyncio.Event()
    started = asyncio.Event()
    job_a = await _make_queued_job(qdb)  # takes the single slot
    job_b = await _make_queued_job(qdb)  # stays queued behind it
    ran: list[int] = []

    async def blocking_exec(_es, job, *, on_progress):  # noqa: ARG001
        ran.append(job.id)
        started.set()
        await gate.wait()

    runner = JobRunner(
        session_factory=qdb,
        es_factory=lambda _c: object(),
        executors={"force_merge": blocking_exec},
        max_concurrent=1,
    )
    runner.submit(job_a)
    runner.submit(job_b)
    await asyncio.wait_for(started.wait(), timeout=10)  # one started + holds the slot
    await asyncio.sleep(0.05)  # let the other settle into 'queued'

    running = ran[0]
    queued = job_b if running == job_a else job_a
    assert await _status(qdb, queued) == "queued"

    assert await runner.cancel(queued) is True
    await runner.wait(queued)
    assert await _status(qdb, queued) == "cancelled"
    assert queued not in ran  # the executor never ran for the cancelled queued job

    gate.set()
    await runner.wait(running)
    assert await _status(qdb, running) == "completed"
