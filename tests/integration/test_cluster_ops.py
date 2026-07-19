"""Integration tests exercising the real ES executors against a live 3-node cluster.

These run only when ``ELASTICOPS_TEST_ES`` points at a reachable Elasticsearch (the
``docker-compose.test.yaml`` cluster, es01 on host port 9201). When the env var is unset or the
cluster is unreachable, the whole module is auto-skipped — so ``uv run pytest`` stays green in CI
without a cluster.

Run with the cluster up::

    make -f Makefile.test test-cluster-up test-cluster-seed
    ELASTICOPS_TEST_ES=http://localhost:9201 uv run pytest tests/integration -v

They use the REAL :class:`ESClient` (no DB, no FastAPI app) and ``SimpleNamespace`` Job-likes that
carry only the attributes each executor reads.
"""

import asyncio
import os
import uuid
from types import SimpleNamespace

import httpx
import pytest

from backend.services import executor
from backend.services.es_client import ESClient

ES_URL = os.environ.get("ELASTICOPS_TEST_ES")
_EXCLUDE_KEY = "cluster.routing.allocation.exclude._name"


def _cluster_reachable(url: str | None) -> bool:
    if not url:
        return False
    try:
        resp = httpx.get(f"{url.rstrip('/')}/_cluster/health", timeout=5.0)
    except httpx.HTTPError:
        return False
    else:
        return resp.status_code == 200


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _cluster_reachable(ES_URL),
        reason="ELASTICOPS_TEST_ES unset or cluster unreachable",
    ),
]


def make_client() -> ESClient:
    """A real ESClient against the test cluster (security disabled → no auth)."""
    return ESClient(base_url=ES_URL, username="", password="", verify_ssl=False)


async def _started_shards(es: ESClient) -> list[dict]:
    return [s for s in await es.cat_shards_detailed() if s.get("state") == "STARTED"]


async def _data_node_names(es: ESClient) -> list[str]:
    return [n["name"] for n in await es.cat_nodes_detailed() if "d" in (n.get("node.role") or "")]


async def _wait_cluster_green(es: ESClient, *, attempts: int = 60, delay: float = 2.0) -> dict:
    for _ in range(attempts):
        health = await es.cluster_health()
        if health.get("status") == "green" and health.get("relocating_shards", 0) == 0:
            return health
        await asyncio.sleep(delay)
    raise TimeoutError("cluster did not reach green in time")  # noqa: TRY003


async def _create_index(es: ESClient, name: str, *, shards: int = 1, replicas: int = 0, docs: int = 0) -> None:
    """Delete-then-create a fresh index and optionally index `docs` documents."""
    await es.delete(f"/{name}", params={"ignore_unavailable": "true"})
    await es.put(f"/{name}", json={"settings": {"number_of_shards": shards, "number_of_replicas": replicas}})
    if docs:
        body = "".join(f'{{"index":{{}}}}\n{{"id":{i}}}\n' for i in range(docs))
        await es.request("POST", f"/{name}/_bulk", content=body, headers={"Content-Type": "application/x-ndjson"})
    await es.post(f"/{name}/_refresh")


@pytest.fixture
async def es() -> ESClient:
    client = make_client()
    await _wait_cluster_green(client)
    return client


@pytest.fixture(autouse=True)
async def _clear_exclusions():
    """Always clear allocation exclusions before and after each test so drains never leak."""
    client = make_client()
    await client.put_cluster_settings({"transient": {_EXCLUDE_KEY: None}})
    yield
    await client.put_cluster_settings({"transient": {_EXCLUDE_KEY: None}})


