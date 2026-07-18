from unittest.mock import AsyncMock

from httpx import AsyncClient

from backend.dependencies import get_es_client
from backend.main import app


async def test_should_return_cluster_health(authed_client: AsyncClient):
    await authed_client.post("/api/clusters", json={"name": "test", "url": "https://es:9200"})

    mock_es = AsyncMock()
    mock_es.cluster_health.return_value = {
        "cluster_name": "test-cluster",
        "status": "green",
        "number_of_nodes": 3,
        "number_of_data_nodes": 2,
        "active_primary_shards": 10,
        "active_shards": 20,
        "relocating_shards": 0,
        "initializing_shards": 0,
        "unassigned_shards": 0,
    }
    app.dependency_overrides[get_es_client] = lambda: mock_es

    try:
        response = await authed_client.get("/api/clusters/1/es/health")
        assert response.status_code == 200
        wrapper = response.json()
        # No snapshot seeded → live fallback, wrapped with stale_seconds == 0.
        assert wrapper["stale_seconds"] == 0
        assert wrapper["fetched_at"] is not None
        data = wrapper["data"]
        assert data["status"] == "green"
        assert data["number_of_nodes"] == 3
    finally:
        app.dependency_overrides.pop(get_es_client, None)


async def test_should_return_node_list(authed_client: AsyncClient):
    await authed_client.post("/api/clusters", json={"name": "test", "url": "https://es:9200"})

    mock_es = AsyncMock()
    mock_es.cat_nodes_detailed.return_value = [
        {
            "name": "hot-01",
            "node.role": "dhi",
            "ip": "10.0.1.1",
            "disk.total": "1000000000000",
            "disk.used": "700000000000",
            "disk.used_percent": "70.0",
            "heap.max": "32000000000",
            "heap.current": "16000000000",
            "heap.percent": "50.0",
            "cpu": "25",
            "load_1m": "2.5",
            "segments.count": "1500",
        }
    ]
    mock_es.cat_shards_detailed.return_value = [
        {
            "index": "idx",
            "shard": "0",
            "prirep": "p",
            "state": "STARTED",
            "docs": "10",
            "store": "100",
            "node": "hot-01",
            "segments.count": "1",
        }
    ]
    app.dependency_overrides[get_es_client] = lambda: mock_es

    try:
        response = await authed_client.get("/api/clusters/1/es/nodes")
        assert response.status_code == 200
        wrapper = response.json()
        assert wrapper["stale_seconds"] == 0
        nodes = wrapper["data"]
        assert len(nodes) == 1
        assert nodes[0]["name"] == "hot-01"
        assert nodes[0]["disk_used_percent"] == 70.0
        # NodeInfoEx precomputed fields.
        assert nodes[0]["shard_count"] == 1
        assert nodes[0]["tier"] == "hot"
    finally:
        app.dependency_overrides.pop(get_es_client, None)


async def test_should_return_overview(authed_client: AsyncClient):
    await authed_client.post("/api/clusters", json={"name": "test", "url": "https://es:9200"})

    mock_es = AsyncMock()
    mock_es.cluster_health.return_value = {
        "cluster_name": "test",
        "status": "yellow",
        "number_of_nodes": 2,
        "number_of_data_nodes": 1,
        "active_primary_shards": 5,
        "active_shards": 5,
        "relocating_shards": 1,
        "initializing_shards": 0,
        "unassigned_shards": 5,
    }
    mock_es.cat_nodes_detailed.return_value = []
    mock_es.cat_indices_detailed.return_value = []
    mock_es.cat_recovery_active.return_value = []
    app.dependency_overrides[get_es_client] = lambda: mock_es

    try:
        response = await authed_client.get("/api/clusters/1/es/overview")
        assert response.status_code == 200
        wrapper = response.json()
        assert wrapper["stale_seconds"] == 0
        data = wrapper["data"]
        assert data["health"]["status"] == "yellow"
        assert data["health"]["unassigned_shards"] == 5
    finally:
        app.dependency_overrides.pop(get_es_client, None)


async def test_should_return_shard_map(authed_client: AsyncClient):
    await authed_client.post("/api/clusters", json={"name": "test", "url": "https://es:9200"})

    mock_es = AsyncMock()
    mock_es.cat_nodes_detailed.return_value = [
        {
            "name": "node-1",
            "node.role": "d",
            "ip": "10.0.1.1",
            "disk.total": "100",
            "disk.used": "50",
            "disk.used_percent": "50",
            "heap.max": "100",
            "heap.current": "50",
            "heap.percent": "50",
            "cpu": "10",
            "load_1m": "1.0",
            "segments.count": "100",
        }
    ]
    mock_es.cat_indices_detailed.return_value = [
        {
            "health": "green",
            "status": "open",
            "index": "test-idx",
            "pri": "1",
            "rep": "0",
            "docs.count": "1000",
            "store.size": "50000",
            "pri.store.size": "50000",
        }
    ]
    mock_es.cat_shards_detailed.return_value = [
        {
            "index": "test-idx",
            "shard": "0",
            "prirep": "p",
            "state": "STARTED",
            "docs": "1000",
            "store": "50000",
            "node": "node-1",
            "segments.count": "5",
        }
    ]
    app.dependency_overrides[get_es_client] = lambda: mock_es

    try:
        response = await authed_client.get("/api/clusters/1/es/shard-map")
        assert response.status_code == 200
        wrapper = response.json()
        assert wrapper["stale_seconds"] == 0
        grid = wrapper["data"]
        # New precomputed grid shape: data_nodes columns, index rows, per-cell chips.
        assert len(grid["data_nodes"]) == 1
        assert grid["data_nodes"][0]["name"] == "node-1"
        assert len(grid["indices"]) == 1
        assert grid["cells"]["test-idx node-1"][0]["shard"] == 0
    finally:
        app.dependency_overrides.pop(get_es_client, None)


async def test_should_return_404_for_unknown_cluster(authed_client: AsyncClient):
    response = await authed_client.get("/api/clusters/999/es/health")
    assert response.status_code == 404
