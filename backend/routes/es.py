from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import require_cluster_access
from backend.database import get_db
from backend.dependencies import get_es_client, require_writable_cluster
from backend.schemas.analysis import AnalysisResponse
from backend.schemas.es import (
    CachedResponse,
    ClusterHealthResponse,
    IndexInfo,
    NodeInfo,
    NodeInfoEx,
    OverviewResponse,
    RecoveryInfo,
    ShardInfo,
    StorageGroup,
)
from backend.services import snapshot_repo
from backend.services.es_client import ESClient
from config.settings import PollingSettings, get_settings

router = APIRouter(
    prefix="/api/clusters/{cluster_id}/es",
    tags=["elasticsearch"],
    dependencies=[Depends(require_cluster_access)],
)

# Which polling cadence governs each snapshot kind, so reads can report a truthful ``next_poll_in``.
# The poller has exactly two ticks: the light tick refreshes ONLY ``health`` (``health_seconds``);
# every other kind (overview, nodes, indices, shards, shardmap, pivot) is rebuilt on the heavy tick
# (``heavy_seconds``), since they all depend on the heavy ``_cat/shards`` + ``_cat/nodes`` fetch.
_LIGHT_KINDS = frozenset({"health"})


def _safe_int(val, default: int = 0) -> int:
    if val is None or val == "":
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _safe_float(val, default: float = 0.0) -> float:
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _parse_node(raw: dict) -> NodeInfo:
    role = raw.get("node.role", "")
    if not role or role == "-":
        role = "coord"
    return NodeInfo(
        name=raw.get("name", ""),
        role=role,
        ip=raw.get("ip", ""),
        version=raw.get("version", ""),
        disk_total=_safe_int(raw.get("disk.total")),
        disk_used=_safe_int(raw.get("disk.used")),
        disk_used_percent=_safe_float(raw.get("disk.used_percent")),
        heap_max=_safe_int(raw.get("heap.max")),
        heap_current=_safe_int(raw.get("heap.current")),
        heap_percent=_safe_float(raw.get("heap.percent")),
        cpu=_safe_float(raw.get("cpu")),
        load_1m=_safe_float(raw.get("load_1m")),
        segments_count=_safe_int(raw.get("segments.count")),
    )


def _parse_index(raw: dict) -> IndexInfo:
    return IndexInfo(
        health=raw.get("health", ""),
        status=raw.get("status", ""),
        index=raw.get("index", ""),
        pri=_safe_int(raw.get("pri")),
        rep=_safe_int(raw.get("rep")),
        docs_count=_safe_int(raw.get("docs.count")),
        docs_deleted=_safe_int(raw.get("docs.deleted")),
        store_size=_safe_int(raw.get("store.size")),
        pri_store_size=_safe_int(raw.get("pri.store.size")),
    )


def _parse_shard(raw: dict) -> ShardInfo:
    return ShardInfo(
        index=raw.get("index", ""),
        shard=_safe_int(raw.get("shard")),
        prirep=raw.get("prirep", ""),
        state=raw.get("state", ""),
        docs=_safe_int(raw.get("docs")),
        store=_safe_int(raw.get("store")),
        node=raw.get("node"),
        segments_count=_safe_int(raw.get("segments.count")),
    )


def _parse_recovery(raw: dict) -> RecoveryInfo:
    return RecoveryInfo(
        index=raw.get("index", ""),
        shard=_safe_int(raw.get("shard")),
        source_node=raw.get("source_node", ""),
        target_node=raw.get("target_node", ""),
        bytes_total=_safe_int(raw.get("bytes_total")),
        bytes_recovered=_safe_int(raw.get("bytes_recovered")),
        bytes_percent=raw.get("bytes_percent", "0%"),
    )


