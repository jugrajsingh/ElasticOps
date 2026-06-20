from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.cluster import Cluster
from backend.services.es_client import ESClient
from backend.services.secrets import decrypt


async def get_es_client(cluster_id: int, db: AsyncSession = Depends(get_db)) -> ESClient:
    """Resolve cluster ID to an ESClient instance."""
    result = await db.execute(select(Cluster).where(Cluster.id == cluster_id))
    cluster = result.scalar_one_or_none()
    if not cluster:
        raise HTTPException(404, "Cluster not found")

    return ESClient(
        base_url=cluster.url,
        username=cluster.username,
        password=decrypt(cluster.password_encrypted),
        verify_ssl=cluster.verify_ssl,
    )
