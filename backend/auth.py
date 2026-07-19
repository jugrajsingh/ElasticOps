from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.user import User
from backend.models.user_cluster import UserCluster
from backend.services.secrets import get_jwt_secret
from config.settings import get_settings

security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_access_token(data: dict) -> str:
    settings = get_settings()
    expire = datetime.now(UTC) + timedelta(minutes=settings.auth.access_token_expire_minutes)
    to_encode = {**data, "exp": expire}
    return jwt.encode(to_encode, get_jwt_secret(), algorithm=settings.auth.jwt_algorithm)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Returns the authenticated User object. Auth is always required."""
    if not credentials:
        raise HTTPException(401, "Missing authorization token")

    settings = get_settings()
    try:
        payload = jwt.decode(
            credentials.credentials,
            get_jwt_secret(),
            algorithms=[settings.auth.jwt_algorithm],
        )
    except jwt.InvalidTokenError as err:
        raise HTTPException(401, "Invalid token") from err

    email: str | None = payload.get("sub")
    if not email:
        raise HTTPException(401, "Token missing subject claim")

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(401, "User not found or deactivated")

    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """Dependency that ensures the current user is an admin."""
    if user.role != "admin":
        raise HTTPException(403, "Admin access required")
    return user


async def require_cluster_access(
    cluster_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Guard the per-cluster routers: valid JWT, plus membership of ``{cluster_id}`` for non-admins.

    Admins bypass the membership check. Non-admins must have a ``user_clusters`` row linking them to
    the requested cluster (mirrors the check in ``routes/clusters.py``); otherwise reject with 403.
    """
    if user.role == "admin":
        return user

    member = await db.execute(
        select(UserCluster).where(UserCluster.user_id == user.id, UserCluster.cluster_id == cluster_id)
    )
    if member.scalar_one_or_none() is None:
        raise HTTPException(403, "You do not have access to this cluster")
    return user