def _build_storage_breakdown(raw_indices: list[dict], max_groups: int = 10) -> list[StorageGroup]:
    groups: dict[str, int] = {}
    for raw in raw_indices:
        name = raw.get("index", "")
        prefix = name.split("-")[0].split("_")[0] if name else "unknown"
        prefix = prefix.lstrip(".")
        if not prefix:
            prefix = "unknown"
        groups[prefix] = groups.get(prefix, 0) + _safe_int(raw.get("store.size"))
    sorted_groups = sorted(groups.items(), key=lambda x: x[1], reverse=True)
    top = sorted_groups[:max_groups]
    rest_bytes = sum(v for _, v in sorted_groups[max_groups:])
    result = [StorageGroup(name=name, size_bytes=size) for name, size in top]
    if rest_bytes > 0:
        result.append(StorageGroup(name="other", size_bytes=rest_bytes))
    return result


def _now() -> datetime:
    """Naive UTC ``now`` matching the naive ``fetched_at`` the snapshot repo stores."""
    return datetime.now(UTC).replace(tzinfo=None)


def _poll_interval(kind: str, polling: PollingSettings) -> int:
    """Seconds the poller waits between refreshes of ``kind`` (drives ``next_poll_in``)."""
    if kind in _LIGHT_KINDS:
        return polling.health_seconds
    return polling.heavy_seconds


async def _serve(
    db: AsyncSession,
    cluster_id: int,
    kind: str,
    build_live: Callable[[], Awaitable[Any]],
) -> CachedResponse:
    """Snapshot-first read with live fallback, wrapped in :class:`CachedResponse`.

    If a snapshot row exists for ``(cluster_id, kind)``, serve it with a computed staleness. If not
    (the poller hasn't run yet, or polling is disabled), run ``build_live`` to compute today's live
    payload, best-effort upsert it so the next read is cached, and return it with ``stale_seconds==0``.
    Never returns empty when the cluster is reachable.
    """
    polling = get_settings().polling
    interval = _poll_interval(kind, polling)

    snapshot = await snapshot_repo.get_latest(db, cluster_id, kind)
    if snapshot is not None:
        stale_seconds = max(0, int((_now() - snapshot.fetched_at).total_seconds()))
        return CachedResponse(
            data=snapshot.payload,
            fetched_at=snapshot.fetched_at,
            stale_seconds=stale_seconds,
            next_poll_in=max(0, interval - stale_seconds),
        )

    payload = await build_live()
    item_count = len(payload) if isinstance(payload, list) else payload.get("index_count", 0)
    fetched = await snapshot_repo.upsert_snapshot(db, cluster_id, kind, payload, item_count, 0)
    return CachedResponse(
        data=payload,
        fetched_at=fetched.fetched_at,
        stale_seconds=0,
        next_poll_in=interval,
    )


# --- Live builders (the fallback path; reuse the same pure builders the poller uses) -------------
#
# ``snapshot_service`` imports the parsers from this module, so it is imported lazily here to avoid a
# circular import at module load. It is fully initialized by the time any request runs these.


async def _live_health(es: ESClient) -> dict:
    return await es.cluster_health()


async def _live_overview(es: ESClient) -> dict:
    from backend.services import snapshot_service

    health = await es.cluster_health()
    raw_nodes = await es.cat_nodes_detailed()
    raw_indices = await es.cat_indices_detailed()
    raw_recoveries = await es.cat_recovery_active()
    nodes = [_parse_node(n).model_dump() for n in raw_nodes]
    indices = [_parse_index(i).model_dump() for i in raw_indices]
    recoveries = [_parse_recovery(r).model_dump() for r in raw_recoveries]
    return snapshot_service.build_overview(health, nodes, indices, recoveries, raw_indices)


async def _live_nodes(es: ESClient) -> list[dict]:
    from backend.services import snapshot_service

    raw_nodes = await es.cat_nodes_detailed()
    raw_shards = await es.cat_shards_detailed()
    nodes = [_parse_node(n).model_dump() for n in raw_nodes]
    shards = [_parse_shard(s).model_dump() for s in raw_shards]
    return snapshot_service.build_nodes(nodes, shards)


async def _live_indices(es: ESClient) -> dict:
    from backend.services import snapshot_service

    raw_indices = await es.cat_indices_detailed()
    raw_shards = await es.cat_shards_detailed()
    indices = [_parse_index(i).model_dump() for i in raw_indices]
    shards = [_parse_shard(s).model_dump() for s in raw_shards]
    return snapshot_service.build_indices(indices, shards)


