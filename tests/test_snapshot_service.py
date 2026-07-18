from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.database import Base
from backend.models.cluster import Cluster
from backend.services import snapshot_repo
from backend.services.snapshot_service import (
    build_indices,
    build_nodes,
    build_overview,
    build_pivot,
    build_shardmap,
    build_shards,
    normalize_shard_node,
    refresh_cluster,
)

GB = 1024**3


def _node(name: str, role: str, disk: float = 50.0) -> dict:
    return {
        "name": name,
        "role": role,
        "ip": "10.0.0.1",
        "version": "8.0.0",
        "disk_total": 100 * GB,
        "disk_used": 50 * GB,
        "disk_used_percent": disk,
        "heap_max": 0,
        "heap_current": 0,
        "heap_percent": 0.0,
        "cpu": 0.0,
        "load_1m": 0.0,
        "segments_count": 0,
    }


def _raw_index(name: str, store_size: int = 5 * GB) -> dict:
    """Raw ``_cat`` index dict with keys matching what ES returns (used by ``_build_storage_breakdown``)."""
    return {
        "index": name,
        "health": "green",
        "status": "open",
        "pri": "1",
        "rep": "0",
        "docs.count": "1000",
        "store.size": str(store_size),
        "pri.store.size": str(store_size),
    }


def _index(name: str, pri: int = 1, pri_store: int = 5 * GB) -> dict:
    return {
        "health": "green",
        "status": "open",
        "index": name,
        "pri": pri,
        "rep": 0,
        "docs_count": 1000,
        "store_size": pri_store,
        "pri_store_size": pri_store,
    }


def _shard(index: str, node: str | None, shard: int = 0, store: int = 5 * GB, prirep: str = "p") -> dict:
    return {
        "index": index,
        "shard": shard,
        "prirep": prirep,
        "state": "STARTED",
        "docs": 1000,
        "store": store,
        "node": node,
        "segments_count": 1,
    }


# Three data-hot nodes + three coordinators (mirrors the masked cluster shape).
NODES = [_node(f"prefix-data-hot-{i}", "his") for i in range(3)] + [
    _node(f"prefix-coordinators-{i}", "coord") for i in range(3)
]

INDICES = [
    _index("cit_products_8"),
    _index("cit_products_68"),
    _index("cit_rank_trails_41_2024"),
    _index("daas_surface_crawl_511_2026_01"),
    _index(".system_index"),  # excluded everywhere
]

SHARDS = [
    _shard("cit_products_8", "prefix-data-hot-0", store=5 * GB),
    _shard("cit_products_68", "prefix-data-hot-0", store=3 * GB),
    _shard("cit_products_68", "prefix-data-hot-1", store=2 * GB, shard=1),
    _shard("cit_rank_trails_41_2024", "prefix-data-hot-2", store=8 * GB),
    _shard("daas_surface_crawl_511_2026_01", "prefix-data-hot-1", store=10 * GB),
    _shard(".system_index", "prefix-data-hot-0", store=1 * GB),
]


class TestNormalizeShardNode:
    def test_should_collapse_relocating_value_to_source_node(self):
        assert normalize_shard_node("src -> ip id dst") == "src"

    def test_should_passthrough_plain_node(self):
        assert normalize_shard_node("prefix-data-hot-0") == "prefix-data-hot-0"

    def test_should_passthrough_none(self):
        assert normalize_shard_node(None) is None


class TestBuildNodes:
    def test_should_compute_shard_count_per_node(self):
        result = {n["name"]: n for n in build_nodes(NODES, SHARDS)}
        # hot-0 carries cit_products_8, cit_products_68, .system_index → 3
        assert result["prefix-data-hot-0"]["shard_count"] == 3
        # hot-1 carries cit_products_68 + daas → 2
        assert result["prefix-data-hot-1"]["shard_count"] == 2
        # hot-2 carries cit_rank_trails → 1
        assert result["prefix-data-hot-2"]["shard_count"] == 1

    def test_should_give_coordinators_zero_shards_and_coord_tier(self):
        result = {n["name"]: n for n in build_nodes(NODES, SHARDS)}
        for i in range(3):
            node = result[f"prefix-coordinators-{i}"]
            assert node["shard_count"] == 0
            assert node["tier"] == "coord"

    def test_should_count_relocating_shard_under_source_node(self):
        nodes = [_node("src", "his"), _node("dst", "his")]
        shards = [_shard("idx", "src -> ip id dst")]
        result = {n["name"]: n for n in build_nodes(nodes, shards)}
        assert result["src"]["shard_count"] == 1
        assert result["dst"]["shard_count"] == 0

    def test_should_label_hot_tier(self):
        result = {n["name"]: n for n in build_nodes(NODES, SHARDS)}
        assert result["prefix-data-hot-0"]["tier"] == "hot"


