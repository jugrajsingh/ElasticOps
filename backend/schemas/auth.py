from datetime import datetime

from pydantic import BaseModel


class SetupRequest(BaseModel):
    name: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class InviteRequest(BaseModel):
    name: str
    email: str
    password: str
    role: str = "user"
    cluster_ids: list[int] = []


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    email: str
    name: str
    role: str
    is_active: bool

    model_config = {"from_attributes": True}


class UserDetailResponse(UserResponse):
    cluster_ids: list[int] = []
    created_at: datetime


class AuthStatusResponse(BaseModel):
    setup_required: bool
    authenticated: bool
    user: UserResponse | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str