async def _live_shards(es: ESClient) -> list[dict]:
    from backend.services import snapshot_service

    raw_shards = await es.cat_shards_detailed()
    shards = [_parse_shard(s).model_dump() for s in raw_shards]
    return snapshot_service.build_shards(shards)


async def _live_shardmap(es: ESClient) -> dict:
    from backend.services import snapshot_service

    raw_nodes = await es.cat_nodes_detailed()
    raw_indices = await es.cat_indices_detailed()
    raw_shards = await es.cat_shards_detailed()
    nodes = [_parse_node(n).model_dump() for n in raw_nodes]
    indices = [_parse_index(i).model_dump() for i in raw_indices]
    shards = [_parse_shard(s).model_dump() for s in raw_shards]
    return snapshot_service.build_shardmap(nodes, indices, shards)


async def _live_pivot(es: ESClient) -> dict:
    from backend.services import snapshot_service
    from config.settings import get_settings

    raw_nodes = await es.cat_nodes_detailed()
    raw_indices = await es.cat_indices_detailed()
    raw_shards = await es.cat_shards_detailed()
    nodes = [_parse_node(n).model_dump() for n in raw_nodes]
    indices = [_parse_index(i).model_dump() for i in raw_indices]
    shards = [_parse_shard(s).model_dump() for s in raw_shards]
    return snapshot_service.build_pivot(indices, shards, nodes, sep=get_settings().polling.pivot_separator)


# --- Read endpoints (snapshot-first, live fallback) ---------------------------------------------


@router.get("/health", response_model=CachedResponse[ClusterHealthResponse])
async def cluster_health(
    cluster_id: int,
    db: AsyncSession = Depends(get_db),
    es: ESClient = Depends(get_es_client),
):
    return await _serve(db, cluster_id, "health", lambda: _live_health(es))


@router.get("/nodes", response_model=CachedResponse[list[NodeInfoEx]])
async def list_nodes(
    cluster_id: int,
    db: AsyncSession = Depends(get_db),
    es: ESClient = Depends(get_es_client),
):
    return await _serve(db, cluster_id, "nodes", lambda: _live_nodes(es))


@router.get("/indices", response_model=CachedResponse[AnalysisResponse])
async def list_indices(
    cluster_id: int,
    problems_only: bool = False,
    db: AsyncSession = Depends(get_db),
    es: ESClient = Depends(get_es_client),
):
    served = await _serve(db, cluster_id, "indices", lambda: _live_indices(es))
    return _apply_problems_only(served, problems_only)


@router.get("/shards", response_model=CachedResponse[list[ShardInfo]])
async def list_shards(
    cluster_id: int,
    db: AsyncSession = Depends(get_db),
    es: ESClient = Depends(get_es_client),
):
    return await _serve(db, cluster_id, "shards", lambda: _live_shards(es))


@router.get("/overview", response_model=CachedResponse[OverviewResponse])
async def overview(
    cluster_id: int,
    db: AsyncSession = Depends(get_db),
    es: ESClient = Depends(get_es_client),
):
    return await _serve(db, cluster_id, "overview", lambda: _live_overview(es))


@router.get("/shard-map", response_model=CachedResponse[dict])
async def shard_map(
    cluster_id: int,
    db: AsyncSession = Depends(get_db),
    es: ESClient = Depends(get_es_client),
):
    return await _serve(db, cluster_id, "shardmap", lambda: _live_shardmap(es))


@router.get("/pivot", response_model=CachedResponse[dict])
async def pivot(
    cluster_id: int,
    db: AsyncSession = Depends(get_db),
    es: ESClient = Depends(get_es_client),
):
    return await _serve(db, cluster_id, "pivot", lambda: _live_pivot(es))


