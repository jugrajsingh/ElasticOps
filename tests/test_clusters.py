from httpx import AsyncClient
from sqlalchemy import select

from backend.models.job import Job
from backend.models.run import Run
from backend.models.snapshot import ClusterSnapshot
from tests.conftest import test_session_factory


async def test_should_cascade_delete_dependent_rows_when_cluster_deleted(authed_client: AsyncClient):
    # Arrange: create cluster via API
    resp = await authed_client.post(
        "/api/clusters",
        json={"name": "cascade-test", "url": "https://es.example.com:9200"},
    )
    assert resp.status_code == 200
    cluster_id = resp.json()["id"]

    # Seed dependent rows directly via the test session factory
    async with test_session_factory() as session:
        run = Run(cluster_id=cluster_id)
        session.add(run)
        await session.flush()

        job = Job(
            run_id=run.id,
            cluster_id=cluster_id,
            index_name="test-idx",
            job_type="force_merge",
            tier=1,
        )
        session.add(job)

        snapshot = ClusterSnapshot(
            cluster_id=cluster_id,
            kind="shards",
            payload={"data": []},
        )
        session.add(snapshot)
        await session.commit()

    # Act: delete the cluster
    delete_resp = await authed_client.delete(f"/api/clusters/{cluster_id}")
    assert delete_resp.status_code == 200

    # Assert: cluster is gone and no orphaned dependents remain
    async with test_session_factory() as session:
        jobs = (await session.execute(select(Job).where(Job.cluster_id == cluster_id))).scalars().all()
        runs = (await session.execute(select(Run).where(Run.cluster_id == cluster_id))).scalars().all()
        snapshots = (
            (await session.execute(select(ClusterSnapshot).where(ClusterSnapshot.cluster_id == cluster_id)))
            .scalars()
            .all()
        )

    assert jobs == [], f"Expected no orphaned Job rows, got {len(jobs)}"
    assert runs == [], f"Expected no orphaned Run rows, got {len(runs)}"
    assert snapshots == [], f"Expected no orphaned ClusterSnapshot rows, got {len(snapshots)}"


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


async def test_should_toggle_is_active_when_patched(authed_client: AsyncClient):
    create = await authed_client.post("/api/clusters", json={"name": "prod", "url": "https://es:9200"})
    cluster_id = create.json()["id"]
    assert create.json()["is_active"] is True

    deactivate = await authed_client.patch(f"/api/clusters/{cluster_id}", json={"is_active": False})
    assert deactivate.status_code == 200
    assert deactivate.json()["is_active"] is False

    reactivate = await authed_client.patch(f"/api/clusters/{cluster_id}", json={"is_active": True})
    assert reactivate.status_code == 200
    assert reactivate.json()["is_active"] is True


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
