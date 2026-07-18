"""Tests for the clear-queue and clear-history job endpoints.

``clear-queue`` deletes ``approved`` jobs (never submitted) and cancels ``queued`` ones via the
runner (which flips them to ``cancelled``), leaving ``executing`` jobs untouched. ``clear-history``
deletes terminal-status jobs (completed/failed/cancelled/rejected).
"""

from httpx import AsyncClient

from backend.dependencies import get_job_runner
from backend.main import app
from backend.models.cluster import Cluster
from backend.models.job import Job
from backend.models.run import Run
from tests.conftest import test_session_factory


async def _make_cluster(name: str) -> int:
    async with test_session_factory() as s:
        cluster = Cluster(name=name, url="https://es.example.com:9200")
        s.add(cluster)
        await s.commit()
        return cluster.id


async def _seed_job(cluster_id: int, *, status: str) -> int:
    async with test_session_factory() as s:
        run = Run(cluster_id=cluster_id)
        s.add(run)
        await s.flush()
        job = Job(
            run_id=run.id,
            cluster_id=cluster_id,
            index_name="idx",
            job_type="force_merge",
            tier=1,
            status=status,
        )
        s.add(job)
        await s.commit()
        return job.id


async def _job_statuses(cluster_id: int) -> dict[int, str]:
    async with test_session_factory() as s:
        from sqlalchemy import select

        rows = (await s.execute(select(Job).where(Job.cluster_id == cluster_id))).scalars().all()
        return {j.id: j.status for j in rows}


async def test_should_delete_approved_and_cancel_queued_on_clear_queue(authed_client: AsyncClient):
    cluster_id = await _make_cluster("clear-queue-cluster")
    approved_id = await _seed_job(cluster_id, status="approved")
    queued_id = await _seed_job(cluster_id, status="queued")
    executing_id = await _seed_job(cluster_id, status="executing")

    cancelled: list[int] = []

    class _FakeRunner:
        async def cancel(self, jid: int) -> bool:
            cancelled.append(jid)
            return True

    app.dependency_overrides[get_job_runner] = lambda: _FakeRunner()
    try:
        resp = await authed_client.post(f"/api/clusters/{cluster_id}/jobs/clear-queue")
    finally:
        app.dependency_overrides.pop(get_job_runner, None)

    assert resp.status_code == 200
    assert resp.json() == {"cleared": 2}  # approved + queued
    # queued job was cancelled via the runner; executing was never touched.
    assert cancelled == [queued_id]

    statuses = await _job_statuses(cluster_id)
    assert approved_id not in statuses  # deleted
    assert statuses[queued_id] == "queued"  # row remains; runner flips it asynchronously
    assert statuses[executing_id] == "executing"  # untouched


async def test_should_delete_terminal_jobs_on_clear_history(authed_client: AsyncClient):
    cluster_id = await _make_cluster("clear-history-cluster")
    terminal_ids = [
        await _seed_job(cluster_id, status="completed"),
        await _seed_job(cluster_id, status="failed"),
        await _seed_job(cluster_id, status="cancelled"),
        await _seed_job(cluster_id, status="rejected"),
    ]
    keep_ids = [
        await _seed_job(cluster_id, status="approved"),
        await _seed_job(cluster_id, status="queued"),
        await _seed_job(cluster_id, status="executing"),
    ]

    resp = await authed_client.post(f"/api/clusters/{cluster_id}/jobs/clear-history")

    assert resp.status_code == 200
    assert resp.json() == {"cleared": 4}

    statuses = await _job_statuses(cluster_id)
    for jid in terminal_ids:
        assert jid not in statuses
    for jid in keep_ids:
        assert jid in statuses
