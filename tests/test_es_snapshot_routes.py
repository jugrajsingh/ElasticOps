"""Phase 3: /es/* read endpoints serve precomputed snapshots, with live fallback + /es/refresh.

Two paths are exercised per endpoint:

* **snapshot-first** — seed a ``cluster_snapshots`` row via ``snapshot_repo.upsert_snapshot`` and
  assert the endpoint returns the wrapped ``{data, fetched_at, stale_seconds, next_poll_in}`` shape
  with ``data == payload`` and **without** touching ES (the ES dependency is a strict mock that
  raises if any cat/health method is called).
* **live fallback** — no snapshot row + a mock ES; assert the endpoint live-builds, wraps with
  ``stale_seconds == 0``, and persists a row so the next read is cached.
"""

from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from backend.dependencies import get_es_client
from backend.main import app
from backend.services import snapshot_repo
from backend.services.es_client import ESClient
from tests.conftest import test_session_factory as session_factory

CLUSTER_BODY = {"name": "test", "url": "https://es.example.com:9200"}


async def _create_cluster(authed_client: AsyncClient) -> int:
    resp = await authed_client.post("/api/clusters", json=CLUSTER_BODY)
    assert resp.status_code in (200, 201)
    return resp.json()["id"]


async def _seed(cluster_id: int, kind: str, payload) -> None:
    async with session_factory() as session:
        await snapshot_repo.upsert_snapshot(session, cluster_id, kind, payload, item_count=1, duration_ms=0)


def _no_es_calls_mock() -> AsyncMock:
    """A mock ES whose every cat/health call raises — proves the snapshot path never hits ES."""
    mock = AsyncMock(spec=ESClient)
    boom = AsyncMock(side_effect=AssertionError("ES must not be called on the snapshot path"))
    for method in (
        "cluster_health",
        "cat_nodes_detailed",
        "cat_indices_detailed",
        "cat_shards_detailed",
        "cat_recovery_active",
    ):
        setattr(mock, method, boom)
    return mock


def _full_mock_es() -> AsyncMock:
    """A mock ES returning a tiny consistent cluster for the live-fallback + refresh paths."""
    mock = AsyncMock(spec=ESClient)
    mock.cluster_health.return_value = {
        "cluster_name": "test",
        "status": "green",
        "number_of_nodes": 1,
        "number_of_data_nodes": 1,
        "active_primary_shards": 1,
        "active_shards": 1,
        "relocating_shards": 0,
        "initializing_shards": 0,
        "unassigned_shards": 0,
    }
    mock.cat_nodes_detailed.return_value = [
        {
            "name": "data-hot-1",
            "node.role": "dh",
            "ip": "10.0.0.1",
            "disk.total": "100",
            "disk.used": "40",
            "disk.used_percent": "40.0",
            "heap.max": "100",
            "heap.current": "50",
            "heap.percent": "50.0",
            "cpu": "10",
            "load_1m": "1.0",
            "segments.count": "5",
        }
    ]
    mock.cat_indices_detailed.return_value = [
        {
            "health": "green",
            "status": "open",
            "index": "logs_app_1_2024",
            "pri": "1",
            "rep": "0",
            "docs.count": "1000",
            "store.size": "50000",
            "pri.store.size": "50000",
        }
    ]
    mock.cat_shards_detailed.return_value = [
        {
            "index": "logs_app_1_2024",
            "shard": "0",
            "prirep": "p",
            "state": "STARTED",
            "docs": "1000",
            "store": "50000",
            "node": "data-hot-1",
            "segments.count": "5",
        }
    ]
    mock.cat_recovery_active.return_value = []
    return mock


# --- Snapshot-first: served from DB, ES never touched -------------------------------------------


@pytest.mark.parametrize(
    ("kind", "path", "payload"),
    [
        (
            "health",
            "health",
            {
                "cluster_name": "c",
                "status": "green",
                "number_of_nodes": 1,
                "number_of_data_nodes": 1,
                "active_primary_shards": 1,
                "active_shards": 1,
                "relocating_shards": 0,
                "initializing_shards": 0,
                "unassigned_shards": 0,
            },
        ),
        (
            "nodes",
            "nodes",
            [
                {
                    "name": "data-hot-1",
                    "role": "dh",
                    "ip": "10.0.0.1",
                    "version": "",
                    "disk_total": 1,
                    "disk_used": 1,
                    "disk_used_percent": 1.0,
                    "heap_max": 1,
                    "heap_current": 1,
                    "heap_percent": 1.0,
                    "cpu": 1.0,
                    "load_1m": 1.0,
                    "segments_count": 1,
                    "shard_count": 7,
                    "tier": "hot",
                }
            ],
        ),
        (
            "shardmap",
            "shard-map",
            {
                "data_nodes": [{"name": "data-hot-1", "short": "data-hot-1", "tier": "hot", "disk_used_percent": 1.0}],
                "indices": [{"index": "logs_app_1_2024", "pri_store_size": 5, "health": "green"}],
                "cells": {"logs_app_1_2024 data-hot-1": []},
            },
        ),
    ],
)
async def test_should_serve_snapshot_without_calling_es(authed_client: AsyncClient, kind, path, payload):
    cluster_id = await _create_cluster(authed_client)
    await _seed(cluster_id, kind, payload)

    app.dependency_overrides[get_es_client] = _no_es_calls_mock
    try:
        resp = await authed_client.get(f"/api/clusters/{cluster_id}/es/{path}")
        assert resp.status_code == 200
        wrapper = resp.json()
        assert wrapper["data"] == payload
        assert wrapper["stale_seconds"] >= 0
        assert wrapper["fetched_at"] is not None
        assert "next_poll_in" in wrapper
    finally:
        app.dependency_overrides.pop(get_es_client, None)


