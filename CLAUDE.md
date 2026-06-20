# CLAUDE.md — ElasticOps

Open-source Elasticsearch cluster operations dashboard. A modern web application for
managing Elasticsearch clusters: shard-level visualization, per-index optimization
analysis, and a job execution engine for operations like force merge and shard reduction.

## Architecture

- **Backend**: FastAPI (async) + SQLAlchemy 2.0 (async) + SQLite (default) / PostgreSQL.
- **Frontend**: React 18 + Vite + Tailwind CSS + shadcn/ui + TanStack Table/Query.
- **No hardcoded cluster references** — all cluster connections are configured via the UI or
  settings; this is a vendor-neutral tool.

### Backend (`backend/`)
- FastAPI with async routes and a lifespan context manager.
- SQLAlchemy 2.0 with `mapped_column` (modern type-hinted style) and an async session factory
  (`async_sessionmaker`).
- Thin routers → service classes for business logic (thin routes, fat services).
- ES client: a **custom async HTTP client built on `httpx`** (no `elasticsearch-py` dependency).
- Auth: local JWT with bcrypt password hashing; the user table lives in the DB.
- Config: Pydantic Settings with YAML + ENV variable support (`config/settings.py`); ship
  `example.env.yaml`, never a real `local.env.yaml`.

### Frontend (`frontend/`)
- React 18 with TypeScript.
- Vite dev server proxies `/api` → the backend during development.
- Production: built into `frontend/dist/` and served by FastAPI as static files.
- shadcn/ui components customized for a warm dark theme.
- TanStack Table for data grids with virtual scroll; TanStack Query for data fetching with
  auto-refresh.

### Database
- SQLite by default (zero setup); PostgreSQL for production.
- SQLAlchemy ORM — switching DB is a connection-string change.
- Schema is auto-created at startup via SQLAlchemy `Base.metadata.create_all` (no migration
  tool in v0.1.0; there is no DB to migrate on a fresh install).
- Tables: clusters, users, runs, jobs, settings snapshots.

## Design system

Warm dark theme. Key colors: Background `#1C1917`, Surface `#292524`, Amber `#D4A574`
(accent), Sage `#7C9885` (healthy), Terracotta `#CC8B65` (warning), Brick `#B8706E`
(critical). Consistent sidebar navigation across screens.

## Architectural patterns

- Pydantic Settings with YAML + ENV variable support (`config/settings.py`).
- Vite proxy pattern (dev) + StaticFiles (prod).
- Thin routers → service classes → DB/ES clients.
- Multi-stage Dockerfile (Node build → Python → runtime).
- Pre-commit hooks (gitleaks, ruff, conventional commits).

## Development commands

```bash
# Backend (from repo root — pyproject.toml is at the root)
uv sync --extra dev
uv run uvicorn backend.main:app --reload --port 4354
# Frontend
cd frontend && npm install && npm run dev
# Tests / lint
uv run pytest -q && uv run ruff check .
# Pre-commit
uv run pre-commit install && uv run pre-commit run --all-files
```

## Contributor notes

- Never commit your local `elasticops.db` or any `*.db` — they are gitignored. The database is
  created at runtime.
- Use `*.example.com` placeholder hostnames (e.g. `es.example.com`) in any committed config or
  fixture. Never commit real cluster hostnames or credentials.
- Secrets (`jwt_secret`, Fernet `encryption_key`) auto-generate into the gitignored
  `.elasticops-secrets.json` on first run; set `AUTH__JWT_SECRET` / `SECURITY__ENCRYPTION_KEY`
  in production. ES cluster credentials are encrypted at rest.
- `reduce_shards` jobs create a shrunk copy `<index>-shrink-<n>` and leave the source intact.
