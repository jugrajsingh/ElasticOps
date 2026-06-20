from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.dependencies import get_es_client
from backend.schemas.analysis import AnalysisResponse
from backend.schemas.es import (
    ClusterHealthResponse,
    IndexInfo,
    NodeInfo,
    NodeRoleCounts,
    OverviewResponse,
    RecoveryInfo,
    ShardInfo,
    ShardMapResponse,
    StorageGroup,
)
from backend.services.analyzer import IndexAnalyzer
from backend.services.es_client import ESClient

router = APIRouter(prefix="/api/clusters/{cluster_id}/es", tags=["elasticsearch"])


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


@router.get("/health", response_model=ClusterHealthResponse)
async def cluster_health(es: ESClient = Depends(get_es_client)):
    return await es.cluster_health()


@router.get("/nodes", response_model=list[NodeInfo])
async def list_nodes(es: ESClient = Depends(get_es_client)):
    raw = await es.cat_nodes_detailed()
    return [_parse_node(n) for n in raw]


@router.get("/indices", response_model=list[IndexInfo])
async def list_indices(es: ESClient = Depends(get_es_client)):
    raw = await es.cat_indices_detailed()
    return [_parse_index(i) for i in raw]


@router.get("/shards", response_model=list[ShardInfo])
async def list_shards(es: ESClient = Depends(get_es_client)):
    raw = await es.cat_shards_detailed()
    return [_parse_shard(s) for s in raw]


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


def _build_role_counts(nodes: list[NodeInfo]) -> NodeRoleCounts:
    counts = NodeRoleCounts()
    for node in nodes:
        role = node.role.lower()
        if role == "coord" or role == "-":
            counts.coord += 1
        elif "m" in role and "d" not in role:
            counts.master += 1
        elif "d" in role:
            counts.data += 1
        elif "i" in role:
            counts.ingest += 1
        else:
            counts.other += 1
    return counts


@router.get("/overview", response_model=OverviewResponse)
async def overview(es: ESClient = Depends(get_es_client)):
    health = await es.cluster_health()
    raw_nodes = await es.cat_nodes_detailed()
    raw_indices = await es.cat_indices_detailed()
    raw_recoveries = await es.cat_recovery_active()
    nodes = [_parse_node(n) for n in raw_nodes]
    return OverviewResponse(
        health=health,
        index_count=len(raw_indices),
        nodes=nodes,
        recoveries=[_parse_recovery(r) for r in raw_recoveries],
        storage_breakdown=_build_storage_breakdown(raw_indices),
        node_role_counts=_build_role_counts(nodes),
    )


@router.get("/shard-map", response_model=ShardMapResponse)
async def shard_map(es: ESClient = Depends(get_es_client)):
    raw_nodes = await es.cat_nodes_detailed()
    raw_indices = await es.cat_indices_detailed()
    raw_shards = await es.cat_shards_detailed()
    return ShardMapResponse(
        nodes=[_parse_node(n) for n in raw_nodes],
        indices=[_parse_index(i) for i in raw_indices],
        shards=[_parse_shard(s) for s in raw_shards],
    )


@router.get("/analyze", response_model=AnalysisResponse)
async def analyze_indices(
    problems_only: bool = False,
    es: ESClient = Depends(get_es_client),
):
    raw_indices = await es.cat_indices_detailed()
    raw_shards = await es.cat_shards_detailed()

    indices = [_parse_index(i).model_dump() for i in raw_indices]
    shards = [_parse_shard(s).model_dump() for s in raw_shards]

    analyzer = IndexAnalyzer(indices, shards)
    results = analyzer.analyze_all(problems_only=problems_only)

    total_wasted = sum(r["wasted_shards"] for r in results)
    with_opps = sum(1 for r in results if r["opportunities"])

    return AnalysisResponse(
        total_indices=len(results),
        total_with_opportunities=with_opps,
        total_wasted_shards=total_wasted,
        indices=results,
    )


@router.get("/settings")
async def get_settings(es: ESClient = Depends(get_es_client)):
    return await es.cluster_settings_full()


class SettingsUpdateRequest(BaseModel):
    persistent: dict | None = None
    transient: dict | None = None


@router.put("/settings")
async def update_settings(body: SettingsUpdateRequest, es: ESClient = Depends(get_es_client)):
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


@router.post("/rest")
async def rest_proxy(req: RestRequest, es: ESClient = Depends(get_es_client)):
    return await es.proxy(req.method, req.path, req.body)
