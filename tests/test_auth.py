from httpx import AsyncClient


async def test_should_report_setup_required_on_fresh_db(client: AsyncClient):
    response = await client.get("/api/auth/status")
    assert response.status_code == 200
    assert response.json()["setup_required"] is True


async def test_should_create_admin_via_setup(client: AsyncClient):
    response = await client.post(
        "/api/auth/setup",
        json={
            "name": "Admin User",
            "email": "admin@test.com",
            "password": "adminpass123",
        },
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


async def test_should_reject_setup_when_users_exist(client: AsyncClient):
    await client.post(
        "/api/auth/setup",
        json={
            "name": "Admin",
            "email": "admin@test.com",
            "password": "adminpass123",
        },
    )
    response = await client.post(
        "/api/auth/setup",
        json={
            "name": "Another",
            "email": "another@test.com",
            "password": "pass123",
        },
    )
    assert response.status_code == 400


async def test_should_login_after_setup(client: AsyncClient):
    await client.post(
        "/api/auth/setup",
        json={
            "name": "Admin",
            "email": "admin@test.com",
            "password": "adminpass123",
        },
    )
    response = await client.post(
        "/api/auth/login",
        json={
            "email": "admin@test.com",
            "password": "adminpass123",
        },
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


async def test_should_reject_wrong_password(client: AsyncClient):
    await client.post(
        "/api/auth/setup",
        json={
            "name": "Admin",
            "email": "admin@test.com",
            "password": "adminpass123",
        },
    )
    response = await client.post(
        "/api/auth/login",
        json={
            "email": "admin@test.com",
            "password": "wrongpass",
        },
    )
    assert response.status_code == 401


async def test_should_return_me_with_valid_token(client: AsyncClient, admin_headers: dict):
    response = await client.get("/api/auth/me", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["role"] == "admin"


async def test_should_reject_unauthenticated_cluster_list(client: AsyncClient):
    response = await client.get("/api/clusters")
    assert response.status_code == 401


async def test_change_password(authed_client):
    resp = await authed_client.post(
        "/api/auth/me/password",
        json={"current_password": "adminpass123", "new_password": "newpass456"},
    )
    assert resp.status_code == 200

    # old password rejected, new password works
    bad = await authed_client.post("/api/auth/login", json={"email": "admin@test.com", "password": "adminpass123"})
    assert bad.status_code == 401
    good = await authed_client.post("/api/auth/login", json={"email": "admin@test.com", "password": "newpass456"})
    assert good.status_code == 200
