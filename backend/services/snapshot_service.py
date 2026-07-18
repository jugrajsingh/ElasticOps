"""Pure precompute functions that turn parsed ES data into ready-to-serve snapshot payloads.

Every ``build_*`` function is pure: it takes parsed dicts (the ``.model_dump()`` shape of the
``routes.es`` parsers) and returns JSON-serializable structures. No IO, no ES, no DB. ``refresh_cluster``
is the only IO entry point: it fetches raw ES once, parses + normalizes, fans out to the build_*
functions, and upserts each snapshot kind.

Reuses the existing parsers (``routes.es``), ``IndexAnalyzer`` and ``_build_storage_breakdown`` —
analysis logic is never duplicated here.
"""

from collections.abc import Callable
from time import perf_counter

from backend.routes.es import (
    _build_storage_breakdown,
    _parse_index,
    _parse_node,
    _parse_recovery,
    _parse_shard,
)
from backend.services.analyzer import IndexAnalyzer
from backend.services.role_logic import is_data_node, node_tier, role_counts


def normalize_shard_node(node: str | None) -> str | None:
    """Normalize a shard's ``node`` value, collapsing relocating-shard strings to the owning node.

    A relocating shard reports its node as e.g. ``"src-node -> 10.0.0.1 abc123 dst-node"``. The
    owning (source) node is the first whitespace-delimited token. Non-relocating values pass through
    unchanged; ``None``/empty stay as-is.
    """
    if not node:
        return node
    if " " in node or "->" in node:
        return node.split()[0]
    return node


def shorten_node_name(name: str) -> str:
    """Last two ``-`` segments of a node name (mirrors the frontend ``shortenNodeName``)."""
    segments = name.split("-")
    if len(segments) <= 2:
        return name
    return "-".join(segments[-2:])


def build_overview(
    health: dict,
    nodes: list[dict],
    indices: list[dict],
    recoveries: list[dict],
    raw_indices: list[dict] | None = None,
) -> dict:
    """Overview payload: health, index count, nodes, recoveries, storage breakdown, role counts.

    Same shape ``OverviewResponse`` produces today, but ``node_role_counts`` is tier-aware.

    ``raw_indices`` must be the raw ``_cat`` dicts (with ``"index"`` and ``"store.size"`` keys) so
    that ``_build_storage_breakdown`` can read the correct key. When omitted (e.g. in tests that
    don't care about the breakdown) the breakdown will be empty.
    """
    return {
        "health": health,
        "index_count": len(indices),
        "nodes": nodes,
        "recoveries": recoveries,
        "storage_breakdown": [g.model_dump() for g in _build_storage_breakdown(raw_indices or [])],
        "node_role_counts": role_counts(nodes),
    }


def build_nodes(nodes: list[dict], shards: list[dict]) -> list[dict]:
    """Each node plus a precomputed ``shard_count`` (normalized owning node) and ``tier`` label."""
    counts: dict[str, int] = {}
    for shard in shards:
        owner = normalize_shard_node(shard.get("node"))
        if owner:
            counts[owner] = counts.get(owner, 0) + 1
    return [{**node, "shard_count": counts.get(node["name"], 0), "tier": node_tier(node["role"])} for node in nodes]


def build_indices(indices: list[dict], shards: list[dict]) -> dict:
    """Full ``AnalysisData`` payload (totals + analyzed indices), analyzer run once here."""
    results = IndexAnalyzer(indices, shards).analyze_all()
    return {
        "total_indices": len(results),
        "total_with_opportunities": sum(1 for r in results if r["opportunities"]),
        "total_wasted_shards": sum(r["wasted_shards"] for r in results),
        "indices": results,
    }


def build_shards(shards: list[dict]) -> list[dict]:
    """Normalized raw shard rows for detail panels (relocating node values collapsed to owner)."""
    return [{**shard, "node": normalize_shard_node(shard.get("node"))} for shard in shards]


