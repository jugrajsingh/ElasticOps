"""Tests for the SPA catch-all route: unknown /api/* paths return JSON 404, not index.html."""

import pytest
from httpx import AsyncClient

from backend.main import STATIC_DIR


async def test_should_return_json_404_for_unknown_api_path(client: AsyncClient):
    response = await client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


@pytest.mark.skipif(not STATIC_DIR.is_dir(), reason="frontend/dist not built; SPA catch-all route not mounted")
async def test_should_return_spa_index_for_unknown_non_api_route(client: AsyncClient):
    response = await client.get("/some-spa-route")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
