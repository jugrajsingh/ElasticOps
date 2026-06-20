# =============================================================================
# Multi-stage build: React frontend + FastAPI backend
# =============================================================================

# Stage 1: Build React frontend
FROM node:20-alpine AS frontend-builder
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

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app" \
    PYTHONUNBUFFERED=1

USER appuser
EXPOSE 4354

ENTRYPOINT ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "4354"]
