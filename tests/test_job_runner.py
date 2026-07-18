import pytest

from backend.models.cluster import Cluster
from backend.models.job import Job
from backend.models.run import Run
from backend.services.job_runner import JobRunner
from tests.conftest import test_session_factory  # in-memory; autouse setup_db creates/drops tables

# NOTE: JobRunner defaults to backend.database.async_session_factory (the real file DB). In tests,
# construct it as JobRunner(session_factory=test_session_factory, ...) so it uses the in-memory DB.


async def _make_job(job_type="force_merge"):
    async with test_session_factory() as s:
        c = Cluster(name=f"c{job_type}", url="http://es.example.com")
        s.add(c)
        await s.flush()
        r = Run(cluster_id=c.id)
        s.add(r)
        await s.flush()  # Run has no `status` column
        j = Job(
            run_id=r.id,
            cluster_id=c.id,
            index_name="i",
            job_type=job_type,
            tier=1,
            status="queued",  # runner now promotes queued -> executing on slot acquisition
        )
        s.add(j)
        await s.commit()
        return j.id, c.id


@pytest.mark.asyncio
async def test_runner_marks_completed_and_records_progress():
    job_id, _ = await _make_job()
    seen = []

    async def fake_exec(_es, job, *, on_progress):
        await on_progress("working")
        seen.append(job.id)

    runner = JobRunner(
        session_factory=test_session_factory,
        es_factory=lambda _c: object(),
        executors={"force_merge": fake_exec},
    )
    runner.submit(job_id)
    await runner.wait(job_id)
    async with test_session_factory() as s:
        j = await s.get(Job, job_id)
        assert j.status == "completed"
        assert j.progress == "working"
    assert seen == [job_id]


@pytest.mark.asyncio
async def test_runner_marks_failed_on_exception():
    job_id, _ = await _make_job()

    async def boom(_es, _job, *, on_progress):  # noqa: ARG001
        raise RuntimeError("nope")

    runner = JobRunner(
        session_factory=test_session_factory,
        es_factory=lambda _c: object(),
        executors={"force_merge": boom},
    )
    runner.submit(job_id)
    await runner.wait(job_id)
    async with test_session_factory() as s:
        j = await s.get(Job, job_id)
        assert j.status == "failed"
        assert "nope" in (j.error_message or "")


@pytest.mark.asyncio
async def test_should_not_overwrite_terminal_status_when_finalize_races():
    # A cancel that already drove the job to a terminal state must win: a late "completed" finalize
    # (the executor finishing just as cancellation lands) must not clobber the cancelled status.
    job_id, _ = await _make_job()
    async with test_session_factory() as s:
        j = await s.get(Job, job_id)
        j.status = "cancelled"
        await s.commit()
        s.expunge(j)
        src = j  # detached real Job (mirrors _run_with_slot's expunged src) — valid NOT NULL fields

    runner = JobRunner(session_factory=test_session_factory, es_factory=lambda _c: object(), executors={})
    await runner._finalize(job_id, "completed", None, src)

    async with test_session_factory() as s:
        j = await s.get(Job, job_id)
        assert j.status == "cancelled"
