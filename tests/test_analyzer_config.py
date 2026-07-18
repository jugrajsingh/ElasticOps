import os

import pytest

from config.settings import get_settings


def _make_index(name: str, pri: int, store_bytes: int, pri_store_bytes: int) -> dict:
    return {
        "health": "green",
        "status": "open",
        "index": name,
        "pri": pri,
        "rep": 0,
        "docs_count": 1_000_000,
        "store_size": store_bytes,
        "pri_store_size": pri_store_bytes,
    }


def _make_shards(name: str, pri: int, store_bytes: int) -> list[dict]:
    return [
        {
            "index": name,
            "shard": i,
            "prirep": "p",
            "state": "STARTED",
            "docs": 1_000_000 // max(pri, 1),
            "store": store_bytes // max(pri, 1),
            "node": f"node-{i}",
            "segments_count": 5,
        }
        for i in range(pri)
    ]


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Clear the lru_cache before and after each test to ensure env overrides are picked up."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_should_flag_under_sharded_when_max_gb_threshold_lowered():
    """Lowering ideal_shard_max_gb to near-zero should flag a 1-shard 500MB index as under-sharded."""
    os.environ["ANALYZER__IDEAL_SHARD_MAX_GB"] = "0.001"
    try:
        from backend.services.analyzer import IndexAnalyzer

        # 500 MB single-shard index — well within the normal 50 GB threshold but
        # far above the test override of 0.001 GB (1 MB).
        store = 500_000_000
        indices = [_make_index("test_idx", 1, store, store)]
        shards = _make_shards("test_idx", 1, store)

        analyzer = IndexAnalyzer(indices, shards)
        results = analyzer.analyze_all()

        assert len(results) == 1
        opps = results[0]["opportunities"]
        assert any(o["type"] == "under-sharded" for o in opps), (
            f"Expected under-sharded opportunity with ANALYZER__IDEAL_SHARD_MAX_GB=0.001; got: {opps}"
        )
    finally:
        os.environ.pop("ANALYZER__IDEAL_SHARD_MAX_GB", None)
        get_settings.cache_clear()


def _has_tiny_over_sharded(opps: list[dict]) -> bool:
    """True if the over-sharded *tiny* branch fired (its detail reads ``should be 1``).

    The secondary over-sharded branch (small-average shards) emits a ``could reduce`` detail, so
    matching on ``should be 1`` isolates the configurable tiny-index branch under test.
    """
    return any(o["type"] == "over-sharded" and "should be 1" in o["detail"] for o in opps)


def test_should_not_flag_over_sharded_tiny_when_threshold_lowered():
    """Lowering tiny_index_max_gb below a small index's size stops the over-sharded-tiny flag.

    A 0.5 GB / 3-shard index IS flagged over-sharded-tiny at the default 1 GB threshold; dropping
    ``ANALYZER__TINY_INDEX_MAX_GB`` to 0.1 GB (below 0.5 GB) suppresses that branch, so a freshly
    split demo index doesn't immediately flip to over-sharded-tiny.
    """
    store = 500_000_000  # 0.5 GB primary store across 3 shards

    # Sanity: at the default 1 GB threshold the tiny-index branch IS flagged.
    from backend.services.analyzer import IndexAnalyzer

    default_results = IndexAnalyzer(
        [_make_index("tiny_idx", 3, store, store)], _make_shards("tiny_idx", 3, store)
    ).analyze_all()
    assert _has_tiny_over_sharded(default_results[0]["opportunities"])

    get_settings.cache_clear()
    os.environ["ANALYZER__TINY_INDEX_MAX_GB"] = "0.1"
    try:
        from backend.services.analyzer import IndexAnalyzer

        results = IndexAnalyzer(
            [_make_index("tiny_idx", 3, store, store)], _make_shards("tiny_idx", 3, store)
        ).analyze_all()

        assert len(results) == 1
        assert not _has_tiny_over_sharded(results[0]["opportunities"]), (
            f"Expected NO over-sharded-tiny flag with ANALYZER__TINY_INDEX_MAX_GB=0.1; "
            f"got: {results[0]['opportunities']}"
        )
    finally:
        os.environ.pop("ANALYZER__TINY_INDEX_MAX_GB", None)
        get_settings.cache_clear()


def test_should_not_flag_healthy_index_at_default_thresholds():
    """At default thresholds a 50 GB / 2-shard index (~25 GB/shard) should have no opportunities."""
    from backend.services.analyzer import IndexAnalyzer

    store = 50_000_000_000
    indices = [_make_index("healthy_idx", 2, store, store)]
    shards = _make_shards("healthy_idx", 2, store)

    analyzer = IndexAnalyzer(indices, shards)
    results = analyzer.analyze_all()

    assert len(results) == 1
    assert results[0]["opportunities"] == []
