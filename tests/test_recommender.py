from backend.services.recommender import RecommendationEngine


def test_should_classify_segment_fragmentation_old_index_as_tier1():
    opp = {"type": "segment-fragmentation", "severity": "medium", "wasted_shards": 0, "target_shards": 5}
    analysis = {"pri_store_bytes": 10_000_000_000, "year": 2024}
    job_type, tier = RecommendationEngine.classify(opp, analysis)
    assert job_type == "force_merge"
    assert tier == 1


def test_should_classify_segment_fragmentation_current_index_as_tier2():
    opp = {"type": "segment-fragmentation", "severity": "low", "wasted_shards": 0, "target_shards": 3}
    analysis = {"pri_store_bytes": 5_000_000_000, "year": 2026}
    job_type, tier = RecommendationEngine.classify(opp, analysis)
    assert job_type == "force_merge"
    assert tier == 2


def test_should_classify_over_sharded_tiny_as_tier3():
    opp = {"type": "over-sharded", "severity": "high", "wasted_shards": 8, "target_shards": 1}
    analysis = {"pri_store_bytes": 100_000_000, "year": None}  # 0.09 GB
    job_type, tier = RecommendationEngine.classify(opp, analysis)
    assert job_type == "reduce_shards"
    assert tier == 3


def test_should_classify_over_sharded_large_as_tier4():
    opp = {"type": "over-sharded", "severity": "medium", "wasted_shards": 4, "target_shards": 2}
    analysis = {"pri_store_bytes": 5_000_000_000, "year": None}  # ~4.6 GB
    job_type, tier = RecommendationEngine.classify(opp, analysis)
    assert job_type == "reduce_shards"
    assert tier == 4


def test_should_skip_shard_imbalance():
    opp = {"type": "shard-imbalance", "severity": "low", "wasted_shards": 0, "target_shards": 5}
    analysis = {"pri_store_bytes": 10_000_000_000, "year": None}
    job_type, tier = RecommendationEngine.classify(opp, analysis)
    assert job_type is None
    assert tier is None


def test_should_generate_jobs_from_analysis():
    results = [
        {
            "name": "tiny_idx",
            "pri_count": 5,
            "rep_count": 1,
            "doc_count": 100,
            "pri_store_bytes": 100_000,
            "store_bytes": 200_000,
            "max_segments_per_shard": 3,
            "year": None,
            "opportunities": [
                {"type": "over-sharded", "severity": "high", "wasted_shards": 8, "target_shards": 1},
            ],
        },
        {
            "name": "frag_idx",
            "pri_count": 3,
            "rep_count": 0,
            "doc_count": 500_000,
            "pri_store_bytes": 15_000_000_000,
            "store_bytes": 15_000_000_000,
            "max_segments_per_shard": 25,
            "year": 2024,
            "opportunities": [
                {"type": "segment-fragmentation", "severity": "medium", "wasted_shards": 0, "target_shards": 3},
            ],
        },
    ]
    jobs = RecommendationEngine.generate_jobs(results)
    assert len(jobs) == 2
    assert jobs[0]["job_type"] == "reduce_shards"
    assert jobs[0]["tier"] == 3
    assert jobs[1]["job_type"] == "force_merge"
    assert jobs[1]["tier"] == 1