RAW_INDICES = [
    _raw_index("cit_products_8", store_size=5 * GB),
    _raw_index("cit_products_68", store_size=3 * GB),
    _raw_index("cit_rank_trails_41_2024", store_size=8 * GB),
    _raw_index("daas_surface_crawl_511_2026_01", store_size=10 * GB),
    _raw_index(".system_index", store_size=1 * GB),
]


class TestBuildOverview:
    def test_should_produce_tier_aware_role_counts(self):
        overview = build_overview({"status": "green"}, NODES, INDICES, [], RAW_INDICES)
        assert overview["node_role_counts"] == {
            "master": 0,
            "data": 3,
            "coord": 3,
            "ingest": 0,
            "other": 0,
        }

    def test_should_count_all_indices_including_system(self):
        overview = build_overview({"status": "green"}, NODES, INDICES, [], RAW_INDICES)
        assert overview["index_count"] == len(INDICES)

    def test_should_produce_non_zero_storage_breakdown_from_raw_indices(self):
        """Breakdown must reflect actual sizes from raw ``store.size`` keys, not zero-filled parsed dicts."""
        raw = [
            _raw_index("cit_products_8", store_size=5 * GB),
            _raw_index("cit_products_68", store_size=3 * GB),
        ]
        overview = build_overview({"status": "green"}, NODES, INDICES, [], raw)
        assert any(g["size_bytes"] > 0 for g in overview["storage_breakdown"])

    def test_should_return_empty_breakdown_when_raw_indices_omitted(self):
        """Backward-compat: callers that omit raw_indices get an empty breakdown, not an error."""
        overview = build_overview({"status": "green"}, NODES, INDICES, [])
        assert overview["storage_breakdown"] == []


class TestBuildShardmap:
    def test_should_include_only_data_nodes_as_columns_sorted(self):
        grid = build_shardmap(NODES, INDICES, SHARDS)
        names = [n["name"] for n in grid["data_nodes"]]
        assert names == ["prefix-data-hot-0", "prefix-data-hot-1", "prefix-data-hot-2"]

    def test_should_exclude_system_indices_from_rows_and_cells(self):
        grid = build_shardmap(NODES, INDICES, SHARDS)
        row_names = {i["index"] for i in grid["indices"]}
        assert ".system_index" not in row_names
        assert "cit_products_8 prefix-data-hot-0" in grid["cells"]
        assert all(not key.startswith(".") for key in grid["cells"])

    def test_should_sort_indices_by_pri_store_desc(self):
        grid = build_shardmap(NODES, INDICES, SHARDS)
        sizes = [i["pri_store_size"] for i in grid["indices"]]
        assert sizes == sorted(sizes, reverse=True)

    def test_should_key_cells_correctly(self):
        grid = build_shardmap(NODES, INDICES, SHARDS)
        cell = grid["cells"]["cit_products_68 prefix-data-hot-1"]
        assert len(cell) == 1
        assert cell[0]["shard"] == 1
        assert cell[0]["store"] == 2 * GB

    def test_should_short_name_data_nodes(self):
        grid = build_shardmap(NODES, INDICES, SHARDS)
        assert grid["data_nodes"][0]["short"] == "hot-0"


