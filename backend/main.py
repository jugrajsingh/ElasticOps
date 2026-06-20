import logging
import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from backend.auth import hash_password
from backend.database import async_session_factory, init_db
from backend.models.user import User
from backend.routes import admin, auth, clusters, es, health, jobs

logger = logging.getLogger("elasticops")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

DEFAULT_ADMIN_EMAIL = "admin@elasticops.local"


async def _ensure_default_admin() -> None:
    """On first run, create a default admin and log credentials."""
    async with async_session_factory() as session:
        user_count = await session.scalar(select(func.count()).select_from(User))
        if user_count > 0:
            return

        password = secrets.token_urlsafe(12)
        user = User(
            email=DEFAULT_ADMIN_EMAIL,
            password_hash=hash_password(password),
            name="Admin",
            role="admin",
        )
        session.add(user)
        await session.commit()

        logger.warning("=" * 60)
        logger.warning("  DEFAULT ADMIN ACCOUNT CREATED")
        logger.warning("  Email:    %s", DEFAULT_ADMIN_EMAIL)
        logger.warning("  Password: %s", password)
        logger.warning("  Change this password after first login!")
        logger.warning("=" * 60)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    await init_db()
    await _ensure_default_admin()
    yield


app = FastAPI(
    title="ElasticOps",
    lifespan=lifespan,
    docs_url=None if STATIC_DIR.is_dir() else "/docs",
    redoc_url=None,
    openapi_url=None if STATIC_DIR.is_dir() else "/openapi.json",
)

if not STATIC_DIR.is_dir():
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(clusters.router)
app.include_router(es.router)
app.include_router(jobs.router)
app.include_router(admin.router)

if STATIC_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{rest_of_path:path}")
    async def spa_fallback(rest_of_path: str) -> FileResponse:  # noqa: ARG001
        """Serve index.html for all non-API routes (SPA client-side routing)."""
        return FileResponse(STATIC_DIR / "index.html")