def build_shardmap(nodes: list[dict], indices: list[dict], shards: list[dict]) -> dict:
    """Precomputed Grid payload: data-node columns, non-system index rows, and per-cell chips.

    ``cells`` is keyed ``"<index> <node>"`` (space separator) so the frontend reads ``cells[key]``
    in O(1). Only data nodes appear as columns (coordinators excluded); columns sorted by name,
    rows sorted by ``pri_store_size`` desc. System indices (``.``-prefixed) dropped.
    """
    data_node_names = {n["name"] for n in nodes if is_data_node(n["role"])}
    data_nodes = sorted(
        (
            {
                "name": n["name"],
                "short": shorten_node_name(n["name"]),
                "tier": node_tier(n["role"]),
                "disk_used_percent": n.get("disk_used_percent", 0.0),
            }
            for n in nodes
            if n["name"] in data_node_names
        ),
        key=lambda n: n["name"],
    )

    grid_indices = sorted(
        (
            {"index": i["index"], "pri_store_size": i["pri_store_size"], "health": i["health"]}
            for i in indices
            if not i["index"].startswith(".")
        ),
        key=lambda i: i["pri_store_size"],
        reverse=True,
    )
    valid_index_names = {i["index"] for i in grid_indices}

    cells: dict[str, list[dict]] = {}
    for shard in shards:
        index = shard.get("index", "")
        owner = normalize_shard_node(shard.get("node"))
        if index not in valid_index_names or owner not in data_node_names:
            continue
        cells.setdefault(f"{index} {owner}", []).append(
            {
                "shard": shard.get("shard", 0),
                "prirep": shard.get("prirep", ""),
                "state": shard.get("state", ""),
                "store": shard.get("store", 0),
                "docs": shard.get("docs", 0),
                "segments_count": shard.get("segments_count", 0),
            }
        )

    return {"data_nodes": data_nodes, "indices": grid_indices, "cells": cells}


def build_pivot(
    indices: list[dict],
    shards: list[dict],
    nodes: list[dict],
    sep: str = "_",
) -> dict:
    """Dynamic-depth rollup tree of index names split on ``sep``.

    For index ``a_b_c_2024`` (sep ``_``) the path is ``a`` -> ``a_b`` -> ``a_b_c`` -> ``a_b_c_2024``
    (leaf). A name with no separator is its own leaf. At every node on a path the index's shards
    (count + size) are accumulated, including a per-data-node breakdown. System indices excluded.
    Children sorted by ``total_size`` desc; ``max_cell_size`` is the max leaf per-node size.
    """
    data_node_names = {n["name"] for n in nodes if is_data_node(n["role"])}
    data_nodes = sorted(
        (
            {
                "name": n["name"],
                "short": shorten_node_name(n["name"]),
                "disk_used_percent": n.get("disk_used_percent", 0.0),
            }
            for n in nodes
            if n["name"] in data_node_names
        ),
        key=lambda n: n["name"],
    )

    # Group shards by index once: (count, size) and per-node (count, size).
    shards_by_index: dict[str, dict] = {}
    for shard in shards:
        index = shard.get("index", "")
        if not index:
            continue
        owner = normalize_shard_node(shard.get("node"))
        bucket = shards_by_index.setdefault(index, {"count": 0, "size": 0, "per_node": {}})
        size = shard.get("store", 0)
        bucket["count"] += 1
        bucket["size"] += size
        if owner in data_node_names:
            node_agg = bucket["per_node"].setdefault(owner, {"shard_count": 0, "size": 0})
            node_agg["shard_count"] += 1
            node_agg["size"] += size

    docs_by_index = {i["index"]: i.get("docs_count", 0) for i in indices}

    roots: dict[str, dict] = {}

    def _new_node(key: str, label: str, depth: int) -> dict:
        return {
            "key": key,
            "label": label,
            "depth": depth,
            "total_size": 0,
            "total_docs": 0,
            "shard_count": 0,
            "index_count": 0,
            "_per_node": {},  # owner -> {shard_count, size}; flattened to per_node at the end
            "_children": {},  # label -> node; flattened to children at the end
            "is_leaf": False,
        }

    for index in indices:
        name = index["index"]
        if name.startswith("."):
            continue
        segments = name.split(sep)
        shard_info = shards_by_index.get(name, {"count": 0, "size": 0, "per_node": {}})
        index_size = shard_info["size"]
        index_count = shard_info["count"]
        index_docs = docs_by_index.get(name, 0)

        siblings = roots
        path_key = ""
        for depth, segment in enumerate(segments):
            path_key = segment if depth == 0 else f"{path_key}{sep}{segment}"
            node = siblings.get(segment)
            if node is None:
                node = _new_node(path_key, segment, depth)
                siblings[segment] = node
            node["total_size"] += index_size
            node["total_docs"] += index_docs
            node["shard_count"] += index_count
            node["index_count"] += 1
            for owner, agg in shard_info["per_node"].items():
                node_agg = node["_per_node"].setdefault(owner, {"shard_count": 0, "size": 0})
                node_agg["shard_count"] += agg["shard_count"]
                node_agg["size"] += agg["size"]
            if depth == len(segments) - 1:
                node["is_leaf"] = True
            siblings = node["_children"]

    max_cell_size = 0
    for index_data in shards_by_index.values():
        for agg in index_data["per_node"].values():
            max_cell_size = max(max_cell_size, agg["size"])

    def _finalize(node: dict) -> dict:
        children = sorted(
            (_finalize(child) for child in node["_children"].values()),
            key=lambda c: c["total_size"],
            reverse=True,
        )
        return {
            "key": node["key"],
            "label": node["label"],
            "depth": node["depth"],
            "total_size": node["total_size"],
            "total_docs": node["total_docs"],
            "shard_count": node["shard_count"],
            "index_count": node["index_count"],
            "per_node": [
                {"node": owner, "shard_count": agg["shard_count"], "size": agg["size"]}
                for owner, agg in node["_per_node"].items()
            ],
            "children": children,
            "is_leaf": node["is_leaf"],
        }

    finalized_roots = sorted(
        (_finalize(root) for root in roots.values()),
        key=lambda r: r["total_size"],
        reverse=True,
    )

    return {
        "separator": sep,
        "data_nodes": data_nodes,
        "max_cell_size": max_cell_size,
        "roots": finalized_roots,
    }


