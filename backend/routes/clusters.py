from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import get_current_user
from backend.database import get_db
from backend.models.cluster import Cluster
from backend.models.user import User
from backend.models.user_cluster import UserCluster
from backend.schemas.cluster import ClusterCreate, ClusterResponse, ClusterUpdate
from backend.services.secrets import encrypt

router = APIRouter(prefix="/api/clusters", tags=["clusters"])


@router.get("", response_model=list[ClusterResponse])
async def list_clusters(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role == "admin":
        result = await db.execute(select(Cluster).order_by(Cluster.name))
    else:
        result = await db.execute(
            select(Cluster)
            .join(UserCluster, Cluster.id == UserCluster.cluster_id)
            .where(UserCluster.user_id == user.id)
            .order_by(Cluster.name)
        )
    return result.scalars().all()


@router.post("", response_model=ClusterResponse)
async def create_cluster(
    body: ClusterCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role != "admin":
        raise HTTPException(403, "Admin access required to add clusters")

    existing = await db.execute(select(Cluster).where(Cluster.name == body.name))
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Cluster name already exists")

    cluster = Cluster(
        name=body.name,
        url=body.url,
        username=body.username,
        password_encrypted=encrypt(body.password),
        verify_ssl=body.verify_ssl,
    )
    db.add(cluster)
    await db.commit()
    await db.refresh(cluster)
    return cluster


@router.get("/{cluster_id}", response_model=ClusterResponse)
async def get_cluster(
    cluster_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Cluster).where(Cluster.id == cluster_id))
    cluster = result.scalar_one_or_none()
    if not cluster:
        raise HTTPException(404, "Cluster not found")

    if user.role != "admin":
        member = await db.execute(
            select(UserCluster).where(
                UserCluster.user_id == user.id, UserCluster.cluster_id == cluster_id
            )
        )
        if member.scalar_one_or_none() is None:
            raise HTTPException(403, "You do not have access to this cluster")

    return cluster


@router.patch("/{cluster_id}", response_model=ClusterResponse)
async def update_cluster(
    cluster_id: int,
    body: ClusterUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role != "admin":
        raise HTTPException(403, "Admin access required to update clusters")

    result = await db.execute(select(Cluster).where(Cluster.id == cluster_id))
    cluster = result.scalar_one_or_none()
    if not cluster:
        raise HTTPException(404, "Cluster not found")

    update_data = body.model_dump(exclude_unset=True)
    if "password" in update_data:
        update_data["password_encrypted"] = encrypt(update_data.pop("password"))

    for key, value in update_data.items():
        setattr(cluster, key, value)

    await db.commit()
    await db.refresh(cluster)
    return cluster


@router.delete("/{cluster_id}")
async def delete_cluster(
    cluster_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role != "admin":
        raise HTTPException(403, "Admin access required to delete clusters")

    result = await db.execute(select(Cluster).where(Cluster.id == cluster_id))
    cluster = result.scalar_one_or_none()
    if not cluster:
        raise HTTPException(404, "Cluster not found")

    await db.delete(cluster)
    await db.commit()
    return {"detail": "Cluster deleted"}
