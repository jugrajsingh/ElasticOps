# Contributing to ElasticOps

Thanks for your interest! ElasticOps is licensed under **AGPL-3.0** (see `LICENSE`). By
contributing you agree your contributions are licensed under the same terms.

## Dev setup
```bash
uv sync --extra dev                                   # backend deps (incl. pytest/ruff)
uv run uvicorn backend.main:app --reload --port 4354  # backend
cd frontend && npm install && npm run dev             # frontend
```

## Before opening a PR
- `uv run pytest -q` — all tests pass
- `uv run ruff check .` — lint clean
- `cd frontend && npm run build` — frontend compiles
- Use **Conventional Commits** (`feat:`, `fix:`, `docs:`, …); pre-commit enforces this.

## Contributor License Agreement

ElasticOps is dual-licensed (AGPL-3.0 + a commercial license). Before your first pull request
can be merged, you must sign the project **Contributor License Agreement** ([CLA.md](CLA.md)).
This is handled automatically by **CLA Assistant** — when you open a PR, a bot will prompt you
to sign electronically. The CLA lets your contributions be included in both the open-source and
commercial offerings; see [COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md).

## Reporting security issues
Email **jugrajskhalsa@gmail.com** rather than opening a public issue.