async def refresh_cluster(es, cluster_id: int, db, sep: str = "_") -> dict[str, int]:
    """Fetch raw ES once, build every snapshot kind, and upsert each. Returns kind -> item_count.

    Read-only against ES: only ``cluster_health`` and the ``cat_*`` GET endpoints are touched.
    """
    from backend.services import snapshot_repo

    health = await es.cluster_health()
    raw_nodes = await es.cat_nodes_detailed()
    raw_indices = await es.cat_indices_detailed()
    raw_shards = await es.cat_shards_detailed()
    raw_recoveries = await es.cat_recovery_active()

    nodes = [_parse_node(n).model_dump() for n in raw_nodes]
    indices = [_parse_index(i).model_dump() for i in raw_indices]
    shards = [_parse_shard(s).model_dump() for s in raw_shards]
    recoveries = [_parse_recovery(r).model_dump() for r in raw_recoveries]

    # (builder, item_count) per kind. item_count reflects the dominant entity each payload represents:
    # nodes for overview/nodes, indices for indices, shards for shardmap/pivot/shards, 1 for health.
    builders: list[tuple[str, Callable[[], dict | list], int]] = [
        ("health", lambda: health, 1),
        ("overview", lambda: build_overview(health, nodes, indices, recoveries, raw_indices), len(nodes)),
        ("nodes", lambda: build_nodes(nodes, shards), len(nodes)),
        ("indices", lambda: build_indices(indices, shards), len(indices)),
        ("shardmap", lambda: build_shardmap(nodes, indices, shards), len(shards)),
        ("pivot", lambda: build_pivot(indices, shards, nodes, sep=sep), len(shards)),
        ("shards", lambda: build_shards(shards), len(shards)),
    ]

    item_counts: dict[str, int] = {}
    for kind, builder, item_count in builders:
        start = perf_counter()
        payload = builder()
        duration_ms = int((perf_counter() - start) * 1000)
        await snapshot_repo.upsert_snapshot(db, cluster_id, kind, payload, item_count, duration_ms)
        item_counts[kind] = item_count

    return item_counts
