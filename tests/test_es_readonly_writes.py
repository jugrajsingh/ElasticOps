"""Read-only safety rail on the ES write paths (settings + REST proxy) and the read_only toggle.

A cluster marked ``read_only=True`` must reject every write that reaches ES:

* ``PUT /es/settings`` — always a cluster write → 403.
* ``POST /es/rest`` with a write verb in the request body (PUT/DELETE/POST/...) → 403; the same
  endpoint with a read verb (GET/HEAD) stays allowed (reads through the console are fine).

The ES dependency is a strict mock whose write methods raise, proving the guard short-circuits
*before* ES is ever touched on the blocked paths. Uses the in-memory ``test_session_factory`` and the
``get_es_client`` override pattern; never imports the real ``backend.database`` engine/factory.
"""

from unittest.mock import AsyncMock

from httpx import AsyncClient

from backend.dependencies import get_es_client
from backend.main import app
from backend.models.cluster import Cluster
from backend.services.es_client import ESClient
from tests.conftest import test_session_factory as session_factory


async def _create_readonly_cluster() -> int:
    """Seed a read-only cluster directly via the session for isolation (avoids auth overhead) and return its id."""
    async with session_factory() as session:
        cluster = Cluster(name="prod-ro", url="https://es.example.com:9200", read_only=True)
        session.add(cluster)
        await session.commit()
        return cluster.id


def _no_write_es_mock() -> AsyncMock:
    """A mock ES whose write methods raise — proves the guard blocks before ES is reached."""
    mock = AsyncMock(spec=ESClient)
    boom = AsyncMock(side_effect=AssertionError("ES write must not be reached on a read-only cluster"))
    mock.put_cluster_settings = boom
    mock.proxy = boom
    return mock


async def test_should_reject_settings_update_on_readonly_cluster(authed_client: AsyncClient):
    cluster_id = await _create_readonly_cluster()

    app.dependency_overrides[get_es_client] = _no_write_es_mock
    try:
        resp = await authed_client.put(
            f"/api/clusters/{cluster_id}/es/settings",
            json={"transient": {"cluster.routing.allocation.cluster_concurrent_rebalance": 10}},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == "cluster is read-only"
    finally:
        app.dependency_overrides.pop(get_es_client, None)


async def test_should_reject_rest_write_verb_on_readonly_cluster(authed_client: AsyncClient):
    cluster_id = await _create_readonly_cluster()

    app.dependency_overrides[get_es_client] = _no_write_es_mock
    try:
        for verb in ("PUT", "DELETE", "POST"):
            resp = await authed_client.post(
                f"/api/clusters/{cluster_id}/es/rest",
                json={"method": verb, "path": "/some-index/_settings", "body": {"index": {"number_of_replicas": 1}}},
            )
            assert resp.status_code == 403, f"{verb} should be blocked on read-only cluster"
            assert resp.json()["detail"] == "cluster is read-only"
    finally:
        app.dependency_overrides.pop(get_es_client, None)


async def test_should_allow_rest_read_verb_on_readonly_cluster(authed_client: AsyncClient):
    cluster_id = await _create_readonly_cluster()

    mock_es = AsyncMock(spec=ESClient)
    mock_es.proxy.return_value = {"cluster_name": "test", "status": "green"}
    app.dependency_overrides[get_es_client] = lambda: mock_es
    try:
        # GET (lower-case too, to exercise case-insensitivity) is a read — must NOT be blocked.
        for verb in ("GET", "get", "HEAD"):
            resp = await authed_client.post(
                f"/api/clusters/{cluster_id}/es/rest",
                json={"method": verb, "path": "/_cluster/health"},
            )
            assert resp.status_code != 403, f"{verb} is a read and must be allowed on read-only cluster"
            assert resp.status_code == 200
    finally:
        app.dependency_overrides.pop(get_es_client, None)


async def test_should_set_read_only_via_patch_and_persist(authed_client: AsyncClient):
    resp = await authed_client.post("/api/clusters", json={"name": "togglable", "url": "https://es.example.com:9200"})
    cluster_id = resp.json()["id"]
    assert resp.json()["read_only"] is False

    patched = await authed_client.patch(f"/api/clusters/{cluster_id}", json={"read_only": True})
    assert patched.status_code == 200
    assert patched.json()["read_only"] is True

    # Re-read confirms it persisted.
    got = await authed_client.get(f"/api/clusters/{cluster_id}")
    assert got.json()["read_only"] is True