async def test_relocate_shard_lands_started_on_target(es: ESClient):
    index = f"it-relocate-{uuid.uuid4().hex[:8]}"
    await _create_index(es, index, shards=1, replicas=0, docs=100)
    try:
        await _wait_cluster_green(es)
        shard_row = next(s for s in await _started_shards(es) if s["index"] == index)
        source = shard_row["node"]
        target = next(n for n in await _data_node_names(es) if n != source)

        job = SimpleNamespace(
            index_name=index,
            shard_number=int(shard_row["shard"]),
            from_node=source,
            to_node=target,
            detail="",
        )
        await executor.execute_relocate_shard(es, job, attempts=60, delay=2.0)

        landed = [
            s
            for s in await es.cat_shards_detailed()
            if s["index"] == index and s["node"] == target and s["state"] == "STARTED"
        ]
        assert landed, f"shard did not land STARTED on {target}"
        assert target in job.detail
    finally:
        await es.delete(f"/{index}", params={"ignore_unavailable": "true"})


async def test_drain_node_migrates_shards_then_undrain_restores(es: ESClient):
    index = f"it-drain-{uuid.uuid4().hex[:8]}"
    # 3 shards / 1 replica spreads copies across all nodes so es03 is guaranteed to hold some.
    await _create_index(es, index, shards=3, replicas=1, docs=300)
    try:
        await _wait_cluster_green(es)
        assert any(s["node"] == "es03" for s in await _started_shards(es)), "es03 holds no shards pre-drain"

        job = SimpleNamespace(node_name="es03", detail="")
        await executor.execute_drain_node(es, job, attempts=120, delay=2.0)

        on_es03 = await es.cat_shards_on_node("es03")
        assert on_es03 == [], f"es03 still holds shards after drain: {on_es03}"
        assert (await es.cluster_health())["status"] == "green"
        assert "drained" in job.detail.lower()

        # Undrain: remove the exclusion; shards become eligible to return and cluster stays green.
        await executor.undrain_node(es, "es03")
        await _wait_cluster_green(es)
        settings = await es.cluster_settings_full()
        excluded = (settings.get("transient") or {}).get(_EXCLUDE_KEY, "")
        assert "es03" not in excluded
    finally:
        await es.delete(f"/{index}", params={"ignore_unavailable": "true"})


async def test_force_merge_happy_path(es: ESClient):
    index = f"it-merge-{uuid.uuid4().hex[:8]}"
    await _create_index(es, index, shards=1, replicas=0, docs=500)
    try:
        # Delete a slice and flush so there are deleted docs / multiple segments to merge away.
        await es.post(
            f"/{index}/_delete_by_query",
            params={"refresh": "true"},
            json={"query": {"range": {"id": {"lt": 100}}}},
        )
        await es.post(f"/{index}/_flush")

        job = SimpleNamespace(index_name=index)
        await executor.execute_force_merge(es, job)

        segs = await es.cat_shards_detailed()
        merged = next(s for s in segs if s["index"] == index and s["prirep"] == "p")
        assert int(merged["segments.count"]) <= 1
    finally:
        await es.delete(f"/{index}", params={"ignore_unavailable": "true"})


async def test_reduce_shards_happy_path(es: ESClient):
    source = f"it-shrink-{uuid.uuid4().hex[:8]}"
    target = f"{source}-shrink-2"
    await _create_index(es, source, shards=4, replicas=0, docs=400)
    try:
        await _wait_cluster_green(es)
        job = SimpleNamespace(
            index_name=source,
            current_shards=4,
            target_shards=2,
            current_replicas=0,
            detail="",
            task_id=None,
        )
        await executor.execute_reduce_shards(es, job, delay=2.0)

        assert job.task_id == target
        target_health = await es.index_health(target)
        assert target_health["status"] == "green"
        target_settings = await es.get(f"/{target}/_settings")
        n_shards = target_settings[target]["settings"]["index"]["number_of_shards"]
        assert int(n_shards) == 2
        # Source index is left intact (non-destructive shrink).
        assert (await es.index_health(source))["status"] == "green"
    finally:
        await es.delete(f"/{source}", params={"ignore_unavailable": "true"})
        await es.delete(f"/{target}", params={"ignore_unavailable": "true"})
