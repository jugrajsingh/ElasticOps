from httpx import AsyncClient


async def test_should_create_cluster(authed_client: AsyncClient):
    response = await authed_client.post(
        "/api/clusters",
        json={
            "name": "production",
            "url": "https://es.example.com:9200",
            "username": "elastic",
            "password": "secret",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "production"
    assert data["url"] == "https://es.example.com:9200"
    assert "password" not in data


async def test_should_list_clusters(authed_client: AsyncClient):
    await authed_client.post("/api/clusters", json={"name": "prod", "url": "https://es1:9200"})
    await authed_client.post("/api/clusters", json={"name": "staging", "url": "https://es2:9200"})
    response = await authed_client.get("/api/clusters")
    assert response.status_code == 200
    assert len(response.json()) == 2


async def test_should_get_cluster_by_id(authed_client: AsyncClient):
    create = await authed_client.post("/api/clusters", json={"name": "prod", "url": "https://es:9200"})
    cluster_id = create.json()["id"]
    response = await authed_client.get(f"/api/clusters/{cluster_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "prod"


async def test_should_update_cluster(authed_client: AsyncClient):
    create = await authed_client.post("/api/clusters", json={"name": "prod", "url": "https://es:9200"})
    cluster_id = create.json()["id"]
    response = await authed_client.patch(f"/api/clusters/{cluster_id}", json={"name": "production"})
    assert response.status_code == 200
    assert response.json()["name"] == "production"


async def test_should_delete_cluster(authed_client: AsyncClient):
    create = await authed_client.post("/api/clusters", json={"name": "prod", "url": "https://es:9200"})
    cluster_id = create.json()["id"]
    response = await authed_client.delete(f"/api/clusters/{cluster_id}")
    assert response.status_code == 200
    response = await authed_client.get(f"/api/clusters/{cluster_id}")
    assert response.status_code == 404


async def test_should_reject_duplicate_cluster_name(authed_client: AsyncClient):
    await authed_client.post("/api/clusters", json={"name": "prod", "url": "https://es1:9200"})
    response = await authed_client.post("/api/clusters", json={"name": "prod", "url": "https://es2:9200"})
    assert response.status_code == 409


async def test_cluster_mutations_require_auth(client: AsyncClient):
    """Unauthenticated requests to mutation/read endpoints must be rejected with 401."""
    assert (await client.patch("/api/clusters/1", json={"name": "x"})).status_code == 401
    assert (await client.delete("/api/clusters/1")).status_code == 401
    assert (await client.get("/api/clusters/1")).status_code == 401