class TestBuildPivot:
    def test_should_build_variable_depth_tree(self):
        pivot = build_pivot(INDICES, SHARDS, NODES, sep="_")
        roots = {r["key"]: r for r in pivot["roots"]}
        assert set(roots) == {"cit", "daas"}

        # cit branch: products (depth1) splits into two leaves; rank → rank_trails → ... depth varies
        cit = roots["cit"]
        cit_children = {c["label"]: c for c in cit["children"]}
        assert set(cit_children) == {"products", "rank"}

        # 2-segment index "cit_products_8": path cit -> cit_products -> cit_products_8 (leaf, depth 2)
        products = cit_children["products"]
        product_leaves = {c["key"]: c for c in products["children"]}
        assert "cit_products_8" in product_leaves
        assert "cit_products_68" in product_leaves
        assert product_leaves["cit_products_8"]["is_leaf"] is True
        assert product_leaves["cit_products_8"]["depth"] == 2

        # 4-segment index "cit_rank_trails_41_2024" → 5 levels deep under cit
        leaf = cit_children["rank"]
        depth_count = 1  # "rank" itself is depth 1
        while leaf["children"]:
            leaf = leaf["children"][0]
            depth_count += 1
        assert leaf["is_leaf"] is True
        assert leaf["key"] == "cit_rank_trails_41_2024"
        # segments: cit, rank, trails, 41, 2024 → leaf depth 4
        assert leaf["depth"] == 4

    def test_should_sum_shard_counts_and_sizes_up_the_tree(self):
        pivot = build_pivot(INDICES, SHARDS, NODES, sep="_")
        roots = {r["key"]: r for r in pivot["roots"]}
        products = next(c for c in roots["cit"]["children"] if c["label"] == "products")
        # cit_products_8 (1 shard 5GB) + cit_products_68 (2 shards 5GB) = 3 shards, 10GB
        assert products["shard_count"] == 3
        assert products["total_size"] == 10 * GB
        assert products["index_count"] == 2

    def test_should_aggregate_per_node_at_each_level(self):
        pivot = build_pivot(INDICES, SHARDS, NODES, sep="_")
        roots = {r["key"]: r for r in pivot["roots"]}
        products = next(c for c in roots["cit"]["children"] if c["label"] == "products")
        per_node = {a["node"]: a for a in products["per_node"]}
        # hot-0: cit_products_8 (5GB) + cit_products_68 shard0 (3GB) = 8GB, 2 shards
        assert per_node["prefix-data-hot-0"]["shard_count"] == 2
        assert per_node["prefix-data-hot-0"]["size"] == 8 * GB
        # hot-1: cit_products_68 shard1 (2GB), 1 shard
        assert per_node["prefix-data-hot-1"]["shard_count"] == 1
        assert per_node["prefix-data-hot-1"]["size"] == 2 * GB

    def test_should_treat_single_segment_index_as_its_own_leaf(self):
        indices = [_index("monolith")]
        shards = [_shard("monolith", "prefix-data-hot-0")]
        pivot = build_pivot(indices, shards, NODES, sep="_")
        assert len(pivot["roots"]) == 1
        root = pivot["roots"][0]
        assert root["key"] == "monolith"
        assert root["depth"] == 0
        assert root["is_leaf"] is True
        assert root["children"] == []

    def test_should_exclude_system_indices(self):
        pivot = build_pivot(INDICES, SHARDS, NODES, sep="_")
        assert all(not r["key"].startswith(".") for r in pivot["roots"])

    def test_should_compute_max_cell_size(self):
        pivot = build_pivot(INDICES, SHARDS, NODES, sep="_")
        # largest single-(index,node) is daas at hot-1 = 10GB (system index 1GB excluded by node? no —
        # max_cell_size is over data-node per-index aggregates; daas 10GB is the max).
        assert pivot["max_cell_size"] == 10 * GB

    def test_should_sort_roots_by_total_size_desc(self):
        pivot = build_pivot(INDICES, SHARDS, NODES, sep="_")
        sizes = [r["total_size"] for r in pivot["roots"]]
        assert sizes == sorted(sizes, reverse=True)

    def test_should_use_configurable_separator(self):
        indices = [_index("a-b-c")]
        shards = [_shard("a-b-c", "prefix-data-hot-0")]
        pivot = build_pivot(indices, shards, NODES, sep="-")
        assert pivot["separator"] == "-"
        root = pivot["roots"][0]
        assert root["key"] == "a"
        assert root["children"][0]["key"] == "a-b"


