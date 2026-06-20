import os

from cryptography.fernet import Fernet

os.environ.setdefault("AUTH__JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("SECURITY__ENCRYPTION_KEY", Fernet.generate_key().decode())

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.database import Base, get_db
from backend.main import app

TEST_DB_URL = "sqlite+aiosqlite://"

test_engine = create_async_engine(TEST_DB_URL, echo=False)
test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def setup_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def override_get_db() -> AsyncGenerator[AsyncSession]:
    async with test_session_factory() as session:
        yield session


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def admin_token(client: AsyncClient) -> str:
    """Create admin via setup and return token."""
    resp = await client.post(
        "/api/auth/setup",
        json={
            "name": "Admin",
            "email": "admin@test.com",
            "password": "adminpass123",
        },
    )
    return resp.json()["access_token"]


@pytest.fixture
async def admin_headers(admin_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
async def authed_client(client: AsyncClient) -> AsyncClient:
    """Client that auto-creates admin and attaches auth header."""
    resp = await client.post(
        "/api/auth/setup",
        json={
            "name": "Admin",
            "email": "admin@test.com",
            "password": "adminpass123",
        },
    )
    token = resp.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client
