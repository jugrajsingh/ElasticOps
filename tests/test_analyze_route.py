from httpx import AsyncClient

from backend.dependencies import get_es_client
from backend.main import app
from backend.services.es_client import ESClient


def _make_mock_es():
    """Create a mock ESClient that returns test data."""
    from unittest.mock import AsyncMock

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
        {
            "health": "green",
            "status": "open",
            "index": "healthy_idx",
            "pri": "2",
            "rep": "1",
            "docs.count": "5000000",
            "store.size": "60000000000",
            "pri.store.size": "30000000000",
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
    ] + [
        {
            "index": "healthy_idx",
            "shard": str(i),
            "prirep": "p",
            "state": "STARTED",
            "docs": "2500000",
            "store": "15000000000",
            "node": f"node-{i}",
            "segments.count": "3",
        }
        for i in range(2)
    ]
    return mock


async def test_should_return_analysis_with_opportunities(authed_client: AsyncClient):
    await authed_client.post("/api/clusters", json={"name": "test", "url": "https://es:9200"})

    mock_es = _make_mock_es()
    app.dependency_overrides[get_es_client] = lambda: mock_es

    response = await authed_client.get("/api/clusters/1/es/analyze")
    assert response.status_code == 200
    data = response.json()
    assert data["total_indices"] == 2
    assert data["total_with_opportunities"] >= 1
    assert data["total_wasted_shards"] > 0

    tiny = next(i for i in data["indices"] if i["name"] == "tiny_idx")
    assert tiny["opportunity_count"] >= 1
    assert any(o["type"] == "over-sharded" for o in tiny["opportunities"])

    app.dependency_overrides.pop(get_es_client, None)


async def test_should_filter_problems_only(authed_client: AsyncClient):
    await authed_client.post("/api/clusters", json={"name": "test", "url": "https://es:9200"})

    mock_es = _make_mock_es()
    app.dependency_overrides[get_es_client] = lambda: mock_es

    response = await authed_client.get("/api/clusters/1/es/analyze?problems_only=true")
    assert response.status_code == 200
    data = response.json()
    assert all(i["opportunity_count"] > 0 for i in data["indices"])

    app.dependency_overrides.pop(get_es_client, None)