class TestBuildIndices:
    def test_should_match_analyzer_output(self):
        from backend.services.analyzer import IndexAnalyzer

        result = build_indices(INDICES, SHARDS)
        direct = IndexAnalyzer(INDICES, SHARDS).analyze_all()
        assert result["total_indices"] == len(direct)
        assert result["indices"] == direct

    def test_should_exclude_system_indices(self):
        result = build_indices(INDICES, SHARDS)
        assert all(not i["name"].startswith(".") for i in result["indices"])


class TestBuildShards:
    def test_should_normalize_relocating_node_values(self):
        shards = [_shard("idx", "src -> ip id dst")]
        result = build_shards(shards)
        assert result[0]["node"] == "src"


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


class TestRefreshCluster:
    async def test_should_upsert_all_kinds(self, db_session):
        cluster = Cluster(name="test", url="https://es.example.com")
        db_session.add(cluster)
        await db_session.commit()
        await db_session.refresh(cluster)

        es = AsyncMock()
        es.cluster_health.return_value = {"status": "green", "cluster_name": "test"}
        es.cat_nodes_detailed.return_value = [
            {"name": n["name"], "node.role": n["role"], "ip": n["ip"], "version": n["version"]} for n in NODES
        ]
        es.cat_indices_detailed.return_value = [
            {
                "index": i["index"],
                "health": i["health"],
                "status": i["status"],
                "pri": str(i["pri"]),
                "rep": str(i["rep"]),
                "docs.count": str(i["docs_count"]),
                "store.size": str(i["store_size"]),
                "pri.store.size": str(i["pri_store_size"]),
            }
            for i in INDICES
        ]
        es.cat_shards_detailed.return_value = [
            {
                "index": s["index"],
                "shard": str(s["shard"]),
                "prirep": s["prirep"],
                "state": s["state"],
                "docs": str(s["docs"]),
                "store": str(s["store"]),
                "node": s["node"],
                "segments.count": str(s["segments_count"]),
            }
            for s in SHARDS
        ]
        es.cat_recovery_active.return_value = []

        counts = await refresh_cluster(es, cluster.id, db_session, sep="_")

        expected_kinds = {"health", "overview", "nodes", "indices", "shardmap", "pivot", "shards"}
        assert set(counts) == expected_kinds
        for kind in expected_kinds:
            snap = await snapshot_repo.get_latest(db_session, cluster.id, kind)
            assert snap is not None, f"missing snapshot for {kind}"
            assert snap.payload is not None

    async def test_should_be_read_only_against_es(self, db_session):
        """refresh_cluster must never call any mutating ES method."""
        cluster = Cluster(name="ro", url="https://es.example.com")
        db_session.add(cluster)
        await db_session.commit()
        await db_session.refresh(cluster)

        es = AsyncMock()
        es.cluster_health.return_value = {"status": "green"}
        es.cat_nodes_detailed.return_value = []
        es.cat_indices_detailed.return_value = []
        es.cat_shards_detailed.return_value = []
        es.cat_recovery_active.return_value = []

        await refresh_cluster(es, cluster.id, db_session)

        es.put.assert_not_called()
        es.post.assert_not_called()
        es.delete.assert_not_called()
        es.put_cluster_settings.assert_not_called()

    async def test_should_upsert_in_place_on_second_refresh(self, db_session):
        cluster = Cluster(name="reupsert", url="https://es.example.com")
        db_session.add(cluster)
        await db_session.commit()
        await db_session.refresh(cluster)

        es = AsyncMock()
        es.cluster_health.return_value = {"status": "green"}
        es.cat_nodes_detailed.return_value = []
        es.cat_indices_detailed.return_value = []
        es.cat_shards_detailed.return_value = []
        es.cat_recovery_active.return_value = []

        await refresh_cluster(es, cluster.id, db_session)
        await refresh_cluster(es, cluster.id, db_session)

        # one row per (cluster, kind) — upsert, not append
        from sqlalchemy import func, select

        from backend.models.snapshot import ClusterSnapshot

        total = await db_session.scalar(
            select(func.count()).select_from(ClusterSnapshot).where(ClusterSnapshot.cluster_id == cluster.id)
        )
        assert total == 7  # 7 kinds
