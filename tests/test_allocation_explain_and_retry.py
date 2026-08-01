"""POST /es/allocation/explain (live, ungated) and POST /es/reroute/retry-failed (gated write).

Explain is read-only against ES (it mutates nothing) so it must work even on a read-only or
about-to-be-fixed cluster: no ``require_writable_cluster`` gate. Retry-failed IS a cluster write
(``_cluster/reroute``) so it goes through the same writable gate as ``PUT /es/settings``: 403 on a
read-only cluster, 409 on an inactive one.
"""

from unittest.mock import AsyncMock

from httpx import AsyncClient

from backend.dependencies import get_es_client
from backend.main import app
from backend.models.cluster import Cluster
from backend.services.es_client import ESClient
from tests.conftest import test_session_factory as session_factory


async def _create_cluster(authed_client: AsyncClient, **overrides) -> int:
    resp = await authed_client.post(
        "/api/clusters", json={"name": "test", "url": "https://es.example.com:9200", **overrides}
    )
    assert resp.status_code in (200, 201)
    return resp.json()["id"]


async def _create_readonly_cluster() -> int:
    async with session_factory() as session:
        cluster = Cluster(name="ro", url="https://es.example.com:9200", read_only=True)
        session.add(cluster)
        await session.commit()
        return cluster.id


# --- POST /es/allocation/explain -----------------------------------------------------------------


async def test_should_pass_explain_body_through_to_es_client(authed_client: AsyncClient):
    cluster_id = await _create_cluster(authed_client)

    mock_es = AsyncMock(spec=ESClient)
    mock_es.allocation_explain.return_value = {
        "index": "idx",
        "shard": 0,
        "primary": True,
        "current_state": "unassigned",
    }
    app.dependency_overrides[get_es_client] = lambda: mock_es
    try:
        resp = await authed_client.post(
            f"/api/clusters/{cluster_id}/es/allocation/explain",
            json={"index": "idx", "shard": 0, "primary": True},
        )
        assert resp.status_code == 200
        assert resp.json()["current_state"] == "unassigned"
        mock_es.allocation_explain.assert_awaited_once_with("idx", 0, True)
    finally:
        app.dependency_overrides.pop(get_es_client, None)


async def test_should_explain_with_no_body_fields_for_first_unassigned_shard(authed_client: AsyncClient):
    cluster_id = await _create_cluster(authed_client)

    mock_es = AsyncMock(spec=ESClient)
    mock_es.allocation_explain.return_value = {"index": "auto-discovered"}
    app.dependency_overrides[get_es_client] = lambda: mock_es
    try:
        resp = await authed_client.post(f"/api/clusters/{cluster_id}/es/allocation/explain", json={})
        assert resp.status_code == 200
        mock_es.allocation_explain.assert_awaited_once_with(None, None, None)
    finally:
        app.dependency_overrides.pop(get_es_client, None)


async def test_should_allow_explain_on_readonly_cluster(authed_client: AsyncClient):
    """Explain mutates nothing — it must not be blocked by the read-only write guard."""
    cluster_id = await _create_readonly_cluster()

    mock_es = AsyncMock(spec=ESClient)
    mock_es.allocation_explain.return_value = {"index": "idx"}
    app.dependency_overrides[get_es_client] = lambda: mock_es
    try:
        resp = await authed_client.post(f"/api/clusters/{cluster_id}/es/allocation/explain", json={"index": "idx"})
        assert resp.status_code == 200
    finally:
        app.dependency_overrides.pop(get_es_client, None)


# --- POST /es/reroute/retry-failed ----------------------------------------------------------------


async def test_should_call_reroute_retry_failed_on_writable_cluster(authed_client: AsyncClient):
    cluster_id = await _create_cluster(authed_client)

    mock_es = AsyncMock(spec=ESClient)
    mock_es.reroute_retry_failed.return_value = {"acknowledged": True}
    app.dependency_overrides[get_es_client] = lambda: mock_es
    try:
        resp = await authed_client.post(f"/api/clusters/{cluster_id}/es/reroute/retry-failed")
        assert resp.status_code == 200
        assert resp.json()["acknowledged"] is True
        mock_es.reroute_retry_failed.assert_awaited_once()
    finally:
        app.dependency_overrides.pop(get_es_client, None)


async def test_should_reject_retry_failed_with_403_on_readonly_cluster(authed_client: AsyncClient):
    cluster_id = await _create_readonly_cluster()

    mock = AsyncMock(spec=ESClient)
    boom = AsyncMock(side_effect=AssertionError("ES write must not be reached on a read-only cluster"))
    mock.reroute_retry_failed = boom
    app.dependency_overrides[get_es_client] = lambda: mock
    try:
        resp = await authed_client.post(f"/api/clusters/{cluster_id}/es/reroute/retry-failed")
        assert resp.status_code == 403
        assert resp.json()["detail"] == "cluster is read-only"
    finally:
        app.dependency_overrides.pop(get_es_client, None)


async def test_should_reject_retry_failed_with_409_on_inactive_cluster(authed_client: AsyncClient):
    cluster_id = await _create_cluster(authed_client)
    await authed_client.patch(f"/api/clusters/{cluster_id}", json={"is_active": False})

    resp = await authed_client.post(f"/api/clusters/{cluster_id}/es/reroute/retry-failed")
    assert resp.status_code == 409
    assert "inactive" in resp.json()["detail"].lower()
