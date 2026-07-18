"""Fingerprint-based dedup + detector-scoping for the /recommend endpoint.

These tests craft mock-ES ``cat_indices_detailed`` / ``cat_shards_detailed`` rows that drive the
analyzer into specific opportunities, then assert that re-running /recommend reconciles pending
jobs by fingerprint (stable row ids, no duplicates, resolved suggestions deleted) and that a
scoped run only touches its own detectors' job_types.
"""

from unittest.mock import AsyncMock

from httpx import AsyncClient

from backend.dependencies import get_es_client
from backend.main import app
from backend.services.es_client import ESClient

ONE_GB = 1024**3

# over-sharded -> reduce_shards: 5 shards for a sub-GB index.
_OVER_SHARDED_INDEX = {
    "health": "green",
    "status": "open",
    "index": "over_idx",
    "pri": "5",
    "rep": "0",
    "docs.count": "100",
    "docs.deleted": "0",
    "store.size": "250000",
    "pri.store.size": "250000",
}

# under-sharded -> split_shards: single 100GB primary shard exceeds the 50GB ideal max.
_UNDER_SHARDED_INDEX = {
    "health": "green",
    "status": "open",
    "index": "under_idx",
    "pri": "1",
    "rep": "0",
    "docs.count": "1000",
    "docs.deleted": "0",
    "store.size": str(100 * ONE_GB),
    "pri.store.size": str(100 * ONE_GB),
}


def _over_sharded_shards() -> list[dict]:
    return [
        {
            "index": "over_idx",
            "shard": str(i),
            "prirep": "p",
            "state": "STARTED",
            "docs": "20",
            "store": "50000",
            "node": f"node-{i}",
            "segments.count": "1",
        }
        for i in range(5)
    ]


def _under_sharded_shards() -> list[dict]:
    return [
        {
            "index": "under_idx",
            "shard": "0",
            "prirep": "p",
            "state": "STARTED",
            "docs": "1000",
            "store": str(100 * ONE_GB),
            "node": "node-0",
            "segments.count": "1",
        }
    ]


def _make_mock_es(indices: list[dict], shards: list[dict]) -> AsyncMock:
    mock = AsyncMock(spec=ESClient)
    mock.cat_indices_detailed.return_value = indices
    mock.cat_shards_detailed.return_value = shards
    return mock


async def _create_cluster(client: AsyncClient, name: str) -> int:
    resp = await client.post("/api/clusters", json={"name": name, "url": "https://es.example.com:9200"})
    return resp.json()["id"]


async def test_should_keep_stable_row_id_when_recommend_runs_twice(authed_client: AsyncClient):
    """Two all-detector runs over identical data must not duplicate and must update rows in place."""
    cluster_id = await _create_cluster(authed_client, "fp-stable")
    mock_es = _make_mock_es([_OVER_SHARDED_INDEX], _over_sharded_shards())
    app.dependency_overrides[get_es_client] = lambda: mock_es

    try:
        await authed_client.post(f"/api/clusters/{cluster_id}/jobs/recommend")
        first = (await authed_client.get(f"/api/clusters/{cluster_id}/jobs?status=pending")).json()

        await authed_client.post(f"/api/clusters/{cluster_id}/jobs/recommend")
        second = (await authed_client.get(f"/api/clusters/{cluster_id}/jobs?status=pending")).json()
    finally:
        app.dependency_overrides.pop(get_es_client, None)

    assert len(first) == 1
    assert len(second) == 1
    # Same index+type -> updated in place, so the row id is stable across runs.
    assert first[0]["job_type"] == "reduce_shards"
    assert first[0]["index_name"] == "over_idx"
    assert second[0]["id"] == first[0]["id"]
    assert second[0]["fingerprint"] == first[0]["fingerprint"]
    assert second[0]["fingerprint"] is not None


