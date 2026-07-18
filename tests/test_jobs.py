from unittest.mock import AsyncMock

from httpx import AsyncClient

from backend.dependencies import get_es_client, get_job_runner
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


async def test_should_include_cancelled_and_rejected_in_summary(authed_client: AsyncClient):
    # cancelled and rejected are real terminal statuses the runner/routes produce; the summary
    # must report them so the UI can account for every job (and not silently drop them from totals).
    await authed_client.post("/api/clusters", json={"name": "test", "url": "https://es:9200"})
    mock_es = _make_mock_es()
    app.dependency_overrides[get_es_client] = lambda: mock_es

    await authed_client.post("/api/clusters/1/jobs/recommend")
    pending = (await authed_client.get("/api/clusters/1/jobs?status=pending")).json()
    await authed_client.put(f"/api/clusters/1/jobs/{pending[0]['id']}/reject")
    data = (await authed_client.get("/api/clusters/1/jobs/summary")).json()

    app.dependency_overrides.pop(get_es_client, None)

    assert "cancelled" in data
    assert "rejected" in data
    assert data["rejected"] == 1


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


async def test_execute_reduce_shards_hands_off_to_runner(authed_client):
    # Execute is now async: it marks the job 'queued' and submits to the background JobRunner,
    # which promotes it to 'executing' on slot acquisition and drives it to its terminal state
    # (covered by the JobRunner tests). The endpoint returns immediately, so we assert the
    # hand-off (status + runner.submit), not completion.
    c = await authed_client.post(
        "/api/clusters",
        json={"name": "c1", "url": "https://es.example.com:9200", "username": "u", "password": "p"},
    )
    cluster_id = c.json()["id"]

    async with test_session_factory() as s:
        run = Run(
            cluster_id=cluster_id,
            total_indices=1,
            total_shards=6,
            total_storage_bytes=0,
            total_opportunities=1,
            total_wasted_shards=3,
        )
        s.add(run)
        await s.flush()
        job = Job(
            run_id=run.id,
            cluster_id=cluster_id,
            index_name="idx",
            job_type="reduce_shards",
            tier=3,
            current_shards=6,
            target_shards=2,
            current_replicas=0,
            status="approved",
        )
        s.add(job)
        await s.commit()
        job_id = job.id

    submitted = []

    class _FakeRunner:
        def submit(self, jid):
            submitted.append(jid)

    app.dependency_overrides[get_job_runner] = lambda: _FakeRunner()
    try:
        resp = await authed_client.post(f"/api/clusters/{cluster_id}/jobs/{job_id}/execute")
    finally:
        app.dependency_overrides.pop(get_job_runner, None)

    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    assert submitted == [job_id]


async def test_should_not_duplicate_pending_jobs_on_repeated_recommend(authed_client: AsyncClient):
    """Calling /recommend twice must NOT stack pending jobs — count must stay stable."""
    await authed_client.post("/api/clusters", json={"name": "dedup-test", "url": "https://es.example.com:9200"})
    mock_es = _make_mock_es()
    app.dependency_overrides[get_es_client] = lambda: mock_es

    try:
        r1 = await authed_client.post("/api/clusters/1/jobs/recommend")
        assert r1.status_code == 200
        first_count = r1.json()["total_opportunities"]

        r2 = await authed_client.post("/api/clusters/1/jobs/recommend")
        assert r2.status_code == 200
        second_count = r2.json()["total_opportunities"]

        jobs = (await authed_client.get("/api/clusters/1/jobs?status=pending")).json()
    finally:
        app.dependency_overrides.pop(get_es_client, None)

    # Pending count must equal second run's opportunities, not double
    assert len(jobs) == second_count
    assert first_count == second_count  # same data → same recommendation count


async def test_should_queue_only_one_job_per_index_on_execute_all(authed_client: AsyncClient):
    """execute-all must not put two jobs for the SAME index in flight at once — they would corrupt
    each other (e.g. force_merge racing an in-place resize). The second stays approved for later."""
    from backend.models.job import Job
    from backend.models.run import Run
    from tests.conftest import test_session_factory

    c = await authed_client.post("/api/clusters", json={"name": "one-per-idx", "url": "https://es.example.com:9200"})
    cluster_id = c.json()["id"]

    async with test_session_factory() as s:
        run = Run(cluster_id=cluster_id)
        s.add(run)
        await s.flush()
        for jt in ("force_merge", "reduce_shards"):
            s.add(
                Job(
                    run_id=run.id,
                    cluster_id=cluster_id,
                    index_name="idx",
                    job_type=jt,
                    tier=1,
                    current_shards=6,
                    target_shards=2,
                    current_replicas=0,
                    status="approved",
                )
            )
        await s.commit()

    submitted: list[int] = []

    class _FakeRunner:
        def submit(self, jid: int) -> None:
            submitted.append(jid)

    app.dependency_overrides[get_job_runner] = lambda: _FakeRunner()
    try:
        resp = await authed_client.post(f"/api/clusters/{cluster_id}/jobs/execute-all")
    finally:
        app.dependency_overrides.pop(get_job_runner, None)

    assert resp.status_code == 200
    assert resp.json()["queued"] == 1
    assert len(submitted) == 1
    still_approved = (await authed_client.get(f"/api/clusters/{cluster_id}/jobs?status=approved")).json()
    assert len(still_approved) == 1


async def test_should_execute_all_approved_jobs(authed_client: AsyncClient):
    """POST /execute-all flips every approved job to queued and calls runner.submit for each."""
    from backend.models.job import Job
    from backend.models.run import Run
    from tests.conftest import test_session_factory

    c = await authed_client.post(
        "/api/clusters",
        json={"name": "exec-all", "url": "https://es.example.com:9200"},
    )
    cluster_id = c.json()["id"]

    # Create 3 approved jobs directly in DB
    async with test_session_factory() as s:
        run = Run(
            cluster_id=cluster_id,
            total_indices=1,
            total_shards=6,
            total_storage_bytes=0,
            total_opportunities=3,
            total_wasted_shards=3,
        )
        s.add(run)
        await s.flush()
        for i in range(3):
            job = Job(
                run_id=run.id,
                cluster_id=cluster_id,
                index_name=f"idx-{i}",
                job_type="reduce_shards",
                tier=3,
                current_shards=6,
                target_shards=2,
                current_replicas=0,
                status="approved",
            )
            s.add(job)
        await s.commit()

    submitted: list[int] = []

    class _FakeRunner:
        def submit(self, jid: int) -> None:
            submitted.append(jid)

    app.dependency_overrides[get_job_runner] = lambda: _FakeRunner()
    try:
        resp = await authed_client.post(f"/api/clusters/{cluster_id}/jobs/execute-all")
    finally:
        app.dependency_overrides.pop(get_job_runner, None)

    assert resp.status_code == 200
    assert resp.json()["queued"] == 3
    assert len(submitted) == 3

    # Verify status in DB — jobs are 'queued' (the FakeRunner never promotes them to 'executing').
    jobs_resp = await authed_client.get(f"/api/clusters/{cluster_id}/jobs?status=queued")
    assert jobs_resp.status_code == 200
    assert len(jobs_resp.json()) == 3
