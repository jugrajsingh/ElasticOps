"""Auth + cluster-access enforcement on the /es and /jobs routers.

Every endpoint under ``/api/clusters/{cluster_id}/es`` and ``/api/clusters/{cluster_id}/jobs`` must
require a valid JWT and, for non-admin users, membership of the target cluster. These tests assert the
guard for a representative read and mutating endpoint on each router.
"""

from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from backend.auth import create_access_token, hash_password
from backend.dependencies import get_es_client
from backend.main import app
from backend.models.cluster import Cluster
from backend.models.user import User
from backend.models.user_cluster import UserCluster
from tests.conftest import test_session_factory as session_factory

GARBAGE_TOKEN = "not-a-real-jwt"


async def _seed_cluster(name: str = "c1", read_only: bool = False) -> int:
    async with session_factory() as session:
        cluster = Cluster(name=name, url="https://es.example.com:9200", read_only=read_only)
        session.add(cluster)
        await session.commit()
        await session.refresh(cluster)
        return cluster.id


async def _seed_user(email: str, role: str = "user", cluster_ids: tuple[int, ...] = ()) -> str:
    async with session_factory() as session:
        user = User(email=email, password_hash=hash_password("pw12345678"), name=email, role=role)
        session.add(user)
        await session.flush()
        for cid in cluster_ids:
            session.add(UserCluster(user_id=user.id, cluster_id=cid))
        await session.commit()
    return create_access_token({"sub": email})


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _mock_es_override() -> AsyncMock:
    """Register an AsyncMock ESClient so authorized calls succeed without a live cluster."""
    mock_es = AsyncMock()
    mock_es.cluster_health.return_value = {
        "cluster_name": "test-cluster",
        "status": "green",
        "number_of_nodes": 1,
        "number_of_data_nodes": 1,
        "active_primary_shards": 1,
        "active_shards": 1,
        "relocating_shards": 0,
        "initializing_shards": 0,
        "unassigned_shards": 0,
    }
    mock_es.put_cluster_settings.return_value = {"acknowledged": True}
    app.dependency_overrides[get_es_client] = lambda: mock_es
    return mock_es


# (label, method, path suffix, json body) for the four representative endpoints.
_ENDPOINTS = [
    ("es_read", "GET", "/es/health", None),
    ("es_write", "PUT", "/es/settings", {"persistent": {"cluster.max_shards_per_node": "2000"}}),
    ("jobs_read", "GET", "/jobs", None),
    ("jobs_write", "POST", "/jobs/clear-history", None),
]

# Parametrized cases carry only (method, suffix, body); the label survives as the test id.
_CASES = [(method, suffix, body) for _, method, suffix, body in _ENDPOINTS]
_IDS = [label for label, *_ in _ENDPOINTS]


def _url(cluster_id: int, suffix: str) -> str:
    return f"/api/clusters/{cluster_id}{suffix}"


async def _request(client: AsyncClient, method: str, url: str, body, headers: dict[str, str] | None = None):
    return await client.request(method, url, json=body, headers=headers)


@pytest.mark.parametrize(("method", "suffix", "body"), _CASES, ids=_IDS)
async def test_should_reject_when_no_token(client: AsyncClient, method, suffix, body):
    cluster_id = await _seed_cluster()
    response = await _request(client, method, _url(cluster_id, suffix), body)
    assert response.status_code == 401


@pytest.mark.parametrize(("method", "suffix", "body"), _CASES, ids=_IDS)
async def test_should_reject_when_garbage_token(client: AsyncClient, method, suffix, body):
    cluster_id = await _seed_cluster()
    response = await _request(client, method, _url(cluster_id, suffix), body, _bearer(GARBAGE_TOKEN))
    assert response.status_code == 401


@pytest.mark.parametrize(("method", "suffix", "body"), _CASES, ids=_IDS)
async def test_should_reject_non_admin_without_membership(client: AsyncClient, method, suffix, body):
    cluster_id = await _seed_cluster()
    token = await _seed_user("outsider@test.com", role="user")
    response = await _request(client, method, _url(cluster_id, suffix), body, _bearer(token))
    assert response.status_code == 403


@pytest.mark.parametrize(("method", "suffix", "body"), _CASES, ids=_IDS)
async def test_should_allow_admin(client: AsyncClient, method, suffix, body):
    cluster_id = await _seed_cluster()
    token = await _seed_user("admin2@test.com", role="admin")
    _mock_es_override()
    try:
        response = await _request(client, method, _url(cluster_id, suffix), body, _bearer(token))
        assert response.status_code < 400
    finally:
        app.dependency_overrides.pop(get_es_client, None)


@pytest.mark.parametrize(("method", "suffix", "body"), _CASES, ids=_IDS)
async def test_should_allow_non_admin_member(client: AsyncClient, method, suffix, body):
    cluster_id = await _seed_cluster()
    token = await _seed_user("member@test.com", role="user", cluster_ids=(cluster_id,))
    _mock_es_override()
    try:
        response = await _request(client, method, _url(cluster_id, suffix), body, _bearer(token))
        assert response.status_code < 400
    finally:
        app.dependency_overrides.pop(get_es_client, None)
