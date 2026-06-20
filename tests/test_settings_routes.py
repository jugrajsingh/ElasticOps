from unittest.mock import AsyncMock

from httpx import AsyncClient

from backend.dependencies import get_es_client
from backend.main import app
from backend.services.es_client import ESClient


async def test_should_return_cluster_settings(authed_client: AsyncClient):
    await authed_client.post("/api/clusters", json={"name": "test", "url": "https://es:9200"})

    mock_es = AsyncMock(spec=ESClient)
    mock_es.cluster_settings_full.return_value = {
        "persistent": {"cluster.max_shards_per_node": "10000"},
        "transient": {},
        "defaults": {"cluster.routing.allocation.balance.shard": "0.45"},
    }
    app.dependency_overrides[get_es_client] = lambda: mock_es

    response = await authed_client.get("/api/clusters/1/es/settings")
    assert response.status_code == 200
    data = response.json()
    assert "persistent" in data
    assert "defaults" in data

    app.dependency_overrides.pop(get_es_client, None)


async def test_should_update_cluster_settings(authed_client: AsyncClient):
    await authed_client.post("/api/clusters", json={"name": "test", "url": "https://es:9200"})

    mock_es = AsyncMock(spec=ESClient)
    mock_es.put_cluster_settings.return_value = {"acknowledged": True}
    app.dependency_overrides[get_es_client] = lambda: mock_es

    response = await authed_client.put(
        "/api/clusters/1/es/settings",
        json={"transient": {"cluster.routing.allocation.cluster_concurrent_rebalance": 10}},
    )
    assert response.status_code == 200
    assert response.json()["acknowledged"] is True

    app.dependency_overrides.pop(get_es_client, None)


async def test_should_proxy_rest_request(authed_client: AsyncClient):
    await authed_client.post("/api/clusters", json={"name": "test", "url": "https://es:9200"})

    mock_es = AsyncMock(spec=ESClient)
    mock_es.proxy.return_value = {"cluster_name": "test", "status": "green"}
    app.dependency_overrides[get_es_client] = lambda: mock_es

    response = await authed_client.post(
        "/api/clusters/1/es/rest",
        json={
            "method": "GET",
            "path": "/_cluster/health",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "green"

    app.dependency_overrides.pop(get_es_client, None)
