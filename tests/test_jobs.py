from unittest.mock import AsyncMock

from httpx import AsyncClient

from backend.dependencies import get_es_client
from backend.main import app
from backend.models.job import Job
from backend.models.run import Run
from backend.services.es_client import ESClient
from tests.conftest import test_session_factory


def _make_mock_es():
    mock = AsyncMock(spec=ESClient)
    mock.cat_indices_detailed.return_value = [
        {
            "health": "green",
            "status": "open",
            "index": "tiny_idx",
            "pri": "5",
            "rep": "1",
            "docs.count": "100",
            "store.size": "500000",
            "pri.store.size": "250000",
        },
    ]
    mock.cat_shards_detailed.return_value = [
        {
            "index": "tiny_idx",
            "shard": str(i),
            "prirep": "p",
            "state": "STARTED",
            "docs": "20",
            "store": "50000",
            "node": f"node-{i}",
            "segments.count": "1",
        }
        for i in range(5)
    ]
    return mock


async def test_should_create_recommendations(authed_client: AsyncClient):
    await authed_client.post("/api/clusters", json={"name": "test", "url": "https://es:9200"})
    mock_es = _make_mock_es()
    app.dependency_overrides[get_es_client] = lambda: mock_es

    response = await authed_client.post("/api/clusters/1/jobs/recommend")
    assert response.status_code == 200
    data = response.json()
    assert data["total_opportunities"] > 0

    # Verify jobs were created
    jobs_resp = await authed_client.get("/api/clusters/1/jobs")
    assert jobs_resp.status_code == 200
    jobs = jobs_resp.json()
    assert len(jobs) > 0
    assert all(j["status"] == "pending" for j in jobs)

    app.dependency_overrides.pop(get_es_client, None)


async def test_should_approve_and_list_job(authed_client: AsyncClient):
    await authed_client.post("/api/clusters", json={"name": "test", "url": "https://es:9200"})
    mock_es = _make_mock_es()
    app.dependency_overrides[get_es_client] = lambda: mock_es

    await authed_client.post("/api/clusters/1/jobs/recommend")
    jobs = (await authed_client.get("/api/clusters/1/jobs")).json()
    job_id = jobs[0]["id"]

    response = await authed_client.put(f"/api/clusters/1/jobs/{job_id}/approve")
    assert response.status_code == 200
    assert response.json()["status"] == "approved"

    # Filter by status
    approved = (await authed_client.get("/api/clusters/1/jobs?status=approved")).json()
    assert len(approved) == 1

    app.dependency_overrides.pop(get_es_client, None)


async def test_should_reject_job(authed_client: AsyncClient):
    await authed_client.post("/api/clusters", json={"name": "test", "url": "https://es:9200"})
    mock_es = _make_mock_es()
    app.dependency_overrides[get_es_client] = lambda: mock_es

    await authed_client.post("/api/clusters/1/jobs/recommend")
    jobs = (await authed_client.get("/api/clusters/1/jobs")).json()
    job_id = jobs[0]["id"]

    response = await authed_client.put(f"/api/clusters/1/jobs/{job_id}/reject")
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"

    app.dependency_overrides.pop(get_es_client, None)


async def test_should_return_job_summary(authed_client: AsyncClient):
    await authed_client.post("/api/clusters", json={"name": "test", "url": "https://es:9200"})
    mock_es = _make_mock_es()
    app.dependency_overrides[get_es_client] = lambda: mock_es

    await authed_client.post("/api/clusters/1/jobs/recommend")
    response = await authed_client.get("/api/clusters/1/jobs/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] > 0
    assert data["pending"] > 0

    app.dependency_overrides.pop(get_es_client, None)


async def test_should_bulk_approve(authed_client: AsyncClient):
    await authed_client.post("/api/clusters", json={"name": "test", "url": "https://es:9200"})
    mock_es = _make_mock_es()
    app.dependency_overrides[get_es_client] = lambda: mock_es

    await authed_client.post("/api/clusters/1/jobs/recommend")
    response = await authed_client.put("/api/clusters/1/jobs/bulk-approve")
    assert response.status_code == 200
    assert response.json()["approved"] > 0

    jobs = (await authed_client.get("/api/clusters/1/jobs?status=approved")).json()
    assert len(jobs) > 0

    app.dependency_overrides.pop(get_es_client, None)


async def test_execute_reduce_shards_completes(authed_client):
    # seed a cluster
    c = await authed_client.post(
        "/api/clusters",
        json={"name": "c1", "url": "https://es.example.com:9200", "username": "u", "password": "p"},
    )
    cluster_id = c.json()["id"]

    async with test_session_factory() as s:
        run = Run(cluster_id=cluster_id, total_indices=1, total_shards=6,
                  total_storage_bytes=0, total_opportunities=1, total_wasted_shards=3)
        s.add(run)
        await s.flush()
        job = Job(run_id=run.id, cluster_id=cluster_id, index_name="idx",
                  job_type="reduce_shards", tier=3, current_shards=6, target_shards=2,
                  current_replicas=0, status="approved")
        s.add(job)
        await s.commit()
        job_id = job.id

    es = AsyncMock()
    es.cat_nodes_detailed.return_value = [{"name": "d1", "node.role": "dim", "disk.total": "100", "disk.used": "1"}]
    es.index_health.return_value = {"status": "green", "relocating_shards": 0}
    es.set_index_settings.return_value = {}
    es.shrink_index.return_value = {}
    app.dependency_overrides[get_es_client] = lambda: es
    try:
        resp = await authed_client.post(f"/api/clusters/{cluster_id}/jobs/{job_id}/execute")
    finally:
        app.dependency_overrides.pop(get_es_client, None)

    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"
    assert resp.json()["task_id"] == "idx-shrink-2"
