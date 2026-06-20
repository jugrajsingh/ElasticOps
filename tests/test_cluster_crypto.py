from httpx import AsyncClient
from sqlalchemy import select

from backend.models.cluster import Cluster
from backend.services.secrets import decrypt
from tests.conftest import test_session_factory


async def test_cluster_password_is_encrypted_at_rest(authed_client: AsyncClient):
    resp = await authed_client.post(
        "/api/clusters",
        json={"name": "c1", "url": "https://es.example.com:9200", "username": "elastic", "password": "s3cret"},
    )
    assert resp.status_code == 200
    async with test_session_factory() as session:
        cluster = (await session.execute(select(Cluster))).scalar_one()
    assert cluster.password_encrypted != "s3cret"  # stored as ciphertext
    assert decrypt(cluster.password_encrypted) == "s3cret"  # decryptable back to plaintext
