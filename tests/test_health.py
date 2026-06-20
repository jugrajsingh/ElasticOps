from httpx import AsyncClient


async def test_should_return_health_ok(client: AsyncClient):
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
