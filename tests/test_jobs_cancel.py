from unittest.mock import AsyncMock

from httpx import AsyncClient

from backend.dependencies import get_es_client, get_job_runner
from backend.main import app
from backend.models.job import Job
from backend.models.run import Run
from backend.services.es_client import ESClient
from tests.conftest import test_session_factory


async def _seed_job(cluster_id: int, *, status: str, job_type: str = "force_merge") -> int:
    async with test_session_factory() as s:
        run = Run(
            cluster_id=cluster_id,
            total_indices=1,
            total_shards=5,
            total_storage_bytes=0,
            total_opportunities=1,
            total_wasted_shards=2,
        )
        s.add(run)
        await s.flush()
        job = Job(
            run_id=run.id,
            cluster_id=cluster_id,
            index_name="idx",
            job_type=job_type,
            tier=1,
            status=status,
        )
        s.add(job)
        await s.commit()
        return job.id


async def test_should_cancel_executing_job(authed_client: AsyncClient):
    c = await authed_client.post(
        "/api/clusters",
        json={"name": "c1", "url": "https://es.example.com:9200"},
    )
    cluster_id = c.json()["id"]
    job_id = await _seed_job(cluster_id, status="executing", job_type="force_merge")

    cancelled = []

    class _FakeRunner:
        async def cancel(self, jid: int) -> bool:
            cancelled.append(jid)
            return True

    mock_es = AsyncMock(spec=ESClient)

    app.dependency_overrides[get_job_runner] = lambda: _FakeRunner()
    app.dependency_overrides[get_es_client] = lambda: mock_es
    try:
        resp = await authed_client.post(f"/api/clusters/{cluster_id}/jobs/{job_id}/cancel")
    finally:
        app.dependency_overrides.pop(get_job_runner, None)
        app.dependency_overrides.pop(get_es_client, None)

    assert resp.status_code == 200
    assert cancelled == [job_id]


async def test_should_reject_cancel_when_not_executing(authed_client: AsyncClient):
    c = await authed_client.post(
        "/api/clusters",
        json={"name": "c2", "url": "https://es.example.com:9200"},
    )
    cluster_id = c.json()["id"]
    job_id = await _seed_job(cluster_id, status="pending", job_type="force_merge")

    class _FakeRunner:
        async def cancel(self, jid: int) -> bool:  # noqa: ARG002
            return True

    mock_es = AsyncMock(spec=ESClient)

    app.dependency_overrides[get_job_runner] = lambda: _FakeRunner()
    app.dependency_overrides[get_es_client] = lambda: mock_es
    try:
        resp = await authed_client.post(f"/api/clusters/{cluster_id}/jobs/{job_id}/cancel")
    finally:
        app.dependency_overrides.pop(get_job_runner, None)
        app.dependency_overrides.pop(get_es_client, None)

    assert resp.status_code == 400