def _apply_problems_only(served: CachedResponse, problems_only: bool) -> CachedResponse:
    """Filter the served ``indices`` payload to opportunity-bearing indices, server-side.

    The poller stores the full analyzed list once; ``problems_only`` is a trivial read-time filter so
    no second payload is stored. Recomputes the totals over the filtered list to stay consistent.
    """
    if not problems_only:
        return served
    payload = served.data
    filtered = [i for i in payload["indices"] if i["opportunity_count"] > 0]
    served.data = {
        "total_indices": len(filtered),
        "total_with_opportunities": len(filtered),
        "total_wasted_shards": sum(i["wasted_shards"] for i in filtered),
        "indices": filtered,
    }
    return served


@router.get("/analyze", response_model=CachedResponse[AnalysisResponse])
async def analyze_indices(
    cluster_id: int,
    problems_only: bool = False,
    db: AsyncSession = Depends(get_db),
    es: ESClient = Depends(get_es_client),
):
    served = await _serve(db, cluster_id, "indices", lambda: _live_indices(es))
    return _apply_problems_only(served, problems_only)


@router.post("/refresh")
async def refresh(
    cluster_id: int,
    kind: str | None = None,
    db: AsyncSession = Depends(get_db),
    es: ESClient = Depends(get_es_client),
):
    """Force a snapshot refresh on demand. Read-only against ES.

    Runs the full :func:`refresh_cluster` (fetches raw ES once and rebuilds every kind), then reports
    the fresh ``fetched_at`` for the requested ``kind`` (or ``health`` when none is given). ``kind`` is
    a hint for which snapshot's timestamp to return; the underlying refresh always rebuilds all kinds
    from the single raw fetch (so a one-off refresh never costs extra ES round-trips).
    """
    from backend.services import snapshot_service

    await snapshot_service.refresh_cluster(es, cluster_id, db, sep=get_settings().polling.pivot_separator)

    snapshot = await snapshot_repo.get_latest(db, cluster_id, kind or "health")
    return {
        "cluster_id": cluster_id,
        "kind": kind,
        "fetched_at": snapshot.fetched_at if snapshot is not None else None,
    }


@router.get("/rebalance-suggestions")
async def rebalance_suggestions(
    cluster_id: int,  # noqa: ARG001 — required path param for router prefix resolution
    es: ESClient = Depends(get_es_client),
):
    """Advisory: suggest relocate moves to even shard count across data nodes. Read-only against ES."""
    from backend.services import rebalance

    nodes = await es.cat_nodes_detailed()
    shards = await es.cat_shards_detailed()
    return {"suggestions": rebalance.suggest_moves(nodes, shards)}


@router.get("/settings")
async def get_settings_endpoint(es: ESClient = Depends(get_es_client)):
    return await es.cluster_settings_full()


class SettingsUpdateRequest(BaseModel):
    persistent: dict | None = None
    transient: dict | None = None


@router.put("/settings")
async def update_settings(
    cluster_id: int,
    body: SettingsUpdateRequest,
    db: AsyncSession = Depends(get_db),
    es: ESClient = Depends(get_es_client),
):
    """Update cluster settings. Blocked on read-only clusters (this is a cluster write)."""
    await require_writable_cluster(cluster_id, db)
    payload: dict = {}
    if body.persistent is not None:
        payload["persistent"] = body.persistent
    if body.transient is not None:
        payload["transient"] = body.transient
    return await es.put_cluster_settings(payload)


class RestRequest(BaseModel):
    method: str
    path: str
    body: dict | None = None


# REST-console verbs that only read; everything else is treated as a write on a read-only cluster.
_REST_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@router.post("/rest")
async def rest_proxy(
    cluster_id: int,
    req: RestRequest,
    db: AsyncSession = Depends(get_db),
    es: ESClient = Depends(get_es_client),
):
    """Proxy an arbitrary ES request. On read-only clusters, only read verbs (GET/HEAD) are allowed.

    The FastAPI request method is always POST here; the verb that matters is ``req.method`` — the ES
    verb carried in the request body. Block any non-read verb on a read-only cluster.
    """
    if req.method.upper() not in _REST_READ_METHODS:
        await require_writable_cluster(cluster_id, db)
    return await es.proxy(req.method, req.path, req.body)
