# ElasticOps

![CI](https://github.com/jugrajsingh/ElasticOps/actions/workflows/ci.yml/badge.svg)

Modern Elasticsearch cluster operations dashboard. Open-source successor to [Cerebro](https://github.com/lmenezes/cerebro).

## Features

- **Cluster Overview** — Health metrics, node disk usage, active shard movements
- **Shard Map** — Pivot table (type→channel→year hierarchy) and grid view (flat with shard chips)
- **Index Explorer** — Per-index analysis with optimization opportunity detection
- **Job Engine** — Automated force merge, shard reduction, with approval workflow
- **Node Management** — Node health, storage breakdown, drain operations
- **Settings Management** — View/edit cluster settings with change tracking
- **Multi-Cluster** — Manage multiple Elasticsearch clusters from one dashboard

## Quick Start

```bash
git clone git@github.com:jugrajsingh/ElasticOps.git
cd ElasticOps

# Backend (from repo root)
uv sync --extra dev
uv run uvicorn backend.main:app --reload --port 4354

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 and add your Elasticsearch cluster connection.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + SQLAlchemy 2.0 (async) |
| Frontend | React 18 + Vite + Tailwind + shadcn/ui |
| Database | SQLite (default) or PostgreSQL |
| Tables | TanStack Table (virtual scroll) |
| State | TanStack Query (caching + auto-refresh) |

## Security

- On first run a random admin password is generated and printed to the logs; change it via
  **Settings → Password** (or `POST /api/auth/me/password`).
- The JWT signing secret and the credential-encryption (Fernet) key auto-generate into a
  gitignored `.elasticops-secrets.json`. For production set `AUTH__JWT_SECRET` and
  `SECURITY__ENCRYPTION_KEY` (env or `local.env.yaml`) so they are managed explicitly.
- Elasticsearch cluster credentials are **encrypted at rest**. Prefer least-privilege ES users.
- `reduce_shards` jobs are **non-destructive**: they create a shrunk copy `<index>-shrink-<n>`
  and leave the original index intact for you to verify before swapping/deleting.
- v0.2 roadmap: app-level login rate limiting and Alembic migrations. (CSRF is N/A — auth uses
  `Authorization: Bearer` tokens, not cookies.)

## License

This project is licensed under the **GNU Affero General Public License v3.0** (AGPL-3.0) — see [LICENSE](LICENSE).

Running a modified version over a network obligates you (under AGPL §13) to offer its complete source to users. A separate **commercial license** that lifts these copyleft/source-disclosure terms (e.g. to run a proprietary managed service) is available on request — contact **jugrajskhalsa@gmail.com**.