def _analyzed_index(name: str, opportunity_count: int, wasted_shards: int) -> dict:
    """A complete ``AnalyzedIndex`` dict so the served payload validates against the response model."""
    opportunities = (
        [
            {
                "type": "over-sharded",
                "severity": "high",
                "detail": "x",
                "wasted_shards": wasted_shards,
                "target_shards": 1,
            }
        ]
        if opportunity_count
        else []
    )
    return {
        "name": name,
        "health": "green",
        "status": "open",
        "pri_count": 1,
        "rep_count": 0,
        "doc_count": 1,
        "pri_store_bytes": 1,
        "store_bytes": 1,
        "avg_shard_size_gb": 0.0,
        "max_shard_size_gb": 0.0,
        "max_segments_per_shard": 1,
        "shard_size_cv": 0.0,
        "opportunities": opportunities,
        "opportunity_count": opportunity_count,
        "wasted_shards": wasted_shards,
    }


async def test_should_serve_indices_snapshot_and_filter_problems_only(authed_client: AsyncClient):
    cluster_id = await _create_cluster(authed_client)
    payload = {
        "total_indices": 2,
        "total_with_opportunities": 1,
        "total_wasted_shards": 3,
        "indices": [
            _analyzed_index("with_opp", opportunity_count=1, wasted_shards=3),
            _analyzed_index("clean", opportunity_count=0, wasted_shards=0),
        ],
    }
    await _seed(cluster_id, "indices", payload)

    app.dependency_overrides[get_es_client] = _no_es_calls_mock
    try:
        # Full list (no filter).
        resp = await authed_client.get(f"/api/clusters/{cluster_id}/es/analyze")
        assert resp.status_code == 200
        assert resp.json()["data"]["total_indices"] == 2

        # problems_only filters server-side from the same stored payload.
        resp = await authed_client.get(f"/api/clusters/{cluster_id}/es/analyze?problems_only=true")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total_indices"] == 1
        assert all(i["opportunity_count"] > 0 for i in data["indices"])
    finally:
        app.dependency_overrides.pop(get_es_client, None)


# --- Live fallback: no snapshot row -> build + persist + wrap with stale_seconds == 0 ------------


async def test_should_live_fallback_when_no_snapshot(authed_client: AsyncClient):
    cluster_id = await _create_cluster(authed_client)

    app.dependency_overrides[get_es_client] = _full_mock_es
    try:
        resp = await authed_client.get(f"/api/clusters/{cluster_id}/es/nodes")
        assert resp.status_code == 200
        wrapper = resp.json()
        assert wrapper["stale_seconds"] == 0
        nodes = wrapper["data"]
        assert nodes[0]["name"] == "data-hot-1"
        assert nodes[0]["shard_count"] == 1
        assert nodes[0]["tier"] == "hot"
    finally:
        app.dependency_overrides.pop(get_es_client, None)

    # The fallback persisted a row, so it now exists in the DB.
    async with session_factory() as session:
        snap = await snapshot_repo.get_latest(session, cluster_id, "nodes")
    assert snap is not None
    assert snap.payload[0]["name"] == "data-hot-1"


# --- POST /es/refresh: triggers a real refresh, subsequent GET serves the fresh snapshot ---------


async def test_should_refresh_then_serve_fresh_snapshot(authed_client: AsyncClient):
    cluster_id = await _create_cluster(authed_client)

    app.dependency_overrides[get_es_client] = _full_mock_es
    try:
        refresh_resp = await authed_client.post(f"/api/clusters/{cluster_id}/es/refresh?kind=nodes")
        assert refresh_resp.status_code == 200
        body = refresh_resp.json()
        assert body["kind"] == "nodes"
        assert body["fetched_at"] is not None

        # A subsequent GET serves the freshly-built snapshot without re-calling ES.
        nodes_es = _no_es_calls_mock()
        app.dependency_overrides[get_es_client] = lambda: nodes_es
        resp = await authed_client.get(f"/api/clusters/{cluster_id}/es/nodes")
        assert resp.status_code == 200
        nodes = resp.json()["data"]
        assert nodes[0]["name"] == "data-hot-1"
    finally:
        app.dependency_overrides.pop(get_es_client, None)

    # Refresh wrote every kind (single raw fetch fanned out).
    async with session_factory() as session:
        for kind in ("health", "overview", "nodes", "indices", "shardmap", "pivot", "shards"):
            assert await snapshot_repo.get_latest(session, cluster_id, kind) is not None
