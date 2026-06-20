from httpx import AsyncClient


async def test_should_invite_user(client: AsyncClient, admin_headers: dict):
    response = await client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={
            "name": "Sarah Chen",
            "email": "sarah@test.com",
            "password": "userpass123",
            "role": "user",
            "cluster_ids": [],
        },
    )
    assert response.status_code == 200
    assert response.json()["email"] == "sarah@test.com"
    assert response.json()["role"] == "user"


async def test_should_list_users(client: AsyncClient, admin_headers: dict):
    await client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={
            "name": "User1",
            "email": "user1@test.com",
            "password": "pass123",
        },
    )
    response = await client.get("/api/admin/users", headers=admin_headers)
    assert response.status_code == 200
    users = response.json()
    assert len(users) == 2  # admin + user1


async def test_should_assign_cluster_access(client: AsyncClient, admin_headers: dict):
    # Create a cluster
    cluster = await client.post(
        "/api/clusters",
        headers=admin_headers,
        json={
            "name": "prod",
            "url": "https://es:9200",
        },
    )
    cluster_id = cluster.json()["id"]

    # Invite user with cluster access
    response = await client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={
            "name": "User1",
            "email": "user1@test.com",
            "password": "pass123",
            "cluster_ids": [cluster_id],
        },
    )
    assert response.status_code == 200
    assert cluster_id in response.json()["cluster_ids"]


async def test_should_filter_clusters_by_user_access(client: AsyncClient, admin_headers: dict):
    # Create two clusters
    c1 = await client.post(
        "/api/clusters",
        headers=admin_headers,
        json={
            "name": "prod",
            "url": "https://es1:9200",
        },
    )
    await client.post(
        "/api/clusters",
        headers=admin_headers,
        json={
            "name": "staging",
            "url": "https://es2:9200",
        },
    )

    # Invite user with access to only prod
    await client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={
            "name": "User1",
            "email": "user1@test.com",
            "password": "pass123",
            "cluster_ids": [c1.json()["id"]],
        },
    )

    # Login as user1
    token_resp = await client.post(
        "/api/auth/login",
        json={
            "email": "user1@test.com",
            "password": "pass123",
        },
    )
    user_headers = {"Authorization": f"Bearer {token_resp.json()['access_token']}"}

    # User should only see prod
    clusters = await client.get("/api/clusters", headers=user_headers)
    assert len(clusters.json()) == 1
    assert clusters.json()[0]["name"] == "prod"

    # Admin should see both
    admin_clusters = await client.get("/api/clusters", headers=admin_headers)
    assert len(admin_clusters.json()) == 2


async def test_should_reject_non_admin_from_user_management(client: AsyncClient, admin_headers: dict):
    await client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={
            "name": "User1",
            "email": "user1@test.com",
            "password": "pass123",
        },
    )
    token_resp = await client.post(
        "/api/auth/login",
        json={
            "email": "user1@test.com",
            "password": "pass123",
        },
    )
    user_headers = {"Authorization": f"Bearer {token_resp.json()['access_token']}"}

    response = await client.get("/api/admin/users", headers=user_headers)
    assert response.status_code == 403


async def test_should_prevent_deleting_last_admin(client: AsyncClient, admin_headers: dict):
    # Get admin user ID from /me
    me = await client.get("/api/auth/me", headers=admin_headers)
    admin_id = me.json()["id"]

    response = await client.delete(f"/api/admin/users/{admin_id}", headers=admin_headers)
    assert response.status_code == 400
