# IMPORTANT: the conftest `client` fixture uses ASGITransport, which does NOT run lifespan events,
# so `app.state.job_runner` is never set in tests. Resolve `get_job_runner` by OVERRIDING the
# dependency (the same way conftest overrides get_db) with a fake runner that records submit() calls.
import pytest

from backend.dependencies import get_job_runner
from backend.main import app


@pytest.fixture
def fake_runner():
    submitted = []

    class _FakeRunner:
        def submit(self, jid):
            submitted.append(jid)

    app.dependency_overrides[get_job_runner] = lambda: _FakeRunner()
    yield submitted
    app.dependency_overrides.pop(get_job_runner, None)


@pytest.mark.asyncio
async def test_execute_returns_queued_without_blocking(authed_client, fake_runner, approved_job_factory):
    # Execute now QUEUES the job (status 'queued'); the runner promotes it to 'executing' when a
    # concurrency slot frees up. The endpoint still returns immediately after submit().
    job_id, cluster_id = await approved_job_factory(job_type="force_merge", read_only=False)
    r = await authed_client.post(f"/api/clusters/{cluster_id}/jobs/{job_id}/execute")
    assert r.status_code == 200
    assert r.json()["status"] == "queued"
    assert fake_runner == [job_id]


@pytest.mark.asyncio
async def test_execute_blocked_on_readonly_cluster(authed_client, fake_runner, approved_job_factory):
    job_id, cluster_id = await approved_job_factory(job_type="force_merge", read_only=True)
    r = await authed_client.post(f"/api/clusters/{cluster_id}/jobs/{job_id}/execute")
    assert r.status_code == 403
    assert fake_runner == []  # guard rejected before submit


@pytest.mark.asyncio
async def test_concurrency_endpoint_reports_cap(authed_client):
    """GET /jobs/concurrency returns the runner's global max_concurrent cap."""

    class _CapRunner:
        max_concurrent = 5

    app.dependency_overrides[get_job_runner] = lambda: _CapRunner()
    try:
        r = await authed_client.get("/api/clusters/1/jobs/concurrency")
    finally:
        app.dependency_overrides.pop(get_job_runner, None)
    assert r.status_code == 200
    assert r.json() == {"max_concurrent": 5}
