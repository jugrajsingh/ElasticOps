"""Tests for POST /api/clusters/{cluster_id}/jobs/reindex endpoint."""

from httpx import AsyncClient

from backend.dependencies import get_job_runner
from backend.main import app
from backend.models.cluster import Cluster
from tests.conftest import test_session_factory


async def _create_cluster(client: AsyncClient, *, name: str = "test-cluster", read_only: bool = False) -> int:
    resp = await client.post("/api/clusters", json={"name": name, "url": "https://es.example.com:9200"})
    cluster_id: int = resp.json()["id"]
    if read_only:
        async with test_session_factory() as s:
            cluster = await s.get(Cluster, cluster_id)
            cluster.read_only = True
            await s.commit()
    return cluster_id


class _FakeRunner:
    def __init__(self) -> None:
        self.submitted: list[int] = []

    def submit(self, job_id: int) -> None:
        self.submitted.append(job_id)


async def test_should_create_reindex_job_and_hand_off_to_runner(authed_client: AsyncClient):
    cluster_id = await _create_cluster(authed_client, name="cluster-reindex")
    fake_runner = _FakeRunner()
    app.dependency_overrides[get_job_runner] = lambda: fake_runner
    try:
        resp = await authed_client.post(
            f"/api/clusters/{cluster_id}/jobs/reindex",
            json={"source": "src-idx", "dest": "dst-idx"},
        )
    finally:
        app.dependency_overrides.pop(get_job_runner, None)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "queued"
    assert body["job_type"] == "reindex"
    assert body["index_name"] == "src-idx"
    assert body["target_index"] == "dst-idx"
    assert len(fake_runner.submitted) == 1
    assert fake_runner.submitted[0] == body["id"]


async def test_should_reject_reindex_on_read_only_cluster(authed_client: AsyncClient):
    cluster_id = await _create_cluster(authed_client, name="cluster-reindex-ro", read_only=True)
    fake_runner = _FakeRunner()
    app.dependency_overrides[get_job_runner] = lambda: fake_runner
    try:
        resp = await authed_client.post(
            f"/api/clusters/{cluster_id}/jobs/reindex",
            json={"source": "src-idx", "dest": "dst-idx"},
        )
    finally:
        app.dependency_overrides.pop(get_job_runner, None)

    assert resp.status_code == 403
    assert fake_runner.submitted == []
