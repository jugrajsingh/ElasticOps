# ElasticOps

![CI](https://github.com/jugrajsingh/ElasticOps/actions/workflows/ci.yml/badge.svg)

Modern Elasticsearch cluster operations dashboard. Open-source successor to [Cerebro](https://github.com/lmenezes/cerebro).

## Features

- **Cluster Overview** — Health metrics, node disk usage, active shard movements
- **Shard Map** — Pivot table (dynamic-depth rollup inferred from index names) and grid view
  (flat with shard chips)
- **Index Explorer** — Per-index analysis with optimization opportunity detection (over-sharded,
  under-sharded, segment fragmentation, and high deleted-doc ratio)
- **Job Engine** — Force merge, shard reduction, **shard split** (under-sharded → `_split`),
  **deleted-doc expunge**, **reindex**, and **promote** (atomic alias swap) with an approval
  workflow, plus operator-driven **shard relocation** and **node drain**, all run by an async
  background runner with live progress
- **Node Management** — Node health, storage breakdown, and **node drain / undrain** with live
  "shards left: N" progress straight from the Nodes view
- **Settings Management** — View/edit cluster settings with change tracking
- **Multi-Cluster** — Manage multiple Elasticsearch clusters from one dashboard; clusters can be
  marked **read-only** to block every write operation

## Quick Start

```bash
git clone https://github.com/jugrajsingh/ElasticOps.git
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

## Cluster Operations

ElasticOps runs operations against your cluster through an async background job runner that reports
live progress and drives each job to a terminal state.

- **Node drain / undrain** — From the **Nodes** view, select a node and click **Drain Node**
  (an inline two-step confirm). Drain runs a pre-flight check first; if migrating the node's shards
  would be unsafe (e.g. too few remaining data nodes), it is refused and the reason is shown inline.
  Once draining, the node card shows live `shards left: N` progress and an **Undrain** button that
  cancels the drain and removes the allocation exclusion. Draining adds the node to
  `cluster.routing.allocation.exclude._name` (never clobbering nodes already excluded) and is fully
  reversible.
- **Shard relocation** — Move a single shard copy from one node to another via `_cluster/reroute`;
  the runner polls until the shard lands `STARTED` on the target.
- **Shard split** — Under-sharded indices are mapped to an ES `_split` job that creates
  `<index>-split-<n>` with the primary count raised to the smallest valid multiple (non-destructive;
  the source index is retained for you to verify before promoting/deleting).
- **Deleted-doc expunge** — Indices with a high deleted-doc ratio are mapped to a force-merge with
  `only_expunge_deletes=true`, reclaiming space without a full segment rewrite.
- **Reindex** — Copy an index into a new destination via the ES `_reindex` Tasks API (async, polled
  to completion); the source is left intact.
- **Promote** — Atomically swap an alias from a source index to a target (e.g. after a split/shrink)
  in a single `_aliases` call, with opt-in deletion of the old source.
- **Rebalance advisory** — From the **Shard Map** view, see suggested relocate moves that even out
  shard count across data nodes; each suggestion is executable as-is via the relocate job.
- **Login rate limiting** — Repeated failed logins from the same IP/account are throttled with a
  sliding-window lockout (in-process, returns HTTP 429), with successful logins clearing the counter.
- **Read-only clusters** — Mark a cluster **read-only** to block every write operation (drain,
  relocate, force merge, shard reduction, split, expunge, reindex, promote, settings edits). The
  backend enforces this rail and the UI hides the corresponding controls, so a read-only cluster
  cannot be mutated by accident.

## Test Cluster

A local 3-node Elasticsearch cluster is provided for integration testing:

```bash
make -f Makefile.test test-cluster-up     # start 3 ES nodes (es01 on host port 9201)
ELASTICOPS_TEST_ES=http://localhost:9201 uv run pytest tests/integration -v
make -f Makefile.test test-cluster-down   # stop and remove the cluster + volumes
```

The integration tests exercise the real relocate / drain / force-merge / shrink executors against
this cluster. They **auto-skip** when `ELASTICOPS_TEST_ES` is unset or the cluster is unreachable,
so the default `uv run pytest` stays green without Docker.

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
- `reduce_shards` and `split_shards` jobs are **non-destructive**: they create a new copy
  (`<index>-shrink-<n>` / `<index>-split-<n>`) and leave the original index intact for you to verify
  before promoting/deleting.
- **Login rate limiting** is enforced app-side (sliding-window lockout, HTTP 429). (CSRF is N/A —
  auth uses `Authorization: Bearer` tokens, not cookies.)
- **Known limitation** — deactivating a cluster stops its status polling and blocks new ES
  operations (execute, execute-all, drain, promote, reindex, relocate, force merge) with HTTP 409,
  but a job already executing when the cluster is deactivated runs to completion; cancelling that
  job remains available regardless of the cluster's active state.
- Remaining roadmap: snapshot/restore, ILM policy management, Alembic migrations, and README
  screenshots.

## License

This project is licensed under the **GNU Affero General Public License v3.0** (AGPL-3.0) — see [LICENSE](LICENSE).

Running a modified version over a network obligates you (under AGPL §13) to offer its complete source to users. A separate **commercial license** that lifts these copyleft/source-disclosure terms (e.g. to run a proprietary managed service) is available on request — contact **jugrajskhalsa@gmail.com**.