async def test_should_only_reconcile_selected_detectors_job_types(authed_client: AsyncClient):
    """A scoped under-sharded run must leave a pre-existing reduce_shards (over-sharded) pending intact."""
    cluster_id = await _create_cluster(authed_client, "fp-scoped")
    indices = [_OVER_SHARDED_INDEX, _UNDER_SHARDED_INDEX]
    shards = _over_sharded_shards() + _under_sharded_shards()
    mock_es = _make_mock_es(indices, shards)
    app.dependency_overrides[get_es_client] = lambda: mock_es

    try:
        # All detectors first: yields both a reduce_shards and a split_shards pending job.
        await authed_client.post(f"/api/clusters/{cluster_id}/jobs/recommend")
        baseline = (await authed_client.get(f"/api/clusters/{cluster_id}/jobs?status=pending")).json()
        by_type = {j["job_type"]: j for j in baseline}
        assert "reduce_shards" in by_type
        assert "split_shards" in by_type
        reduce_id = by_type["reduce_shards"]["id"]
        split_id = by_type["split_shards"]["id"]

        # Scoped run: only under-sharded -> only split_shards is reconciled.
        await authed_client.post(
            f"/api/clusters/{cluster_id}/jobs/recommend",
            json={"detectors": ["under-sharded"]},
        )
        after = (await authed_client.get(f"/api/clusters/{cluster_id}/jobs?status=pending")).json()
        after_by_type = {j["job_type"]: j for j in after}
    finally:
        app.dependency_overrides.pop(get_es_client, None)

    # reduce_shards untouched (out of scope); split_shards updated in place (stable id).
    assert "reduce_shards" in after_by_type
    assert after_by_type["reduce_shards"]["id"] == reduce_id
    assert "split_shards" in after_by_type
    assert after_by_type["split_shards"]["id"] == split_id


async def test_should_not_regenerate_suggestion_when_already_approved(authed_client: AsyncClient):
    """Re-running analysis after approving a suggestion must not resurrect it as a new pending dup.

    The fingerprint dedup must consider active (approved/queued/executing) jobs, not just pending —
    otherwise an opportunity the operator already acted on regenerates every Run Analysis.
    """
    cluster_id = await _create_cluster(authed_client, "fp-approved")
    mock_es = _make_mock_es([_OVER_SHARDED_INDEX], _over_sharded_shards())
    app.dependency_overrides[get_es_client] = lambda: mock_es

    try:
        await authed_client.post(f"/api/clusters/{cluster_id}/jobs/recommend")
        pending = (await authed_client.get(f"/api/clusters/{cluster_id}/jobs?status=pending")).json()
        assert len(pending) == 1
        job_id = pending[0]["id"]

        # Operator approves the suggestion.
        await authed_client.put(f"/api/clusters/{cluster_id}/jobs/{job_id}/approve")

        # Re-run analysis over the SAME data: opportunity still detected, but already acted on.
        await authed_client.post(f"/api/clusters/{cluster_id}/jobs/recommend")
        pending_after = (await authed_client.get(f"/api/clusters/{cluster_id}/jobs?status=pending")).json()
        approved_after = (await authed_client.get(f"/api/clusters/{cluster_id}/jobs?status=approved")).json()
    finally:
        app.dependency_overrides.pop(get_es_client, None)

    assert pending_after == []  # no regenerated duplicate
    assert len(approved_after) == 1  # the approved suggestion is untouched
    assert approved_after[0]["id"] == job_id


async def test_should_delete_resolved_pending_suggestion_on_rerun(authed_client: AsyncClient):
    """If the 2nd run's analysis no longer yields a fingerprint, its pending job is deleted."""
    cluster_id = await _create_cluster(authed_client, "fp-resolved")
    mock_es = _make_mock_es([_OVER_SHARDED_INDEX], _over_sharded_shards())
    app.dependency_overrides[get_es_client] = lambda: mock_es

    try:
        await authed_client.post(f"/api/clusters/{cluster_id}/jobs/recommend")
        first = (await authed_client.get(f"/api/clusters/{cluster_id}/jobs?status=pending")).json()
        assert len(first) == 1

        # Resolve: the over-sharded index is now collapsed to a single shard -> no opportunity.
        mock_es.cat_indices_detailed.return_value = []
        mock_es.cat_shards_detailed.return_value = []
        await authed_client.post(f"/api/clusters/{cluster_id}/jobs/recommend")
        second = (await authed_client.get(f"/api/clusters/{cluster_id}/jobs?status=pending")).json()
    finally:
        app.dependency_overrides.pop(get_es_client, None)

    assert second == []
