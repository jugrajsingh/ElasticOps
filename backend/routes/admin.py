from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import hash_password, require_admin
from backend.database import get_db
from backend.models.user import User
from backend.models.user_cluster import UserCluster
from backend.schemas.auth import InviteRequest, UserDetailResponse

router = APIRouter(prefix="/api/admin/users", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("", response_model=list[UserDetailResponse])
async def list_users(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).order_by(User.name))
    users = result.scalars().all()
    response = []
    for user in users:
        cluster_result = await db.execute(select(UserCluster.cluster_id).where(UserCluster.user_id == user.id))
        cluster_ids = [row[0] for row in cluster_result.all()]
        response.append(
            UserDetailResponse(
                id=user.id,
                email=user.email,
                name=user.name,
                role=user.role,
                is_active=user.is_active,
                cluster_ids=cluster_ids,
                created_at=user.created_at,
            )
        )
    return response


@router.post("", response_model=UserDetailResponse)
async def invite_user(body: InviteRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Email already registered")

    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        name=body.name,
        role=body.role,
    )
    db.add(user)
    await db.flush()

    for cluster_id in body.cluster_ids:
        db.add(UserCluster(user_id=user.id, cluster_id=cluster_id))

    await db.commit()
    await db.refresh(user)

    return UserDetailResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        is_active=user.is_active,
        cluster_ids=body.cluster_ids,
        created_at=user.created_at,
    )


@router.put("/{user_id}/clusters")
async def update_user_clusters(
    user_id: int,
    cluster_ids: list[int],
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user(user_id, db)

    # Remove existing
    existing = await db.execute(select(UserCluster).where(UserCluster.user_id == user.id))
    for uc in existing.scalars().all():
        await db.delete(uc)

    # Add new
    for cid in cluster_ids:
        db.add(UserCluster(user_id=user.id, cluster_id=cid))

    await db.commit()
    return {"detail": "Cluster access updated"}


@router.delete("/{user_id}")
async def delete_user(user_id: int, db: AsyncSession = Depends(get_db)):
    user = await _get_user(user_id, db)
    if user.role == "admin":
        admin_count = await db.scalar(select(func.count()).select_from(User).where(User.role == "admin"))
        if admin_count <= 1:
            raise HTTPException(400, "Cannot delete the last admin")

    await db.delete(user)
    await db.commit()
    return {"detail": "User deleted"}


async def _get_user(user_id: int, db: AsyncSession) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    return user
