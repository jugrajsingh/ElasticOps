# =============================================================================
# Multi-stage build: React frontend + FastAPI backend
# =============================================================================

# Stage 1: Build React frontend
FROM node:26-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# Stage 2: Build Python dependencies
FROM python:3.12-alpine AS backend-builder
COPY --from=ghcr.io/astral-sh/uv:0.11.19 /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
RUN uv sync --frozen --no-dev --no-install-project

# Stage 3: Production runtime
FROM python:3.12-alpine AS runtime
WORKDIR /app

RUN addgroup -g 1000 appuser && adduser -u 1000 -G appuser -D appuser

COPY --from=backend-builder /app/.venv /app/.venv
COPY --from=frontend-builder /app/frontend/dist /app/static

COPY --chown=appuser:appuser config/ config/
COPY --chown=appuser:appuser backend/ backend/

# Persisted state lives on a single dir owned by the runtime user. A fresh named volume mounted
# here inherits this ownership, so both the SQLite DB and the auto-generated secrets file are
# writable + survive container recreation. The Fernet key in the secrets file decrypts saved
# cluster passwords, so it MUST persist — losing it orphans every stored credential.
RUN mkdir -p /app/data && chown appuser:appuser /app/data
VOLUME ["/app/data"]

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app" \
    PYTHONUNBUFFERED=1 \
    DATABASE__URL="sqlite+aiosqlite:////app/data/elasticops.db" \
    SECURITY__SECRETS_FILE="/app/data/.elasticops-secrets.json"

USER appuser
EXPOSE 4354

# Liveness check using the stdlib (alpine has no curl) — succeeds only when the app answers 200.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4354/api/health')"]

ENTRYPOINT ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "4354"]
