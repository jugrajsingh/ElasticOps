from backend.services.analyzer import IndexAnalyzer


def test_should_detect_over_sharded_tiny_index():
    """Index <1GB with 5 shards should report over-sharded with wasted shards."""
    indices = [
        {
            "health": "green",
            "status": "open",
            "index": "tiny_idx",
            "pri": 5,
            "rep": 1,
            "docs_count": 1000,
            "store_size": 600_000_000,
            "pri_store_size": 300_000_000,
        }
    ]
    shards = [
        {
            "index": "tiny_idx",
            "shard": i,
            "prirep": "p",
            "state": "STARTED",
            "docs": 200,
            "store": 60_000_000,
            "node": f"node-{i}",
            "segments_count": 3,
        }
        for i in range(5)
    ]
    analyzer = IndexAnalyzer(indices, shards)
    results = analyzer.analyze_all()

    assert len(results) == 1
    r = results[0]
    assert r["pri_count"] == 5
    assert len(r["opportunities"]) >= 1
    opp = next(o for o in r["opportunities"] if o["type"] == "over-sharded")
    assert opp["severity"] == "high"
    assert opp["target_shards"] == 1
    assert opp["wasted_shards"] == 8  # (5-1) * (1+1) = 8


def test_should_detect_segment_fragmentation():
    """Index with >10 segments per shard should report fragmentation."""
    indices = [
        {
            "health": "green",
            "status": "open",
            "index": "fragmented_idx",
            "pri": 1,
            "rep": 0,
            "docs_count": 100000,
            "store_size": 5_000_000_000,
            "pri_store_size": 5_000_000_000,
        }
    ]
    shards = [
        {
            "index": "fragmented_idx",
            "shard": 0,
            "prirep": "p",
            "state": "STARTED",
            "docs": 100000,
            "store": 5_000_000_000,
            "node": "node-1",
            "segments_count": 25,
        }
    ]
    analyzer = IndexAnalyzer(indices, shards)
    results = analyzer.analyze_all()

    assert len(results) == 1
    opps = results[0]["opportunities"]
    assert any(o["type"] == "segment-fragmentation" for o in opps)


def test_should_not_flag_healthy_index():
    """Well-sized index with few segments should have no opportunities."""
    indices = [
        {
            "health": "green",
            "status": "open",
            "index": "healthy_idx",
            "pri": 2,
            "rep": 1,
            "docs_count": 5_000_000,
            "store_size": 60_000_000_000,
            "pri_store_size": 30_000_000_000,
        }
    ]
    shards = [
        {
            "index": "healthy_idx",
            "shard": i,
            "prirep": "p",
            "state": "STARTED",
            "docs": 2_500_000,
            "store": 15_000_000_000,
            "node": f"node-{i}",
            "segments_count": 5,
        }
        for i in range(2)
    ]
    analyzer = IndexAnalyzer(indices, shards)
    results = analyzer.analyze_all()

    assert len(results) == 1
    assert results[0]["opportunities"] == []


def test_should_skip_system_indices():
    """Indices starting with . should be excluded."""
    indices = [
        {
            "health": "green",
            "status": "open",
            "index": ".kibana",
            "pri": 1,
            "rep": 0,
            "docs_count": 10,
            "store_size": 1000,
            "pri_store_size": 1000,
        }
    ]
    shards = [
        {
            "index": ".kibana",
            "shard": 0,
            "prirep": "p",
            "state": "STARTED",
            "docs": 10,
            "store": 1000,
            "node": "node-1",
            "segments_count": 1,
        }
    ]
    analyzer = IndexAnalyzer(indices, shards)
    results = analyzer.analyze_all()
    assert len(results) == 0


def test_should_detect_under_sharded_index():
    """Index with max shard >50GB should report under-sharded."""
    indices = [
        {
            "health": "green",
            "status": "open",
            "index": "big_idx",
            "pri": 1,
            "rep": 0,
            "docs_count": 50_000_000,
            "store_size": 80_000_000_000,
            "pri_store_size": 80_000_000_000,
        }
    ]
    shards = [
        {
            "index": "big_idx",
            "shard": 0,
            "prirep": "p",
            "state": "STARTED",
            "docs": 50_000_000,
            "store": 80_000_000_000,
            "node": "node-1",
            "segments_count": 8,
        }
    ]
    analyzer = IndexAnalyzer(indices, shards)
    results = analyzer.analyze_all()

    assert len(results) == 1
    opps = results[0]["opportunities"]
    assert any(o["type"] == "under-sharded" for o in opps)


def test_should_filter_problems_only():
    """problems_only=True should exclude indices with no opportunities."""
    indices = [
        {
            "health": "green",
            "status": "open",
            "index": "good_idx",
            "pri": 2,
            "rep": 1,
            "docs_count": 5_000_000,
            "store_size": 60_000_000_000,
            "pri_store_size": 30_000_000_000,
        },
        {
            "health": "green",
            "status": "open",
            "index": "bad_idx",
            "pri": 10,
            "rep": 1,
            "docs_count": 100,
            "store_size": 1_000_000,
            "pri_store_size": 500_000,
        },
    ]
    shards = [
        {
            "index": "good_idx",
            "shard": i,
            "prirep": "p",
            "state": "STARTED",
            "docs": 2_500_000,
            "store": 15_000_000_000,
            "node": f"node-{i}",
            "segments_count": 3,
        }
        for i in range(2)
    ] + [
        {
            "index": "bad_idx",
            "shard": i,
            "prirep": "p",
            "state": "STARTED",
            "docs": 10,
            "store": 50_000,
            "node": f"node-{i}",
            "segments_count": 1,
        }
        for i in range(10)
    ]
    analyzer = IndexAnalyzer(indices, shards)
    results = analyzer.analyze_all(problems_only=True)
    assert len(results) == 1
    assert results[0]["name"] == "bad_idx"


def test_should_compute_wasted_shards_summary():
    """Total wasted shards should be sum of all opportunity wasted_shards."""
    indices = [
        {
            "health": "green",
            "status": "open",
            "index": "tiny",
            "pri": 5,
            "rep": 2,
            "docs_count": 100,
            "store_size": 300_000,
            "pri_store_size": 100_000,
        }
    ]
    shards = [
        {
            "index": "tiny",
            "shard": i,
            "prirep": "p",
            "state": "STARTED",
            "docs": 20,
            "store": 20_000,
            "node": f"n-{i}",
            "segments_count": 1,
        }
        for i in range(5)
    ]
    analyzer = IndexAnalyzer(indices, shards)
    results = analyzer.analyze_all()
    assert results[0]["wasted_shards"] == (5 - 1) * (1 + 2)  # 12
