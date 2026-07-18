"""Tests for POST /api/clusters/{cluster_id}/jobs/drain endpoint (Task 11)."""

from httpx import AsyncClient

from backend.dependencies import get_es_client, get_job_runner
from backend.main import app
from backend.models.cluster import Cluster
from tests.conftest import test_session_factory


async def _create_cluster(
    client: AsyncClient,
    *,
    name: str = "test-cluster",
    read_only: bool = False,
) -> int:
    """Create a cluster via the API and return its id."""
    resp = await client.post(
        "/api/clusters",
        json={"name": name, "url": "https://es.example.com:9200"},
    )
    cluster_id: int = resp.json()["id"]

    if read_only:
        async with test_session_factory() as s:
            cluster = await s.get(Cluster, cluster_id)
            cluster.read_only = True
            await s.commit()

    return cluster_id


class _FakeRunner:
    """Minimal stand-in for JobRunner that records submit calls."""

    def __init__(self) -> None:
        self.submitted: list[int] = []

    def submit(self, job_id: int) -> None:  # noqa: D401
        self.submitted.append(job_id)


def _node(name: str, role: str = "d", total: str = "100000000", used: str = "10000000") -> dict:
    return {"name": name, "node.role": role, "disk.total": total, "disk.used": used}


def _shard(node: str, store: str = "5") -> dict:
    return {"node": node, "store": store}


# ---------------------------------------------------------------------------
# (a) Pre-flight FAILS → 400 with reason, submit NOT called
# ---------------------------------------------------------------------------


async def test_should_return_400_when_preflight_fails_too_few_data_nodes(
    authed_client: AsyncClient,
) -> None:
    """POST /drain returns 400 when fewer than 2 other data nodes exist; runner not called."""
    cluster_id = await _create_cluster(authed_client, name="cluster-drain-fail")

    fake_runner = _FakeRunner()

    # Only 1 data node total — preflight must fail (0 other data nodes)
    nodes = [_node("es01")]
    shards = [_shard("es01", store="5")]

    async def fake_es_client(_cluster_id: int = cluster_id):  # noqa: ARG001
        class _FakeES:
            async def cat_nodes_detailed(self):
                return nodes

            async def cat_shards_detailed(self):
                return shards

        return _FakeES()

    app.dependency_overrides[get_es_client] = fake_es_client
    app.dependency_overrides[get_job_runner] = lambda: fake_runner

    try:
        resp = await authed_client.post(
            f"/api/clusters/{cluster_id}/jobs/drain",
            json={"node": "es01"},
        )
    finally:
        app.dependency_overrides.pop(get_es_client, None)
        app.dependency_overrides.pop(get_job_runner, None)

    assert resp.status_code == 400, resp.text
    # Reason must be in the detail
    assert "node" in resp.json()["detail"].lower() or "drain" in resp.json()["detail"].lower()
    # Runner must NOT have been called
    assert fake_runner.submitted == []


# ---------------------------------------------------------------------------
# (b) Success: 3 data nodes, small shards → 200, queued, submit called
# ---------------------------------------------------------------------------


async def test_should_create_drain_job_and_submit_when_preflight_passes(
    authed_client: AsyncClient,
) -> None:
    """POST /drain succeeds when 3 data nodes and enough disk space; runner called."""
    cluster_id = await _create_cluster(authed_client, name="cluster-drain-ok")

    fake_runner = _FakeRunner()

    nodes = [
        _node("es01", total="100000000", used="10000000"),
        _node("es02", total="100000000", used="10000000"),
        _node("es03", total="100000000", used="10000000"),
    ]
    shards = [_shard("es01", store="5")]

    async def fake_es_client(_cluster_id: int = cluster_id):  # noqa: ARG001
        class _FakeES:
            async def cat_nodes_detailed(self):
                return nodes

            async def cat_shards_detailed(self):
                return shards

        return _FakeES()

    app.dependency_overrides[get_es_client] = fake_es_client
    app.dependency_overrides[get_job_runner] = lambda: fake_runner

    try:
        resp = await authed_client.post(
            f"/api/clusters/{cluster_id}/jobs/drain",
            json={"node": "es01"},
        )
    finally:
        app.dependency_overrides.pop(get_es_client, None)
        app.dependency_overrides.pop(get_job_runner, None)

    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["status"] == "queued"
    assert body["job_type"] == "drain_node"
    assert body["node_name"] == "es01"
    assert body["cluster_id"] == cluster_id
    assert body["progress"] == "queued"
    assert body["index_name"] == ""

    # Runner must have been called with the new job id
    assert len(fake_runner.submitted) == 1
    assert fake_runner.submitted[0] == body["id"]


# ---------------------------------------------------------------------------
# (c) Read-only cluster → 403, submit NOT called
# ---------------------------------------------------------------------------


async def test_should_return_403_for_read_only_cluster(
    authed_client: AsyncClient,
) -> None:
    """POST /drain returns 403 for a read-only cluster; runner not called."""
    cluster_id = await _create_cluster(authed_client, name="cluster-drain-ro", read_only=True)

    fake_runner = _FakeRunner()
    app.dependency_overrides[get_job_runner] = lambda: fake_runner

    try:
        resp = await authed_client.post(
            f"/api/clusters/{cluster_id}/jobs/drain",
            json={"node": "es01"},
        )
    finally:
        app.dependency_overrides.pop(get_job_runner, None)

    assert resp.status_code == 403, resp.text
    assert fake_runner.submitted == []
