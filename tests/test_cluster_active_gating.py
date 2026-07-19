"""Tests for wiring Cluster.is_active end to end: poll-manager add/remove on PATCH toggle,
and a 409 from get_es_client / require_writable_cluster for any operation against an inactive
cluster.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from backend.dependencies import get_job_runner
from backend.main import app
from backend.models.cluster import Cluster
from backend.models.job import Job
from backend.models.run import Run
from tests.conftest import test_session_factory


@pytest.fixture
def fake_runner():
    """Override the job runner so execute/execute-all/promote/reindex/relocate never touch a
    real background worker; records submit() calls so tests can assert nothing was queued.
    """
    submitted = []

    class _FakeRunner:
        def submit(self, jid):
            submitted.append(jid)

    app.dependency_overrides[get_job_runner] = lambda: _FakeRunner()
    yield submitted
    app.dependency_overrides.pop(get_job_runner, None)


async def test_should_reject_es_read_with_409_when_cluster_inactive(authed_client: AsyncClient):
    create = await authed_client.post("/api/clusters", json={"name": "prod", "url": "https://es.example.com:9200"})
    cluster_id = create.json()["id"]

    deactivate = await authed_client.patch(f"/api/clusters/{cluster_id}", json={"is_active": False})
    assert deactivate.status_code == 200
    assert deactivate.json()["is_active"] is False

    response = await authed_client.get(f"/api/clusters/{cluster_id}/es/health")
    assert response.status_code == 409
    assert "inactive" in response.json()["detail"].lower()


async def test_should_allow_db_only_endpoints_when_cluster_inactive(authed_client: AsyncClient):
    create = await authed_client.post("/api/clusters", json={"name": "prod", "url": "https://es.example.com:9200"})
    cluster_id = create.json()["id"]
    await authed_client.patch(f"/api/clusters/{cluster_id}", json={"is_active": False})

    summary = await authed_client.get(f"/api/clusters/{cluster_id}/jobs/summary")
    assert summary.status_code == 200

    get_cluster = await authed_client.get(f"/api/clusters/{cluster_id}")
    assert get_cluster.status_code == 200


async def test_should_toggle_poll_manager_on_is_active_patch(authed_client: AsyncClient):
    class FakePollManager:
        def __init__(self) -> None:
            self.added: list[int] = []
            self.removed: list[int] = []

        async def add_cluster(self, cluster_id: int) -> None:
            self.added.append(cluster_id)

        async def remove_cluster(self, cluster_id: int) -> None:
            self.removed.append(cluster_id)

    manager = FakePollManager()
    app.state.poll_manager = manager
    try:
        create = await authed_client.post("/api/clusters", json={"name": "prod", "url": "https://es.example.com:9200"})
        cluster_id = create.json()["id"]
        assert manager.added == [cluster_id]  # add_cluster hook fires on creation
        manager.added.clear()

        deactivate = await authed_client.patch(f"/api/clusters/{cluster_id}", json={"is_active": False})
        assert deactivate.status_code == 200
        assert manager.removed == [cluster_id]

        reactivate = await authed_client.patch(f"/api/clusters/{cluster_id}", json={"is_active": True})
        assert reactivate.status_code == 200
        assert manager.added == [cluster_id]

        # A patch that does not touch is_active must not call the poll manager again.
        manager.added.clear()
        manager.removed.clear()
        await authed_client.patch(f"/api/clusters/{cluster_id}", json={"name": "prod2"})
        assert manager.added == []
        assert manager.removed == []
    finally:
        del app.state.poll_manager


async def test_should_reject_execute_with_409_when_cluster_inactive(authed_client, fake_runner, approved_job_factory):
    """A deactivated cluster must not accept new job executions (Task 3 review finding)."""
    job_id, cluster_id = await approved_job_factory(job_type="force_merge", is_active=False)
    r = await authed_client.post(f"/api/clusters/{cluster_id}/jobs/{job_id}/execute")
    assert r.status_code == 409
    assert "inactive" in r.json()["detail"].lower()
    assert fake_runner == []  # guard rejected before submit


async def test_should_reject_execute_all_with_409_when_cluster_inactive(
    authed_client, fake_runner, approved_job_factory
):
    job_id, cluster_id = await approved_job_factory(job_type="force_merge", is_active=False)
    r = await authed_client.post(f"/api/clusters/{cluster_id}/jobs/execute-all")
    assert r.status_code == 409
    assert "inactive" in r.json()["detail"].lower()
    assert fake_runner == []

    # the job must remain untouched (still approved), not silently skipped/queued
    listing = await authed_client.get(f"/api/clusters/{cluster_id}/jobs")
    job = next(j for j in listing.json() if j["id"] == job_id)
    assert job["status"] == "approved"


async def test_should_reject_promote_with_409_when_cluster_inactive(authed_client, fake_runner):
    create = await authed_client.post("/api/clusters", json={"name": "prod", "url": "https://es.example.com:9200"})
    cluster_id = create.json()["id"]
    await authed_client.patch(f"/api/clusters/{cluster_id}", json={"is_active": False})

    r = await authed_client.post(
        f"/api/clusters/{cluster_id}/jobs/promote",
        json={"source": "idx-shrink-1", "target": "idx", "alias": "idx-alias"},
    )
    assert r.status_code == 409
    assert "inactive" in r.json()["detail"].lower()
    assert fake_runner == []


async def test_should_reject_reindex_with_409_when_cluster_inactive(authed_client, fake_runner):
    create = await authed_client.post("/api/clusters", json={"name": "prod", "url": "https://es.example.com:9200"})
    cluster_id = create.json()["id"]
    await authed_client.patch(f"/api/clusters/{cluster_id}", json={"is_active": False})

    r = await authed_client.post(
        f"/api/clusters/{cluster_id}/jobs/reindex",
        json={"source": "idx", "dest": "idx-v2"},
    )
    assert r.status_code == 409
    assert "inactive" in r.json()["detail"].lower()
    assert fake_runner == []


async def test_should_reject_relocate_with_409_when_cluster_inactive(authed_client, fake_runner):
    create = await authed_client.post("/api/clusters", json={"name": "prod", "url": "https://es.example.com:9200"})
    cluster_id = create.json()["id"]
    await authed_client.patch(f"/api/clusters/{cluster_id}", json={"is_active": False})

    r = await authed_client.post(
        f"/api/clusters/{cluster_id}/jobs/relocate",
        json={"index": "idx", "shard": 0, "from_node": "node-1", "to_node": "node-2"},
    )
    assert r.status_code == 409
    assert "inactive" in r.json()["detail"].lower()
    assert fake_runner == []


async def test_should_allow_approve_reject_list_when_cluster_inactive(authed_client, approved_job_factory):
    """Approve/reject/list are DB-only and must keep working on a deactivated cluster."""
    pending_job_id, cluster_id = await approved_job_factory(job_type="force_merge", is_active=False)

    listing = await authed_client.get(f"/api/clusters/{cluster_id}/jobs")
    assert listing.status_code == 200

    # approved_job_factory creates an already-"approved" job; reject exercises the DB-only path.
    reject = await authed_client.put(f"/api/clusters/{cluster_id}/jobs/{pending_job_id}/reject")
    assert reject.status_code == 400  # not pending (already approved), proving the route ran past any 409 gate
    assert reject.json()["detail"] != "Cluster is inactive; reactivate it to perform ES operations"


class _FakeCancelRunner:
    """Job runner stub that records cancel() calls without touching a real background worker."""

    def __init__(self) -> None:
        self.cancelled: list[int] = []

    async def cancel(self, jid: int) -> bool:
        self.cancelled.append(jid)
        return True


async def _seed_cancellable_job(
    *, status: str, job_type: str = "force_merge", node_name: str | None = None, is_active: bool = True
) -> tuple[int, int]:
    """Create a cluster + run + job in the given status; return ``(job_id, cluster_id)``."""
    async with test_session_factory() as session:
        cluster = Cluster(
            name=f"cancel-{job_type}-{status}-{is_active}",
            url="https://es.example.com:9200",
            is_active=is_active,
        )
        session.add(cluster)
        await session.flush()

        run = Run(cluster_id=cluster.id)
        session.add(run)
        await session.flush()

        job = Job(
            run_id=run.id,
            cluster_id=cluster.id,
            index_name="idx",
            job_type=job_type,
            tier=1,
            status=status,
            node_name=node_name,
        )
        session.add(job)
        await session.commit()
        return job.id, cluster.id


async def test_should_allow_cancel_of_queued_job_when_cluster_inactive(authed_client: AsyncClient):
    """cancel_job must not depend on get_es_client: a queued job on a deactivated cluster is still
    cancellable without reactivating the cluster first.
    """
    job_id, cluster_id = await _seed_cancellable_job(status="queued", is_active=False)
    runner = _FakeCancelRunner()
    app.dependency_overrides[get_job_runner] = lambda: runner
    try:
        response = await authed_client.post(f"/api/clusters/{cluster_id}/jobs/{job_id}/cancel")
    finally:
        app.dependency_overrides.pop(get_job_runner, None)

    assert response.status_code == 200
    assert runner.cancelled == [job_id]


async def test_should_allow_cancel_of_executing_job_when_cluster_inactive(authed_client: AsyncClient):
    job_id, cluster_id = await _seed_cancellable_job(status="executing", is_active=False)
    runner = _FakeCancelRunner()
    app.dependency_overrides[get_job_runner] = lambda: runner
    try:
        response = await authed_client.post(f"/api/clusters/{cluster_id}/jobs/{job_id}/cancel")
    finally:
        app.dependency_overrides.pop(get_job_runner, None)

    assert response.status_code == 200
    assert runner.cancelled == [job_id]


async def test_should_undrain_on_cancel_when_cluster_inactive(authed_client: AsyncClient):
    """The drain_node undrain-on-cancel branch resolves its own ES client and must keep working
    even when the cluster is inactive (undrain is remediation, not a new operation).
    """
    job_id, cluster_id = await _seed_cancellable_job(
        status="executing", job_type="drain_node", node_name="es01", is_active=False
    )
    runner = _FakeCancelRunner()
    app.dependency_overrides[get_job_runner] = lambda: runner
    try:
        with patch("backend.services.executor.undrain_node", new=AsyncMock()) as mock_undrain:
            response = await authed_client.post(f"/api/clusters/{cluster_id}/jobs/{job_id}/cancel")
    finally:
        app.dependency_overrides.pop(get_job_runner, None)

    assert response.status_code == 200
    mock_undrain.assert_awaited_once()
    assert mock_undrain.await_args.args[1] == "es01"
    assert runner.cancelled == [job_id]


async def test_should_require_auth_on_cancel(client: AsyncClient):
    """Removing the get_es_client dependency from cancel_job must not touch router-level auth:
    require_cluster_access is applied at the router prefix and must still reject unauthenticated
    requests before the endpoint body runs.
    """
    job_id, cluster_id = await _seed_cancellable_job(status="queued")
    response = await client.post(f"/api/clusters/{cluster_id}/jobs/{job_id}/cancel")
    assert response.status_code == 401
