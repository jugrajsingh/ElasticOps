from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import create_access_token, get_current_user, hash_password, verify_password
from backend.database import get_db
from backend.models.user import User
from backend.schemas.auth import (
    AuthStatusResponse,
    LoginRequest,
    PasswordChange,
    SetupRequest,
    TokenResponse,
    UserResponse,
)
from backend.services.rate_limit import login_throttle

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/status", response_model=AuthStatusResponse)
async def auth_status(db: AsyncSession = Depends(get_db)):
    """Check if setup is needed or if user is authenticated. No auth required."""
    user_count = await db.scalar(select(func.count()).select_from(User))
    return AuthStatusResponse(
        setup_required=user_count == 0,
        authenticated=False,
        user=None,
    )


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)):
    """Return the current authenticated user."""
    return user


@router.post("/setup", response_model=TokenResponse)
async def setup(body: SetupRequest, db: AsyncSession = Depends(get_db)):
    """First-run only: create the admin account. Fails if any user already exists."""
    user_count = await db.scalar(select(func.count()).select_from(User))
    if user_count > 0:
        raise HTTPException(400, "Setup already completed. Use /login instead.")

    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        name=body.name,
        role="admin",
    )
    db.add(user)
    await db.commit()

    return TokenResponse(access_token=create_access_token({"sub": user.email}))


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    key = f"{request.client.host if request.client else '?'}:{body.email}"
    login_throttle.check(key)

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.password_hash):
        login_throttle.record_failure(key)
        raise HTTPException(401, "Invalid email or password")

    if not user.is_active:
        raise HTTPException(401, "Account deactivated")

    login_throttle.reset(key)
    return TokenResponse(access_token=create_access_token({"sub": user.email}))


@router.post("/me/password")
async def change_password(
    body: PasswordChange,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    if len(body.new_password) < 8:
        raise HTTPException(400, "New password must be at least 8 characters")
    user.password_hash = hash_password(body.new_password)
    await db.commit()
    return {"detail": "Password updated"}
